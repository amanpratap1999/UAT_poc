"""Integration test: RecordLockManager Redis-backed lease with two concurrent workers.

Audit issue I46 (P2): verifies that when worker A holds a lease on a
record, worker B's acquire_lease for the same record returns False
(lease contention). This is the highest-risk concurrency path in the
system — without proper lease semantics, two workers can mutate the
same ServiceNow record simultaneously, causing data corruption.

This test is skipped when Redis is not available. Run with:
    pytest tests/integration/test_record_lock_redis_concurrent.py -v
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


def _redis_available() -> bool:
    """Check if a Redis server is reachable at the configured URL."""
    try:
        import redis as sync_redis
        from agent.core.config import get_settings
        settings = get_settings()
        if settings.session.store_type != "redis":
            return False
        client = sync_redis.Redis.from_url(
            settings.session.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available (set SESSION_STORE_TYPE=redis and REDIS_URL)",
)
@pytest.mark.asyncio
async def test_record_lock_contention_two_workers() -> None:
    """Worker A acquires a lease; worker B's acquire_lease for the same record returns False."""
    from agent.core.config import get_settings
    from agent.core.locks import RecordLockManager

    settings = get_settings()
    lock_mgr_a = RecordLockManager(settings)
    lock_mgr_b = RecordLockManager(settings)

    record_id = "INC0009999"
    table = "incident"
    instance = "test.service-now.com"

    # Worker A acquires the lease
    acquired_a = await lock_mgr_a.acquire_lease(
        record_id=record_id,
        session_id="worker-A-session",
        timeout_seconds=300,
        table=table,
        instance=instance,
    )
    assert acquired_a is True, "worker A should acquire the lease"

    # Worker B tries to acquire the same lease — should be rejected
    acquired_b = await lock_mgr_b.acquire_lease(
        record_id=record_id,
        session_id="worker-B-session",
        timeout_seconds=300,
        table=table,
        instance=instance,
    )
    assert acquired_b is False, (
        "worker B should NOT acquire the lease while worker A holds it — "
        "if this fails, the lease semantics are broken and concurrent "
        "workers can corrupt ServiceNow records"
    )

    # Worker A releases the lease
    await lock_mgr_a.release_lease(record_id, table=table, instance=instance)

    # Now worker B can acquire
    acquired_b_retry = await lock_mgr_b.acquire_lease(
        record_id=record_id,
        session_id="worker-B-session",
        timeout_seconds=300,
        table=table,
        instance=instance,
    )
    assert acquired_b_retry is True, "worker B should acquire the lease after A releases"

    await lock_mgr_b.release_lease(record_id, table=table, instance=instance)


@pytest.mark.skipif(
    not _redis_available(),
    reason="Redis not available",
)
@pytest.mark.asyncio
async def test_record_lock_lease_extension() -> None:
    """Verify that re-acquiring with the SAME session_id extends the lease
    rather than rejecting it (this is the path fixed in audit issue I44)."""
    from agent.core.config import get_settings
    from agent.core.locks import RecordLockManager

    settings = get_settings()
    lock_mgr = RecordLockManager(settings)

    record_id = "INC0008888"
    session_id = "same-session-id"

    acquired_first = await lock_mgr.acquire_lease(
        record_id=record_id, session_id=session_id, table="incident",
    )
    assert acquired_first is True

    # Same session re-acquires — should extend, not reject
    acquired_second = await lock_mgr.acquire_lease(
        record_id=record_id, session_id=session_id, table="incident",
    )
    assert acquired_second is True, (
        "same session re-acquiring should extend the lease — "
        "if this fails with AttributeError: 'str' object has no attribute 'decode', "
        "audit issue I44 is still present (decode_responses=True not set)"
    )

    await lock_mgr.release_lease(record_id, table="incident")
