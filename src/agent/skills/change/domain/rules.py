"""Deterministic domain rules for Change Management."""

from typing import ClassVar

from agent.skills.change.domain.models import ChangeState, ChangeType


class ChangeBusinessRules:
    """Evaluates valid transitions and required fields for Change Requests."""

    # Expected standard state progression
    _STATE_FLOW: ClassVar[dict[ChangeState, list[ChangeState]]] = {
        ChangeState.NEW: [ChangeState.ASSESS, ChangeState.CANCELED],
        ChangeState.ASSESS: [ChangeState.AUTHORIZE, ChangeState.CANCELED],
        ChangeState.AUTHORIZE: [ChangeState.SCHEDULED, ChangeState.CANCELED],
        ChangeState.SCHEDULED: [ChangeState.IMPLEMENT, ChangeState.CANCELED],
        ChangeState.IMPLEMENT: [ChangeState.REVIEW, ChangeState.CANCELED],
        ChangeState.REVIEW: [ChangeState.CLOSED, ChangeState.CANCELED],
        ChangeState.CLOSED: [],
        ChangeState.CANCELED: [],
    }

    @classmethod
    def is_valid_transition(cls, current: ChangeState | None, target: ChangeState | None) -> bool:
        """Check if a state transition is valid under default rules."""
        if current is None or target is None:
            return True  # Not enough info to fail
        if current == target:
            return True
        valid_next_states = cls._STATE_FLOW.get(current, [])
        return target in valid_next_states

    @classmethod
    def get_mandatory_fields_for_state(
        cls, state: ChangeState, change_type: ChangeType
    ) -> list[str]:
        """Get deterministically expected mandatory fields by state."""
        fields = ["short_description", "assignment_group"]

        if state in (ChangeState.ASSESS, ChangeState.AUTHORIZE):
            fields.extend(
                [
                    "justification",
                    "risk_impact_analysis",
                    "implementation_plan",
                    "backout_plan",
                    "test_plan",
                ]
            )

        return fields
