"""Unit tests for Reasoning Trace (Deliverable 7)."""

from __future__ import annotations

from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.reasoning.trace import ReasoningTrace


def test_reasoning_trace_recording() -> None:
    """Test recording cycles in reasoning trace."""
    trace = ReasoningTrace()

    action = AgentAction(action_type=ActionType.CLICK, target="text:Submit", reasoning="Submit form")
    cycle = trace.record_cycle(
        step_index=1,
        state_name="reasoning",
        observation_summary="On incident creation form",
        hypotheses=["Form is ready"],
        decision_rationale="Click submit",
        chosen_action=action,
        confidence_score=0.95,
    )

    assert len(trace.cycles) == 1
    assert cycle.step_index == 1
    assert cycle.confidence_score == 0.95

    log = trace.to_readable_log()
    assert "REASONING TRACE LOG" in log
    assert "Click submit" in log
