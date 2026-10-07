"""Database persistence for Operational Learning records."""

from __future__ import annotations

from typing import Any

from agent.core.config import DomainConfig
from agent.core.logging import get_logger
from agent.learning.types import (
    LearnedExperience,
    LearnedExplorationOutcome,
    LearnedRecovery,
    LearnedStrategyEffectiveness,
)

try:
    import asyncpg  # type: ignore

    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

logger = get_logger(__name__)


class LearningStore:
    """Persists learning records in PostgreSQL."""

    def __init__(self, config: DomainConfig) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None
        self._initialized = False
        self._memory_recoveries: dict[tuple[str, str], LearnedRecovery] = {}
        self._memory_strategies: dict[tuple[Any, ...], LearnedStrategyEffectiveness] = {}
        self._memory_explorations: dict[tuple[Any, ...], LearnedExplorationOutcome] = {}
        self._memory_experiences: list[LearnedExperience] = []

    async def _init_pool(self) -> None:
        if self._initialized or not HAS_POSTGRES or not self._config.postgres_url:
            return

        try:
            self._pool = await asyncpg.create_pool(self._config.asyncpg_dsn)

            async with self._pool.acquire() as conn:
                # Recoveries
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_recoveries (
                        id VARCHAR(255) PRIMARY KEY,
                        target_description TEXT,
                        page_fingerprint TEXT,
                        original_locator TEXT,
                        successful_locator TEXT,
                        confidence FLOAT,
                        verification_count INTEGER,
                        failure_count INTEGER,
                        first_verified_at TIMESTAMP WITH TIME ZONE,
                        last_verified_at TIMESTAMP WITH TIME ZONE,
                        expires_at TIMESTAMP WITH TIME ZONE
                    )
                """)
                # Strategy Effectiveness
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_strategy_effectiveness (
                        id SERIAL PRIMARY KEY,
                        module VARCHAR(255),
                        field_type VARCHAR(255),
                        workflow_type VARCHAR(255),
                        strategy TEXT,
                        executions INTEGER,
                        findings INTEGER,
                        confidence FLOAT,
                        UNIQUE(module, field_type, workflow_type, strategy)
                    )
                """)
                # Exploration Outcomes
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_exploration_outcomes (
                        id SERIAL PRIMARY KEY,
                        module VARCHAR(255),
                        exploration_type TEXT,
                        executions INTEGER,
                        findings INTEGER,
                        confidence FLOAT,
                        UNIQUE(module, exploration_type)
                    )
                """)
                # Experiences
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_experiences (
                        id SERIAL PRIMARY KEY,
                        module VARCHAR(255),
                        observation TEXT,
                        outcome TEXT,
                        evidence_reference TEXT,
                        occurrence_count INTEGER,
                        confidence FLOAT,
                        first_seen TIMESTAMP WITH TIME ZONE,
                        last_seen TIMESTAMP WITH TIME ZONE
                    )
                """)
            self._initialized = True
            logger.info("learning_store_initialized")
        except Exception as e:
            self._initialized = True
            self._pool = None
            logger.warning("learning_store_using_in_memory_fallback", error=str(e))

    # --- Recoveries ---

    async def get_recovery(
        self, page_fingerprint: str, target_description: str
    ) -> LearnedRecovery | None:
        await self._init_pool()
        if not self._pool:
            return self._memory_recoveries.get((page_fingerprint, target_description))

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM learning_recoveries
                    WHERE page_fingerprint = $1 AND target_description = $2
                """,
                    page_fingerprint,
                    target_description,
                )

                if row:
                    return LearnedRecovery(**dict(row))
        except Exception as e:
            logger.error("failed_to_get_recovery", error=str(e))
        return self._memory_recoveries.get((page_fingerprint, target_description))

    async def save_recovery(self, recovery: LearnedRecovery) -> None:
        self._memory_recoveries[(recovery.page_fingerprint, recovery.target_description)] = recovery
        await self._init_pool()
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO learning_recoveries (
                        id, target_description, page_fingerprint, original_locator,
                        successful_locator, confidence, verification_count, failure_count,
                        first_verified_at, last_verified_at, expires_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        verification_count = EXCLUDED.verification_count,
                        failure_count = EXCLUDED.failure_count,
                        last_verified_at = EXCLUDED.last_verified_at,
                        expires_at = EXCLUDED.expires_at,
                        successful_locator = EXCLUDED.successful_locator
                """,
                    recovery.id,
                    recovery.target_description,
                    recovery.page_fingerprint,
                    recovery.original_locator,
                    recovery.successful_locator,
                    recovery.confidence,
                    recovery.verification_count,
                    recovery.failure_count,
                    recovery.first_verified_at,
                    recovery.last_verified_at,
                    recovery.expires_at,
                )
        except Exception as e:
            logger.error("failed_to_save_recovery", error=str(e))

    async def delete_recovery(self, recovery_id: str) -> None:
        await self._init_pool()
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute("DELETE FROM learning_recoveries WHERE id = $1", recovery_id)
        except Exception as e:
            logger.error("failed_to_delete_recovery", error=str(e))

    # --- Strategy Effectiveness ---

    async def save_strategy_effectiveness(self, eff: LearnedStrategyEffectiveness) -> None:
        await self._init_pool()
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO learning_strategy_effectiveness (
                        module, field_type, workflow_type, strategy,
executions, findings, confidence
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (module, field_type, workflow_type, strategy) DO UPDATE SET
                        executions = EXCLUDED.executions,
                        findings = EXCLUDED.findings,
                        confidence = EXCLUDED.confidence
                """,
                    eff.module,
                    eff.field_type or "",
                    eff.workflow_type or "",
                    eff.strategy,
                    eff.executions,
                    eff.findings,
                    eff.confidence,
                )
        except Exception as e:
            logger.error("failed_to_save_strategy", error=str(e))

    async def get_strategy_effectiveness(
        self,
        module: str,
        strategy: str,
        field_type: str | None = None,
        workflow_type: str | None = None,
    ) -> LearnedStrategyEffectiveness | None:
        await self._init_pool()
        if not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM learning_strategy_effectiveness
                    WHERE module = $1 AND strategy = $2 AND field_type = $3 AND workflow_type = $4
                """,
                    module,
                    strategy,
                    field_type or "",
                    workflow_type or "",
                )

                if row:
                    return LearnedStrategyEffectiveness(**dict(row))
        except Exception as e:
            logger.error("failed_to_get_strategy", error=str(e))
        return None

    # --- Exploratory Outcomes ---

    async def save_exploration_outcome(self, ext: LearnedExplorationOutcome) -> None:
        await self._init_pool()
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO learning_exploration_outcomes (
                        module, exploration_type, executions, findings, confidence
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (module, exploration_type) DO UPDATE SET
                        executions = EXCLUDED.executions,
                        findings = EXCLUDED.findings,
                        confidence = EXCLUDED.confidence
                """,
                    ext.module,
                    ext.exploration_type,
                    ext.executions,
                    ext.findings,
                    ext.confidence,
                )
        except Exception as e:
            logger.error("failed_to_save_exploration", error=str(e))

    async def get_exploration_outcome(
        self, module: str, exploration_type: str
    ) -> LearnedExplorationOutcome | None:
        await self._init_pool()
        if not self._pool:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM learning_exploration_outcomes
                    WHERE module = $1 AND exploration_type = $2
                """,
                    module,
                    exploration_type,
                )

                if row:
                    return LearnedExplorationOutcome(**dict(row))
        except Exception as e:
            logger.error("failed_to_get_exploration", error=str(e))
        return None

    # --- Experiences ---

    async def save_experience(self, exp: LearnedExperience) -> None:
        await self._init_pool()
        if not self._pool:
            return

        try:
            async with self._pool.acquire() as conn:
                if exp.id:
                    await conn.execute(
                        """
                        UPDATE learning_experiences SET
                            occurrence_count = $1,
                            last_seen = $2,
                            confidence = $3
                        WHERE id = $4
                    """,
                        exp.occurrence_count,
                        exp.last_seen,
                        exp.confidence,
                        int(exp.id),
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO learning_experiences (
                            module, observation, outcome, evidence_reference,
                            occurrence_count, confidence, first_seen, last_seen
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                        exp.module,
                        exp.observation,
                        exp.outcome,
                        exp.evidence_reference,
                        exp.occurrence_count,
                        exp.confidence,
                        exp.first_seen,
                        exp.last_seen,
                    )
        except Exception as e:
            logger.error("failed_to_save_experience", error=str(e))

    async def query_experiences(self, module: str) -> list[LearnedExperience]:
        await self._init_pool()
        if not self._pool:
            return []

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM learning_experiences WHERE module = $1
                """,
                    module,
                )

                return [LearnedExperience(**dict(row)) for row in rows]
        except Exception as e:
            logger.error("failed_to_query_experiences", error=str(e))
            return []

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self._initialized = False
