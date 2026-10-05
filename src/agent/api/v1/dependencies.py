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
from agent.core.logging import get_logger
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
from agent.skills.change.skill import ChangeSkill
from agent.skills.incident.skill import IncidentSkill
from agent.testing.generator import ScenarioGenerator
from agent.testing.store import TestIntelligenceStore
from agent.testing.strategy_selector import StrategySelector
from agent.tools.browser_tools import register_default_tools
from agent.tools.registry import ToolRegistry
from agent.validation.engine import ValidationEngine
from agent.world.model import WorldModel

logger = get_logger(__name__)


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
    """Create a CapabilityRegistry pre-registered with the domain skills."""
    s = settings or get_cached_settings()
    registry = CapabilityRegistry()
    # Instantiate specific skills with required config
    incident_skill = IncidentSkill(config=s.servicenow)
    registry.register(incident_skill, incident_skill.get_capability_definition())
    # INC-UAT-13 (Minor): ChangeSkill is NOT registered for the Incident-only
    # POC scope. The product scope is restricted to ServiceNow Incident
    # Management; registering ChangeSkill would leak scope and make the
    # product contract less clear. To re-enable ChangeSkill for a future
    # multi-module release, uncomment the lines below:
    # change_skill = ChangeSkill(base_url=s.servicenow.instance_url)
    # registry.register(change_skill, change_skill.get_capability_definition())
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
    """Create a DecisionEngine instance.

    LAYA supplies bounded verification decisions when its service config
    is available; otherwise the existing Gemini-backed path remains active.

    P3-LAYA: now also wires a LayaActionPolicy when LAYA_ACTION_ENABLED=true.
    The policy is loaded once (singleton) and warmed up at startup.
    On any failure (missing checkpoint, missing LAYA SDK,
    warm-up failure), the policy is None and the DecisionEngine falls
    back to the existing Gemini path unchanged.
    """
    llm = get_llm_client(settings, purpose='decision')

    # P1-01: LAYA replaces JEV as the default DecisionProvider.
    # LAYA is a bounded typed-decision model that classifies, routes,
    # and scores information — NOT a generative planner or browser executor.
    # If LAYA is not configured or fails to initialize, fall back to
    # the internal LLM-based verification (P1-06 fallback traceability).
    decision_provider = None
    try:
        from agent.decision.laya_adapter import LayaAdapter
        laya = LayaAdapter(settings)
        # Only attach if the adapter loaded its config successfully
        if laya.is_configured():
            # P1-05: warm up the model during startup
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Can't await in a sync context — schedule warm-up
                    loop.create_task(laya.warm_up())
                else:
                    loop.run_until_complete(laya.warm_up())
            except Exception:
                # Warm-up failure is non-fatal — LAYA will be used
                # on first actual decision call
                logger.warning("laya_warmup_skipped")
            decision_provider = laya
            logger.info("laya_decision_provider_attached")
        else:
            logger.info("laya_not_configured_using_llm_fallback")
    except Exception as e:
        logger.warning("laya_adapter_init_failed", error=str(e))

    # P3-LAYA: wire the local LAYA action-policy adapter (separate from
    # the remote LayaAdapter verifier above). The action policy is
    # loaded once as a singleton and warmed up at startup. On any
    # failure it is None and the DecisionEngine uses the Gemini path.
    laya_action_policy = get_laya_action_policy(settings)

    return DecisionEngine(
        llm_client=llm,
        confidence_engine=get_confidence_engine(),
        reflection_engine=get_reflection_engine(settings),
        tool_registry=get_tool_registry(),
        decision_provider=decision_provider,
        laya_action_policy=laya_action_policy,
    )


# P6-LAYA/P7-LAYA: singleton action-policy instance — loaded once,
# warmed at startup, shut down at app exit. Stored as a module-level
# singleton so the same model instance is reused across all runs in
# the process (the model is expensive to load).
_laya_action_policy_singleton: Any = None


def get_laya_action_policy(settings: Settings | None = None) -> Any:
    """P6-LAYA: create (or return the singleton) LayaActionPolicy.

    The policy is loaded once per process. If the optional
    ``laya`` dependency is not installed, or the
    checkpoint path is empty, or warm-up fails, returns None — the
    DecisionEngine then uses the existing Gemini path unchanged.

    Does NOT require Jev endpoint credentials — LAYA runs locally.
    """
    global _laya_action_policy_singleton
    if _laya_action_policy_singleton is not None:
        return _laya_action_policy_singleton
    s = settings or get_cached_settings()
    cfg = getattr(s, "laya_action", None)
    if cfg is None or not cfg.enabled:
        return None
    try:
        from agent.decision.laya_action_policy import (
            LayaActionPolicy,
            LayaActionPolicyConfig,
        )
        policy_cfg = LayaActionPolicyConfig(
            enabled=cfg.enabled,
            mode=cfg.mode,
            checkpoint=cfg.checkpoint,
            model_subfolder=cfg.model_subfolder,
            device=cfg.device,
            confidence_threshold=cfg.confidence_threshold,
            inference_timeout_seconds=cfg.inference_timeout_seconds,
            max_candidates=cfg.max_candidates,
            warmup_at_startup=cfg.warmup_at_startup,
            model_max_len=cfg.model_max_len,
            head_max_len=cfg.head_max_len,
        )
        policy = LayaActionPolicy(config=policy_cfg)
        if policy.is_configured():
            # P7-LAYA: warm up eagerly if configured to do so. The warm-up
            # is async but get_decision_engine is sync — schedule it on
            # the running event loop if one exists, otherwise skip
            # (the policy will warm up lazily on first use).
            if cfg.warmup_at_startup:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(policy.warm_up())
                    else:
                        loop.run_until_complete(policy.warm_up())
                except Exception as e:
                    logger.warning("laya_action_policy_warmup_skipped", error=str(e))
            _laya_action_policy_singleton = policy
            logger.info(
                "laya_action_policy_attached",
                mode=cfg.mode,
                checkpoint=cfg.checkpoint,
                device=cfg.device,
            )
            return policy
        else:
            logger.info("laya_action_policy_not_configured_no_checkpoint")
            return None
    except Exception as e:
        logger.warning("laya_action_policy_init_failed", error=str(e))
        return None


async def shutdown_laya_action_policy() -> None:
    """P7-LAYA: shut down the singleton action policy at app exit.

    Called from the FastAPI lifespan shutdown handler in main.py.
    Releases the model and tokenizer resources.
    """
    global _laya_action_policy_singleton
    if _laya_action_policy_singleton is not None:
        try:
            await _laya_action_policy_singleton.shutdown()
        except Exception as e:
            logger.warning("laya_action_policy_shutdown_failed", error=str(e))
        _laya_action_policy_singleton = None


def get_laya_action_policy_diagnostics() -> dict[str, Any]:
    """P7-LAYA: health + stats for the /api/v1/ready diagnostics endpoint."""
    if _laya_action_policy_singleton is None:
        return {
            "enabled": False,
            "healthy": False,
            "backend": "none",
        }
    policy = _laya_action_policy_singleton
    stats = policy.get_stats()
    return {
        "enabled": stats["enabled"],
        "healthy": policy.is_healthy(),
        "backend": stats["device"],
        "mode": stats["mode"],
        "checkpoint": stats["checkpoint"],
        "model_version": stats["model_version"],
        "is_warm": stats["is_warm"],
        "inference_count": stats["inference_count"],
        "fallback_count": stats["fallback_count"],
        "avg_inference_latency_ms": stats["avg_inference_latency_ms"],
    }


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


