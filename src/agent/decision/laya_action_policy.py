"""LAYA Action Policy — browser-level decision adapter (P2-LAYA).

This module is SEPARATE from ``LayaAdapter`` (which handles bounded
verification / risk / escalation decisions). The Action Policy's sole job
is: given the current plan step and a compact indexed list of visible,
eligible browser controls, choose one operation + target index and return
it as the project's existing ``AgentAction`` type.

Inspired by the jev-ultrafast architecture (https://github.com/browser-use/jev-ultrafast)
and the LAYA decision model (a 421M-parameter open-weights Apache-2.0
ModernBERT-large checkpoint). The key safety property preserved from
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
  • Does NOT require Jev endpoint credentials — LAYA runs locally via
    ``transformers`` (CPU/GPU) or via an optional MLX backend on Apple
    Silicon. The adapter gracefully degrades to ``NotImplementedError``
    when the optional ``transformers`` dependency is not installed, so
    the rest of the system continues to work with the Gemini path.

This file does NOT replace ``LayaAdapter`` — that adapter's
intent/risk/escalation functions remain unchanged until usage and tests
prove they can be consolidated safely.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    device: str = "auto"  # "auto" | "cpu" | "cuda" | "mps" | "mlx"
    confidence_threshold: float = 0.65
    inference_timeout_seconds: float = 5.0
    max_candidates: int = 250  # hard cap, mirrors jev-ultrafast
    warmup_at_startup: bool = True


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
        """True if the policy is enabled AND a checkpoint path is set."""
        return self._config.enabled and bool(self._config.checkpoint)

    def is_healthy(self) -> bool:
        """Readiness check — model loaded and warm-up completed."""
        return self._warm and self._model is not None

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
            "inference_count": self._inference_count,
            "fallback_count": self._fallback_count,
            "avg_inference_latency_ms": round(avg_latency, 2),
            "total_inference_ms": round(self._total_inference_ms, 2),
        }

    async def warm_up(self) -> bool:
        """Load the model and run a trivial inference to verify readiness.

        Returns False (and logs) if the optional ``transformers`` dependency
        is not installed — the system continues to work with the Gemini
        path. Called once at app startup (P7).
        """
        if not self.is_configured():
            logger.info("laya_action_policy_not_configured")
            return False
        try:
            self._load_model()
            # Trivial warm-up inference: a single empty action space
            warmup_space = _ActionSpacePayload(
                fingerprint="warmup",
                page_url="",
                page_title="",
                candidates=[],
                plan_step="warmup",
                persona="itil",
                allowed_operations=list(LAYA_OPERATIONS),
            )
            decision = await self._infer(warmup_space)
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
        """Load the LAYA checkpoint via ``transformers`` (or MLX if available).

        Gracefully degrades if the optional dependency is missing — the
        policy reports ``is_healthy() == False`` and the DecisionEngine
        falls back to Gemini.
        """
        if self._model is not None:
            return
        if not self._config.checkpoint:
            raise ValueError("LAYA_ACTION_CHECKPOINT is not set")

        # Try MLX first on Apple Silicon (fastest local runtime for LAYA)
        device = self._resolve_device()
        self._device = device

        loaded = False
        if device == "mlx":
            loaded = self._try_load_mlx()
        if not loaded:
            loaded = self._try_load_transformers(device)

        if not loaded:
            raise RuntimeError(
                "Could not load LAYA checkpoint — neither mlx nor transformers "
                "backend is available. Install the optional 'laya' extra: "
                "pip install -e '.[laya]'"
            )

    def _resolve_device(self) -> str:
        """Resolve 'auto' to a concrete device string."""
        cfg_device = self._config.device
        if cfg_device != "auto":
            return cfg_device
        # Auto-detect: prefer MLX on Apple Silicon, then CUDA, then CPU
        import platform
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            return "mlx"
        try:
            import torch  # type: ignore[import-untyped]
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _try_load_mlx(self) -> bool:
        """Attempt to load via MLX (Apple Silicon only)."""
        try:
            # MLX LM bridge — optional dependency
            from mlx_lm import load as mlx_load  # type: ignore[import-untyped]
            self._model, self._tokenizer = mlx_load(self._config.checkpoint)
            self._model_version = f"mlx:{self._config.checkpoint}"
            logger.info("laya_action_policy_loaded_mlx", checkpoint=self._config.checkpoint)
            return True
        except ImportError:
            logger.info("laya_action_policy_mlx_unavailable_trying_transformers")
            return False
        except Exception as e:
            logger.warning("laya_action_policy_mlx_load_failed", error=str(e))
            return False

    def _try_load_transformers(self, device: str) -> bool:
        """Attempt to load via HuggingFace transformers."""
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore[import-untyped]
            self._tokenizer = AutoTokenizer.from_pretrained(self._config.checkpoint)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._config.checkpoint,
            )
            if device in ("cuda", "mps"):
                import torch  # type: ignore[import-untyped]
                self._model = self._model.to(device)
            self._model_version = f"transformers:{self._config.checkpoint}"
            logger.info(
                "laya_action_policy_loaded_transformers",
                checkpoint=self._config.checkpoint,
                device=device,
            )
            return True
        except ImportError:
            logger.info(
                "laya_action_policy_transformers_not_installed",
                hint="Install with: pip install -e '.[laya]'",
            )
            return False
        except Exception as e:
            logger.warning("laya_action_policy_transformers_load_failed", error=str(e))
            return False

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

    async def _infer(self, action_space: "_ActionSpacePayload") -> LayaActionDecision | None:
        """Run a single LAYA inference and resolve it to an AgentAction.

        The inference is serialized through ``self._lock`` because the
        transformers/MLX backends are not guaranteed thread-safe across
        async tasks.
        """
        start = time.monotonic()
        async with self._lock:
            try:
                raw = await asyncio.wait_for(
                    self._run_model(action_space),
                    timeout=self._config.inference_timeout_seconds,
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

        This method is the single place where the actual model backend is
        touched — swapping MLX ↔ transformers ↔ a future ONNX runtime only
        requires changing this method.
        """
        # Build the model input: a compact text representation of the
        # action space + the plan step. LAYA is a sequence-classification
        # model, so the input is a single text string.
        prompt = self._build_prompt(action_space)
        if self._tokenizer is None or self._model is None:
            return None

        # Tokenize + run inference (sync — wrapped in to_thread to avoid
        # blocking the event loop)
        def _sync_infer() -> dict[str, Any] | None:
            try:
                inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
                if self._device in ("cuda", "mps"):
                    inputs = {k: v.to(self._device) for k, v in inputs.items()}
                import torch  # type: ignore[import-untyped]
                with torch.no_grad():
                    outputs = self._model(**inputs)
                # The LAYA checkpoint's head layout varies by checkpoint;
                # we treat the output logits as a per-operation score and
                # pick the argmax. For target selection, we use a second
                # forward pass over the candidates (mirroring jev-ultrafast's
                # speculative target heads, but simplified to a single pass
                # per candidate since LAYA is small enough to run multiple
                # passes cheaply).
                logits = outputs.logits if hasattr(outputs, "logits") else outputs[0]
                # If logits has shape [1, num_operations], pick argmax
                if logits.dim() >= 2:
                    op_idx = int(logits[0].argmax().item())
                    confidence = float(torch.softmax(logits[0], dim=-1).max().item())
                else:
                    op_idx = int(logits.argmax().item())
                    confidence = float(torch.softmax(logits, dim=-1).max().item())

                operations = sorted(action_space.allowed_operations)
                if op_idx >= len(operations):
                    op_idx = op_idx % len(operations)
                operation = operations[op_idx]

                # Target selection: for click/fill/select, score each
                # candidate by a second pass with "operation=<op>" prepended
                target_index = None
                if operation in _TARGET_OPERATIONS and action_space.candidates:
                    target_index = self._select_target(operation, action_space)

                return {
                    "operation": operation,
                    "target_index": target_index,
                    "confidence": confidence,
                }
            except Exception as e:
                logger.warning("laya_action_policy_model_inference_failed", error=str(e))
                return None

        return await asyncio.to_thread(_sync_infer)

    def _select_target(
        self, operation: str, action_space: "_ActionSpacePayload",
    ) -> int | None:
        """Score each candidate for the chosen operation and return the best index.

        Mirrors jev-ultrafast's per-operation target head, simplified: we
        run a single forward pass per candidate with the prompt
        "operation={op} target={candidate_label}" and pick the argmax
        confidence. For a 421M model this is fast enough (a few ms per
        candidate on CPU).
        """
        if not action_space.candidates:
            return None
        try:
            import torch  # type: ignore[import-untyped]
            best_idx = None
            best_score = -1.0
            for candidate in action_space.candidates[: self._config.max_candidates]:
                prompt = f"operation={operation} target={candidate.label}"
                inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
                if self._device in ("cuda", "mps"):
                    inputs = {k: v.to(self._device) for k, v in inputs.items()}
                with torch.no_grad():
                    outputs = self._model(**inputs)
                logits = outputs.logits if hasattr(outputs, "logits") else outputs[0]
                score = float(torch.softmax(logits[0] if logits.dim() >= 2 else logits, dim=-1).max().item())
                if score > best_score:
                    best_score = score
                    best_idx = candidate.index
            return best_idx
        except Exception as e:
            logger.warning("laya_action_policy_target_selection_failed", error=str(e))
            return action_space.candidates[0].index if action_space.candidates else None

    def _build_prompt(self, action_space: "_ActionSpacePayload") -> str:
        """Build a compact text prompt for the LAYA model.

        Format mirrors jev-ultrafast's question schema: goal, plan step,
        page context, and an indexed candidate list. Page content is
        treated as untrusted data (never as instructions).
        """
        lines = [
            f"goal: {action_space.plan_step}",
            f"persona: {action_space.persona}",
            f"page: {action_space.page_title} ({action_space.page_url})",
            "candidates:",
        ]
        for c in action_space.candidates[: self._config.max_candidates]:
            lines.append(f"  [{c.index}] {c.kind} {c.role} '{c.label}' value='{c.value}'")
        lines.append(f"allowed_operations: {','.join(sorted(action_space.allowed_operations))}")
        return "\n".join(lines)

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
                # transformers models don't have a standard close() —
                # dereference and let GC handle it. On CUDA we'd also
                # flush the cache, but for CPU/MPS this is sufficient.
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
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
