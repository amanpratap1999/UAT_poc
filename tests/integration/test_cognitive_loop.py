"""Integration test for full Phase 1.5 Cognitive Intelligence Loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.capabilities.registry import CapabilityRegistry
from agent.confidence.engine import ConfidenceEngine
from agent.core.config import AgentConfig, BrowserConfig, LLMConfig, ServiceNowConfig, Settings
from agent.core.types import PageType
from agent.decision.engine import DecisionEngine
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.intent.manager import IntentManager
from agent.knowledge.store import InMemoryKnowledgeStore
from agent.main import AgentOrchestrator
from agent.memory.long_term import KnowledgeMemory
from agent.memory.session_store import InMemorySessionStore
from agent.observation.engine import ObservationEngine
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reflection.engine import ReflectionEngine
from agent.reporting.engine import ReportingEngine
from agent.skills.incident.skill import IncidentSkill
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry
from agent.validation.engine import ValidationEngine
from agent.world.model import WorldModel
from tests.conftest import MockLLMClient


@pytest.fixture
def mock_cognitive_settings(tmp_path: Path) -> Settings:
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
async def test_cognitive_loop_end_to_end(mock_cognitive_settings: Settings, tmp_path: Path) -> None:
    """Test the complete Phase 1.5 cognitive loop end-to-end."""

    # Mock responses for Intent, Plan, Decision, Reflection, Completion, Report
    llm_responses = [
        # 1. IntentManager parse
        {
            "intent_type": "IncidentValidation",
            "goal": "Validate incident form",
            "target_module": "incident",
            "priority": "Normal",
            "confidence": 0.96,
        },
        # 2. CognitiveOrchestrator _formulate_hypotheses
        {
            "hypotheses": [
                {
                    "id": "hyp-1",
                    "capability": "incident",
                    "statement": "Verify incident form",
                    "rationale": "Test requirement",
                    "strategy": "Positive Testing",
                    "expected_outcome": "Form fields visible",
                    "falsification_condition": "Form fails to load",
                }
            ]
        },
        # 3. DecisionEngine decide_next_action
        {
            "action_type": "fill",
            "target": "label:Short Description",
            "value": "Test Incident",
            "reasoning": "Fill description",
            "expected_outcome": "Description filled",
            "confidence": 0.95,
        },
        # 4. ReflectionEngine reflect
        {
            "is_as_expected": True,
            "hypotheses": ["Action succeeded"],
            "recommended_plan_adaptation": None,
            "confidence": 0.95,
        },
        # 5. Planner completion check
        {
            "is_complete": True,
            "reasoning": "Goal accomplished",
            "summary": "Form validated",
        },
        # 6. Report summary
        {
            "summary": "Cognitive test run complete.",
            "recommendations": [],
            "root_cause_hypotheses": [],
        },
    ]

    mock_llm = MockLLMClient(responses=llm_responses)

    # Component setup
    intent_manager = IntentManager(llm_client=mock_llm)
    planner = Planner(llm_client=mock_llm)
    world_model = WorldModel()

    skill_registry = CapabilityRegistry()
    incident_skill = IncidentSkill()
    skill_registry.register(incident_skill, incident_skill.get_capability_definition())

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

    # Mock browser infrastructure
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
        url="https://test.service-now.com/incident.do?sys_id=-1",
        title="New Incident",
        page_type=PageType.FORM,
        visible_fields=[
            FieldInfo(name="Short Description", value="", is_mandatory=True),
        ],
        buttons=[ButtonInfo(label="Submit")],
    )
    observation_engine.observe = AsyncMock(return_value=sample_obs)

    orchestrator = AgentOrchestrator(
        settings=mock_cognitive_settings,
        planner=planner,
        browser_manager=browser_manager,
        observation_engine=observation_engine,
        validation_engine=ValidationEngine(),
        recovery_engine=RecoveryEngine(max_retries=1),
        reporting_engine=ReportingEngine(output_dir=tmp_path / "reports"),
        knowledge_store=InMemoryKnowledgeStore(docs_dir=Path("servicenow_docs")),
        session_store=InMemorySessionStore(),
        intent_manager=intent_manager,
        world_model=world_model,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        reflection_engine=reflection_engine,
        confidence_engine=confidence_engine,
        knowledge_memory=knowledge_memory,
        decision_engine=decision_engine,
        learning_service=MagicMock(),
    )

    mock_interactor = MagicMock()
    mock_interactor.fill = AsyncMock()
    mock_interactor.click = AsyncMock()

    with patch.object(orchestrator, "_page_interactor", mock_interactor):
        report = await orchestrator.run("Check whether incidents can be created.")

    assert report is not None
    assert orchestrator.memory.structured_intent is not None
    assert orchestrator.memory.structured_intent.intent_type == "IncidentValidation"
    assert len(orchestrator.memory.timeline) > 0
