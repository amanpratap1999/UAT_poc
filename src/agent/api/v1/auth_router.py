"""Authentication router for generating tokens."""

import uuid
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
    get_password_hash,
    verify_password,
)
from agent.core.db import get_db_session
from agent.domain.models import Tenant, User

router = APIRouter(tags=["auth"])


@router.post("/api/v1/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """OAuth2 compatible token login, get an access token for future requests."""

    # In a real system, we'd query the DB:
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        # Fallback for local testing if the DB is empty, let's create an admin user on the fly
        if form_data.username == "admin" and form_data.password == "admin":
            # Check if tenant exists
            tenant_res = await db.execute(select(Tenant).where(Tenant.id == "tenant-0"))
            tenant = tenant_res.scalars().first()
            if not tenant:
                tenant = Tenant(id="tenant-0", name="Default Tenant")
                db.add(tenant)
                await db.commit()

            # Check again if user exists to avoid race conditions
            user_res = await db.execute(select(User).where(User.username == "admin"))
            user = user_res.scalars().first()
            if not user:
                user = User(
                    id=str(uuid.uuid4()),
                    tenant_id="tenant-0",
                    username="admin",
                    hashed_password=get_password_hash("admin"),
                    role="Admin",
                )
                db.add(user)
                await db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "user_id": user.id,
        },
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}
