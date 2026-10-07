"""Unit tests for Agent State Machine (Deliverable 10)."""

from __future__ import annotations

import pytest

from agent.core.state_machine import AgentStateMachine, StateTransitionError
from agent.core.types import AgentState


def test_state_machine_valid_transitions() -> None:
    """Test valid explicit state transitions."""
    sm = AgentStateMachine(initial_state=AgentState.IDLE)
    assert sm.current_state == AgentState.IDLE

    sm.transition_to(AgentState.INTENT_ANALYSIS, reason="Parsing intent")
    assert sm.current_state == AgentState.INTENT_ANALYSIS

    sm.transition_to(AgentState.PLANNING, reason="Creating plan")
    assert sm.current_state == AgentState.PLANNING

    sm.transition_to(AgentState.OBSERVING, reason="Observing browser")
    assert sm.current_state == AgentState.OBSERVING

    sm.transition_to(AgentState.REASONING, reason="Reasoning over world state")
    assert sm.current_state == AgentState.REASONING

    assert len(sm.history) == 4


def test_state_machine_invalid_transition() -> None:
    """Test that invalid transitions raise StateTransitionError."""
    sm = AgentStateMachine(initial_state=AgentState.IDLE)

    with pytest.raises(StateTransitionError):
        # Direct jump from IDLE to EXECUTING is invalid
        sm.transition_to(AgentState.EXECUTING)
