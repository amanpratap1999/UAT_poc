"""Session Store — persistence abstraction for session state.

Defines the SessionStore interface and provides two implementations:
- InMemorySessionStore: dict-backed store for tests and development.
- RedisSessionStore: Redis-backed store for production use.

Both backends pass the same interface contract tests.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


class SessionStore(ABC):
    """Abstract interface for session state persistence.

    All consuming code programs against this interface. The backend
    (in-memory or Redis) is selected at wiring time, not at call sites.
    """

    @abstractmethod
    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        """Persist session data under the given session ID.

        If a session with this ID already exists, it is overwritten.
        """

    @abstractmethod
    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load session data by session ID.

        Returns None if the session does not exist.
        """

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete a session by ID.

        No-op if the session does not exist.
        """

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """Check whether a session exists."""


class InMemorySessionStore(SessionStore):
    """Dict-backed session store for tests and development."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        self._store[session_id] = data
        logger.debug("session_saved_in_memory", session_id=session_id)

    async def load(self, session_id: str) -> dict[str, Any] | None:
        return self._store.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        logger.debug("session_deleted_in_memory", session_id=session_id)

    async def exists(self, session_id: str) -> bool:
        return session_id in self._store


class RedisSessionStore(SessionStore):
    """Redis-backed session store for production use.

    Requires the ``redis`` package (``pip install redis[hiredis]``).
    Accepts any ``redis.asyncio.Redis`` instance so the caller
    controls connection pooling and configuration.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        key_prefix: str = "session:",
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Args:
            redis_client: An ``redis.asyncio.Redis`` instance.
            key_prefix: Prefix prepended to every session key.
            ttl_seconds: Optional TTL applied on save. None means no expiry.
        """
        self._redis = redis_client
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        key = self._key(session_id)
        payload = json.dumps(data)
        if self._ttl is not None:
            await self._redis.setex(key, self._ttl, payload)
        else:
            await self._redis.set(key, payload)
        logger.debug("session_saved_redis", session_id=session_id)

    async def load(self, session_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(self._key(session_id))
        logger.debug("session_deleted_redis", session_id=session_id)

    async def exists(self, session_id: str) -> bool:
        return bool(await self._redis.exists(self._key(session_id)))
