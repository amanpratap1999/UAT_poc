"""Contract tests for SessionStore implementations.

Both InMemorySessionStore and RedisSessionStore must pass the same
interface contract. Redis tests are automatically skipped when a
Redis server is not available.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from agent.memory.session_store import InMemorySessionStore, RedisSessionStore, SessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redis_available() -> bool:
    """Check if a local Redis server is reachable."""
    try:
        import redis as _redis

        client = _redis.Redis()
        client.ping()
        client.close()
        return True
    except Exception:
        return False


_HAS_REDIS = _redis_available()


@pytest.fixture
def in_memory_store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
async def redis_store() -> AsyncGenerator[RedisSessionStore, None]:
    """Create a RedisSessionStore backed by a real Redis connection.

    Uses a unique key prefix per test to avoid collisions, and flushes
    those keys on teardown.
    """
    import redis.asyncio as aioredis

    client = aioredis.Redis(decode_responses=True)
    prefix = "test_session_store:"
    store = RedisSessionStore(redis_client=client, key_prefix=prefix)
    yield store

    # Cleanup: delete all keys with our test prefix
    async for key in client.scan_iter(match=f"{prefix}*"):
        await client.delete(key)
    await client.aclose()


# ---------------------------------------------------------------------------
# InMemory contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_load_in_memory(in_memory_store: SessionStore) -> None:
    """Saved data can be loaded back."""
    data = {"goal": "Test incident", "state": "idle", "step": 0}
    await in_memory_store.save("sess-1", data)

    loaded = await in_memory_store.load("sess-1")
    assert loaded == data


@pytest.mark.asyncio
async def test_load_nonexistent_returns_none_in_memory(in_memory_store: SessionStore) -> None:
    """Loading a non-existent session returns None."""
    assert await in_memory_store.load("does-not-exist") is None


@pytest.mark.asyncio
async def test_delete_in_memory(in_memory_store: SessionStore) -> None:
    """Deleted sessions are no longer loadable."""
    await in_memory_store.save("sess-2", {"x": 1})
    assert await in_memory_store.exists("sess-2") is True

    await in_memory_store.delete("sess-2")
    assert await in_memory_store.load("sess-2") is None
    assert await in_memory_store.exists("sess-2") is False


@pytest.mark.asyncio
async def test_delete_nonexistent_is_noop_in_memory(in_memory_store: SessionStore) -> None:
    """Deleting a session that doesn't exist does not raise."""
    await in_memory_store.delete("never-existed")  # should not raise


@pytest.mark.asyncio
async def test_exists_in_memory(in_memory_store: SessionStore) -> None:
    """exists() reflects save and delete."""
    assert await in_memory_store.exists("sess-3") is False

    await in_memory_store.save("sess-3", {"data": True})
    assert await in_memory_store.exists("sess-3") is True

    await in_memory_store.delete("sess-3")
    assert await in_memory_store.exists("sess-3") is False


@pytest.mark.asyncio
async def test_overwrite_in_memory(in_memory_store: SessionStore) -> None:
    """Saving to an existing session overwrites the data."""
    await in_memory_store.save("sess-4", {"version": 1})
    await in_memory_store.save("sess-4", {"version": 2})

    loaded = await in_memory_store.load("sess-4")
    assert loaded == {"version": 2}


@pytest.mark.asyncio
async def test_save_complex_data_in_memory(in_memory_store: SessionStore) -> None:
    """Sessions can hold nested dicts, lists, and various JSON types."""
    data = {
        "session_id": "abc-123",
        "goal": "Validate incident lifecycle",
        "steps": [
            {"index": 0, "action": "navigate", "success": True},
            {"index": 1, "action": "fill", "success": False},
        ],
        "counters": {"actions": 2, "failures": 1},
        "active": True,
        "score": 0.85,
    }
    await in_memory_store.save("sess-complex", data)

    loaded = await in_memory_store.load("sess-complex")
    assert loaded == data


# ---------------------------------------------------------------------------
# Redis contract tests — identical interface, skipped without Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_save_and_load_redis(redis_store: SessionStore) -> None:
    """Saved data can be loaded back."""
    data = {"goal": "Test incident", "state": "idle", "step": 0}
    await redis_store.save("sess-1", data)

    loaded = await redis_store.load("sess-1")
    assert loaded == data


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_load_nonexistent_returns_none_redis(redis_store: SessionStore) -> None:
    """Loading a non-existent session returns None."""
    assert await redis_store.load("does-not-exist") is None


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_delete_redis(redis_store: SessionStore) -> None:
    """Deleted sessions are no longer loadable."""
    await redis_store.save("sess-2", {"x": 1})
    assert await redis_store.exists("sess-2") is True

    await redis_store.delete("sess-2")
    assert await redis_store.load("sess-2") is None
    assert await redis_store.exists("sess-2") is False


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_delete_nonexistent_is_noop_redis(redis_store: SessionStore) -> None:
    """Deleting a session that doesn't exist does not raise."""
    await redis_store.delete("never-existed")  # should not raise


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_exists_redis(redis_store: SessionStore) -> None:
    """exists() reflects save and delete."""
    assert await redis_store.exists("sess-3") is False

    await redis_store.save("sess-3", {"data": True})
    assert await redis_store.exists("sess-3") is True

    await redis_store.delete("sess-3")
    assert await redis_store.exists("sess-3") is False


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_overwrite_redis(redis_store: SessionStore) -> None:
    """Saving to an existing session overwrites the data."""
    await redis_store.save("sess-4", {"version": 1})
    await redis_store.save("sess-4", {"version": 2})

    loaded = await redis_store.load("sess-4")
    assert loaded == {"version": 2}


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_REDIS, reason="Redis server not available")
async def test_save_complex_data_redis(redis_store: SessionStore) -> None:
    """Sessions can hold nested dicts, lists, and various JSON types."""
    data = {
        "session_id": "abc-123",
        "goal": "Validate incident lifecycle",
        "steps": [
            {"index": 0, "action": "navigate", "success": True},
            {"index": 1, "action": "fill", "success": False},
        ],
        "counters": {"actions": 2, "failures": 1},
        "active": True,
        "score": 0.85,
    }
    await redis_store.save("sess-complex", data)

    loaded = await redis_store.load("sess-complex")
    assert loaded == data
