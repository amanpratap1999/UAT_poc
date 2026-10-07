"""Reflection Engine for Deliverable 5.

Purpose:
- Evaluates expected vs observed state.
- Forms hypotheses when discrepancies occur (e.g. page loading delay).
- Recommends intelligent plan adaptations instead of blind retries.
"""

from __future__ import annotations

from agent.core.logging import get_logger
from agent.core.untrusted import UNTRUSTED_DATA_POLICY, wrap_untrusted, scan_for_injection
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.reflection import ReflectionResult
from agent.domain.world import SemanticWorldState
from agent.planner.llm_client import BaseLLMClient

logger = get_logger(__name__)

REFLECTION_PROMPT = """Reflect on the outcome of the following browser action in ServiceNow.

Action Executed: {action_description}
Expected Outcome: {expected_outcome}
Observed World State: {world_state_summary}
Action Result Success: {success}
Action Error: {error}

Analyze why the discrepancy occurred (if any) and suggest a cognitive adaptation.
Consider:
1. Is the page still loading?
2. Are mandatory fields missing?
3. Did permissions or element visibility block the action?

Respond with a JSON object:
{{
    "is_as_expected": true/false,
    "hypotheses": ["hypothesis 1", "hypothesis 2"],
    "recommended_plan_adaptation": "suggested next step adaptation",
    "confidence": 0.85
}}
"""


class ReflectionEngine:
    """Evaluates action execution and forms cognitive hypotheses for unexpected outcomes."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self._llm = llm_client

    async def reflect(
        self,
        action: AgentAction,
        result: ActionResult,
        world_state: SemanticWorldState,
        expected_outcome: str = "",
    ) -> ReflectionResult:
        """Reflect on an action outcome against the semantic world state.

        Args:
            action: Action that was taken.
            result: ActionResult from execution.
            world_state: Post-action SemanticWorldState.
            expected_outcome: Expected outcome description.

        Returns:
            A ReflectionResult with hypotheses and adaptations.
        """
        logger.info("reflecting_on_action", action=action.action_type, success=result.success)

        target_safe = wrap_untrusted("action.target", action.target)
        value_safe = wrap_untrusted("action.value", action.value)
        state_safe = wrap_untrusted("world_state", world_state.to_compact_cognitive_summary())
        error_str = result.error or "None"
        error_safe = wrap_untrusted("result.error", error_str)

        if (scan_for_injection(action.target) or scan_for_injection(action.value) or 
            scan_for_injection(world_state.to_compact_cognitive_summary()) or scan_for_injection(error_str)):
            logger.warning("prompt_injection_detected_in_reflection")

        action_desc = f"{action.action_type} on '{target_safe}' (value: '{value_safe}')"
        if not expected_outcome:
            expected_outcome = f"Page responds to {action.action_type}"

        if self._llm:
            try:
                response = await self._llm.complete_json(
                    messages=[
                        {
                            "role": "system",
                            "content": f"You are a Cognitive Reflection Engine evaluating autonomous agent actions.\n\n{UNTRUSTED_DATA_POLICY}",  # noqa: E501
                        },
                        {
                            "role": "user",
                            "content": REFLECTION_PROMPT.format(
                                action_description=action_desc,
                                expected_outcome=expected_outcome,
                                world_state_summary=state_safe,
                                success=result.success,
                                error=error_safe,
                            ),
                        },
                    ]
                )
                return ReflectionResult(
                    action_evaluated=action_desc,
                    expected_outcome=expected_outcome,
                    observed_outcome=world_state.to_compact_cognitive_summary(),
                    is_as_expected=bool(response.get("is_as_expected", result.success)),
                    hypotheses=response.get("hypotheses", []),
                    recommended_plan_adaptation=response.get("recommended_plan_adaptation"),
                    confidence=float(response.get("confidence", 0.9)),
                )
            except Exception as e:
                logger.warning("llm_reflection_failed_fallback_to_heuristics", error=str(e))

        # Heuristic fallback reflection logic
        hypotheses = []
        adaptation = None
        is_expected = result.success

        if not result.success:
            if "not found" in (result.error or "").lower():
                hypotheses.append("Element selector not visible on current page layout")
                adaptation = "Wait for network idle or re-observe page elements"
            else:
                hypotheses.append(f"Execution error: {result.error}")
                adaptation = "Observe page and search documentation"
        elif world_state.missing_mandatory_fields and action.target.lower() in (
            "resolve",
            "submit",
        ):
            is_expected = False
            hypotheses.append(
                f"Action blocked by missing mandatory fields: {', '.join(world_state.missing_mandatory_fields)}"  # noqa: E501
            )
            adaptation = f"Fill mandatory fields: {', '.join(world_state.missing_mandatory_fields)}"

        return ReflectionResult(
            action_evaluated=action_desc,
            expected_outcome=expected_outcome,
            observed_outcome=world_state.to_compact_cognitive_summary(),
            is_as_expected=is_expected,
            hypotheses=hypotheses or ["Action executed as expected"],
            recommended_plan_adaptation=adaptation,
            confidence=0.9 if is_expected else 0.6,
        )
