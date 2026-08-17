"""Testing Store for persisting scenarios, risk scores, and findings."""

from __future__ import annotations

import json

from agent.core.config import DomainConfig
from agent.core.logging import get_logger
from agent.testing.generator import TestScenario

try:
    import asyncpg  # type: ignore

    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

logger = get_logger(__name__)


class TestIntelligenceStore:
    """Persists scenarios, execution records, and findings to Postgres."""

    def __init__(self, config: DomainConfig) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None
        self._initialized = False

    async def _init_pool(self) -> None:
        if self._initialized or not HAS_POSTGRES or not self._config.postgres_url:
            return

        try:
            self._pool = await asyncpg.create_pool(self._config.asyncpg_dsn)

            async with self._pool.acquire() as conn:
                # Scenarios table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS test_scenarios (
                        id VARCHAR(255) PRIMARY KEY,
                        title TEXT,
                        description TEXT,
                        steps JSONB,
                        expected_outcome TEXT,
                        is_exploratory BOOLEAN,
                        risk_score INTEGER,
                        strategies_applied JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Findings table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS test_findings (
                        id SERIAL PRIMARY KEY,
                        scenario_id VARCHAR(255) REFERENCES test_scenarios(id),
                        finding_type VARCHAR(50),
                        description TEXT,
                        evidence_reference TEXT,
                        before_evidence_reference TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            self._initialized = True
            logger.info("test_intelligence_store_initialized")
        except Exception as e:
            logger.error("test_intelligence_store_init_failed", error=str(e))

    async def save_scenario(self, scenario: TestScenario) -> None:
        """Save a generated scenario to the database."""
        await self._init_pool()
        if not self._pool:
            logger.debug("skipping_save_scenario_no_db", scenario_id=scenario.id)
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO test_scenarios (
                        id, title, description, steps, expected_outcome,
                        is_exploratory, risk_score, strategies_applied
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        steps = EXCLUDED.steps,
                        expected_outcome = EXCLUDED.expected_outcome,
                        is_exploratory = EXCLUDED.is_exploratory,
                        risk_score = EXCLUDED.risk_score,
                        strategies_applied = EXCLUDED.strategies_applied
                """,
                    scenario.id,
                    scenario.title,
                    scenario.description,
                    json.dumps(scenario.steps),
                    scenario.expected_outcome,
                    scenario.is_exploratory,
                    scenario.risk_score,
                    json.dumps(scenario.strategies_applied),
                )
        except Exception as e:
            logger.error("failed_to_save_scenario", error=str(e), scenario_id=scenario.id)

    async def save_finding(
        self,
        scenario_id: str,
        finding_type: str,
        description: str,
        evidence_reference: str | None = None,
        before_evidence_reference: str | None = None,
    ) -> None:
        """Record a test execution finding in the database."""
        await self._init_pool()
        if not self._pool:
            logger.debug("skipping_save_finding_no_db", scenario_id=scenario_id)
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO test_findings (
                        scenario_id, finding_type, description,
                        evidence_reference, before_evidence_reference
                    )
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    scenario_id,
                    finding_type,
                    description,
                    evidence_reference,
                    before_evidence_reference,
                )
                logger.debug("finding_saved", scenario_id=scenario_id, finding_type=finding_type)
        except Exception as e:
            logger.error("failed_to_save_finding", error=str(e), scenario_id=scenario_id)

    async def close(self) -> None:
        """Close the database pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
