"""Authentication router for generating tokens."""

import time
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.api.v1.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    Token,
    create_access_token,
    verify_password,
)
from agent.core.db import get_db_session
from agent.domain.models import User

router = APIRouter(tags=["auth"])

_login_attempts: dict[str, list[float]] = defaultdict(list)
MAX_ATTEMPTS = 5
LOCKOUT_WINDOW = 300  # 5 minutes

@router.post("/api/v1/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""

    now = time.time()
    username = form_data.username
    attempts = _login_attempts[username]
    
    # Filter attempts within window
    _login_attempts[username] = [t for t in attempts if now - t < LOCKOUT_WINDOW]
    
    if len(_login_attempts[username]) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Account temporarily locked.",
        )

    user = None
    try:
        result = await db.execute(select(User).where(User.username == form_data.username))
        user = result.scalars().first()
    except Exception:
        user = None

    if not user:
        _login_attempts[username].append(time.time())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not verify_password(form_data.password, user.hashed_password):
        _login_attempts[username].append(time.time())
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
    if username in _login_attempts:
        del _login_attempts[username]

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}
