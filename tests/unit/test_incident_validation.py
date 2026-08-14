"""Unit tests for Incident Validation Intelligence (Deliverable 7)."""

from __future__ import annotations

from agent.skills.incident.domain.models import (
    Assignment,
    Impact,
    Incident,
    IncidentState,
    Resolution,
    Urgency,
)
from agent.skills.incident.validation import IncidentValidator


def test_validate_business_outcome_success() -> None:
    """Test validating successful incident business outcome."""
    validator = IncidentValidator()

    before = Incident(
        number="INC001",
        state=IncidentState.NEW,
        impact=Impact.HIGH,
        urgency=Urgency.HIGH,
    )
    after = Incident(
        number="INC001",
        state=IncidentState.RESOLVED,
        impact=Impact.HIGH,
        urgency=Urgency.HIGH,
        priority=__import__(
            "agent.skills.incident.domain.models", fromlist=["IncidentPriority"]
        ).IncidentPriority.CRITICAL,
        assignment=Assignment(group="Service Desk"),
        resolution=Resolution(code="Solved (Permanently)", notes="Fixed bug"),
    )

    res = validator.validate_business_outcome(before, after, expected_step="Resolve Incident")

    assert res.passed is True
    assert res.incident_number == "INC001"


def test_validate_business_outcome_priority_mismatch() -> None:
    """Test validating priority matrix mismatch."""
    validator = IncidentValidator()

    before = Incident(number="INC001", impact=Impact.HIGH, urgency=Urgency.HIGH)
    after = Incident(
        number="INC001",
        impact=Impact.HIGH,
        urgency=Urgency.HIGH,
        # Priority should be CRITICAL (1), but set to LOW (4)
        priority=__import__(
            "agent.skills.incident.domain.models", fromlist=["IncidentPriority"]
        ).IncidentPriority.LOW,
    )

    res = validator.validate_business_outcome(before, after, expected_step="Check Priority Matrix")

    assert res.passed is False
    assert "Priority calculation mismatch" in (res.error_message or "")
