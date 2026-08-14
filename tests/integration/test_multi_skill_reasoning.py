from unittest.mock import AsyncMock, Mock

import pytest

from agent.capabilities.registry import CapabilityRegistry
from agent.cognition.orchestrator import CognitiveOrchestrator
from agent.memory.session import SessionMemory
from agent.world.model import PageType


@pytest.mark.asyncio
async def test_multi_skill_cognitive_loop():
    # 1. Setup minimal dependencies
    registry = CapabilityRegistry()
    registry.register = Mock()  # Override just for safety, but we'll mock get_skill

    change_skill = Mock()
    incident_skill = Mock()

    def get_skill(module):
        if module == "change_request":
            return change_skill
        if module == "incident":
            return incident_skill
        return None

    registry.get_skill_for_module = get_skill

    llm = AsyncMock()
    # Provide multi-skill hypotheses
    llm.complete_json.return_value = {
        "hypotheses": [
            {
                "id": "hyp-change",
                "capability": "change_request",
                "statement": "Change moves to Implement.",
                "rationale": "Testing Change flow.",
                "supporting_facts": [],
                "strategy": "Integration Testing",
                "expected_outcome": "Implement",
                "falsification_condition": "New",
                "risk": 5,
                "provenance": {},
            },
            {
                "id": "hyp-inc",
                "capability": "incident",
                "statement": "Incident is linked.",
                "rationale": "Testing Integration.",
                "supporting_facts": [],
                "strategy": "Integration Testing",
                "expected_outcome": "Linked",
                "falsification_condition": "Not linked",
                "risk": 5,
                "provenance": {},
            },
        ]
    }

    # 2. Setup Orchestrator
    orchestrator = CognitiveOrchestrator(
        skill_registry=registry,
        decision_engine=AsyncMock(),
        validation_engine=AsyncMock(),
        observation_engine=AsyncMock(),
        browser_manager=Mock(),
        execution_controller=AsyncMock(),
        llm_client=llm,
    )

    orchestrator._decision_engine.decide_next_action.return_value = Mock(action=Mock())
    mock_obs = Mock()
    mock_obs.page_type = PageType.FORM
    mock_obs.url = "mock"
    mock_obs.title = "mock"
    mock_obs.record_number = "mock"
    mock_obs.current_state = "mock"
    mock_obs.validation_messages = []
    mock_obs.notification_messages = []
    mock_obs.buttons = []
    mock_obs.visible_fields = []
    mock_obs.mandatory_fields = []
    mock_obs.available_actions = []
    orchestrator._observation_engine.observe.return_value = mock_obs
    # Validation passes for change, fails for incident (to trigger investigation)
    validation_pass = Mock(overall_passed=True)
    validation_fail = Mock(overall_passed=False, reasoning="Not linked")
    orchestrator._validation_engine.validate_action.side_effect = [validation_pass, validation_fail]

    inv_result = Mock(
        is_defect=True, classification="verified_defect", reasoning="No explanation found"
    )
    orchestrator._investigation_engine = AsyncMock()
    orchestrator._investigation_engine.investigate_mismatch.return_value = inv_result

    # 3. Run
    memory = SessionMemory(observation_window=5)
    await orchestrator.run_cognitive_loop(memory, "Test Change and Incident integration")

    # 4. Verify outcomes
    assert orchestrator._decision_engine.decide_next_action.call_count == 2
    assert orchestrator._validation_engine.validate_action.call_count == 2
    assert orchestrator._investigation_engine.investigate_mismatch.call_count == 1

    # Check that a verified defect failure was logged in memory
    assert len(memory.failures) == 1
    assert memory.failures[0].error_type == "InvestigationVerifiedDefect"
    assert "hyp-inc" in memory.failures[0].error_message
