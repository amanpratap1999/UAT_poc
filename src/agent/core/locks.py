import asyncio
import os
import redis.asyncio as redis
from typing import Any
from agent.core.config import get_settings

class RecordLockManager:
    """Manages leases/locks for ServiceNow records to ensure concurrency isolation."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.use_redis = self.settings.session.store_type == "redis"
        self._redis: redis.Redis | None = None
        self._local_locks: dict[str, asyncio.Lock] = {}
        
    async def get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(self.settings.session.redis_url)
        return self._redis

    async def acquire_lease(self, record_id: str, session_id: str, timeout_seconds: int = 300) -> bool:
        """Acquire an exclusive lease for a given record.
        Returns True if acquired, False if currently locked by another session.
        """
        if not record_id:
            return True
            
        lock_key = f"uat:lease:record:{record_id}"
        
        if self.use_redis:
            r = await self.get_redis()
            acquired = await r.set(lock_key, session_id, nx=True, ex=timeout_seconds)
            if not acquired:
                # Check if we already own it
                current = await r.get(lock_key)
                if current and current.decode('utf-8') == session_id:
                    # Extend our lease
                    await r.expire(lock_key, timeout_seconds)
                    return True
            return bool(acquired)
        else:
            if lock_key not in self._local_locks:
                self._local_locks[lock_key] = asyncio.Lock()
            # If we already hold it, we can't easily tell with standard Lock,
            # but if it's not locked, we can acquire it.
            if self._local_locks[lock_key].locked():
                return False
            await self._local_locks[lock_key].acquire()
            return True

    async def release_lease(self, record_id: str, session_id: str) -> None:
        """Release a lease for a given record if we own it."""
        if not record_id:
            return
            
        lock_key = f"uat:lease:record:{record_id}"
        
        if self.use_redis:
            r = await self.get_redis()
            current = await r.get(lock_key)
            if current and current.decode('utf-8') == session_id:
                await r.delete(lock_key)
        else:
            if lock_key in self._local_locks and self._local_locks[lock_key].locked():
                # We can't trivially check ownership of an asyncio.Lock without custom wrappers,
                # but we'll try to release if locked. (Note: standard Lock throws if not owner).
                try:
                    self._local_locks[lock_key].release()
                except RuntimeError:
                    pass

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
