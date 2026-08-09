"""FastAPI dependency injection factories.

Provides dependency factories for all engine components. These are
used with FastAPI's Depends() to wire together the agent's
component graph.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent.browser.manager import BrowserManager
from agent.browser.page_interactor import PageInteractor
from agent.core.config import Settings, get_settings
from agent.execution.controller import ExecutionController
from agent.knowledge.store import KnowledgeStore
from agent.observation.engine import ObservationEngine
from agent.planner.llm_client import OpenAILLMClient
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reporting.engine import ReportingEngine
from agent.validation.engine import ValidationEngine


@lru_cache
def get_cached_settings() -> Settings:
    """Cached settings instance."""
    settings = get_settings()
    settings.ensure_directories()
    return settings


def get_knowledge_store(
    settings: Settings | None = None,
) -> KnowledgeStore:
    """Create a KnowledgeStore instance."""
    return KnowledgeStore(
        docs_dir=Path("servicenow_docs"),
    )


def get_llm_client(
    settings: Settings | None = None,
) -> OpenAILLMClient:
    """Create an LLM client instance."""
    s = settings or get_cached_settings()
    return OpenAILLMClient(config=s.llm)


def get_planner(
    settings: Settings | None = None,
) -> Planner:
    """Create a Planner instance."""
    llm_client = get_llm_client(settings)
    return Planner(llm_client=llm_client)


def get_browser_manager(
    settings: Settings | None = None,
) -> BrowserManager:
    """Create a BrowserManager instance."""
    s = settings or get_cached_settings()
    return BrowserManager(
        browser_config=s.browser,
        servicenow_config=s.servicenow,
        screenshot_dir=s.screenshot_dir,
    )


def get_recovery_engine(
    settings: Settings | None = None,
) -> RecoveryEngine:
    """Create a RecoveryEngine instance."""
    s = settings or get_cached_settings()
    return RecoveryEngine(max_retries=s.agent.max_retries)


def get_observation_engine() -> ObservationEngine:
    """Create an ObservationEngine instance."""
    return ObservationEngine()


def get_validation_engine() -> ValidationEngine:
    """Create a ValidationEngine instance."""
    return ValidationEngine()


from agent.confidence.engine import ConfidenceEngine
from agent.decision.engine import DecisionEngine
from agent.intent.manager import IntentManager
from agent.memory.long_term import KnowledgeMemory
from agent.reflection.engine import ReflectionEngine
from agent.skills.incident.skill import IncidentSkill
from agent.skills.registry import SkillRegistry
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry
from agent.world.model import WorldModel


def get_intent_manager(settings: Settings | None = None) -> IntentManager:
    """Create an IntentManager instance."""
    llm = get_llm_client(settings)
    return IntentManager(llm_client=llm)


def get_world_model() -> WorldModel:
    """Create a WorldModel instance."""
    return WorldModel()


def get_skill_registry() -> SkillRegistry:
    """Create a SkillRegistry pre-registered with IncidentSkill."""
    registry = SkillRegistry()
    registry.register(IncidentSkill())
    return registry


def get_tool_registry() -> ToolRegistry:
    """Create a ToolRegistry pre-registered with default tools."""
    registry = ToolRegistry()
    return register_default_tools(registry)


def get_reflection_engine(settings: Settings | None = None) -> ReflectionEngine:
    """Create a ReflectionEngine instance."""
    llm = get_llm_client(settings)
    return ReflectionEngine(llm_client=llm)


def get_confidence_engine() -> ConfidenceEngine:
    """Create a ConfidenceEngine instance."""
    return ConfidenceEngine(default_threshold=0.70)


def get_knowledge_memory() -> KnowledgeMemory:
    """Create a KnowledgeMemory instance."""
    return KnowledgeMemory()


def get_decision_engine(settings: Settings | None = None) -> DecisionEngine:
    """Create a DecisionEngine instance."""
    llm = get_llm_client(settings)
    return DecisionEngine(
        llm_client=llm,
        confidence_engine=get_confidence_engine(),
        reflection_engine=get_reflection_engine(settings),
        tool_registry=get_tool_registry(),
    )


def get_reporting_engine(
    settings: Settings | None = None,
) -> ReportingEngine:
    """Create a ReportingEngine instance."""
    s = settings or get_cached_settings()
    return ReportingEngine(output_dir=s.report_output_dir)
