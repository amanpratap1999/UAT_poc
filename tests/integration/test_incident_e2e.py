"""Integration test for full ServiceNow IncidentSkill workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.confidence.engine import ConfidenceEngine
from agent.core.config import AgentConfig, BrowserConfig, LLMConfig, ServiceNowConfig, Settings
from agent.core.types import PageType
from agent.decision.engine import DecisionEngine
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.intent.manager import IntentManager
from agent.knowledge.store import KnowledgeStore
from agent.main import AgentOrchestrator
from agent.memory.long_term import KnowledgeMemory
from agent.observation.engine import ObservationEngine
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reflection.engine import ReflectionEngine
from agent.reporting.engine import ReportingEngine
from agent.skills.incident.skill import IncidentSkill
from agent.skills.registry import SkillRegistry
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry
from agent.validation.engine import ValidationEngine
from agent.world.model import WorldModel
from tests.conftest import MockLLMClient


@pytest.fixture
def mock_incident_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm=LLMConfig(provider="openai", api_key="test", model="test"),
        servicenow=ServiceNowConfig(
            instance_url="https://test.service-now.com",
            username="admin",
            password="test",
        ),
        browser=BrowserConfig(headless=True),
        agent=AgentConfig(max_steps=10, max_retries=1, observation_window=5),
        report_output_dir=tmp_path / "reports",
        screenshot_dir=tmp_path / "screenshots",
    )


@pytest.mark.asyncio
async def test_incident_e2e_workflow(mock_incident_settings: Settings, tmp_path: Path) -> None:
    """Test full IncidentSkill workflow from goal to report."""
    llm_responses = [
        # 1. Intent parsing
        {
            "intent_type": "IncidentLifecycle",
            "goal": "Test complete incident lifecycle",
            "target_module": "incident",
            "priority": "Normal",
            "confidence": 0.98,
        },
    ]
    # Decision + Reflection pairs for up to 10 steps
    for i in range(10):
        llm_responses.extend([
            {
                "action_type": "fill" if i == 0 else "wait",
                "target": "label:Short Description" if i == 0 else "",
                "value": "Test Incident flow" if i == 0 else "1000",
                "reasoning": f"Step {i} execution",
                "expected_outcome": "Step outcome OK",
                "confidence": 0.95,
            },
            {
                "is_as_expected": True,
                "hypotheses": ["Step executed successfully"],
                "recommended_plan_adaptation": None,
                "confidence": 0.95,
            },
            {
                "is_complete": True if i >= 1 else False,
                "reasoning": "Incident lifecycle completed",
                "summary": "Lifecycle finished",
            },
        ])

    # Final report summary
    llm_responses.append({
        "summary": "Incident workflow executed successfully.",
        "recommendations": [],
        "root_cause_hypotheses": [],
    })

    mock_llm = MockLLMClient(responses=llm_responses)

    # Wiring components
    intent_manager = IntentManager(llm_client=mock_llm)
    planner = Planner(llm_client=mock_llm)
    world_model = WorldModel()

    skill_registry = SkillRegistry()
    incident_skill = IncidentSkill(base_url="https://test.service-now.com")
    skill_registry.register(incident_skill)

    tool_registry = ToolRegistry()
    register_default_tools(tool_registry)

    reflection_engine = ReflectionEngine(llm_client=mock_llm)
    confidence_engine = ConfidenceEngine(default_threshold=0.70)
    knowledge_memory = KnowledgeMemory(storage_file=tmp_path / "km.json")

    decision_engine = DecisionEngine(
        llm_client=mock_llm,
        confidence_engine=confidence_engine,
        reflection_engine=reflection_engine,
        tool_registry=tool_registry,
    )

    # Browser & Observation mocks
    browser_manager = MagicMock()
    browser_manager.launch = AsyncMock()
    browser_manager.close = AsyncMock()
    browser_manager.navigate = AsyncMock()
    browser_manager.wait_for_load = AsyncMock()
    browser_manager.take_screenshot = AsyncMock(return_value=str(tmp_path / "shot.png"))
    browser_manager.get_page_errors = MagicMock(return_value=[])
    browser_manager.clear_logs = MagicMock()
    browser_manager.get_page = MagicMock(return_value=MagicMock())

    observation_engine = MagicMock(spec=ObservationEngine)
    sample_obs = PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc123",
        title="Incident | INC0010001",
        page_type=PageType.FORM,
        current_state="New",
        incident_number="INC0010001",
        visible_fields=[
            FieldInfo(name="Short Description", value="", is_mandatory=True),
            FieldInfo(name="Caller", value="Abel Tuter", is_mandatory=True),
        ],
        buttons=[ButtonInfo(label="Update"), ButtonInfo(label="Resolve Incident")],
    )
    observation_engine.observe = AsyncMock(return_value=sample_obs)

    orchestrator = AgentOrchestrator(
        settings=mock_incident_settings,
        planner=planner,
        browser_manager=browser_manager,
        observation_engine=observation_engine,
        validation_engine=ValidationEngine(),
        recovery_engine=RecoveryEngine(max_retries=1),
        reporting_engine=ReportingEngine(output_dir=tmp_path / "reports"),
        knowledge_store=KnowledgeStore(docs_dir=Path("servicenow_docs")),
        intent_manager=intent_manager,
        world_model=world_model,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        reflection_engine=reflection_engine,
        confidence_engine=confidence_engine,
        knowledge_memory=knowledge_memory,
        decision_engine=decision_engine,
    )

    mock_interactor = MagicMock()
    mock_interactor.fill = AsyncMock()
    mock_interactor.click = AsyncMock()

    with patch.object(orchestrator, '_page_interactor', mock_interactor):
        report = await orchestrator.run("Open any existing Incident in New state and validate the complete Incident flow.")

    assert report is not None
    assert orchestrator.memory.structured_intent is not None
    assert orchestrator.memory.structured_intent.target_module == "incident"
    assert len(incident_skill.evidence_collector.items) > 0
