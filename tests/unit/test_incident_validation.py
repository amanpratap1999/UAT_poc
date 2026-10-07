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


def test_validate_precondition_missing_record_number_fails() -> None:
    """QA-011: an expected record precondition must FAIL when no incident
    number was observed on the page — silence is not a pass."""
    validator = IncidentValidator()

    inc = Incident(state=IncidentState.NEW)

    res = validator.validate_precondition(inc, expected_record="INC0000007")

    assert res.passed is False
    assert res.error_message is not None
    assert "no incident number was observed" in res.error_message


def test_validate_precondition_unparseable_expected_state_fails() -> None:
    """QA-011: an unresolvable expected state fails closed instead of
    passing against an UNKNOWN actual state."""
    validator = IncidentValidator()

    inc = Incident(number="INC001")  # state defaults to UNKNOWN

    res = validator.validate_precondition(inc, expected_state="Gibberish")

    assert res.passed is False


def test_validate_precondition_unknown_actual_state_fails() -> None:
    """QA-011: an unobserved actual state cannot satisfy a valid expectation."""
    validator = IncidentValidator()

    inc = Incident(number="INC001")  # state UNKNOWN

    res = validator.validate_precondition(inc, expected_state="New")

    assert res.passed is False
    assert res.error_message is not None
    assert "was not observed" in res.error_message


def test_validate_business_outcome_unverified_priority_fails() -> None:
    """QA-004: unobserved impact/urgency/priority must yield UNVERIFIED, not a
    fabricated LOW-vs-LOW pass."""
    validator = IncidentValidator()

    before = Incident(number="INC001", state=IncidentState.NEW)
    after = Incident(number="INC001", state=IncidentState.IN_PROGRESS)

    res = validator.validate_business_outcome(before, after, expected_step="Update state")

    assert res.passed is False
    assert res.error_message is not None
    assert res.error_message.startswith("UNVERIFIED")
    assert res.details.get("priority_check") == "unverified"
