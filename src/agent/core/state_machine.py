"""Agent State Machine — explicit formal state management.

Deliverable 10: Formalizes runtime states and explicit transitions:
  Idle -> Intent Analysis -> Planning -> Observation -> Reasoning -> Decision
  -> Execution -> Validation -> Reflection -> Learning -> Completed / Failed
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agent.core.exceptions import AgentError
from agent.core.logging import get_logger
from agent.core.types import AgentState

logger = get_logger(__name__)


class StateTransitionError(AgentError):
    """Raised when an invalid state transition is attempted."""


class StateTransitionEvent(BaseModel):
    """Record of a state transition event."""

    from_state: AgentState
    to_state: AgentState
    reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentStateMachine:
    """Explicit, formalized state machine for the cognitive agent loop.

    Valid transitions graph:
      IDLE -> INTENT_ANALYSIS
      INTENT_ANALYSIS -> PLANNING, FAILED
      PLANNING -> OBSERVATION, DECISION, FAILED
      OBSERVATION -> REASONING, DECISION, FAILED
      REASONING -> DECISION, REFLECTION, PLANNING, FAILED
      DECISION -> EXECUTING, RECOVERING, COMPLETED, FAILED
      EXECUTING -> OBSERVING, VALIDATING, FAILED
      VALIDATING -> REFLECTION, REASONING, FAILED
      REFLECTION -> LEARNING, REASONING, DECISION, RECOVERING, FAILED
      RECOVERING -> EXECUTING, REASONING, FAILED
      LEARNING -> REASONING, OBSERVATION, COMPLETED, FAILED
      COMPLETED -> IDLE
      FAILED -> IDLE
    """

    ALLOWED_TRANSITIONS: ClassVar[dict[AgentState, set[AgentState]]] = {
        AgentState.IDLE: {AgentState.INTENT_ANALYSIS, AgentState.PLANNING, AgentState.FAILED},
        AgentState.INTENT_ANALYSIS: {AgentState.PLANNING, AgentState.FAILED},
        AgentState.PLANNING: {
            AgentState.OBSERVING,
            AgentState.DECISION,
            AgentState.FAILED,
            AgentState.COMPLETED,
        },
        AgentState.OBSERVING: {
            AgentState.REASONING,
            AgentState.DECISION,
            AgentState.VALIDATING,
            AgentState.FAILED,
        },
        AgentState.REASONING: {
            AgentState.DECISION,
            AgentState.REFLECTION,
            AgentState.PLANNING,
            AgentState.OBSERVING,
            AgentState.COMPLETED,
            AgentState.FAILED,
        },
        AgentState.DECISION: {
            AgentState.EXECUTING,
            AgentState.RECOVERING,
            AgentState.COMPLETED,
            AgentState.FAILED,
        },
        AgentState.EXECUTING: {AgentState.OBSERVING, AgentState.VALIDATING, AgentState.FAILED},
        AgentState.VALIDATING: {AgentState.REFLECTION, AgentState.REASONING, AgentState.FAILED},
        AgentState.REFLECTION: {
            AgentState.LEARNING,
            AgentState.REASONING,
            AgentState.DECISION,
            AgentState.RECOVERING,
            AgentState.FAILED,
        },
        AgentState.RECOVERING: {
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            AgentState.REASONING,
            AgentState.FAILED,
        },
        AgentState.LEARNING: {
            AgentState.REASONING,
            AgentState.OBSERVING,
            AgentState.RECOVERING,
            AgentState.COMPLETED,
            AgentState.FAILED,
        },
        AgentState.COMPLETED: {AgentState.IDLE},
        AgentState.FAILED: {AgentState.IDLE},
    }

    def __init__(self, initial_state: AgentState = AgentState.IDLE) -> None:
        self._current_state = initial_state
        self._history: list[StateTransitionEvent] = []
        self._listeners: list[Callable[[StateTransitionEvent], None]] = []

    @property
    def current_state(self) -> AgentState:
        return self._current_state

    @property
    def history(self) -> list[StateTransitionEvent]:
        return list(self._history)

    def add_listener(self, listener: Callable[[StateTransitionEvent], None]) -> None:
        """Add a callback listener for state transitions."""
        self._listeners.append(listener)

    def transition_to(
        self,
        to_state: AgentState,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> StateTransitionEvent:
        """Attempt to transition to a new state.

        Args:
            to_state: Target state.
            reason: Explanation for transition.
            metadata: Optional additional metadata.

        Returns:
            The transition event.

        Raises:
            StateTransitionError: If the transition is not permitted.
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self._current_state, set())

        if to_state not in allowed and to_state != self._current_state:
            raise StateTransitionError(
                f"Invalid state transition from {self._current_state.value} to {to_state.value}. "
                f"Allowed target states: {[s.value for s in allowed]}",
                details={
                    "from_state": self._current_state.value,
                    "to_state": to_state.value,
                    "reason": reason,
                },
            )

        from_state = self._current_state
        self._current_state = to_state

        event = StateTransitionEvent(
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            metadata=metadata or {},
        )
        self._history.append(event)

        logger.info(
            "state_transition",
            from_state=from_state.value,
            to_state=to_state.value,
            reason=reason,
        )

        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.warning("state_listener_error", error=str(e))

        return event
