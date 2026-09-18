"""FastAPI dependency injection factories.

Provides dependency factories for all engine components. These are
used with FastAPI's Depends() to wire together the agent's
component graph.
"""

from __future__ import annotations

from functools import lru_cache

from agent.browser.manager import BrowserManager
from agent.capabilities.registry import CapabilityRegistry
from agent.confidence.engine import ConfidenceEngine
from agent.core.config import Settings, get_settings
from agent.decision.engine import DecisionEngine
from agent.domain.discovery import CustomerDiscoveryAgent
from agent.domain.knowledge_model import CustomerKnowledgeModel
from agent.intent.manager import IntentManager
from agent.knowledge.embeddings import EmbeddingClient, OpenAIEmbeddingClient
from agent.knowledge.store import (
    HAS_PGVECTOR,
    InMemoryKnowledgeStore,
    KnowledgeStore,
    PgVectorKnowledgeStore,
)
from agent.learning.service import LearningService
from agent.learning.store import LearningStore
from agent.memory.long_term import KnowledgeMemory
from agent.memory.session_store import InMemorySessionStore, RedisSessionStore, SessionStore
from agent.observation.engine import ObservationEngine
from agent.perception.backends import (
    GeminiBackend,
    GrounderBackend,
    MoondreamBackend,
)
from agent.perception.router import PerceptionRouter
from agent.perception.verifier import BehavioralVerifier, LLMBehavioralVerifier
from agent.planner.llm_client import OpenAILLMClient
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reflection.engine import ReflectionEngine
from agent.reporting.engine import ReportingEngine
from agent.skills.incident.skill import IncidentSkill
from agent.testing.generator import ScenarioGenerator
from agent.testing.store import TestIntelligenceStore
from agent.testing.strategy_selector import StrategySelector
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry
from agent.validation.engine import ValidationEngine
from agent.world.model import WorldModel


@lru_cache
def get_cached_settings() -> Settings:
    """Cached settings instance."""
    settings = get_settings()
    settings.ensure_directories()
    return settings


def get_session_store(
    settings: Settings | None = None,
) -> SessionStore:
    """Create a SessionStore instance."""
    s = settings or get_cached_settings()
    if s.session.store_type == "redis":
        import redis.asyncio as aioredis

        client = aioredis.from_url(s.session.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        return RedisSessionStore(redis_client=client, key_prefix=s.session.redis_prefix)
    return InMemorySessionStore()


def _get_cached_llm_client(purpose: str = "general") -> OpenAILLMClient:
    """Internal factory for OpenAILLMClient (no longer cached to isolate lifecycles)."""
    config = get_cached_settings()
    return OpenAILLMClient(config=config.llm, purpose=purpose)


def get_llm_client(
    settings: Settings | None = None,
    purpose: str = "general",
) -> OpenAILLMClient:
    """Create an LLM client instance."""
    return _get_cached_llm_client(purpose)


def get_planner(
    settings: Settings | None = None,
    knowledge_model: CustomerKnowledgeModel | None = None,
) -> Planner:
    """Create a Planner instance."""
    llm_client = get_llm_client(settings, purpose="planner")
    km = knowledge_model or get_customer_knowledge_model()
    return Planner(llm_client=llm_client, knowledge_model=km)


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
    """Create a RecoveryEngine instance with bounded retry/recovery limits."""
    s = settings or get_cached_settings()
    return RecoveryEngine(
        max_retries=s.agent.max_retries,
        max_recovery_depth=s.agent.max_recovery_depth,
        max_backoff=s.agent.max_backoff_delay,
    )


def get_observation_engine() -> ObservationEngine:
    """Create an ObservationEngine instance."""
    return ObservationEngine()


def get_validation_engine() -> ValidationEngine:
    """Create a ValidationEngine instance."""
    return ValidationEngine()


def get_intent_manager(settings: Settings | None = None) -> IntentManager:
    """Create an IntentManager instance."""
    llm = get_llm_client(settings)
    return IntentManager(llm_client=llm)


def get_world_model() -> WorldModel:
    """Create a WorldModel instance."""
    return WorldModel()


def get_skill_registry(settings: Settings | None = None) -> CapabilityRegistry:
    """Create a CapabilityRegistry pre-registered with IncidentSkill."""
    s = settings or get_cached_settings()
    registry = CapabilityRegistry()
    # Instantiate specific skills with required config
    incident_skill = IncidentSkill(config=s.servicenow)
    registry.register(incident_skill, incident_skill.get_capability_definition())
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


@lru_cache
def get_knowledge_model() -> CustomerKnowledgeModel:
    """Provide the CustomerKnowledgeModel singleton."""
    return CustomerKnowledgeModel()


@lru_cache
def _get_cached_discovery_agent() -> CustomerDiscoveryAgent:
    """Internal cached factory for CustomerDiscoveryAgent."""
    config = get_cached_settings()
    return CustomerDiscoveryAgent(config=config.servicenow)


def get_discovery_agent(config: Settings | None = None) -> CustomerDiscoveryAgent:
    """Provide the CustomerDiscoveryAgent."""
    return _get_cached_discovery_agent()


def _get_cached_embedding_client() -> EmbeddingClient:
    """Internal factory for EmbeddingClient (no longer cached to isolate lifecycles)."""
    config = get_cached_settings()
    return OpenAIEmbeddingClient(config=config.llm)


def get_embedding_client(config: Settings | None = None) -> EmbeddingClient:
    """Provide the EmbeddingClient."""
    return _get_cached_embedding_client()


def _get_cached_knowledge_store() -> KnowledgeStore:
    """Internal factory for KnowledgeStore."""
    config = get_cached_settings()
    embedding_client = get_embedding_client(config)
    if HAS_PGVECTOR and config.domain.postgres_url:
        return PgVectorKnowledgeStore(
            config=config.domain, embedding_client=embedding_client, llm_config=config.llm
        )
    return InMemoryKnowledgeStore()


def get_knowledge_store(
    config: Settings | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> KnowledgeStore:
    """Provide the KnowledgeStore (PgVector if available, else InMemory)."""
    return _get_cached_knowledge_store()


def _get_cached_learning_store() -> LearningStore:
    """Internal factory for LearningStore (no longer cached to isolate lifecycles)."""
    config = get_cached_settings()
    return LearningStore(config=config.domain)


def get_learning_store(config: Settings | None = None) -> LearningStore:
    return _get_cached_learning_store()


def _get_cached_learning_service() -> LearningService:
    """Internal factory for LearningService (no longer cached to isolate lifecycles)."""
    store = _get_cached_learning_store()
    return LearningService(store=store)


def get_learning_service(store: LearningStore | None = None) -> LearningService:
    return _get_cached_learning_service()


def get_customer_knowledge_model() -> CustomerKnowledgeModel:
    """Provide the CustomerKnowledgeModel instance."""
    return CustomerKnowledgeModel()


def _get_cached_strategy_selector() -> StrategySelector:
    """Internal factory for StrategySelector (no longer cached to isolate lifecycles)."""
    learning = _get_cached_learning_service()
    return StrategySelector(learning_service=learning)


def get_strategy_selector(
    learning: LearningService | None = None,
) -> StrategySelector:
    return _get_cached_strategy_selector()


def _get_cached_scenario_generator() -> ScenarioGenerator:
    llm_client = get_llm_client()
    strategy_selector = _get_cached_strategy_selector()
    learning = _get_cached_learning_service()
    return ScenarioGenerator(
        llm_client=llm_client, strategy_selector=strategy_selector, learning_service=learning
    )


def get_scenario_generator(
    llm_client: OpenAILLMClient | None = None,
    strategy_selector: StrategySelector | None = None,
    learning: LearningService | None = None,
) -> ScenarioGenerator:
    return _get_cached_scenario_generator()


@lru_cache
def _get_cached_test_intelligence_store() -> TestIntelligenceStore:
    config = get_cached_settings()
    return TestIntelligenceStore(config=config.domain)


def get_test_intelligence_store(config: Settings | None = None) -> TestIntelligenceStore:
    return _get_cached_test_intelligence_store()


def get_knowledge_memory() -> KnowledgeMemory:
    """Create a KnowledgeMemory instance."""
    return KnowledgeMemory()


def get_decision_engine(settings: Settings | None = None) -> DecisionEngine:
    """Create a DecisionEngine instance."""
    llm = get_llm_client(settings, purpose='decision')
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


# get_recovery_store has been removed in favor of get_learning_store


def get_grounder_backend(settings: Settings | None = None) -> GrounderBackend:
    """Create a PerceptionRouter configured with primary/fallback grounders."""
    s = settings or get_cached_settings()

    moondream_key = (
        s.perception.moondream_api_key if hasattr(s.perception, "moondream_api_key") else None
    )
    gemini_key = s.perception.gemini_api_key if hasattr(s.perception, "gemini_api_key") else None

    primary = MoondreamBackend(api_key=moondream_key)
    fallback = GeminiBackend(api_key=gemini_key)

    conf_high = getattr(s.perception, "confidence_high", 0.85)
    conf_med = getattr(s.perception, "confidence_medium", 0.60)

    return PerceptionRouter(
        primary=primary,
        fallback=fallback,
        confidence_high=conf_high,
        confidence_medium=conf_med,
    )


def get_behavioral_verifier(settings: Settings | None = None) -> BehavioralVerifier:
    """Create a BehavioralVerifier instance."""
    s = settings or get_cached_settings()
    llm = get_llm_client(s, purpose="verification")
    return LLMBehavioralVerifier(llm_client=llm)


