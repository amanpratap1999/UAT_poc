"""LAYA Action Policy — browser-level decision adapter (P2-LAYA).

This module is SEPARATE from ``LayaAdapter`` (which handles bounded
verification / risk / escalation decisions). The Action Policy's sole job
is: given the current plan step and a compact indexed list of visible,
eligible browser controls, choose one operation + target index and return
it as the project's existing ``AgentAction`` type.

Inspired by the jev-ultrafast architecture (https://github.com/browser-use/jev-ultrafast)
and LAYA's open-source typed-decision model. The key safety property preserved from
jev-ultrafast: **the model emits only ``{operation, target_index}``; the
code owns execution and resolves the target index to a safe Playwright
locator via the ``BrowserActionSpace`` mapping. The model never emits
selectors, coordinates, shell, or JS.**

Design decisions:
  • LAYA stays separate from Gemini — Gemini still does high-level test
    planning (see ``planner.py`` docstring guard).
  • The adapter returns ``AgentAction`` so the existing
    ``ExecutionController`` dispatch table works unchanged.
  • On unsupported pages, low confidence, timeout, or model failure, the
    caller (``DecisionEngine``) falls back to the existing Gemini decision
    path and then its existing heuristic fallback.
  • Modes: ``shadow`` (runs LAYA but records the decision for comparison
    without using it) or ``primary`` (uses LAYA's decision when confidence
    ≥ threshold). Default is ``shadow`` so existing flows are unaffected
    until LAYA is proven.
  • The model is loaded once at startup (P7 wiring) and reused for the
    process lifetime. ``warm_up()`` verifies the checkpoint loads and a
    trivial inference completes; ``shutdown()`` releases resources.
  • Does NOT require Jev endpoint credentials — LAYA runs locally through
    its typed-decision SDK. If the optional SDK is unavailable, the rest
    of the system continues to work through the Gemini path.

This file does NOT replace ``LayaAdapter`` — that adapter's
intent/risk/escalation functions remain unchanged until usage and tests
prove they can be consolidated safely.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import AgentAction

logger = get_logger(__name__)

# ── Bounded operation set ──
# Mirrors jev-ultrafast's operation vocabulary so the LAYA checkpoint
# (which was trained on a similar indexed-element task) can be reused.
# WAIT / SCROLL_DOWN / SCROLL_UP / DONE / BLOCKED are "control" operations
# that don't require a target index.
LAYA_OPERATIONS = frozenset({
    "click",
    "fill",
    "select",
    "wait",
    "scroll_down",
    "scroll_up",
    "done",
    "blocked",
})

_CONTROL_OPERATIONS = frozenset({"wait", "scroll_down", "scroll_up", "done", "blocked"})
_TARGET_OPERATIONS = frozenset({"click", "fill", "select"})


@dataclass
class LayaActionDecision:
    """Typed result of a LAYA action-policy inference.

    Carries the resolved ``AgentAction`` (so the existing ExecutionController
    dispatch works unchanged) plus provider metadata for telemetry and
    fallback traceability.
    """
    action: AgentAction
    operation: str  # one of LAYA_OPERATIONS
    target_index: int | None  # 1-indexed position in the action space, or None for controls
    confidence: float  # 0.0–1.0
    provider: str = "laya"
    model_version: str = ""
    inference_latency_ms: float = 0.0
    fallback_reason: str = ""  # empty if LAYA made the decision; set if this was a fallback
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target_index": self.target_index,
            "confidence": round(self.confidence, 4),
            "provider": self.provider,
            "model_version": self.model_version,
            "inference_latency_ms": round(self.inference_latency_ms, 2),
            "fallback_reason": self.fallback_reason,
            "action_type": str(self.action.action_type),
            "target": self.action.target,
            "value": self.action.value,
            "metadata": self.metadata,
        }


@dataclass
class LayaActionPolicyConfig:
    """Configuration for the LAYA action policy (P6).

    Loaded from ``LayaActionPolicyConfig`` in ``core/config.py`` (which
    reads ``LAYA_ACTION_*`` env vars). Defaults are conservative: the
    policy is OFF by default so existing flows are unaffected until an
    operator explicitly enables it.
    """
    enabled: bool = False
    mode: str = "shadow"  # "shadow" | "primary"
    checkpoint: str = ""  # HuggingFace repo or local path to the LAYA checkpoint
    model_subfolder: str = "typed-decisions"
    device: str = "auto"  # "auto" | "cpu" | "cuda" | "mps"
    confidence_threshold: float = 0.65
    inference_timeout_seconds: float = 5.0
    max_candidates: int = 250  # hard cap, mirrors jev-ultrafast
    warmup_at_startup: bool = True
    model_max_len: int = 2048
    head_max_len: int = 768
    # Remote API fallback (jev-ultrafast style)
    endpoint: str = ""  # if set with api_key, uses remote API instead of local checkpoint
    api_key: str = ""


class LayaActionPolicy:
    """Local LAYA policy adapter for browser-level decisions.

    Responsibilities:
      • Load the LAYA checkpoint once (lazy on first use, or eagerly if
        ``warm_up()`` is called at startup — see P7 wiring in main.py).
      • Accept a compact indexed action space (from ``BrowserActionSpace``)
        and the current plan step, and return a ``LayaActionDecision``
        containing a resolved ``AgentAction``.
      • In ``shadow`` mode, run the inference but ALWAYS return
        ``fallback_reason="shadow_mode"`` so the caller uses the Gemini
        path; the shadow decision is recorded for offline comparison.
      • In ``primary`` mode, return the LAYA decision when confidence ≥
        threshold; otherwise return a fallback decision with
        ``fallback_reason="low_confidence"``.
      • On any error (timeout, model failure, unsupported page, missing
        dependency), return a fallback decision with a descriptive
        ``fallback_reason`` so the caller transparently uses the Gemini
        path.

    The adapter NEVER emits a selector, coordinates, shell, or JS — only
    an operation name + a target index into the supplied action space.
    The caller (``DecisionEngine``) resolves the index to an actual
    ``AgentAction`` via the ``BrowserActionSpace`` mapping.
    """

    def __init__(self, config: LayaActionPolicyConfig | None = None) -> None:
        self._config = config or LayaActionPolicyConfig()
        self._model = None
        self._tokenizer = None
        self._device = "cpu"
        self._warm = False
        self._model_version = ""
        self._inference_count = 0
        self._total_inference_ms = 0.0
        self._fallback_count = 0
        self._lock = asyncio.Lock()  # serialize inferences if the backend isn't thread-safe

    @property
    def config(self) -> LayaActionPolicyConfig:
        return self._config

    @property
    def is_enabled(self) -> bool:
        return self._config.enabled

    @property
    def mode(self) -> str:
        return self._config.mode

    @property
    def is_warm(self) -> bool:
        return self._warm

    @property
    def model_version(self) -> str:
        return self._model_version

    def is_configured(self) -> bool:
        """True if the policy is enabled.

        With the Router backend (default), just ``enabled=true`` is enough —
        the Router auto-downloads the checkpoint from HuggingFace on first use.
        No checkpoint path or API key needed.
        """
        return self._config.enabled

    def is_healthy(self) -> bool:
        """Readiness check — model loaded and warm-up completed."""
        return self._warm and self._model is not None

    @staticmethod
    def is_confidence_calibrated() -> bool:
        """True only after the exact checkpoint has been calibrated."""
        import os
        return os.getenv("LAYA_ACTION_CONFIDENCE_CALIBRATED", "false").lower() in {
            "1", "true", "yes", "on"
        }

    def get_stats(self) -> dict[str, Any]:
        """Telemetry snapshot for diagnostics (P9)."""
        avg_latency = (
            self._total_inference_ms / self._inference_count
            if self._inference_count > 0
            else 0.0
        )
        return {
            "enabled": self._config.enabled,
            "mode": self._config.mode,
            "checkpoint": self._config.checkpoint,
            "device": self._device,
            "model_version": self._model_version,
            "is_warm": self._warm,
            "confidence_calibrated": self.is_confidence_calibrated(),
            "inference_count": self._inference_count,
            "fallback_count": self._fallback_count,
            "avg_inference_latency_ms": round(avg_latency, 2),
            "total_inference_ms": round(self._total_inference_ms, 2),
        }

    async def warm_up(self) -> bool:
        """Load the model and run a trivial inference to verify readiness.

        Returns False (and logs) if the optional ``laya`` dependency
        is not installed — the system continues to work with the Gemini
        path. Called once at app startup (P7).

        The warmup uses a minimal action space with ONE dummy candidate
        so the model has something to choose from. We don't care whether
        the model picks the right operation — we just need to confirm
        the model loaded and can produce a response. If the Router
        responds with click/fill/select on the dummy candidate, that's
        proof it's working; the warmup marks the policy as healthy.
        """
        if not self.is_configured():
            logger.info("laya_action_policy_not_configured")
            return False
        try:
            self._load_model()
            # Warmup with a single dummy candidate so the model has
            # something to choose from. We accept ANY response (including
            # a fallback) as proof the model loaded successfully — the
            # goal is to verify the model is callable, not that it makes
            # the right decision on a dummy input.
            warmup_space = _ActionSpacePayload(
                fingerprint="warmup",
                page_url="https://warmup.example.com",
                page_title="Warmup",
                candidates=[
                    ActionSpaceCandidate(
                        index=1,
                        kind="click",
                        role="button",
                        label="warmup_button",
                        value="",
                        locator="role:button:warmup_button",
                    )
                ],
                plan_step="warmup",
                persona="itil",
                allowed_operations=list(LAYA_OPERATIONS),
            )
            decision = await self._infer(
                warmup_space,
                timeout_seconds=max(120.0, self._config.inference_timeout_seconds),
            )
            # Accept any non-None decision as proof the model is callable.
            # Even a fallback decision (e.g., low_confidence) proves the
            # model loaded and ran inference — the policy is "warm".
            self._warm = decision is not None
            if self._warm:
                logger.info(
                    "laya_action_policy_warmup_success",
                    checkpoint=self._config.checkpoint,
                    device=self._device,
                    model_version=self._model_version,
                )
            return self._warm
        except Exception as e:
            logger.warning("laya_action_policy_warmup_failed", error=str(e))
            self._warm = False
            return False

    def _load_model(self) -> None:
        """Load the LAYA model using the best available backend.

        Tries three backends in order:
        1. ``laya.Router`` (local, auto-download) — the simplest path.
           Just ``pip install laya`` and it works — the Router auto-downloads
           the checkpoint from HuggingFace on first use. No checkpoint path
           or API key needed. This is the approach the user validated.
        2. ``laya.load()`` (local, explicit checkpoint) — for when you want
           to pin a specific checkpoint / subfolder.
        3. Remote API (jev-ultrafast style) — calls an OpenAI-compatible
           HTTP endpoint. No local dependencies needed.

        Gracefully degrades if no backend is available.
        """
        if self._model is not None:
            return

        # Path 1: laya.Router (auto-download, simplest path)
        # This is what the user tested successfully — just import laya,
        # create a Router(), and call system_one(). The Router handles
        # checkpoint downloading + device selection internally.
        try:
            from laya import Router  # type: ignore[import-not-found]
            self._model = Router()
            self._model_version = "laya:router"
            self._device = "auto-router"
            logger.info("laya_action_policy_loaded_router", backend="laya.Router")
            return
        except ImportError:
            logger.info("laya_router_not_available_trying_fallbacks")
        except Exception as e:
            logger.warning("laya_router_init_failed", error=str(e)[:200])

        # Path 2: Remote API (jev-ultrafast style)
        if self._config.endpoint and self._config.api_key:
            self._model = _RemoteLayaBackend(
                endpoint=self._config.endpoint,
                api_key=self._config.api_key,
                timeout=self._config.inference_timeout_seconds,
            )
            self._model_version = f"laya-remote:{self._config.endpoint}"
            self._device = "remote"
            logger.info(
                "laya_action_policy_loaded_remote",
                endpoint=self._config.endpoint,
            )
            return

        # Path 3: Local LAYA SDK with explicit checkpoint
        if self._config.checkpoint:
            device = self._resolve_device()
            self._device = device
            try:
                import laya  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "Could not load LAYA. Install with: pip install laya "
                    "(for Router auto-download) OR pip install -e '.[laya]' "
                    "(for explicit checkpoint) OR set LAYA_ACTION_ENDPOINT + "
                    "LAYA_ACTION_API_KEY (for remote API)."
                ) from exc
            self._model = laya.load(
                self._config.checkpoint,
                device=device,
                subfolder=self._config.model_subfolder or None,
            )
            self._model_version = (
                f"laya:{self._config.checkpoint}"
                + (f"/{self._config.model_subfolder}" if self._config.model_subfolder else "")
            )
            logger.info(
                "laya_action_policy_loaded_local",
                checkpoint=self._config.checkpoint,
                subfolder=self._config.model_subfolder,
                device=device,
            )
            return

        raise RuntimeError(
            "No LAYA backend available. Install laya (pip install laya) for "
            "auto-download mode, OR set LAYA_ACTION_CHECKPOINT for explicit "
            "checkpoint, OR set LAYA_ACTION_ENDPOINT + LAYA_ACTION_API_KEY "
            "for remote API mode."
        )

    def _resolve_device(self) -> str:
        """Resolve 'auto' to a concrete device string."""
        cfg_device = self._config.device
        if cfg_device != "auto":
            return cfg_device
        # Auto-detect CUDA when present; otherwise use the SDK's CPU backend.
        try:
            import torch  # type: ignore[import-untyped]
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    async def choose_action(
        self,
        action_space: "_ActionSpacePayload",
    ) -> LayaActionDecision:
        """Choose an operation + target from the indexed action space.

        This is the main entry point called by ``DecisionEngine`` (P3).
        Returns a ``LayaActionDecision`` containing a resolved
        ``AgentAction``. On any error, low confidence, shadow mode, or
        unsupported page, returns a fallback decision with a descriptive
        ``fallback_reason`` so the caller transparently uses the Gemini
        path.

        Args:
            action_space: compact indexed list of visible+eligible controls
                (produced by ``BrowserActionSpace`` in P4), plus the current
                plan step, persona, and allowed operations.
        """
        if not self.is_configured():
            return self._fallback(
                action_space, reason="policy_disabled",
            )
        if not self._warm and self._config.warmup_at_startup:
            # Attempt a lazy warm-up if startup warm-up was skipped
            try:
                await self.warm_up()
            except Exception:
                pass
        if not self.is_healthy():
            return self._fallback(action_space, reason="model_not_healthy")
        if not self.is_confidence_calibrated():
            return self._fallback(action_space, reason="confidence_uncalibrated")

        # Reject empty action spaces — LAYA cannot choose from nothing
        if not action_space.candidates:
            return self._fallback(action_space, reason="empty_action_space")

        # Shadow mode: run the inference but always return a fallback
        # so the caller uses the Gemini path; record the shadow decision
        # for offline comparison.
        if self._config.mode == "shadow":
            try:
                shadow_decision = await self._infer(action_space)
                if shadow_decision:
                    # Record the shadow decision in telemetry but return a fallback
                    logger.info(
                        "laya_action_policy_shadow_decision",
                        operation=shadow_decision.operation,
                        target_index=shadow_decision.target_index,
                        confidence=shadow_decision.confidence,
                    )
            except Exception as e:
                logger.warning("laya_action_policy_shadow_inference_failed", error=str(e))
            return self._fallback(action_space, reason="shadow_mode")

        # Primary mode: use the LAYA decision if confidence ≥ threshold
        try:
            decision = await self._infer(action_space)
            if decision is None:
                return self._fallback(action_space, reason="inference_returned_none")
            if decision.confidence < self._config.confidence_threshold:
                return self._fallback(
                    action_space,
                    reason=f"low_confidence:{decision.confidence:.2f}",
                    shadow_decision=decision,
                )
            return decision
        except asyncio.TimeoutError:
            return self._fallback(action_space, reason="inference_timeout")
        except Exception as e:
            logger.warning("laya_action_policy_inference_failed", error=str(e))
            return self._fallback(action_space, reason=f"inference_error:{type(e).__name__}")

    async def _infer(
        self,
        action_space: "_ActionSpacePayload",
        *,
        timeout_seconds: float | None = None,
    ) -> LayaActionDecision | None:
        """Run a single LAYA inference and resolve it to an AgentAction.

        The inference is serialized through ``self._lock`` because the
                LAYA inference calls are serialized because the SDK backend is
                not guaranteed thread-safe across
        async tasks.
        """
        start = time.monotonic()
        inference_timeout = (
            self._config.inference_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        async with self._lock:
            try:
                raw = await asyncio.wait_for(
                    self._run_model(action_space),
                    timeout=inference_timeout,
                )
            except asyncio.TimeoutError:
                self._fallback_count += 1
                raise
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._inference_count += 1
        self._total_inference_ms += elapsed_ms
        if raw is None:
            return None
        return self._resolve_to_action(raw, action_space, elapsed_ms)

    async def _run_model(self, action_space: "_ActionSpacePayload") -> dict[str, Any] | None:
        """Invoke the loaded model on the serialized action space.

        Returns a dict with keys: ``operation`` (str), ``target_index``
        (int|None), ``confidence`` (float). Returns None if the model
        could not produce a valid decision.

        LAYA evaluates the operation and operation-specific target questions
        together in one typed decision pass. Its returned choices are mapped
        back to the bounded, code-owned action space below.
        """
        if self._model is None:
            return None
        candidates = action_space.candidates[: self._config.max_candidates]
        compatible = {
            "click": [c for c in candidates if c.kind == "click"],
            "fill": [c for c in candidates if c.kind == "fill"],
            "select": [c for c in candidates if c.kind == "select"],
        }
        operations = [
            op for op in sorted(set(action_space.allowed_operations) & LAYA_OPERATIONS)
            if op in _CONTROL_OPERATIONS or compatible.get(op)
        ]
        if not operations:
            return None
        state = {
            "goal": action_space.plan_step,
            "persona": action_space.persona,
            "page": {"title": action_space.page_title, "url": action_space.page_url},
            "visible_controls": [
                {
                    "index": c.index,
                    "kind": c.kind,
                    "role": c.role,
                    "label": c.label,
                    "value": c.value,
                }
                for c in candidates
            ],
            "content_is_untrusted_data": True,
        }
        questions: dict[str, dict[str, Any]] = {
            "operation": {
                "type": "choice",
                "instructions": (
                    "Choose the next browser operation that advances the stated goal "
                    "using the visible controls. Choose done only when the goal is "
                    "observably complete; choose blocked only when required controls are absent."
                ),
                "criteria": {op: op for op in operations},
            }
        }
        for op, options in compatible.items():
            if op in operations and options:
                questions[f"{op}_target"] = {
                    "type": "choice",
                    "instructions": f"Choose the visible control to use for the {op} operation.",
                    "criteria": {
                        str(c.index): f"{c.role} {c.label}; current value {c.value}"
                        for c in options
                    },
                }

        def _sync_infer() -> dict[str, Any] | None:
            result = self._model.system_one(
                json.dumps(state, ensure_ascii=False),
                questions,
                max_len=self._config.model_max_len,
                head_max_len=self._config.head_max_len,
            )
            answers = result.get("answers", {})
            op_answer = answers.get("operation", {})
            operation = str(op_answer.get("choice", ""))
            if operation not in operations:
                return None
            # LAYA's `confidence` on choice answers is normalized entropy;
            # answer_confidence is the comparable probability mass on the choice.
            confidence = float(op_answer.get("answer_confidence", 0.0) or 0.0)
            target_index = None
            if operation in _TARGET_OPERATIONS:
                target_answer = answers.get(f"{operation}_target", {})
                choice = str(target_answer.get("choice", ""))
                valid_indexes = {str(c.index) for c in compatible[operation]}
                if choice not in valid_indexes:
                    return None
                target_index = int(choice)
                confidence = min(
                    confidence,
                    float(target_answer.get("answer_confidence", 0.0) or 0.0),
                )
            return {
                "operation": operation,
                "target_index": target_index,
                "confidence": confidence,
                "usage": result.get("usage", {}),
            }

        return await asyncio.to_thread(_sync_infer)

    def _resolve_to_action(
        self,
        raw: dict[str, Any],
        action_space: "_ActionSpacePayload",
        elapsed_ms: float,
    ) -> LayaActionDecision:
        """Resolve the model's raw output to an ``AgentAction``.

        Maps the LAYA operation vocabulary to the project's ``ActionType``
        enum and looks up the candidate by index to populate the
        ``target`` / ``value`` fields. Control operations (wait/scroll)
        become ``WAIT``/``SCROLL`` actions with no target.
        """
        operation = str(raw.get("operation", "wait"))
        target_index = raw.get("target_index")
        confidence = float(raw.get("confidence", 0.0))

        # Map LAYA operation → ActionType
        op_to_action_type = {
            "click": ActionType.CLICK,
            "fill": ActionType.FILL,
            "select": ActionType.SELECT,
            "wait": ActionType.WAIT,
            "scroll_down": ActionType.SCROLL,
            "scroll_up": ActionType.SCROLL,
            "done": ActionType.VALIDATE,
            "blocked": ActionType.VALIDATE,
        }
        action_type = op_to_action_type.get(operation, ActionType.WAIT)

        if operation in {"done", "blocked"}:
            return self._fallback(
                action_space,
                reason=f"laya_{operation}_terminal_signal",
                elapsed_ms=elapsed_ms,
                shadow_confidence=confidence,
            )

        # LAYA chooses a browser control, but it does not generate the text
        # or option value that the planner must enter. Avoid filling with a
        # control's existing value; hand those actions to the existing LLM
        # decision path until the plan supplies a structured action value.
        if operation in {"fill", "select"}:
            return self._fallback(
                action_space,
                reason=f"planner_value_required:{operation}",
                elapsed_ms=elapsed_ms,
                shadow_confidence=confidence,
            )

        target = ""
        value = ""
        candidate = None
        if target_index is not None and operation in _TARGET_OPERATIONS:
            candidate = next(
                (c for c in action_space.candidates if c.index == target_index),
                None,
            )
            if candidate:
                target = candidate.locator
                value = candidate.value
            else:
                # Stale index — the page changed between observation and
                # inference. Fall back with a descriptive reason.
                return self._fallback(
                    action_space,
                    reason=f"stale_target_index:{target_index}",
                    elapsed_ms=elapsed_ms,
                    shadow_confidence=confidence,
                )

        # Control operations
        if operation == "wait":
            value = "1000"
        elif operation == "scroll_down":
            value = "560"
        elif operation == "scroll_up":
            value = "-560"

        action = AgentAction(
            action_type=action_type,
            target=target,
            value=value,
            reasoning=f"LAYA action-policy: {operation}"
            + (f" on [{target_index}] {candidate.label}" if candidate else ""),
            metadata={
                "laya_source": True,
                "laya_operation": operation,
                "laya_target_index": target_index,
                "laya_confidence": confidence,
                "laya_action_space_fingerprint": action_space.fingerprint,
            },
        )
        return LayaActionDecision(
            action=action,
            operation=operation,
            target_index=target_index,
            confidence=confidence,
            provider="laya",
            model_version=self._model_version,
            inference_latency_ms=elapsed_ms,
            metadata={
                "action_space_fingerprint": action_space.fingerprint,
                "candidate_count": len(action_space.candidates),
                "laya_usage": raw.get("usage", {}),
            },
        )

    def _fallback(
        self,
        action_space: "_ActionSpacePayload",
        reason: str,
        elapsed_ms: float = 0.0,
        shadow_decision: LayaActionDecision | None = None,
        shadow_confidence: float = 0.0,
    ) -> LayaActionDecision:
        """Build a fallback decision so the caller uses the Gemini path.

        The returned ``AgentAction`` is a no-op WAIT — the caller (DecisionEngine)
        checks ``fallback_reason`` and, if non-empty, ignores the action
        and proceeds with the existing Gemini/LLM decision path.
        """
        self._fallback_count += 1
        action = AgentAction(
            action_type=ActionType.WAIT,
            target="",
            value="0",
            reasoning=f"LAYA fallback: {reason}",
            metadata={
                "laya_source": False,
                "laya_fallback_reason": reason,
                "laya_action_space_fingerprint": action_space.fingerprint,
            },
        )
        extra_metadata: dict[str, Any] = {}
        if shadow_decision is not None:
            extra_metadata["shadow_decision"] = shadow_decision.to_dict()
        if shadow_confidence:
            extra_metadata["shadow_confidence"] = round(shadow_confidence, 4)
        return LayaActionDecision(
            action=action,
            operation="fallback",
            target_index=None,
            confidence=0.0,
            provider="laya",
            model_version=self._model_version,
            inference_latency_ms=elapsed_ms,
            fallback_reason=reason,
            metadata={
                "action_space_fingerprint": action_space.fingerprint,
                "candidate_count": len(action_space.candidates),
                **extra_metadata,
            },
        )

    async def shutdown(self) -> None:
        """Release model resources. Called at app shutdown (P7)."""
        try:
            if self._model is not None:
                # Dereference the SDK model and let GC release its resources.
                del self._model
                self._model = None
            self._tokenizer = None
            self._warm = False
            logger.info("laya_action_policy_shutdown")
        except Exception as e:
            logger.warning("laya_action_policy_shutdown_failed", error=str(e))


# ── Action space payload (produced by BrowserActionSpace in P4) ──


@dataclass
class ActionSpaceCandidate:
    """A single visible+eligible control in the indexed action space.

    The ``locator`` field is the safe Playwright locator string that the
    ``PageInteractor`` will resolve at execution time. It is NEVER
    model-generated — it is always produced by the observation engine
    from the actual DOM.
    """
    index: int  # 1-indexed
    kind: str  # "click" | "fill" | "select"
    role: str  # ARIA role or tag-derived role
    label: str  # accessible name
    value: str  # current value (for fill/select)
    locator: str  # safe Playwright locator (role:/label:/text:/css:/xpath:)
    node_id: int = 0  # internal DOM node ID for freshness checks


@dataclass
class _ActionSpacePayload:
    """Internal payload passed to the LAYA model.

    Carries the compact indexed candidate list plus the context the model
    needs: the current plan step, the active persona, the allowed
    operations, and a page fingerprint so stale action spaces can be
    rejected before inference.
    """
    fingerprint: str  # SHA-256 of {url, title, candidate signatures}
    page_url: str
    page_title: str
    candidates: list[ActionSpaceCandidate]
    plan_step: str
    persona: str
    allowed_operations: list[str]


class _RemoteLayaBackend:
    """Remote LAYA API backend (jev-ultrafast style).

    Calls an OpenAI-compatible HTTP endpoint that serves LAYA decisions.
    This is the same architecture as jev-ultrafast, which calls
    ``api.typesafe.ai/v1/systemone``. The backend exposes the same
    ``system_one()`` interface as the local LAYA SDK so the rest of the
    action policy code is unchanged.

    The endpoint must accept a JSON body with:
        - ``state``: the serialized action space (string)
        - ``questions``: the decision questions (dict)
    And return a JSON response with:
        - ``answers``: dict of question_name → {choice, confidence, ...}
        - ``usage``: optional token/cost telemetry
    """

    def __init__(self, endpoint: str, api_key: str, timeout: float = 5.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def system_one(
        self,
        state: str,
        questions: dict[str, Any],
        max_len: int = 2048,
        head_max_len: int = 768,
    ) -> dict[str, Any]:
        """Call the remote LAYA endpoint with the state + questions.

        Returns a dict matching the local SDK's response shape:
        ``{"answers": {...}, "usage": {...}}``
        """
        import httpx

        # Build the request payload — matches the LAYA API contract
        payload = {
            "state": state[:max_len],  # truncate to configured max
            "questions": questions,
            "max_len": max_len,
            "head_max_len": head_max_len,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Determine the full URL. If the endpoint is a base URL, append
        # the LAYA system_one path.
        url = self._endpoint
        if not url.endswith("/system_one") and not url.endswith("/v1/systemone"):
            if "/v1/" in url:
                url = f"{url}/systemone"
            else:
                url = f"{url}/v1/systemone"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "laya_remote_http_error",
                status_code=e.response.status_code,
                url=url,
                error=str(e)[:200],
            )
            # Return an empty answers dict so the caller falls back gracefully
            return {"answers": {}, "usage": {}, "error": f"HTTP {e.response.status_code}"}
        except Exception as e:
            logger.warning("laya_remote_call_failed", url=url, error=str(e)[:200])
            return {"answers": {}, "usage": {}, "error": str(e)[:200]}
