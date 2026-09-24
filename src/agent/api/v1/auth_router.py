"""Authentication router for generating tokens."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.api.v1.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    Token,
    create_access_token,
    verify_password,
)
from agent.core.config import get_settings
from agent.core.db import get_db_session
from agent.core.logging import get_logger
from agent.domain.models import User

logger = get_logger(__name__)
router = APIRouter(tags=["auth"])

_local_attempts: dict[str, list[float]] = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 300  # 5 minutes

# Audit issue I3 (P1): previously, every call to _check_rate_limit,
# _record_failed_attempt, and _clear_attempts opened a fresh
# redis.from_url(...) connection and awaited r.aclose() — an attacker
# spamming failed logins could trigger a Redis connection storm and
# exhaust the broker/backend connection pool. Now we share a single
# module-level ConnectionPool that the redis-py client uses to multiplex
# all requests on a small set of long-lived connections.
_redis_pool = None  # type: ignore[no-untyped-def]


async def _get_redis_client():
    """Return a Redis client backed by a shared connection pool.

    The pool is created once on first use and reused across all rate-limit
    calls. TLS is configured when rediss:// URL is set, mirroring the broker
    TLS configuration in celery_app.py.
    """
    global _redis_pool
    import redis.asyncio as redis
    if _redis_pool is None:
        settings = get_settings()
        pool_kwargs: dict[str, Any] = {"decode_responses": True}
        redis_url = settings.session.redis_url
        if redis_url.startswith("rediss://"):
            ca_cert = settings.session.redis_tls_ca_cert or os.getenv("REDIS_TLS_CA_CERT", "")
            client_cert = settings.session.redis_tls_cert or os.getenv("REDIS_TLS_CERT", "")
            client_key = settings.session.redis_tls_key or os.getenv("REDIS_TLS_KEY", "")
            if ca_cert and os.path.exists(ca_cert):
                pool_kwargs["ssl_ca_certs"] = ca_cert
                pool_kwargs["ssl_cert_reqs"] = "required"
            else:
                pool_kwargs["ssl_cert_reqs"] = "none"
            if client_cert and os.path.exists(client_cert):
                pool_kwargs["ssl_certfile"] = client_cert
            if client_key and os.path.exists(client_key):
                pool_kwargs["ssl_keyfile"] = client_key
        _redis_pool = redis.ConnectionPool.from_url(redis_url, **pool_kwargs)  # type: ignore[no-untyped-call]
    return redis.Redis(connection_pool=_redis_pool)  # type: ignore[no-untyped-call]


def _is_fail_closed() -> bool:
    """Return True if Redis errors should fail-closed (raise 503) rather than fall back.

    Audit issue I4 (P1): previously the check was
    `is_prod = runtime_mode == "docker" or environment not in ("development", "dev", "local")`.
    This treated `runtime_mode="local" AND environment="staging"` as not-prod (because
    the docker check failed), so a staging environment silently fell back to the
    in-process _local_attempts dict, disabling brute-force protection during a real
    Redis outage. Fix: the fallback is now explicit-only for `environment in
    ("development", "dev", "local")` — every other environment (staging, qa, uat,
    production, anything unnamed) fails closed.
    """
    settings = get_settings()
    return settings.environment not in ("development", "dev", "local")


async def _check_rate_limit(key: str) -> bool:
    """Check if key has exceeded MAX_ATTEMPTS. Returns True if locked out."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            r = await _get_redis_client()
            count = await r.get(f"uat:auth:lock:{key}")
            # Note: pool-managed client — do NOT call r.aclose() (audit issue I3).
            if count and int(count) >= MAX_ATTEMPTS:
                return True
            return False
        except Exception as e:
            if _is_fail_closed():
                logger.error("redis_auth_lock_failed", error=str(e))
                raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
            logger.warning("redis_auth_lock_fallback", error=str(e))

    now = time.time()
    attempts = [t for t in _local_attempts[key] if now - t < LOCKOUT_WINDOW]
    _local_attempts[key] = attempts
    return len(attempts) >= MAX_ATTEMPTS


async def _record_failed_attempt(key: str) -> None:
    """Record a failed login attempt with expiration."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            r = await _get_redis_client()
            pipe = r.pipeline()
            redis_key = f"uat:auth:lock:{key}"
            pipe.incr(redis_key)
            pipe.expire(redis_key, LOCKOUT_WINDOW)
            await pipe.execute()
            # Note: pool-managed client — do NOT call r.aclose() (audit issue I3).
            return
        except Exception as e:
            if _is_fail_closed():
                logger.error("redis_auth_record_failed", error=str(e))
                raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
            logger.warning("redis_auth_record_fallback", error=str(e))

    _local_attempts[key].append(time.time())


async def _clear_attempts(key: str) -> None:
    """Clear failed attempts on successful login."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            r = await _get_redis_client()
            await r.delete(f"uat:auth:lock:{key}")
            # Note: pool-managed client — do NOT call r.aclose() (audit issue I3).
            return
        except Exception as e:
            if _is_fail_closed():
                logger.error("redis_auth_clear_failed", error=str(e))
                raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
            logger.warning("redis_auth_clear_fallback", error=str(e))

    _local_attempts.pop(key, None)


@router.post("/api/v1/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""
    username = form_data.username
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

    # Check lockout for username and client IP
    if await _check_rate_limit(f"user:{username}") or await _check_rate_limit(f"ip:{client_ip}"):
        logger.warning(
            "auth_lockout_rejected",
            username=username,
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Account temporarily locked.",
        )

    # Query database with typed error handling
    try:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalars().first()
    except SQLAlchemyError as db_err:
        logger.error("auth_db_connection_error", error=str(db_err), client_ip=client_ip)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from db_err

    # Unified rejection for non-existent user or invalid password (no username disclosure)
    if not user or not verify_password(form_data.password, user.hashed_password):
        await _record_failed_attempt(f"user:{username}")
        await _record_failed_attempt(f"ip:{client_ip}")
        logger.warning(
            "auth_login_failed",
            username=username,
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = {
        "sub": user.username,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "user_id": user.id,
    }

    # Reset attempts on success
    await _clear_attempts(f"user:{username}")
    await _clear_attempts(f"ip:{client_ip}")
    logger.info("auth_login_success", username=username, client_ip=client_ip)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}
