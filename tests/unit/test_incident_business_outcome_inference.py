"""Regression tests: incident business-outcome validation must not infer the
expected state from free-text reasoning that mentions BOTH the from-state and
the to-state.

Reproduces the live false-positive from E2E run RPT-83661773 (2026-09-12):
the select-action reasoning was "The current incident state is 'On Hold'
(value 3). ... Selecting '2' will change the state to In Progress ..." and
the keyword matcher latched onto "hold" → expected ON_HOLD after a successful
select of In Progress → false DEFECT.
"""

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
from agent.skills.incident.validation import IncidentValidator

REASONING_BOTH_STATES = (
    "The current incident state is 'On Hold' (value 3). According to the plan, "
    "Step 2 is to update the state to 'In Progress' (value 2). The State field "
    "is a choice list/dropdown on the incident form. Selecting '2' will change "
    "the state to In Progress before we click Update in the next step."
)

REASONING_UNAMBIGUOUS_HOLD = (
    "The incident is on hold awaiting caller; put the record On Hold by "
    "selecting hold reason Awaiting Caller."
)


def _incident(state: IncidentState) -> Incident:
    # impact/urgency/priority kept matrix-consistent (LOW x LOW -> PLANNING),
    # matching how IncidentObserver builds incidents in live runs (it derives
    # priority from impact x urgency, never from the displayed field).
    return Incident(
        number="INC0000007",
        state=state,
        short_description="Need access to sales DB for the West",
        caller="Joe Employee",
        assignment=Assignment(group="Service Desk"),
        resolution=Resolution(code="", notes=""),
        priority=IncidentPriority.PLANNING,
        impact=Impact.LOW,
        urgency=Urgency.LOW,
    )


def _default_before() -> Incident:
    return _incident(IncidentState.ON_HOLD)


class TestBusinessOutcomeStateInference:
    def test_select_to_in_progress_with_hold_in_reasoning_passes(self) -> None:
        """The live RPT-83661773 scenario: select 2 (In Progress) succeeded but
        free-text reasoning also mentions 'On Hold' — must PASS, not defect."""
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_default_before(),
            after=_incident(IncidentState.IN_PROGRESS),
            expected_step=REASONING_BOTH_STATES,
            expected_state="2",  # the select action's authoritative value
        )
        assert result.passed is True, result.error_message
        assert result.error_message is None

    def test_ambiguous_reasoning_without_explicit_state_skips_inference(self) -> None:
        """No explicit value and text mentions two states: keyword inference
        must be skipped entirely (no false expectation manufactured)."""
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_default_before(),
            after=_incident(IncidentState.IN_PROGRESS),
            expected_step=REASONING_BOTH_STATES,
        )
        assert result.passed is True, result.error_message

    def test_unambiguous_hold_reasoning_still_enforces_on_hold(self) -> None:
        """Single-state text ('On Hold' only) still infers ON_HOLD — a select
        that produced IN_PROGRESS must still fail (true positive)."""
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_incident(IncidentState.IN_PROGRESS),
            after=_incident(IncidentState.IN_PROGRESS),
            expected_step=REASONING_UNAMBIGUOUS_HOLD,
        )
        assert result.passed is False
        assert "ON_HOLD" in (result.error_message or "")

    def test_explicit_expected_state_mismatch_still_fails(self) -> None:
        """Explicit value remains authoritative: expected 3 but observed 2 -> fail."""
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_default_before(),
            after=_incident(IncidentState.IN_PROGRESS),
            expected_step="Select the State dropdown",
            expected_state="3",
        )
        assert result.passed is False
        assert "State mismatch" in (result.error_message or "")

    def test_explicit_state_accepts_label_string(self) -> None:
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_default_before(),
            after=_incident(IncidentState.IN_PROGRESS),
            expected_step=REASONING_BOTH_STATES,
            expected_state="In Progress",
        )
        assert result.passed is True, result.error_message

    def test_resolve_step_still_requires_resolution_fields(self) -> None:
        v = IncidentValidator()
        result = v.validate_business_outcome(
            before=_incident(IncidentState.IN_PROGRESS),
            after=_incident(IncidentState.RESOLVED),
            expected_step="Fill resolution details and resolve the incident",
        )
        # State inference is skipped (ambiguous: 'resolve' + 'resolved' both
        # present is fine — resolves to RESOLVED via single candidate).
        assert result.passed is False  # missing resolution code/notes
        assert "Resolution" in (result.error_message or "")
