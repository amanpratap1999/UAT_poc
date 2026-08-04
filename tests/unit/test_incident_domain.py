"""Unit tests for Incident Domain Models (Deliverable 1)."""

from __future__ import annotations

from agent.skills.incident.domain.models import (
    Assignment,
    Impact,
    Incident,
    IncidentPriority,
    IncidentState,
    Resolution,
    Urgency,
)


def test_incident_domain_model_defaults() -> None:
    """Test default creation of Incident domain object."""
    inc = Incident(
        number="INC0012345",
        state=IncidentState.NEW,
        short_description="Network degradation in datacenter",
    )

    assert inc.number == "INC0012345"
    assert inc.state == IncidentState.NEW
    assert inc.short_description == "Network degradation in datacenter"
    assert inc.assignment.group == ""
    assert inc.resolution.code == ""


def test_incident_state_parsing() -> None:
    """Test state string to IncidentState enum parsing."""
    assert IncidentState.from_string("New") == IncidentState.NEW
    assert IncidentState.from_string("In Progress") == IncidentState.IN_PROGRESS
    assert IncidentState.from_string("Resolved") == IncidentState.RESOLVED
    assert IncidentState.from_string("Closed") == IncidentState.CLOSED
