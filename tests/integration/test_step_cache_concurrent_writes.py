"""Integration test: StepCache SQLite WAL behavior under concurrent writes.

Audit issue I46 (P2): verifies that two concurrent writes to the StepCache
SQLite DB (one from the API process, one from the worker process) do not
corrupt each other. The SQLite WAL (Write-Ahead Log) journal mode + busy
timeout should serialize writers; without them, a writer would see
"database is locked" errors or silent data loss.

This test runs entirely in-process (no external infrastructure needed).
Run with:
    pytest tests/integration/test_step_cache_concurrent_writes.py -v
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sys
from pathlib import Path

import pytest


def _step_cache_writable(tmp_path: Path) -> bool:
    """Verify we can construct a StepCache at the tmp_path."""
    try:
        from agent.cognition.step_cache import StepCache
        StepCache(db_path=str(tmp_path / "test_step_cache.db"))
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_step_cache_same_tenant_different_goals(tmp_path: Path) -> None:
    """Two async writers with different goals but same tenant_id should
    both succeed without corruption."""
    from agent.cognition.step_cache import StepCache
    from agent.domain.actions import AgentAction

    cache = StepCache(db_path=str(tmp_path / "concurrent.db"))

    action_a = AgentAction(
        action_type="click", target="button#save", reasoning="action A",
    )
    action_b = AgentAction(
        action_type="fill", target="input#name", reasoning="action B", value="test",
    )

    # Concurrent saves with different goals but same tenant
    await asyncio.gather(
        cache.save_action("goal A", "validate", "step 1", "outcome 1", action_a, "tenant-1"),
        cache.save_action("goal B", "validate", "step 1", "outcome 1", action_b, "tenant-1"),
    )

    # Both should be retrievable
    retrieved_a = cache.get_action("goal A", "validate", "step 1", "outcome 1", "tenant-1")
    retrieved_b = cache.get_action("goal B", "validate", "step 1", "outcome 1", "tenant-1")

    assert retrieved_a is not None, "action A should be retrievable"
    assert retrieved_b is not None, "action B should be retrievable"
    assert retrieved_a.action_type == "click"
    assert retrieved_b.action_type == "fill"


@pytest.mark.asyncio
async def test_step_cache_tenant_isolation_in_sqlite(tmp_path: Path) -> None:
    """Verify that the same (goal, intent_type, step_desc, expected) tuple
    with different tenant_ids produces DIFFERENT cache entries (audit issue I25)."""
    from agent.cognition.step_cache import StepCache
    from agent.domain.actions import AgentAction

    cache = StepCache(db_path=str(tmp_path / "tenant_isolation.db"))

    action_a = AgentAction(
        action_type="click", target="button#save", reasoning="tenant A action",
    )

    # Save with tenant-A
    cache.save_action(
        "same goal", "validate", "same step", "same outcome", action_a, "tenant-A"
    )

    # Retrieve with tenant-B — should return None (cross-tenant leak would return action_a)
    retrieved_b = cache.get_action(
        "same goal", "validate", "same step", "same outcome", "tenant-B"
    )
    assert retrieved_b is None, (
        "tenant B should NOT retrieve tenant A's cached action — "
        "if this fails, audit issue I25 (cross-tenant step cache leak) is present"
    )

    # Retrieve with tenant-A — should return action_a
    retrieved_a = cache.get_action(
        "same goal", "validate", "same step", "same outcome", "tenant-A"
    )
    assert retrieved_a is not None
    assert retrieved_a.action_type == "click"


def test_step_cache_cross_process_writes(tmp_path: Path) -> None:
    """Two PROCESSES (not just coroutines) writing to the same SQLite DB
    should not corrupt each other. This is the API-vs-worker concurrency
    scenario the audit flagged.

    Uses concurrent.futures.ProcessPoolExecutor to spawn actual subprocesses
    (not just threads — SQLite's WAL handles concurrent processes correctly,
    but the test verifies this end-to-end).
    """
    import sqlite3
    db_path = str(tmp_path / "cross_process.db")

    # Initialize the DB schema in the main process first
    from agent.cognition.step_cache import StepCache
    cache = StepCache(db_path=db_path)
    # Schema is now created

    def _write_from_subprocess(process_id: int, db_path: str) -> str:
        """Run in a subprocess — write a row and report success/error."""
        try:
            from agent.cognition.step_cache import StepCache
            from agent.domain.actions import AgentAction
            cache = StepCache(db_path=db_path)
            action = AgentAction(
                action_type="click",
                target=f"button#proc-{process_id}",
                reasoning=f"subprocess {process_id}",
            )
            cache.save_action(
                goal=f"goal-from-proc-{process_id}",
                intent_type="validate",
                step_desc="step",
                expected="outcome",
                action=action,
                tenant_id=f"tenant-{process_id}",
            )
            return f"OK-{process_id}"
        except Exception as e:
            return f"FAIL-{process_id}: {type(e).__name__}: {e}"

    # Spawn 4 subprocesses that all write to the same DB
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_write_from_subprocess, i, db_path)
            for i in range(4)
        ]
        results = [f.result() for f in futures]

    # All should succeed (no "database is locked" errors)
    failures = [r for r in results if r.startswith("FAIL")]
    assert not failures, (
        f"subprocess writes failed (SQLite WAL should serialize): {failures}"
    )

    # Verify all 4 rows are present
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT COUNT(*) FROM step_cache")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 4, f"expected 4 cached actions, got {count}"
