"""Authentication router for generating tokens."""

from __future__ import annotations

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


async def _check_rate_limit(key: str) -> bool:
    """Check if key has exceeded MAX_ATTEMPTS. Returns True if locked out."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            import redis.asyncio as redis
            r = redis.from_url(settings.session.redis_url)  # type: ignore[no-untyped-call]
            count = await r.get(f"uat:auth:lock:{key}")
            await r.aclose()
            if count and int(count) >= MAX_ATTEMPTS:
                return True
            return False
        except Exception:
            pass

    now = time.time()
    attempts = [t for t in _local_attempts[key] if now - t < LOCKOUT_WINDOW]
    _local_attempts[key] = attempts
    return len(attempts) >= MAX_ATTEMPTS


async def _record_failed_attempt(key: str) -> None:
    """Record a failed login attempt with expiration."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            import redis.asyncio as redis
            r = redis.from_url(settings.session.redis_url)  # type: ignore[no-untyped-call]
            pipe = r.pipeline()
            redis_key = f"uat:auth:lock:{key}"
            pipe.incr(redis_key)
            pipe.expire(redis_key, LOCKOUT_WINDOW)
            await pipe.execute()
            await r.aclose()
            return
        except Exception:
            pass

    _local_attempts[key].append(time.time())


async def _clear_attempts(key: str) -> None:
    """Clear failed attempts on successful login."""
    settings = get_settings()
    if settings.session.store_type == "redis":
        try:
            import redis.asyncio as redis
            r = redis.from_url(settings.session.redis_url)  # type: ignore[no-untyped-call]
            await r.delete(f"uat:auth:lock:{key}")
            await r.aclose()
        except Exception:
            pass

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
