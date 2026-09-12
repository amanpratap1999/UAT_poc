"""Testing Store for persisting scenarios, risk scores, and findings."""

from __future__ import annotations

import json
from typing import Any

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
    """Persists scenarios, execution records, and findings to Postgres and memory."""

    def __init__(self, config: DomainConfig) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None
        self._initialized = False
        self._memory_cases: dict[str, dict[str, Any]] = {}

    def save_test_case(self, test_case: Any, tenant_id: str = "unknown") -> str:
        """Save a generated structured test case with tenant scoping."""
        import uuid as _uuid

        if isinstance(test_case, dict):
            tc_id = test_case.get("id") or str(_uuid.uuid4())
            raw_steps = test_case.get("ordered_steps") or test_case.get("steps") or []
            raw_assertions = test_case.get("final_assertions") or []
            raw_cleanup = test_case.get("cleanup_steps") or test_case.get("cleanup_requirements") or []
            title = test_case.get("title") or test_case.get("name") or f"Test Case {tc_id}"
            description = test_case.get("description", "")
            target_record = test_case.get("target_record")
            initial_state = test_case.get("expected_initial_state")
            preconditions = list(test_case.get("preconditions") or [])
            expected_outcomes = list(test_case.get("expected_outcomes") or [])
            risk_level = str(test_case.get("risk_level", "Medium"))
            acceptance_criteria = list(test_case.get("acceptance_criteria") or [])
            story_id = test_case.get("story_id")
        else:
            tc_id = getattr(test_case, "id", None) or str(_uuid.uuid4())
            raw_steps = getattr(test_case, "ordered_steps", None) or getattr(test_case, "steps", [])
            raw_assertions = getattr(test_case, "final_assertions", [])
            raw_cleanup = getattr(test_case, "cleanup_steps", []) or getattr(test_case, "cleanup_requirements", [])
            title = getattr(test_case, "title", None) or getattr(test_case, "name", f"Test Case {tc_id}")
            description = getattr(test_case, "description", "")
            target_record = getattr(test_case, "target_record", None)
            initial_state = getattr(test_case, "expected_initial_state", None)
            preconditions = list(getattr(test_case, "preconditions", []))
            expected_outcomes = list(getattr(test_case, "expected_outcomes", []))
            risk_level = str(getattr(test_case, "risk_level", "Medium"))
            acceptance_criteria = list(getattr(test_case, "acceptance_criteria", []))
            story_id = getattr(test_case, "story_id", None)

        steps_dump = []
        for s in raw_steps:
            if hasattr(s, "model_dump"):
                steps_dump.append(s.model_dump())
            elif isinstance(s, dict):
                steps_dump.append(s)
            else:
                steps_dump.append({"description": str(s)})

        assertions_dump = [
            a.model_dump() if hasattr(a, "model_dump") else a for a in raw_assertions
        ]
        cleanup_dump = [
            c.model_dump() if hasattr(c, "model_dump") else c for c in raw_cleanup
        ]

        record = {
            "id": tc_id,
            "tenant_id": tenant_id,
            "story_id": story_id,
            "title": title,
            "description": description,
            "target_record": target_record,
            "expected_initial_state": initial_state,
            "preconditions": preconditions,
            "steps": steps_dump,
            "ordered_steps": steps_dump,
            "final_assertions": assertions_dump,
            "cleanup_steps": cleanup_dump,
            "expected_outcomes": expected_outcomes,
            "risk_level": risk_level,
            "acceptance_criteria": acceptance_criteria,
        }
        self._memory_cases[tc_id] = record

        # Persist to Postgres in the background if an event loop is running
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_case_db(record))
        except RuntimeError:
            pass

        return tc_id

    async def _persist_case_db(self, record: dict[str, Any]) -> None:
        """Persist a test case record to PostgreSQL."""
        await self._init_pool()
        if not self._pool:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO test_cases (
                        id, tenant_id, story_id, title, description,
                        target_record, expected_initial_state, preconditions,
                        steps, final_assertions, cleanup_steps, acceptance_criteria,
                        risk_level
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        target_record = EXCLUDED.target_record,
                        expected_initial_state = EXCLUDED.expected_initial_state,
                        preconditions = EXCLUDED.preconditions,
                        steps = EXCLUDED.steps,
                        final_assertions = EXCLUDED.final_assertions,
                        cleanup_steps = EXCLUDED.cleanup_steps,
                        acceptance_criteria = EXCLUDED.acceptance_criteria,
                        risk_level = EXCLUDED.risk_level
                """,
                    record["id"],
                    record["tenant_id"],
                    record.get("story_id"),
                    record["title"],
                    record["description"],
                    record.get("target_record"),
                    record.get("expected_initial_state"),
                    json.dumps(record.get("preconditions") or []),
                    json.dumps(record.get("steps") or []),
                    json.dumps(record.get("final_assertions") or []),
                    json.dumps(record.get("cleanup_steps") or []),
                    json.dumps(record.get("acceptance_criteria") or []),
                    record.get("risk_level", "Medium"),
                )
        except Exception as e:
            logger.debug("failed_to_persist_test_case_db", error=str(e), id=record.get("id"))

    def get_test_case(
        self, test_case_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """Retrieve a stored test case, enforcing tenant isolation when tenant_id is given."""
        case = self._memory_cases.get(test_case_id)
        if not case:
            return None
        if tenant_id and case.get("tenant_id") not in (tenant_id, "unknown"):
            return None
        return case

    def list_test_cases(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List all test cases for a tenant."""
        return [
            c
            for c in self._memory_cases.values()
            if not tenant_id or c.get("tenant_id") in (tenant_id, "unknown")
        ]

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
