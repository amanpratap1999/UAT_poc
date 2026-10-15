"""Decision Engine for Deliverable 9.

Separates macro-planning (Planner) from immediate action selection.
Inputs:
- StructuredIntent
- SemanticWorldState
- SessionMemory
- ConfidenceAssessment
- ReflectionResult
- ToolRegistry

Output:
- AgentAction with target, reasoning, confidence, expected outcome
"""

from __future__ import annotations

from pydantic import BaseModel

from agent.confidence.engine import ConfidenceAssessment, ConfidenceEngine
from agent.core.exceptions import AgentError
from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.reflection import ReflectionResult
from agent.domain.world import SemanticWorldState
from agent.memory.session import SessionMemory
from agent.planner.llm_client import BaseLLMClient
from agent.reflection.engine import ReflectionEngine
from agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


class DecisionUnavailableError(AgentError):
    """Raised when the LAYA action policy cannot safely select an executable action."""


class CognitiveDecision(BaseModel):
    """Output of the DecisionEngine."""

    action: AgentAction
    reasoning: str
    expected_outcome: str
    confidence_assessment: ConfidenceAssessment


class DecisionEngine:
    """Selects immediate browser actions through the LAYA Action Policy.

    LAYA owns the browser-level operation and target decision. The LLM remains
    responsible for reasoning, planning, validation interpretation, and
    recovery reasoning. No LLM/Gemini/heuristic fallback may select a browser
    action.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        reflection_engine: ReflectionEngine | None = None,
        tool_registry: ToolRegistry | None = None,
        # INC-UAT-07: optional DecisionProvider for independent verification.
        # When set, the provider's verify() takes precedence over the
        # internal LLM-based verification. Provider provenance is recorded
        # in the CognitiveDecision output.
        decision_provider: Any = None,
        # LAYA is the authoritative browser-level action selector. The
        # llm_client parameter is retained for dependency compatibility only
        # and is never used for browser action selection.
        laya_action_policy: Any = None,
    ) -> None:
        self._llm = llm_client
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._reflection_engine = reflection_engine or ReflectionEngine(llm_client)
        self._tool_registry = tool_registry
        # INC-UAT-07: store the verification provider (e.g., JEVAdapter).
        self._decision_provider = decision_provider
        # P3-LAYA: store the action-policy adapter (separate from the
        # verification provider — LayaAdapter does verification; this
        # does action selection).
        self._laya_action_policy = laya_action_policy


    # INC-UAT-07: public accessor so CognitiveOrchestrator can check
    # whether a decision provider is attached and record its provenance.
    def get_decision_provider(self) -> Any:
        """Return the attached DecisionProvider (or None if not set)."""
        return self._decision_provider

    @property
    def has_decision_provider(self) -> bool:
        """True if a DecisionProvider (e.g., JEVAdapter) is attached."""
        return self._decision_provider is not None

    # P3-LAYA: public accessors for the action policy
    def get_laya_action_policy(self) -> Any:
        """Return the attached LayaActionPolicy (or None if not set)."""
        return self._laya_action_policy

    @property
    def has_laya_action_policy(self) -> bool:
        """True when a configured LAYA action selector is attached."""
        return (
            self._laya_action_policy is not None
            and getattr(self._laya_action_policy, "is_configured", lambda: False)()
        )

    async def decide_next_action(
        self,
        intent: StructuredIntent,
        world_state: SemanticWorldState,
        memory: SessionMemory,
        latest_reflection: ReflectionResult | None = None,
    ) -> CognitiveDecision:
        """Select the immediate browser action through LAYA only.

        The LLM remains responsible for macro reasoning and planning. This
        method is the sole browser-action selection boundary. Any unavailable,
        stale, low-confidence, timed-out, disabled, or otherwise unsafe LAYA
        decision fails closed; there is no alternative model or heuristic
        action-selection path.
        """
        logger.info("making_immediate_decision_via_laya", step=memory.current_step_index)

        policy = self._laya_action_policy
        if policy is None:
            raise DecisionUnavailableError(
                "LAYA action selector is not wired; browser action selection is blocked"
            )
        if not getattr(policy, "is_configured", lambda: False)():
            raise DecisionUnavailableError(
                "LAYA action selector is disabled; browser action selection is blocked"
            )

        plan_desc = ""
        plan_expected = ""
        if memory.plan and memory.plan.current_step:
            step = memory.plan.current_step
            plan_desc = step.description
            plan_expected = step.expected_outcome

        action_space = self._build_laya_action_space(
            world_state=world_state,
            memory=memory,
            plan_step=plan_desc,
            planned_values=self._build_laya_planned_values(intent, memory),
        )
        if action_space is None:
            raise DecisionUnavailableError(
                "No current browser observation is available for LAYA action selection"
            )

        try:
            laya_decision = await policy.choose_action(action_space)
        except Exception as exc:
            logger.error("laya_action_selection_failed_closed", error=str(exc))
            raise DecisionUnavailableError(
                f"LAYA action selection failed: {type(exc).__name__}: {exc}"
            ) from exc

        if not laya_decision or laya_decision.fallback_reason:
            reason = laya_decision.fallback_reason if laya_decision else "no_decision"
            logger.warning("laya_action_selection_blocked", reason=reason)
            raise DecisionUnavailableError(
                f"LAYA action selection unavailable: {reason}"
            )

        chosen_action = laya_decision.action
        if not chosen_action.metadata:
            chosen_action.metadata = {}
        chosen_action.metadata.update(
            {
                "action_source": "laya",
                "laya_source": True,
                "laya_operation": laya_decision.operation,
                "laya_target_index": laya_decision.target_index,
                "laya_confidence": laya_decision.confidence,
                "laya_inference_latency_ms": laya_decision.inference_latency_ms,
                "laya_model_version": laya_decision.model_version,
            }
        )

        confidence_assessment = self._confidence_engine.evaluate_confidence(
            action=chosen_action,
            world_state=world_state,
        )

        return CognitiveDecision(
            action=chosen_action,
            reasoning=(
                f"LAYA action selector chose {laya_decision.operation}"
                + (
                    f" on target index {laya_decision.target_index}"
                    if laya_decision.target_index is not None
                    else ""
                )
            ),
            expected_outcome=plan_expected or "Action executes successfully",
            confidence_assessment=confidence_assessment,
        )

    def _build_laya_planned_values(
        self,
        intent: StructuredIntent,
        memory: SessionMemory,
    ) -> dict[str, str]:
        """Collect already-reasoned values that LAYA may route to a field."""
        values: dict[str, str] = {}

        def add_mapping(mapping: Any) -> None:
            if not isinstance(mapping, dict):
                return
            for key, value in mapping.items():
                if key in {"action_type", "target"} or value is None:
                    continue
                if isinstance(value, (str, int, float, bool)):
                    text = str(value).strip()
                    if text:
                        values[str(key)] = text

        add_mapping(getattr(intent, "extracted_entities", None))
        current_step = (
            memory.plan.current_step
            if memory.plan and memory.plan.current_step
            else None
        )
        add_mapping(getattr(current_step, "expected_values", None))

        test_case_data = getattr(memory, "test_case_data", None) or {}
        if isinstance(test_case_data, dict):
            add_mapping(test_case_data.get("expected_values"))
            acceptance = test_case_data.get("acceptance_criteria", []) or []
            for item in acceptance:
                if not isinstance(item, dict):
                    continue
                field = str(
                    item.get("field") or item.get("field_path") or ""
                ).strip()
                expected = item.get("expected") or item.get("expected_value")
                if field and expected is not None:
                    values[field] = str(expected).strip()
        return values

    def _build_laya_action_space(
        self,
        world_state: SemanticWorldState,
        memory: SessionMemory,
        plan_step: str,
        planned_values: dict[str, str] | None = None,
    ) -> Any | None:
        """Build the bounded action space consumed by LAYA."""
        try:
            from agent.browser.action_space import BrowserActionSpace
        except ImportError:
            return None

        latest_obs = memory.observations[-1] if memory.observations else None
        if latest_obs is None:
            return None

        persona = getattr(memory, "persona", "") or "itil"
        return BrowserActionSpace.from_observation(
            observation=latest_obs,
            world_state=world_state,
            plan_step=plan_step,
            persona=persona,
            planned_values=planned_values or {},
        )

    def _heuristic_decision(
        self, world_state: SemanticWorldState, memory: SessionMemory
    ) -> AgentAction:
        """Legacy compatibility shim; arbitrary browser clicks are disabled."""
        raise DecisionUnavailableError(
            "Heuristic browser action fallback is disabled for autonomous safety"
        )
