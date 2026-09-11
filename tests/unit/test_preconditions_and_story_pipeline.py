"""Unit tests verifying Precondition validation, Story-to-Test-Case pipeline, and QA status rules.

Acceptance criteria verified:
1. Mismatched initial state results in PRECONDITION_FAILED (not application defect).
2. ReportingEngine sets status to precondition_failed and defect_count=0.
3. Story-to-test-case decomposition outputs complete structured schema without unscripted deviations.
4. Action execution success does not equal business rule satisfaction.
5. Strict completion rules: partial runs never marked completed.
"""

from __future__ import annotations

import pytest

from agent.cognition.investigation import InvestigationEngine
from agent.core.types import ActionType, AgentState
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.defect_scope import classify_step_failure
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.memory.session import SessionMemory
from agent.reporting.engine import ReportingEngine
from agent.skills.incident.domain.models import Incident, IncidentState
from agent.skills.incident.validation import IncidentValidator
from agent.testing.generator import ScenarioGenerator


@pytest.fixture
def reporting_engine(tmp_path) -> ReportingEngine:
    return ReportingEngine(output_dir=tmp_path)


@pytest.fixture
def investigation_engine() -> InvestigationEngine:
    return InvestigationEngine()


@pytest.fixture
def incident_validator() -> IncidentValidator:
    return IncidentValidator()


@pytest.mark.asyncio
async def test_precondition_initial_state_mismatch_detected(incident_validator: IncidentValidator):
    """Test that live state In Progress when expected On Hold triggers precondition failure."""
    incident = Incident(
        number="INC0000007",
        state=IncidentState.IN_PROGRESS,  # live state is 2 (In Progress)
        short_description="Email server outage",
    )

    result = incident_validator.validate_precondition(
        incident=incident,
        expected_record="INC0000007",
        expected_state="On Hold",  # expected state is 3 (On Hold)
    )

    assert not result.passed
    assert "Precondition failed" in (result.error_message or "")
    assert "Expected initial state 'ON_HOLD'" in (result.error_message or "")

    std_result = incident_validator.to_standard_validation_result(result, is_precondition=True)
    assert std_result.is_precondition_check is True
    assert std_result.precondition_failed is True
    assert std_result.precondition_details["current_state"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_precondition_failure_not_classified_as_defect(investigation_engine: InvestigationEngine):
    """Precondition failure is classified as non-defect and scope is precondition."""
    action = AgentAction(
        action_type=ActionType.NAVIGATE,
        target="incident.do?sysparm_query=number=INC0000007",
        reasoning="Open incident and verify initial state is On Hold",
    )
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(
        action_description="Precondition Verification",
        is_precondition_check=True,
        precondition_failed=True,
        precondition_details={"current_state": "IN_PROGRESS", "expected_state": "ON_HOLD"},
    )
    validation.add_check(
        ValidationCheck(
            check_name="Precondition Validation",
            description="Verify initial state is On Hold",
            passed=False,
            expected="On Hold",
            actual="State: IN_PROGRESS",
            error_message="Precondition failed: Expected initial state 'ON_HOLD', but actual state is 'IN_PROGRESS'",
        )
    )

    scope = classify_step_failure(result, validation)
    assert scope == "precondition"

    verdict = await investigation_engine.investigate_mismatch(
        action=action,
        expected="On Hold",
        actual="IN_PROGRESS",
        result=result,
        validation=validation,
    )

    assert verdict.is_defect is False
    assert verdict.classification == "precondition_failed"
    assert "Precondition failed" in verdict.reasoning


@pytest.mark.asyncio
async def test_reporting_engine_marks_precondition_failed_status(reporting_engine: ReportingEngine):
    """ReportingEngine outputs status 'precondition_failed' with defect_count=0."""
    memory = SessionMemory(goal="Verify incident INC0000007 lifecycle from On Hold to In Progress")
    action = AgentAction(
        action_type=ActionType.NAVIGATE,
        target="incident.do?sysparm_query=number=INC0000007",
        reasoning="Precondition check: incident initial state must be On Hold",
    )
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(
        action_description="Precondition Verification",
        is_precondition_check=True,
        precondition_failed=True,
    )
    validation.add_check(
        ValidationCheck(
            check_name="Precondition Check",
            passed=False,
            expected="On Hold",
            actual="In Progress",
            error_message="Precondition failed: Expected initial state 'ON_HOLD', but actual state is 'IN_PROGRESS'",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)
    memory.precondition_failed = True

    report = await reporting_engine.generate_report(memory)

    assert report.status == "precondition_failed"
    assert report.defect_count == 0
    assert len(report.defects) == 0


@pytest.mark.asyncio
async def test_story_to_test_case_decomposition():
    """Story-to-test-case generator produces structured test case with preconditions and assertions."""
    generator = ScenarioGenerator(llm_client=None, strategy_selector=None)  # type: ignore

    story = (
        "Open incident INC0000007. Verify that the incident number is INC0000007 and the current state is On Hold. "
        "Change the state to In Progress and click Update. Re-open the incident and verify that the state is still In Progress."
    )

    tc = await generator.decompose_story_to_test_case(story)

    assert tc.target_record == "INC0000007"
    assert tc.expected_initial_state == "On Hold"
    assert tc.is_exploratory is False
    assert len(tc.ordered_steps) >= 5
    assert any(step.is_precondition_check for step in tc.ordered_steps)
    assert any(assertion.field == "state" and assertion.expected_value == "In Progress" for assertion in tc.final_assertions)
    assert "INC0000007" in tc.preconditions[0]


@pytest.mark.asyncio
async def test_partial_validations_never_marked_completed(reporting_engine: ReportingEngine):
    """Run with 2 passing and 2 failing validations is marked 'partial', never 'completed'."""
    memory = SessionMemory(goal="Test state transition")

    # Step 1: Navigate (passed)
    a1 = AgentAction(action_type=ActionType.NAVIGATE, target="incident.do")
    r1 = ActionResult(success=True, action=a1)
    v1 = ValidationResult(action_description="nav")
    v1.add_check(ValidationCheck(check_name="c1", passed=True, expected="ok", actual="ok"))
    memory.add_completed_step(action=a1, result=r1, validation=v1)

    # Step 2: Select state (failed behavioral check)
    a2 = AgentAction(action_type=ActionType.SELECT, target="incident.state", value="2")
    r2 = ActionResult(success=True, action=a2)
    v2 = ValidationResult(action_description="select")
    v2.add_check(ValidationCheck(check_name="c2", passed=False, expected="2", actual="1", error_message="State did not update in DOM"))
    memory.add_completed_step(action=a2, result=r2, validation=v2)

    # Step 3: Click update (failed)
    a3 = AgentAction(action_type=ActionType.CLICK, target="sysverb_update")
    r3 = ActionResult(success=True, action=a3)
    v3 = ValidationResult(action_description="click")
    v3.add_check(ValidationCheck(check_name="c3", passed=False, expected="saved", actual="unsaved", error_message="Record update failed"))
    memory.add_completed_step(action=a3, result=r3, validation=v3)

    # Step 4: Final verification (passed)
    a4 = AgentAction(action_type=ActionType.VALIDATE, target="incident.state")
    r4 = ActionResult(success=True, action=a4)
    v4 = ValidationResult(action_description="verify")
    v4.add_check(ValidationCheck(check_name="c4", passed=True, expected="ok", actual="ok"))
    memory.add_completed_step(action=a4, result=r4, validation=v4)

    report = await reporting_engine.generate_report(memory)

    assert report.status == "partial"
    assert report.status != "completed"
    assert report.total_validations == 4
    assert report.passed_validations == 2
    assert report.failed_validations == 2


@pytest.mark.asyncio
async def test_story_preserves_acceptance_criteria_and_persists_in_store():
    """Verify that decompose_story_to_test_case preserves every acceptance criterion and store saves it."""
    from unittest.mock import AsyncMock
    from agent.testing.generator import ScenarioGenerator
    from agent.testing.strategy_selector import StrategySelector
    from agent.testing.store import TestIntelligenceStore
    from agent.core.config import DomainConfig

    mock_llm = AsyncMock()
    mock_selector = StrategySelector()
    generator = ScenarioGenerator(llm_client=mock_llm, strategy_selector=mock_selector)

    story = "As an ITIL technician, open INC0000007, verify it is On Hold, and set state to In Progress."
    criteria = [
        "AC-1: Initial state must be On Hold",
        "AC-2: State dropdown must update to In Progress",
        "AC-3: Update button persists changes without error",
    ]

    tc = await generator.decompose_story_to_test_case(
        story_text=story,
        acceptance_criteria=criteria,
        table_name="incident",
    )

    # Every AC is preserved
    assert len(tc.acceptance_criteria) == 3
    assert tc.acceptance_criteria[0].statement == criteria[0]
    assert tc.acceptance_criteria[1].statement == criteria[1]
    assert tc.acceptance_criteria[2].statement == criteria[2]

    # Stored in TestIntelligenceStore with tenant scoping
    store = TestIntelligenceStore(DomainConfig())
    tc_id = store.save_test_case(tc, tenant_id="tenant-uat")
    assert tc_id == tc.id

    fetched = store.get_test_case(tc_id, tenant_id="tenant-uat")
    assert fetched is not None
    assert len(fetched["acceptance_criteria"]) == 3
    assert len(fetched["ordered_steps"]) >= 4


@pytest.mark.asyncio
async def test_idempotent_target_state_is_valid_pass_noop(investigation_engine: InvestigationEngine):
    """If the entity is already in the target state, the operation is an idempotent pass/no-op, not a defect."""
    action = AgentAction(
        action_type=ActionType.SELECT,
        target="incident.state",
        value="In Progress",
        reasoning="Transition to In Progress",
    )
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(
        action_description="State Selection",
        overall_passed=True,
    )
    validation.add_check(
        ValidationCheck(
            check_name="State Verification",
            passed=True,
            expected="In Progress",
            actual="In Progress",
        )
    )

    scope = classify_step_failure(result, validation)
    # Passed validation should not be flagged as defect
    assert scope != "defect"

    investigation = await investigation_engine.investigate_mismatch(
        action=action,
        expected="In Progress",
        actual="In Progress",
        result=result,
        validation=validation,
    )
    assert investigation.is_defect is False

