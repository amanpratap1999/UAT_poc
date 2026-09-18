"""Celery application configuration."""

import os
import socket
import sys

from celery import Celery  # type: ignore

from agent.core.config import get_settings

_settings = get_settings()


def _redis_major_version(host: str, port: int, timeout: float = 1.5) -> int | None:
    """Ask the Redis server for its major version via an inline INFO probe.

    Uses Redis's inline command format (plain text terminated by CRLF), which
    works on every Redis version and needs no handshake.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"INFO server\r\n")
            data = b""
            while b"redis_version:" not in data and len(data) < 4096:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            text = data.decode("utf-8", errors="replace")
            for line in text.replace("\r\r\n", "\n").splitlines():
                if "redis_version:" in line:
                    version_str = line.split(":", 1)[1].strip()
                    return int(version_str.split(".")[0])
    except OSError:
        pass
    return None


def _apply_redis_resp2_default() -> None:
    """Force redis-py's default RESP protocol to 2 (no HELLO handshake).

    redis-py 8.x defaults to RESP3, whose handshake sends the HELLO command —
    unknown to Redis < 6 (the bundled Windows Redis is 5.0.14). kombu 5.6 does
    not forward a protocol option, so we flip redis-py's global default when
    an old server is detected.

    Implementation note: ``redis.connection`` (and possibly other modules)
    import ``DEFAULT_RESP_VERSION`` by name — a copied binding — so patching
    ``redis.utils`` alone is not enough. We patch the attribute in every
    already-loaded ``redis.*`` module. Redis >= 6 keeps the RESP3 default.
    """
    try:
        from urllib.parse import urlparse

        url = os.getenv(
            "CELERY_BROKER_URL",
            _settings.session.celery_broker_url or _settings.session.redis_url,
        )
        if not url or not url.startswith("redis://"):
            return
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 6379
        major = _redis_major_version(host, port)
        if major is None or major >= 6:
            return

        import redis.utils as _redis_utils

        _redis_utils.DEFAULT_RESP_VERSION = 2  # type: ignore[attr-defined]
        patched = ["redis.utils"]
        # Update the copied by-name bindings in every already-imported module.
        for name, mod in list(sys.modules.items()):
            if name == "redis.utils" or not name.startswith("redis"):
                continue
            if mod is not None and hasattr(mod, "DEFAULT_RESP_VERSION"):
                mod.DEFAULT_RESP_VERSION = 2  # type: ignore[attr-defined]
                patched.append(name)
    except Exception:
        # Never let broker-version detection break application startup.
        pass


_apply_redis_resp2_default()

broker_url = os.getenv(
    "CELERY_BROKER_URL",
    _settings.session.celery_broker_url or _settings.session.redis_url,
)
backend_url = os.getenv(
    "CELERY_RESULT_BACKEND",
    _settings.session.celery_result_backend or _settings.session.redis_url,
)

celery_app = Celery(
    "agent_worker",
    broker=broker_url,
    backend=backend_url,
    include=["agent.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
)
