"""Integration test — full agent loop with mocked LLM and browser.

Simulates a complete goal → plan → execute → validate → report cycle
to verify the orchestrator loop works end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.config import Settings, LLMConfig, ServiceNowConfig, BrowserConfig, AgentConfig
from agent.core.types import ActionType, AgentState
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.core.types import PageType
from agent.knowledge.store import KnowledgeStore
from agent.main import AgentOrchestrator
from agent.memory.session import SessionMemory
from agent.observation.engine import ObservationEngine
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reporting.engine import ReportingEngine
from agent.validation.engine import ValidationEngine
from tests.conftest import MockLLMClient


def _make_observation(step: int) -> PageObservation:
    """Create a mock observation for a given step."""
    if step == 0:
        return PageObservation(
            url="https://test.service-now.com/login.do",
            title="ServiceNow - Login",
            page_type=PageType.LOGIN,
            visible_fields=[
                FieldInfo(name="User name", field_type="text", value=""),
                FieldInfo(name="Password", field_type="password", value=""),
            ],
            buttons=[ButtonInfo(label="Log in")],
        )
    elif step <= 2:
        return PageObservation(
            url="https://test.service-now.com/incident.do?sys_id=-1",
            title="New Incident",
            page_type=PageType.FORM,
            current_state="New",
            visible_fields=[
                FieldInfo(name="Short Description", value="", is_mandatory=True),
                FieldInfo(name="Caller", value="", is_mandatory=True),
            ],
            mandatory_fields=["Short Description", "Caller"],
            buttons=[ButtonInfo(label="Submit")],
        )
    else:
        return PageObservation(
            url="https://test.service-now.com/incident.do?sys_id=abc",
            title="Incident | INC0010001",
            page_type=PageType.FORM,
            current_state="New",
            incident_number="INC0010001",
            visible_fields=[
                FieldInfo(name="Short Description", value="Test", is_mandatory=True),
            ],
            buttons=[ButtonInfo(label="Update")],
        )


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    """Test settings."""
    return Settings(
        llm=LLMConfig(provider="openai", api_key="test", model="test"),
        servicenow=ServiceNowConfig(
            instance_url="https://test.service-now.com",
            username="admin",
            password="test",
        ),
        browser=BrowserConfig(headless=True),
        agent=AgentConfig(max_steps=5, max_retries=1, observation_window=5),
        report_output_dir=tmp_path / "reports",
        screenshot_dir=tmp_path / "screenshots",
    )


@pytest.mark.asyncio
async def test_agent_loop_end_to_end(mock_settings: Settings, tmp_path: Path) -> None:
    """Test the full agent orchestration loop with mocked components."""

    # Configure mock LLM responses
    llm_responses = [
        # 1. create_plan
        {
            "steps": [
                {"description": "Fill form", "expected_outcome": "Fields populated"},
                {"description": "Submit", "expected_outcome": "Incident created"},
            ]
        },
        # 2. decide_next_action (step 1)
        {
            "action_type": "fill",
            "target": "label:Short Description",
            "value": "Test incident",
            "reasoning": "Fill the description",
            "field_label": "Short Description",
        },
        # 3. validation assessment (step 1)
        {
            "overall_passed": True,
            "checks": [
                {
                    "check_name": "field_filled",
                    "description": "Field was filled",
                    "passed": True,
                    "expected": "Test incident",
                    "actual": "Test incident",
                }
            ],
        },
        # 4. decide_next_action (step 2)
        {
            "action_type": "click",
            "target": "text:Submit",
            "value": "",
            "reasoning": "Submit the form",
        },
        # 5. validation assessment (step 2)
        {
            "overall_passed": True,
            "checks": [
                {
                    "check_name": "form_submitted",
                    "passed": True,
                    "expected": "submitted",
                    "actual": "submitted",
                }
            ],
        },
        # 6. completion check
        {
            "is_complete": True,
            "reasoning": "Form submitted successfully",
            "summary": "Incident created",
        },
        # 7. report summary
        {
            "summary": "Test completed successfully.",
            "recommendations": [],
            "root_cause_hypotheses": [],
        },
    ]

    mock_llm = MockLLMClient(responses=llm_responses)
    planner = Planner(llm_client=mock_llm)

    # Mock browser manager
    browser_manager = MagicMock()
    browser_manager.launch = AsyncMock()
    browser_manager.close = AsyncMock()
    browser_manager.navigate = AsyncMock()
    browser_manager.wait_for_load = AsyncMock()
    browser_manager.take_screenshot = AsyncMock(return_value=str(tmp_path / "shot.png"))
    browser_manager.get_page_errors = MagicMock(return_value=[])
    browser_manager.clear_logs = MagicMock()

    mock_page = MagicMock()
    browser_manager.get_page = MagicMock(return_value=mock_page)

    # Mock observation engine to return sequential observations
    observation_engine = MagicMock(spec=ObservationEngine)
    obs_call_count = 0

    async def mock_observe(page):
        nonlocal obs_call_count
        obs = _make_observation(obs_call_count)
        obs_call_count += 1
        return obs

    observation_engine.observe = mock_observe

    # Real engines (they don't need browser)
    validation_engine = ValidationEngine()
    recovery_engine = RecoveryEngine(max_retries=1)
    reporting_engine = ReportingEngine(output_dir=tmp_path / "reports")
    knowledge_store = KnowledgeStore(docs_dir=Path("servicenow_docs"))

    # Create orchestrator
    orchestrator = AgentOrchestrator(
        settings=mock_settings,
        planner=planner,
        browser_manager=browser_manager,
        observation_engine=observation_engine,
        validation_engine=validation_engine,
        recovery_engine=recovery_engine,
        reporting_engine=reporting_engine,
        knowledge_store=knowledge_store,
    )

    # Mock the page interactor and execution controller
    mock_interactor = MagicMock()
    mock_interactor.click = AsyncMock()
    mock_interactor.fill = AsyncMock()

    # Patch the internal execution
    with patch.object(orchestrator, '_page_interactor', mock_interactor):
        report = await orchestrator.run("Test incident creation")

    # Verify
    assert report is not None
    assert report.goal == "Test incident creation"
    assert orchestrator.memory.total_actions_executed > 0
    browser_manager.launch.assert_called_once()
    browser_manager.close.assert_called_once()


@pytest.mark.asyncio
async def test_agent_stop_request(mock_settings: Settings, tmp_path: Path) -> None:
    """Test that the agent stops when a stop is requested."""
    mock_llm = MockLLMClient(responses=[
        # Plan
        {"steps": [{"description": "Step 1", "expected_outcome": "Done"}]},
        # Next action
        {"action_type": "wait", "target": "", "value": "", "reasoning": "Wait"},
        # Report summary
        {"summary": "Stopped.", "recommendations": [], "root_cause_hypotheses": []},
    ])

    planner = Planner(llm_client=mock_llm)

    browser_manager = MagicMock()
    browser_manager.launch = AsyncMock()
    browser_manager.close = AsyncMock()
    browser_manager.navigate = AsyncMock()
    browser_manager.take_screenshot = AsyncMock(return_value="shot.png")
    browser_manager.get_page_errors = MagicMock(return_value=[])
    browser_manager.clear_logs = MagicMock()
    browser_manager.get_page = MagicMock(return_value=MagicMock())
    browser_manager.wait_for_load = AsyncMock()

    observation_engine = MagicMock(spec=ObservationEngine)
    observation_engine.observe = AsyncMock(return_value=_make_observation(0))

    orchestrator = AgentOrchestrator(
        settings=mock_settings,
        planner=planner,
        browser_manager=browser_manager,
        observation_engine=observation_engine,
        validation_engine=ValidationEngine(),
        recovery_engine=RecoveryEngine(max_retries=1),
        reporting_engine=ReportingEngine(output_dir=tmp_path / "reports"),
        knowledge_store=KnowledgeStore(docs_dir=Path("servicenow_docs")),
    )

    # Request stop before running
    orchestrator.request_stop("Test stop")

    report = await orchestrator.run("Test goal")

    assert orchestrator.memory.state == AgentState.COMPLETED
