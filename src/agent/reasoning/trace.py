"""Reasoning Trace implementation for Deliverable 7.

Maintains an auditable, step-by-step cognitive reasoning trace for every
reasoning cycle (observation -> hypothesis -> decision -> confidence -> outcome -> reflection).
Hidden from end-users by default; available for debugging and analysis.
"""

from __future__ import annotations

from typing import Any

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.reflection import ReasoningCycle, ReflectionResult

logger = get_logger(__name__)


class ReasoningTrace:
    """Audit logger for tracking cognitive reasoning cycles."""

    def __init__(self) -> None:
        self._cycles: list[ReasoningCycle] = []

    def record_cycle(
        self,
        step_index: int,
        state_name: str,
        observation_summary: str,
        hypotheses: list[str] | None = None,
        decision_rationale: str = "",
        chosen_action: AgentAction | None = None,
        confidence_score: float = 1.0,
        outcome_summary: str = "",
        reflection: ReflectionResult | None = None,
    ) -> ReasoningCycle:
        """Record a cognitive reasoning cycle.

        Returns:
            The recorded ReasoningCycle model.
        """
        cycle = ReasoningCycle(
            step_index=step_index,
            state_name=state_name,
            observation_summary=observation_summary,
            hypotheses=hypotheses or [],
            decision_rationale=decision_rationale,
            chosen_action=chosen_action,
            confidence_score=confidence_score,
            outcome_summary=outcome_summary,
            reflection=reflection,
        )
        self._cycles.append(cycle)
        logger.debug("reasoning_cycle_recorded", step=step_index, state=state_name, confidence=confidence_score)
        return cycle

    @property
    def cycles(self) -> list[ReasoningCycle]:
        """Return all recorded reasoning cycles."""
        return list(self._cycles)

    def get_summary_dict(self) -> list[dict[str, Any]]:
        """Return machine-readable list of reasoning cycle summaries."""
        return [c.model_dump(mode="json") for c in self._cycles]

    def to_readable_log(self) -> str:
        """Format reasoning trace as a human-readable text block for debugging."""
        lines = ["=== REASONING TRACE LOG ==="]
        for c in self._cycles:
            lines.append(f"\n[Step {c.step_index}] State: {c.state_name} (Confidence: {c.confidence_score:.2f})")
            lines.append(f"  Observation: {c.observation_summary[:120]}")
            if c.decision_rationale:
                lines.append(f"  Rationale: {c.decision_rationale}")
            if c.chosen_action:
                lines.append(f"  Chosen Action: {c.chosen_action.action_type} -> {c.chosen_action.target}")
            if c.hypotheses:
                lines.append(f"  Hypotheses: {'; '.join(c.hypotheses)}")
            if c.reflection:
                lines.append(f"  Reflection: expected='{c.reflection.expected_outcome}', adaptation='{c.reflection.recommended_plan_adaptation or 'none'}'")
        return "\n".join(lines)
