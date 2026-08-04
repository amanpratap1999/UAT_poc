"""Unit tests for Incident Knowledge Model (Deliverable 2)."""

from __future__ import annotations

from agent.skills.incident.domain.models import Impact, IncidentPriority, IncidentState, Urgency
from agent.skills.incident.knowledge.rules import IncidentBusinessRules, IncidentLifecycle


def test_priority_matrix_calculation() -> None:
    """Test Impact x Urgency Priority Matrix calculation."""
    # High x High = Critical (1)
    assert IncidentBusinessRules.calculate_priority(Impact.HIGH, Urgency.HIGH) == IncidentPriority.CRITICAL

    # High x Medium = High (2)
    assert IncidentBusinessRules.calculate_priority(Impact.HIGH, Urgency.MEDIUM) == IncidentPriority.HIGH

    # Low x Low = Planning (5)
    assert IncidentBusinessRules.calculate_priority(Impact.LOW, Urgency.LOW) == IncidentPriority.PLANNING


def test_incident_lifecycle_transitions() -> None:
    """Test valid vs invalid lifecycle state transitions."""
    # New -> In Progress: Valid
    assert IncidentLifecycle.is_valid_transition(IncidentState.NEW, IncidentState.IN_PROGRESS) is True

    # New -> Closed: Invalid
    assert IncidentLifecycle.is_valid_transition(IncidentState.NEW, IncidentState.CLOSED) is False

    # In Progress -> Resolved: Valid
    assert IncidentLifecycle.is_valid_transition(IncidentState.IN_PROGRESS, IncidentState.RESOLVED) is True


def test_mandatory_fields_per_state() -> None:
    """Test mandatory required fields per target state."""
    resolved_fields = IncidentBusinessRules.get_mandatory_fields_for_state(IncidentState.RESOLVED)
    assert "Resolution Code" in resolved_fields
    assert "Resolution Notes" in resolved_fields
