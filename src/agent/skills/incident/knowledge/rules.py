"""Incident Knowledge Model for Deliverable 2.

Centralizes all ServiceNow Incident Management business rules, valid state transitions,
mandatory field requirements per transition, and Priority Matrix calculations.
"""

from __future__ import annotations

from typing import ClassVar

from agent.skills.incident.domain.models import (
    Impact,
    IncidentPriority,
    IncidentState,
    Urgency,
)


class IncidentLifecycle:
    """Defines valid state transitions for ServiceNow Incident Management."""

    # Map current state -> allowed next states
    VALID_TRANSITIONS: ClassVar[dict[IncidentState, set[IncidentState]]] = {
        IncidentState.NEW: {IncidentState.IN_PROGRESS, IncidentState.CANCELED},
        IncidentState.IN_PROGRESS: {
            IncidentState.ON_HOLD,
            IncidentState.RESOLVED,
            IncidentState.CANCELED,
        },
        IncidentState.ON_HOLD: {
            IncidentState.IN_PROGRESS,
            IncidentState.RESOLVED,
            IncidentState.CANCELED,
        },
        IncidentState.RESOLVED: {IncidentState.IN_PROGRESS, IncidentState.CLOSED},
        IncidentState.CLOSED: set(),
        IncidentState.CANCELED: set(),
    }

    @classmethod
    def is_valid_transition(cls, current: IncidentState, target: IncidentState) -> bool:
        """Check if transition from current to target state is permitted."""
        allowed = cls.VALID_TRANSITIONS.get(current, set())
        return target in allowed

    @classmethod
    def get_allowed_transitions(cls, current: IncidentState) -> set[IncidentState]:
        """Get set of allowed target states from current state."""
        return cls.VALID_TRANSITIONS.get(current, set())

    SIDE_EFFECT_MAP: ClassVar[dict[tuple[IncidentState, IncidentState], list[str]]] = {
        (IncidentState.NEW, IncidentState.IN_PROGRESS): ["audit:state", "sla:start"],
        (IncidentState.IN_PROGRESS, IncidentState.ON_HOLD): ["audit:state", "sla:pause", "notification:on_hold"],
        (IncidentState.ON_HOLD, IncidentState.IN_PROGRESS): ["audit:state", "sla:resume"],
        (IncidentState.IN_PROGRESS, IncidentState.RESOLVED): ["audit:state", "notification:resolved", "sla:stop"],
        (IncidentState.RESOLVED, IncidentState.CLOSED): ["audit:state", "notification:closed"],
        (IncidentState.RESOLVED, IncidentState.IN_PROGRESS): ["audit:state", "sla:restart"],
    }

    @classmethod
    def expected_side_effects(cls, from_state: IncidentState, to_state: IncidentState) -> list[str]:
        return cls.SIDE_EFFECT_MAP.get((from_state, to_state), [])


class IncidentBusinessRules:
    """Calculates priority and determines mandatory fields for Incident transitions."""

    # Priority matrix lookup table: (impact, urgency) -> IncidentPriority
    _PRIORITY_MATRIX: ClassVar[dict[tuple[Impact, Urgency], IncidentPriority]] = {
        (Impact.HIGH, Urgency.HIGH): IncidentPriority.CRITICAL,
        (Impact.HIGH, Urgency.MEDIUM): IncidentPriority.HIGH,
        (Impact.HIGH, Urgency.LOW): IncidentPriority.MODERATE,
        (Impact.MEDIUM, Urgency.HIGH): IncidentPriority.HIGH,
        (Impact.MEDIUM, Urgency.MEDIUM): IncidentPriority.MODERATE,
        (Impact.MEDIUM, Urgency.LOW): IncidentPriority.LOW,
        (Impact.LOW, Urgency.HIGH): IncidentPriority.MODERATE,
        (Impact.LOW, Urgency.MEDIUM): IncidentPriority.LOW,
        (Impact.LOW, Urgency.LOW): IncidentPriority.PLANNING,
    }

    @classmethod
    def calculate_priority(cls, impact: Impact, urgency: Urgency) -> IncidentPriority:
        """Calculate expected Priority from Impact x Urgency according to ServiceNow standard matrix."""
        return cls._PRIORITY_MATRIX.get((impact, urgency), IncidentPriority.MODERATE)

    # Mandatory fields per state transition target
    _TRANSITION_MANDATORY_FIELDS: ClassVar[dict[IncidentState, list[str]]] = {
        IncidentState.NEW: ["Short Description", "Caller"],
        IncidentState.IN_PROGRESS: ["Short Description", "Caller", "Assignment Group"],
        IncidentState.ON_HOLD: [
            "Short Description",
            "Caller",
            "Assignment Group",
            "On Hold Reason",
        ],
        IncidentState.RESOLVED: [
            "Short Description",
            "Caller",
            "Assignment Group",
            "Resolution Code",
            "Resolution Notes",
        ],
        IncidentState.CLOSED: ["Resolution Code", "Resolution Notes"],
    }

    # Conditional mandatory rules: placing an incident On Hold with a specific
    # reason makes additional fields mandatory (QA-009).
    _ON_HOLD_CONDITIONAL_RULES: ClassVar[dict[str, list[str]]] = {
        "awaiting caller": ["Additional comments"],
    }

    @classmethod
    def get_conditional_mandatory_fields(
        cls, target_state: IncidentState, hold_reason: str
    ) -> list[str]:
        """Get fields that become mandatory due to conditional lifecycle rules.

        Args:
            target_state: State being transitioned into.
            hold_reason: On Hold Reason currently set on the record.

        Returns:
            List of additional mandatory field labels (may be empty).
        """
        if target_state != IncidentState.ON_HOLD:
            return []
        reason = (hold_reason or "").strip().lower()
        return list(cls._ON_HOLD_CONDITIONAL_RULES.get(reason, []))

    @classmethod
    def get_mandatory_fields_for_state(cls, target_state: IncidentState) -> list[str]:
        """Get required mandatory fields to transition into or save in target state."""
        return cls._TRANSITION_MANDATORY_FIELDS.get(target_state, ["Short Description", "Caller"])
