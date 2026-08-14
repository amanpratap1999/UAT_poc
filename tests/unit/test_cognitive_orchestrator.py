from unittest.mock import AsyncMock, Mock

import pytest

from agent.cognition.orchestrator import CognitiveOrchestrator
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

    decision_engine = AsyncMock()
    decision = Mock()
    decision.action = Mock()
    decision.action.action_type = "click"
    decision_engine.decide_next_action.return_value = decision

    validation_engine = AsyncMock()
    validation = Mock()
    validation.overall_passed = True
    validation_engine.validate_action.return_value = validation

    observation_engine = AsyncMock()
    from agent.core.types import PageType
    from agent.domain.observation import PageObservation

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

    return CognitiveOrchestrator(
        skill_registry=registry,
        decision_engine=decision_engine,
        validation_engine=validation_engine,
        observation_engine=observation_engine,
        browser_manager=Mock(),
        execution_controller=AsyncMock(),
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

    # The investigation engine should not be called because validation passes


@pytest.mark.asyncio
async def test_run_cognitive_loop_mismatch_investigation(orchestrator):
    memory = SessionMemory(observation_window=5)

    # Force validation to fail, which triggers investigation
    val_mock = Mock()
    val_mock.overall_passed = False
    val_mock.reasoning = "Mismatch"
    val_mock.to_summary.return_value = "Mismatch"
    orchestrator._validation_engine.validate_action.return_value = val_mock

    # Mock investigation to return a false positive
    inv = Mock()
    inv.is_defect = False
    inv.classification = "false_positive_customization"
    orchestrator._investigation_engine = AsyncMock()
    orchestrator._investigation_engine.investigate_mismatch.return_value = inv

    await orchestrator.run_cognitive_loop(memory, "Test failure")

    assert orchestrator._investigation_engine.investigate_mismatch.call_count == 2

    # Because it was a false positive, it should NOT add a failure to memory
    assert len(memory.failures) == 0
