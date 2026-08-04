"""Unit tests for Incident Lifecycle Intelligence (Deliverable 6)."""

from __future__ import annotations

from agent.skills.incident.domain.models import Assignment, Incident, IncidentState, Resolution
from agent.skills.incident.lifecycle import LifecycleEngine


def test_evaluate_valid_transition() -> None:
    """Test valid transition with mandatory fields populated."""
    engine = LifecycleEngine()

    inc = Incident(
        number="INC001",
        state=IncidentState.NEW,
        short_description="Issue",
        caller="Admin",
        assignment=Assignment(group="Service Desk"),
    )

    assessment = engine.evaluate_transition(inc, IncidentState.IN_PROGRESS)

    assert assessment.is_valid_transition is True
    assert assessment.is_blocked is False


def test_evaluate_blocked_transition_missing_mandatory() -> None:
    """Test valid transition blocked by missing mandatory resolution fields."""
    engine = LifecycleEngine()

    inc = Incident(
        number="INC001",
        state=IncidentState.IN_PROGRESS,
        short_description="Issue",
        caller="Admin",
        assignment=Assignment(group="Service Desk"),
        resolution=Resolution(code="", notes=""),
    )

    assessment = engine.evaluate_transition(inc, IncidentState.RESOLVED)

    assert assessment.is_valid_transition is True
    assert assessment.is_blocked is True
    assert "Resolution Code" in assessment.missing_mandatory_fields
