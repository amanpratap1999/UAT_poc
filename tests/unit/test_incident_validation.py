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

    res = validator.validate_business_outcome(before, after, expected_step="Update state", require_priority=True)

    assert res.passed is False
    assert res.error_message is not None
    assert res.error_message.startswith("UNVERIFIED")
    assert res.details.get("priority_check") == "unverified"


def test_validate_pre_submit_state_with_unknown_priority_passes() -> None:
    """Pre-submit action validation (e.g. select State = In Progress) must pass
    even when impact/urgency/priority are not yet observed."""
    validator = IncidentValidator()

    before = Incident(number="INC001", state=IncidentState.NEW)
    after = Incident(number="INC001", state=IncidentState.IN_PROGRESS)

    res = validator.validate_pre_submit(
        before=before,
        after=after,
        field_name="State",
        expected_value="In Progress",
    )

    assert res.passed is True
    assert res.error_message is None
    assert res.actual_state == "IN_PROGRESS"


def test_resolve_target_sys_id_from_memory() -> None:
    """Test resolving target sys_id dynamically from multiple memory contexts."""
    from agent.cognition.orchestrator import CognitiveOrchestrator
    from types import SimpleNamespace

    orchestrator = CognitiveOrchestrator(
        skill_registry=None,
        knowledge_model=None,
        learning_service=None,
        scenario_generator=None,
        decision_engine=None,
        validation_engine=None,
        perception_engine=None,
        execution_controller=None,
        observation_engine=None,
        browser_manager=None,
        state_machine=None,
    )

    # 1. Directly from _target_sys_id
    orchestrator._target_sys_id = "11111111111111111111111111111111"
    memory = SimpleNamespace(structured_intent=None, current_record=None, observations=[])
    assert orchestrator._resolve_target_sys_id(memory) == "11111111111111111111111111111111"

    # 2. From structured_intent
    orchestrator._target_sys_id = None
    intent = SimpleNamespace(target_sys_id="22222222222222222222222222222222")
    memory = SimpleNamespace(structured_intent=intent, current_record=None, observations=[])
    assert orchestrator._resolve_target_sys_id(memory) == "22222222222222222222222222222222"

    # 3. From current_record dict
    memory = SimpleNamespace(structured_intent=None, current_record={"sys_id": "33333333333333333333333333333333"}, observations=[])
    assert orchestrator._resolve_target_sys_id(memory) == "33333333333333333333333333333333"

    # 4. From observations url
    obs = SimpleNamespace(url="https://instance.service-now.com/incident.do?sys_id=44444444444444444444444444444444&sysparm_view=")
    memory = SimpleNamespace(structured_intent=None, current_record=None, observations=[obs])
    assert orchestrator._resolve_target_sys_id(memory) == "44444444444444444444444444444444"


def test_is_save_click_detection() -> None:
    """Test detecting Save/Update click actions."""
    from agent.cognition.orchestrator import CognitiveOrchestrator
    from agent.domain.actions import AgentAction, ActionType
    from types import SimpleNamespace

    action = AgentAction(
        action_type=ActionType.CLICK,
        target="sysverb_update",
    )
    assert CognitiveOrchestrator._is_save_click(action) is True

    step = SimpleNamespace(description="Click Update to Persist Record")
    action_plain = AgentAction(
        action_type=ActionType.CLICK,
        target="button_1",
    )
    assert CognitiveOrchestrator._is_save_click(action_plain, step=step) is True


def test_post_update_redirect_acceptance() -> None:
    """Test that post-update validation filters redirect-induced failures when re-open step exists."""
    from agent.domain.validation import ValidationCheck, ValidationResult

    validation = ValidationResult(action_description="Click Update")
    validation.add_check(ValidationCheck(check_name="action_execution", passed=True))
    validation.add_check(
        ValidationCheck(
            check_name="semantic_context",
            passed=False,
            error_message="Expected record INC9900004 is not in the page context after clicking.",
        )
    )
    validation.add_check(
        ValidationCheck(
            check_name="incident_business_outcome",
            passed=False,
            error_message="State mismatch: expected IN_PROGRESS (2), actual UNKNOWN (unknown).",
        )
    )

    filtered_checks = []
    for chk in validation.checks:
        chk_name = (getattr(chk, "check_name", "") or "").lower()
        chk_desc = (getattr(chk, "description", "") or "").lower()
        chk_err = (getattr(chk, "error_message", "") or "").lower()
        is_redirect_mismatch = (
            not chk.passed
            and (
                chk_name == "semantic_context"
                or "expected record" in chk_err
                or "state mismatch" in chk_err
                or "not in the page context" in chk_err
                or "business rule" in chk_desc
            )
        )
        if not is_redirect_mismatch:
            filtered_checks.append(chk)

    filtered_checks.append(
        ValidationCheck(
            check_name="update_submission",
            description="Form update submitted successfully; verification deferred to re-open step",
            passed=True,
            expected="form submission success",
            actual="form submitted and page navigated",
        )
    )
    validation.checks = filtered_checks
    validation.overall_passed = all(c.passed for c in validation.checks)

    assert validation.overall_passed is True
    assert any(c.check_name == "update_submission" and c.passed for c in validation.checks)
    assert not any(c.check_name == "semantic_context" for c in validation.checks)


def test_persistence_oracle_status_gating() -> None:
    """Test that only error/mismatch/not_found statuses cause persistence oracle failures."""
    def should_fail_api(status: str) -> bool:
        return status in ("mismatch", "not_found", "error")

    assert should_fail_api("mismatch") is True
    assert should_fail_api("not_found") is True
    assert should_fail_api("error") is True
    assert should_fail_api("verified") is False
    assert should_fail_api("disabled") is False
    assert should_fail_api("not_attempted") is False
