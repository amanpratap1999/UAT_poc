from unittest.mock import AsyncMock, Mock

import pytest

from agent.cognition.orchestrator import CognitiveOrchestrator
from agent.core.types import ActionType, PageType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import PageObservation
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.memory.session import SessionMemory


@pytest.fixture
def orchestrator():
    registry = Mock()
    # Mock registry returns some fake definitions
    meta = Mock()
    meta.name = "Incident"
    meta.module_name = "incident"
    meta.description = "Test Incident"
    registry._skills = {"incident": (Mock(), meta)}

    skill = AsyncMock()
    registry.get_skill_for_module.return_value = skill

    llm = AsyncMock()
    # Simulate LLM returning two hypotheses spanning skills
    llm.complete_json.return_value = {
        "hypotheses": [
            {
                "id": "hyp-1",
                "capability": "change_request",
                "statement": "Verify Change transitions to Implement.",
                "rationale": "Testing Change flow.",
                "supporting_facts": [],
                "strategy": "Positive Testing",
                "expected_outcome": "State is Implement",
                "falsification_condition": "State remains New",
                "risk": 5,
                "provenance": {},
            },
            {
                "id": "hyp-2",
                "capability": "incident",
                "statement": "Verify Change creates Incident.",
                "rationale": "Testing integration.",
                "supporting_facts": [],
                "strategy": "Integration Testing",
                "expected_outcome": "Incident is linked",
                "falsification_condition": "Incident is not linked",
                "risk": 6,
                "provenance": {},
            },
        ]
    }

    from agent.core.types import ActionType
    from agent.domain.actions import ActionResult, AgentAction
    from agent.domain.validation import ValidationCheck, ValidationResult

    action = AgentAction(action_type=ActionType.CLICK, target="btn")
    decision_engine = AsyncMock()
    decision = Mock()
    decision.action = action
    decision_engine.decide_next_action.return_value = decision

    validation_engine = AsyncMock()
    validation = ValidationResult(action_description="click: btn")
    validation.add_check(
        ValidationCheck(
            check_name="action_execution",
            description="Action executed",
            passed=True,
            expected="success",
            actual="success",
        )
    )
    validation_engine.validate_action.return_value = validation

    observation_engine = AsyncMock()
    mock_obs = PageObservation(
        page_type=PageType.FORM,
        url="https://test",
        title="Test Page",
        record_number="INC001",
        current_state="New",
        visible_fields=[],
        mandatory_fields=[],
        buttons=[],
        links=[],
        validation_messages=[],
        notification_messages=[],
    )
    observation_engine.observe.return_value = mock_obs

    execution_controller = AsyncMock()
    execution_controller.execute.return_value = ActionResult(success=True, action=action)

    return CognitiveOrchestrator(
        skill_registry=registry,
        decision_engine=decision_engine,
        validation_engine=validation_engine,
        observation_engine=observation_engine,
        browser_manager=Mock(),
        execution_controller=execution_controller,
        llm_client=llm,
    )


@pytest.mark.asyncio
async def test_formulate_hypotheses(orchestrator):
    hypotheses = await orchestrator._formulate_hypotheses("Test Change to Incident flow")
    assert len(hypotheses) == 2
    assert hypotheses[0].capability == "change_request"
    assert hypotheses[1].capability == "incident"


@pytest.mark.asyncio
async def test_run_cognitive_loop_success(orchestrator):
    memory = SessionMemory(observation_window=5)
    memory.total_actions_executed = 0

    # We mock everything so it should just loop through the 2 hypotheses and execute them
    await orchestrator.run_cognitive_loop(memory, "Test multi-skill")

    # decision engine should be called twice (once per hypothesis)
    assert orchestrator._decision_engine.decide_next_action.call_count == 2
    assert orchestrator._validation_engine.validate_action.call_count == 2
    assert memory.total_actions_executed == 2
    assert len(memory.completed_steps) == 2
    assert len(memory.timeline) == 2

    # The investigation engine should not be called because validation passes


@pytest.mark.asyncio
async def test_run_cognitive_loop_mismatch_investigation(orchestrator):
    memory = SessionMemory(observation_window=5)

    # Agent-scope failure (action could not execute) — investigation must be
    # SKIPPED: no conclusion about the application can be drawn.
    val_mock = ValidationResult(action_description="click: btn")
    val_mock.add_check(
        ValidationCheck(
            check_name="action_execution",
            description="Action failed",
            passed=False,
            expected="success",
            actual="failed",
            error_message="Mismatch",
        )
    )
    orchestrator._validation_engine.validate_action.return_value = val_mock

    orchestrator._investigation_engine = AsyncMock()

    await orchestrator.run_cognitive_loop(memory, "Test failure")

    # Agent-scope mismatches never reach the investigation engine
    assert orchestrator._investigation_engine.investigate_mismatch.call_count == 0

    # No failure recorded as an application defect
    assert len(memory.failures) == 0
    # No defect verdict recorded
    assert len(memory.defect_verdicts) == 0


@pytest.mark.asyncio
async def test_run_cognitive_loop_app_mismatch_investigation(orchestrator):
    """Application-scope mismatches ARE investigated, and verdicts recorded."""
    memory = SessionMemory(observation_window=5)

    # The action executed fine, but the app demonstrably kept the wrong value
    action = AgentAction(action_type=ActionType.SELECT, target="State", value="2")
    val_app = ValidationResult(action_description="select: State")
    val_app.add_check(
        ValidationCheck(
            check_name="action_execution",
            description="Action executed",
            passed=True,
            expected="success",
            actual="success",
        )
    )
    val_app.add_check(
        ValidationCheck(
            check_name="field_update",
            description="Field updated",
            passed=False,
            expected="2",
            actual="1",
            error_message="Field value mismatch",
        )
    )
    orchestrator._validation_engine.validate_action.return_value = val_app

    # Execution succeeded — classify_step_failure will see application scope
    orchestrator._execution_controller.execute.return_value = ActionResult(
        success=True, action=action
    )

    inv = Mock()
    inv.is_defect = True
    inv.classification = "verified_defect"
    inv.reasoning = "No authoritative configuration explains the mismatch"
    inv.knowledge_reference = None
    orchestrator._investigation_engine = AsyncMock()
    orchestrator._investigation_engine.investigate_mismatch.return_value = inv

    await orchestrator.run_cognitive_loop(memory, "Test app failure")

    # Application-scope mismatches are investigated once per hypothesis
    assert orchestrator._investigation_engine.investigate_mismatch.call_count == 2

    # The verified-defect verdict is recorded for the reporting engine
    assert len(memory.defect_verdicts) == 2
    assert all(v.is_defect for v in memory.defect_verdicts)
    # And the failure is logged as a verified application defect
    assert len(memory.failures) == 2
    assert all(
        f.error_type == "InvestigationVerifiedDefect" for f in memory.failures
    )


@pytest.mark.asyncio
async def test_run_cognitive_loop_no_hypotheses_failure(orchestrator):
    memory = SessionMemory(observation_window=5)
    orchestrator._llm.complete_json.return_value = {"hypotheses": []}

    with pytest.raises(RuntimeError, match="PlanningFailure"):
        await orchestrator.run_cognitive_loop(memory, "Impossible goal")

    assert len(memory.failures) == 1
    assert memory.failures[0].error_type == "PlanningFailure"
