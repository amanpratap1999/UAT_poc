"""Real-time Run Event Streaming and Interactive Control Protocol.

Provides Redis Pub/Sub and stream history backed event streaming for desktop-style live updates
(SSE/WebSocket) and interactive runtime control (Pause, Resume, Cancel, Clarify, Approve).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from agent.core.logging import get_logger
from agent.core.types import RunControlStatus, RunEventType

logger = get_logger(__name__)


class RunEventPublisher:
    """Publishes canonical live run execution events to Redis Pub/Sub and event history."""

    def __init__(self, redis_url: str, run_id: str) -> None:
        self.redis_url = redis_url
        self.run_id = run_id
        self._redis: Any = None
        self._connected = False
        self._sequence = 0

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import os
                import redis.asyncio as aioredis
                from agent.core.config import get_settings

                settings = get_settings()
                ssl_kwargs: dict[str, Any] = {}
                if self.redis_url.startswith("rediss://"):
                    ca_cert = settings.session.redis_tls_ca_cert or os.getenv("REDIS_TLS_CA_CERT", "")
                    if ca_cert and os.path.exists(ca_cert):
                        ssl_kwargs["ssl_ca_certs"] = ca_cert
                        ssl_kwargs["ssl_cert_reqs"] = "required"
                    else:
                        ssl_kwargs["ssl_cert_reqs"] = "none"

                self._redis = aioredis.from_url(
                    self.redis_url, decode_responses=True, **ssl_kwargs
                )  # type: ignore[no-untyped-call]
                self._connected = True
            except Exception as e:
                logger.warning("redis_event_publisher_connection_failed", error=str(e))
                self._connected = False
                return None
        return self._redis

    async def publish(
        self,
        event_type: RunEventType | str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish a canonical event to Redis Pub/Sub channel and historical log.

        Canonical Event Contract:
        {
            "run_id": str,
            "event_type": str,
            "timestamp": ISO-8601 string,
            "sequence": int,
            "payload": dict
        }
        """
        self._sequence += 1
        event_name = event_type.value if hasattr(event_type, "value") else str(event_type)

        message: dict[str, Any] = {
            "run_id": self.run_id,
            "event_type": event_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": self._sequence,
            "payload": payload or {},
        }
        raw = json.dumps(message)

        try:
            r = await self._get_redis()
            if r is not None:
                channel = f"run_events:{self.run_id}"
                await r.publish(channel, raw)
                # Store event history for reliable reconnection replay
                history_key = f"run_events_history:{self.run_id}"
                await r.rpush(history_key, raw)
                await r.expire(history_key, 7200)
                # Store latest state snapshot
                await r.set(f"run_state:{self.run_id}", raw, ex=7200)
        except Exception as e:
            logger.debug("event_publish_failed", event_type=event_name, error=str(e))

        return message

    async def get_history(self, from_sequence: int = 0) -> list[dict[str, Any]]:
        """Retrieve stored event history for reconnecting clients."""
        try:
            r = await self._get_redis()
            if not r:
                return []
            history_key = f"run_events_history:{self.run_id}"
            raw_events = await r.lrange(history_key, 0, -1)
            events: list[dict[str, Any]] = []
            for raw in raw_events:
                try:
                    data = json.loads(raw)
                    if data.get("sequence", 0) >= from_sequence:
                        events.append(data)
                except Exception:
                    continue
            return events
        except Exception as e:
            logger.debug("get_history_failed", error=str(e))
            return []

    async def close(self) -> None:
        """Close the underlying Redis client."""
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None


class RunControlReceiver:
    """Interacts with Redis to receive interactive commands (pause, resume, cancel, clarify, approve)."""

    def __init__(self, redis_url: str, run_id: str) -> None:
        self.redis_url = redis_url
        self.run_id = run_id
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
            except Exception as e:
                logger.warning("redis_control_receiver_connection_failed", error=str(e))
                return None
        return self._redis

    async def get_status(self) -> str:
        """Return the current control status (lowercase: 'running', 'paused', 'cancelled', etc.)."""
        try:
            r = await self._get_redis()
            if r:
                status = await r.get(f"run_control:{self.run_id}:status")
                return (status or RunControlStatus.RUNNING.value).lower().strip()
        except Exception as e:
            logger.debug("get_control_status_failed", error=str(e))
        return RunControlStatus.RUNNING.value

    async def set_status(self, status: RunControlStatus | str) -> None:
        """Set the control status in lowercase."""
        val = status.value if hasattr(status, "value") else str(status).lower()
        try:
            r = await self._get_redis()
            if r:
                await r.set(f"run_control:{self.run_id}:status", val, ex=7200)
        except Exception as e:
            logger.debug("set_control_status_failed", error=str(e))

    async def await_resume_or_cancel(self, poll_interval: float = 0.5) -> str:
        """Wait while the status is paused until it becomes running or cancelled."""
        while True:
            status = await self.get_status()
            if status != RunControlStatus.PAUSED.value:
                return status
            await asyncio.sleep(poll_interval)

    async def request_clarification(
        self,
        question: str,
        options: list[str] | None = None,
        timeout: float = 120.0,
        publisher: RunEventPublisher | None = None,
    ) -> str | None:
        """Request user input and wait for a response using request-specific IDs."""
        r = await self._get_redis()
        if not r:
            return None

        request_id = str(uuid.uuid4())[:8]
        prompt_key = f"run_control:{self.run_id}:clarification:{request_id}:prompt"
        answer_key = f"run_control:{self.run_id}:clarification:{request_id}:answer"

        prompt_data = {
            "request_id": request_id,
            "question": question,
            "options": options or [],
        }
        await r.set(prompt_key, json.dumps(prompt_data), ex=int(timeout) + 30)
        await self.set_status(RunControlStatus.AWAITING_USER_INPUT)

        if publisher:
            await publisher.publish(RunEventType.CLARIFICATION_REQUESTED, prompt_data)

        elapsed = 0.0
        while elapsed < timeout:
            ans = await r.get(answer_key)
            if ans:
                await r.delete(answer_key)
                await r.delete(prompt_key)
                await self.set_status(RunControlStatus.RUNNING)
                return str(ans)

            current = await self.get_status()
            if current == RunControlStatus.CANCELLED.value:
                return None

            await asyncio.sleep(0.5)
            elapsed += 0.5

        await self.set_status(RunControlStatus.RUNNING)
        return None

    async def request_approval(
        self,
        action_description: str,
        risk_score: int,
        timeout: float = 60.0,
        publisher: RunEventPublisher | None = None,
    ) -> bool:
        """Request human approval before a risky mutation. Fail-closed: returns False on error/timeout."""
        r = await self._get_redis()
        if not r:
            # Fail-closed: Redis failure must NEVER automatically approve a risky action
            logger.error("approval_rejected_redis_unavailable", run_id=self.run_id)
            return False

        prompt_id = str(uuid.uuid4())[:8]
        prompt_key = f"run_control:{self.run_id}:approval:{prompt_id}:prompt"
        decision_key = f"run_control:{self.run_id}:approval:{prompt_id}:decision"

        prompt_data = {
            "prompt_id": prompt_id,
            "action": action_description,
            "risk_score": risk_score,
        }
        await r.set(prompt_key, json.dumps(prompt_data), ex=int(timeout) + 30)
        await self.set_status(RunControlStatus.AWAITING_APPROVAL)

        if publisher:
            await publisher.publish(RunEventType.APPROVAL_PROMPT, prompt_data)

        elapsed = 0.0
        while elapsed < timeout:
            decision = await r.get(decision_key)
            if decision is not None:
                await r.delete(decision_key)
                await r.delete(prompt_key)
                await self.set_status(RunControlStatus.RUNNING)
                return str(decision).strip().lower() in ("true", "1", "yes", "approved")

            current = await self.get_status()
            if current == RunControlStatus.CANCELLED.value:
                return False

            await asyncio.sleep(0.5)
            elapsed += 0.5

        # Fail-closed timeout
        logger.warning("approval_timed_out_fail_closed", run_id=self.run_id, prompt_id=prompt_id)
        await self.set_status(RunControlStatus.RUNNING)
        return False

    async def close(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
