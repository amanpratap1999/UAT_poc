"""API v1 router — routing layer for agent operations, multi-tenant aware."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent import __version__
from agent.api.v1.auth import TokenData, get_current_user_token, require_qa_manager
from agent.api.v1.schemas import (
    FindingResponse,
    HealthResponse,
    MetricsResponse,
    RunDetailResponse,
    RunRequest,
    RunResponse,
)
from agent.core.db import get_db_session
from agent.domain.models import Finding, Run
from agent.worker.tasks import execute_run

router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=__version__,
    )


@router.post("/runs", response_model=RunResponse)
async def create_run(
    request: RunRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunResponse:
    """Start an autonomous agent run. Queues a Celery task."""
    run_id = str(uuid.uuid4())

    new_run = Run(
        id=run_id,
        tenant_id=token.tenant_id or "unknown",
        requester_id=token.user_id,
        goal=request.goal,
        status="queued",
    )
    db.add(new_run)
    await db.commit()

    # Enqueue Celery task (we use .delay which is synchronous but fast)
    execute_run.delay(run_id=run_id, goal=request.goal, tenant_id=token.tenant_id)

    return RunResponse(
        session_id=run_id,
        status="queued",
        message=f"Agent run queued for goal: {request.goal}",
    )


@router.get("/runs", response_model=list[RunDetailResponse])
async def list_runs(
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """List runs for the current tenant."""
    result = await db.execute(
        select(Run)
        .where(Run.tenant_id == token.tenant_id)
        .order_by(Run.start_time.desc())
        .limit(100)
    )
    runs = result.scalars().all()
    return runs


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get details of a specific run."""
    result = await db.execute(select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id))
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/findings", response_model=list[FindingResponse])
async def list_findings(
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """List findings across all runs for the tenant."""
    result = await db.execute(
        select(Finding)
        .where(Finding.tenant_id == token.tenant_id)
        .order_by(Finding.created_at.desc())
        .limit(100)
    )
    return result.scalars().all()


@router.get("/metrics", response_model=MetricsResponse, dependencies=[Depends(require_qa_manager)])
async def get_metrics(
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get aggregated metrics for the tenant. Requires QA Manager or Admin role."""
    # Total runs
    runs_result = await db.execute(
        select(func.count(Run.id)).where(Run.tenant_id == token.tenant_id)
    )
    total_runs = runs_result.scalar() or 0

    # Total defects
    defects_result = await db.execute(
        select(func.sum(Run.defect_count)).where(Run.tenant_id == token.tenant_id)
    )
    total_defects = defects_result.scalar() or 0

    # Average duration
    duration_result = await db.execute(
        select(func.avg(Run.duration_seconds)).where(
            Run.tenant_id == token.tenant_id, Run.status == "completed"
        )
    )
    avg_duration = duration_result.scalar()

    return MetricsResponse(
        tenant_id=token.tenant_id or "unknown",
        total_runs=total_runs,
        total_defects=int(total_defects),
        average_duration_seconds=float(avg_duration) if avg_duration else None,
    )
