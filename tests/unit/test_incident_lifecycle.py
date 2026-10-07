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


def test_on_hold_transition_not_blocked_when_hold_reason_present() -> None:
    """QA-009: the On Hold Reason requirement must be satisfiable — the model
    and field getter must expose hold_reason so the transition isn't always
    blocked."""
    engine = LifecycleEngine()

    inc = Incident(
        number="INC001",
        state=IncidentState.IN_PROGRESS,
        short_description="Issue",
        caller="Admin",
        assignment=Assignment(group="Service Desk"),
        hold_reason="Awaiting Vendor",
    )

    assessment = engine.evaluate_transition(inc, IncidentState.ON_HOLD)

    assert assessment.is_blocked is False, assessment.block_reasons
    assert "On Hold Reason" not in assessment.missing_mandatory_fields


def test_on_hold_awaiting_caller_requires_additional_comments() -> None:
    """QA-009: conditional lifecycle rule — 'Awaiting Caller' makes Additional
    comments mandatory."""
    engine = LifecycleEngine()

    inc_no_comments = Incident(
        number="INC001",
        state=IncidentState.IN_PROGRESS,
        short_description="Issue",
        caller="Admin",
        assignment=Assignment(group="Service Desk"),
        hold_reason="Awaiting Caller",
    )
    assessment = engine.evaluate_transition(inc_no_comments, IncidentState.ON_HOLD)
    assert assessment.is_blocked is True
    assert "Additional comments" in assessment.missing_mandatory_fields

    inc_with_comments = inc_no_comments.model_copy(deep=True)
    inc_with_comments.work_notes.additional_comments = ["Customer notified"]
    assessment_ok = engine.evaluate_transition(inc_with_comments, IncidentState.ON_HOLD)
    assert assessment_ok.is_blocked is False, assessment_ok.block_reasons
