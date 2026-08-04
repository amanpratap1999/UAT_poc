"""Incident Knowledge Model for Deliverable 2.

Centralizes all ServiceNow Incident Management business rules, valid state transitions,
mandatory field requirements per transition, and Priority Matrix calculations.
"""

from __future__ import annotations

from agent.skills.incident.domain.models import (
    Impact,
    IncidentPriority,
    IncidentState,
    Urgency,
)


class IncidentLifecycle:
    """Defines valid state transitions for ServiceNow Incident Management."""

    # Map current state -> allowed next states
    VALID_TRANSITIONS: dict[IncidentState, set[IncidentState]] = {
        IncidentState.NEW: {IncidentState.IN_PROGRESS, IncidentState.CANCELED},
        IncidentState.IN_PROGRESS: {IncidentState.ON_HOLD, IncidentState.RESOLVED, IncidentState.CANCELED},
        IncidentState.ON_HOLD: {IncidentState.IN_PROGRESS, IncidentState.RESOLVED, IncidentState.CANCELED},
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


class IncidentBusinessRules:
    """Calculates priority and determines mandatory fields for Incident transitions."""

    # Priority matrix lookup table: (impact, urgency) -> IncidentPriority
    _PRIORITY_MATRIX: dict[tuple[Impact, Urgency], IncidentPriority] = {
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

    # Mandatory fields per state transition target
    _TRANSITION_MANDATORY_FIELDS: dict[IncidentState, list[str]] = {
        IncidentState.NEW: ["Short Description", "Caller"],
        IncidentState.IN_PROGRESS: ["Short Description", "Caller", "Assignment Group"],
        IncidentState.ON_HOLD: ["Short Description", "Caller", "Assignment Group", "On Hold Reason"],
        IncidentState.RESOLVED: [
            "Short Description",
            "Caller",
            "Assignment Group",
            "Resolution Code",
            "Resolution Notes",
        ],
        IncidentState.CLOSED: ["Resolution Code", "Resolution Notes"],
    }

    @classmethod
    def calculate_priority(cls, impact: Impact, urgency: Urgency) -> IncidentPriority:
        """Calculate Priority from Impact x Urgency according to ServiceNow standard matrix.

        Args:
            impact: High (1), Medium (2), Low (3)
            urgency: High (1), Medium (2), Low (3)

        Returns:
            Calculated IncidentPriority.
        """
        return cls._PRIORITY_MATRIX.get((impact, urgency), IncidentPriority.MODERATE)

    @classmethod
    def get_mandatory_fields_for_state(cls, target_state: IncidentState) -> list[str]:
        """Get required mandatory fields to transition into or save in target state."""
        return cls._TRANSITION_MANDATORY_FIELDS.get(target_state, ["Short Description", "Caller"])
