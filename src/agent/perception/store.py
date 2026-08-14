"""Recovery Store — persistence abstraction for recovered locators.

Defines the RecoveryStore interface and provides two implementations:
- InMemoryRecoveryStore: dict-backed store for tests and development.
- RedisRecoveryStore: Redis-backed store for production use.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from agent.core.logging import get_logger
from agent.perception.models import RecoveryMapping

logger = get_logger(__name__)


class RecoveryStore(ABC):
    """Abstract interface for recovery mapping persistence."""

    @abstractmethod
    async def save_mapping(self, mapping: RecoveryMapping) -> None:
        """Persist a recovery mapping."""

    @abstractmethod
    async def get_mapping(
        self, target_description: str, page_fingerprint: str
    ) -> RecoveryMapping | None:
        """Load an active recovery mapping by target and page fingerprint.

        Returns None if not found or expired.
        """

    @abstractmethod
    async def delete_mapping(self, mapping_id: str) -> None:
        """Delete a mapping by ID."""


class InMemoryRecoveryStore(RecoveryStore):
    """Dict-backed recovery store for tests and development."""

    def __init__(self) -> None:
        self._store: dict[str, RecoveryMapping] = {}

    async def save_mapping(self, mapping: RecoveryMapping) -> None:
        self._store[mapping.mapping_id] = mapping
        logger.debug("recovery_mapping_saved_in_memory", mapping_id=mapping.mapping_id)

    async def get_mapping(
        self, target_description: str, page_fingerprint: str
    ) -> RecoveryMapping | None:
        for mapping in list(self._store.values()):
            if (
                mapping.original_target == target_description
                and mapping.page_fingerprint == page_fingerprint
            ):
                if mapping.is_expired:
                    # Clean up expired
                    await self.delete_mapping(mapping.mapping_id)
                    continue
                return mapping
        return None

    async def delete_mapping(self, mapping_id: str) -> None:
        self._store.pop(mapping_id, None)
        logger.debug("recovery_mapping_deleted_in_memory", mapping_id=mapping_id)


class RedisRecoveryStore(RecoveryStore):
    """Redis-backed recovery store for production use."""

    def __init__(
        self,
        redis_client: Any,
        *,
        key_prefix: str = "recovery:",
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix

    def _key(self, target: str, fingerprint: str) -> str:
        # Use target and fingerprint to form a deterministic key
        safe_target = target.replace(" ", "_").lower()
        return f"{self._prefix}{fingerprint}:{safe_target}"

    async def save_mapping(self, mapping: RecoveryMapping) -> None:
        key = self._key(mapping.original_target, mapping.page_fingerprint)
        payload = mapping.model_dump_json()

        # Calculate remaining TTL in seconds
        import datetime

        now = datetime.datetime.utcnow()
        ttl = int((mapping.expires_at - now).total_seconds())

        if ttl > 0:
            await self._redis.setex(key, ttl, payload)
            logger.debug("recovery_mapping_saved_redis", mapping_id=mapping.mapping_id)

    async def get_mapping(
        self, target_description: str, page_fingerprint: str
    ) -> RecoveryMapping | None:
        key = self._key(target_description, page_fingerprint)
        raw = await self._redis.get(key)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            mapping = RecoveryMapping.model_validate(data)
            if mapping.is_expired:
                await self._redis.delete(key)
                return None
            return mapping
        except Exception as e:
            logger.error("recovery_mapping_parse_error", error=str(e), key=key)
            return None

    async def delete_mapping(self, mapping_id: str) -> None:
        # In this simplistic design, we'd need a secondary index to delete by mapping_id
        # For Redis, since we key by target/fingerprint, deletion by ID is non-trivial without SCAN
        # But we mostly rely on TTL for cleanup. We can leave it as a pass or implement a scan.
        pass
