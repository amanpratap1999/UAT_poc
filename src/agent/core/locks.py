"""Record-level concurrency isolation via distributed leases.

Uses Redis ``SET NX EX`` for cross-worker leases when available, and falls
back to a process-local ``OwnedLock`` with TTL for single-process dev mode.
The local fallback emits a warning on every acquire to surface the limitation.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as redis

from agent.core.config import get_settings
from agent.core.logging import get_logger

logger = get_logger(__name__)

LUA_RELEASE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@dataclass
class OwnedLock:
    """Process-local lock with ownership tracking and TTL expiration."""

    session_id: str
    acquired_at: float  # time.monotonic()
    ttl_seconds: float

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.acquired_at) > self.ttl_seconds


class RecordLockManager:
    """Manages leases/locks for ServiceNow records to ensure concurrency isolation.

    Production mode (``store_type == "redis"``): Uses Redis ``SET NX EX`` for
    distributed cross-worker leases with automatic TTL expiration, atomic Lua release,
    and optional renewal heartbeats.

    Dev-local mode: Falls back to ``OwnedLock`` — a process-local dict with
    session ownership and TTL. **Not cross-process.** A warning is logged on
    every acquire to make the limitation visible.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.is_production = (
            self.settings.runtime_mode == "docker"
            or self.settings.environment not in ("development", "dev", "local")
        )
        self.use_redis = self.settings.session.store_type == "redis"
        if self.is_production and not self.use_redis:
            logger.error(
                "production_locking_misconfigured",
                note="Production runtime must use Redis-backed distributed locks.",
            )
            raise RuntimeError(
                "Production runtime configuration error: SESSION_STORE_TYPE must be 'redis' "
                "for distributed record locking."
            )

        self._redis: Any | None = None
        self._local_locks: dict[str, OwnedLock] = {}
        self._heartbeats: dict[str, asyncio.Task[None]] = {}

    async def get_redis(self) -> Any:
        if self._redis is None:
            redis_url = self.settings.session.redis_url
            ssl_kwargs: dict[str, Any] = {}
            if redis_url.startswith("rediss://"):
                ca_cert = self.settings.session.redis_tls_ca_cert or os.getenv("REDIS_TLS_CA_CERT", "")
                if ca_cert and os.path.exists(ca_cert):
                    ssl_kwargs["ssl_ca_certs"] = ca_cert
                    ssl_kwargs["ssl_cert_reqs"] = "required"
                elif self.is_production:
                    raise RuntimeError("Missing REDIS_TLS_CA_CERT in production for rediss:// URL")
                else:
                    ssl_kwargs["ssl_cert_reqs"] = "none"
            self._redis = redis.from_url(redis_url, **ssl_kwargs)  # type: ignore[no-untyped-call]
        return self._redis

    def _build_lock_key(
        self, record_id: str, table: str = "", instance: str = ""
    ) -> str:
        inst_part = instance.strip().lower() or "instance"
        tbl_part = table.strip().lower() or "record"
        return f"uat:lease:{inst_part}:{tbl_part}:{record_id.strip()}"

    # ------------------------------------------------------------------
    # Acquire
    # ------------------------------------------------------------------

    async def acquire_lease(
        self,
        record_id: str,
        session_id: str,
        timeout_seconds: int = 300,
        table: str = "",
        instance: str = "",
    ) -> bool:
        """Acquire an exclusive lease for a given record.

        Returns ``True`` if acquired or already owned by this session,
        ``False`` if currently locked by another session.
        """
        if not record_id:
            return True

        lock_key = self._build_lock_key(record_id, table, instance)

        if self.use_redis:
            try:
                return await self._acquire_redis(lock_key, session_id, timeout_seconds)
            except Exception as e:
                if self.is_production:
                    logger.error("redis_lock_failed_production", error=str(e), lock_key=lock_key)
                    raise RuntimeError(f"Failed to acquire distributed lock in production: {e}") from e
                logger.warning("redis_lock_failed_fallback_local", error=str(e))
                return self._acquire_local(lock_key, session_id, timeout_seconds)

        return self._acquire_local(lock_key, session_id, timeout_seconds)

    async def _acquire_redis(
        self, lock_key: str, session_id: str, timeout_seconds: int
    ) -> bool:
        r = await self.get_redis()
        acquired = await r.set(lock_key, session_id, nx=True, ex=timeout_seconds)
        if not acquired:
            current = await r.get(lock_key)
            if current and current.decode("utf-8") == session_id:
                # Extend our own lease
                await r.expire(lock_key, timeout_seconds)
                return True
            return False
        return True

    def _acquire_local(
        self, lock_key: str, session_id: str, timeout_seconds: int
    ) -> bool:
        logger.warning(
            "local_lock_fallback",
            lock_key=lock_key,
            session_id=session_id,
            note="Process-local lock — not cross-worker. Set store_type=redis for production.",
        )

        self._evict_expired()

        existing = self._local_locks.get(lock_key)
        if existing is not None:
            if existing.expired:
                # Expired — reclaim
                del self._local_locks[lock_key]
            elif existing.session_id == session_id:
                # Same owner — extend
                existing.acquired_at = time.monotonic()
                existing.ttl_seconds = float(timeout_seconds)
                return True
            else:
                # Held by another session
                return False

        self._local_locks[lock_key] = OwnedLock(
            session_id=session_id,
            acquired_at=time.monotonic(),
            ttl_seconds=float(timeout_seconds),
        )
        return True

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    async def release_lease(
        self,
        record_id: str,
        session_id: str,
        table: str = "",
        instance: str = "",
    ) -> None:
        """Release a lease for a given record if we own it."""
        if not record_id:
            return

        lock_key = self._build_lock_key(record_id, table, instance)

        # Stop heartbeat if running
        heartbeat = self._heartbeats.pop(lock_key, None)
        if heartbeat and not heartbeat.done():
            heartbeat.cancel()

        if self.use_redis:
            try:
                r = await self.get_redis()
                await r.eval(LUA_RELEASE, 1, lock_key, session_id)
            except Exception as e:
                logger.warning("redis_release_lease_error", error=str(e), lock_key=lock_key)
        else:
            existing = self._local_locks.get(lock_key)
            if existing is not None and existing.session_id == session_id:
                del self._local_locks[lock_key]

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def start_heartbeat(
        self,
        record_id: str,
        session_id: str,
        interval_seconds: float = 60.0,
        ttl_seconds: int = 300,
        table: str = "",
        instance: str = "",
    ) -> None:
        """Start a background heartbeat to refresh lease TTL periodically."""
        lock_key = self._build_lock_key(record_id, table, instance)
        if lock_key in self._heartbeats and not self._heartbeats[lock_key].done():
            return

        async def _beat() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    if self.use_redis and self._redis:
                        r = await self.get_redis()
                        curr = await r.get(lock_key)
                        if curr and curr.decode("utf-8") == session_id:
                            await r.expire(lock_key, ttl_seconds)
                        else:
                            break
                    elif lock_key in self._local_locks:
                        lock = self._local_locks[lock_key]
                        if lock.session_id == session_id and not lock.expired:
                            lock.acquired_at = time.monotonic()
                        else:
                            break
                    else:
                        break
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    logger.warning("lock_heartbeat_error", error=str(ex), lock_key=lock_key)

        self._heartbeats[lock_key] = asyncio.create_task(_beat())

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove expired local locks to bound memory growth."""
        expired_keys = [k for k, v in self._local_locks.items() if v.expired]
        for k in expired_keys:
            del self._local_locks[k]

    async def close(self) -> None:
        for task in self._heartbeats.values():
            if not task.done():
                task.cancel()
        self._heartbeats.clear()
        if self._redis:
            await self._redis.aclose()
