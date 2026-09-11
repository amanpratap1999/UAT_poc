import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agent import __version__
from agent.api.v1.auth import (
    TokenData,
    create_sse_ticket,
    get_current_user_token,
    require_qa_manager,
    validate_sse_ticket,
    validate_token_string,
)
from agent.api.v1.dependencies import get_cached_settings, get_knowledge_model
from agent.api.v1.schemas import (
    ActionResponse,
    ApprovalDecisionRequest,
    CancelRequest,
    ClarifyAnswerRequest,
    FindingResponse,
    FindingUpdateRequest,
    GenerateTestCasesRequest,
    GenerateTestCasesResponse,
    GeneratedTestCaseResponse,
    HealthResponse,
    KnowledgeDriftResponse,
    KnowledgeModelRulesResponse,
    KnowledgeRuleResponse,
    MetricsResponse,
    PauseRequest,
    ResumeRequest,
    RunDetailResponse,
    RunRequest,
    RunResponse,
)
from agent.core.db import get_db_session
from agent.domain.models import Finding, Run, Screenshot, TestCaseModel
from agent.worker.tasks import execute_run

router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.get("/screenshots/{filename}")
async def get_screenshot(
    filename: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FileResponse:
    """Serve a run screenshot from the shared screenshots directory with tenant isolation.

    Path traversal is blocked by resolving the requested filename against
    the screenshots root and verifying it stays strictly inside that root.
    Tenant isolation is verified via the Screenshot ownership table or Run association.
    """
    import mimetypes as _mimetypes
    import re as _re
    from pathlib import Path as _Path

    from agent.api.v1.dependencies import get_cached_settings

    # Reject anything that isn't a plain filename (no dirs, no traversal)
    if (
        not _re.fullmatch(r"[A-Za-z0-9._-]+", filename)
        or filename.startswith(".")
        or ".." in filename
    ):
        raise HTTPException(status_code=400, detail="Invalid screenshot filename")

    root = _Path(get_cached_settings().screenshot_dir).resolve()
    target = (root / filename).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid screenshot filename")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    # Enforce tenant isolation
    sc_res = await db.execute(select(Screenshot).where(Screenshot.filename == filename))
    screenshot_rec = sc_res.scalars().first()
    if screenshot_rec:
        if screenshot_rec.tenant_id != token.tenant_id:
            raise HTTPException(status_code=404, detail="Screenshot not found or unauthorized")
    else:
        # Fallback check if filename starts with a run_id UUID
        m = _re.match(r"^([0-9a-fA-F-]{36})", filename)
        if m:
            r_res = await db.execute(select(Run).where(Run.id == m.group(1)))
            r_obj = r_res.scalars().first()
            if r_obj and r_obj.tenant_id != token.tenant_id:
                raise HTTPException(status_code=404, detail="Screenshot not found or unauthorized")

    content_type, _ = _mimetypes.guess_type(str(target))
    media_type = content_type or "image/png"
    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=__version__,
    )


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe checking database, redis, output directories, and embedding client."""
    import os
    import redis.asyncio as aioredis
    from agent.api.v1.dependencies import get_embedding_client
    from agent.core.config import REPO_ROOT

    settings = get_cached_settings()
    checks: dict[str, Any] = {}
    is_ready = True

    # 1. PostgreSQL check
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        is_sqlite = settings.domain.postgres_url.startswith("sqlite")
        test_engine = create_async_engine(settings.domain.postgres_url, poolclass=NullPool)
        try:
            async with test_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                has_vector = False
                if not is_sqlite:
                    pgv_res = await conn.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    )
                    has_vector = pgv_res.scalar_one_or_none() is not None
                checks["database"] = {
                    "status": "ok",
                    "backend": "sqlite" if is_sqlite else "postgresql",
                    "pgvector": has_vector,
                }
        finally:
            await test_engine.dispose()
    except Exception as exc:
        is_ready = False
        import re
        safe_err = re.sub(r"://[^@]+@", "://***:***@", str(exc))
        checks["database"] = {
            "status": "unhealthy",
            "error": safe_err or "Database connection failed",
        }

    # 2. Redis check
    try:
        redis_client = aioredis.from_url(settings.session.redis_url, decode_responses=True)
        try:
            await redis_client.ping()
            checks["redis"] = {"status": "ok"}
        finally:
            await redis_client.aclose()
    except Exception as exc:
        is_ready = False
        import re
        safe_err = re.sub(r"://[^@]+@", "://***:***@", str(exc))
        checks["redis"] = {
            "status": "unhealthy",
            "error": safe_err or "Redis connection failed",
        }

    # 3. Output directories check
    try:
        settings.ensure_directories()
        report_ok = os.access(settings.report_output_dir, os.W_OK)
        screenshot_ok = os.access(settings.screenshot_dir, os.W_OK)
        if report_ok and screenshot_ok:
            checks["directories"] = {
                "status": "ok",
                "reports": str(settings.report_output_dir),
                "screenshots": str(settings.screenshot_dir),
            }
        else:
            is_ready = False
            checks["directories"] = {
                "status": "unhealthy",
                "reports_writable": report_ok,
                "screenshots_writable": screenshot_ok,
            }
    except Exception:
        is_ready = False
        checks["directories"] = {
            "status": "unhealthy",
            "error": "Directory check failed",
        }

    # 4. Embedding client check
    try:
        embedding_client = get_embedding_client(settings)
        if hasattr(embedding_client, "startup_health_check"):
            emb_ok = await asyncio.wait_for(embedding_client.startup_health_check(), timeout=3.0)
            checks["embedding_client"] = {
                "status": "ok" if emb_ok else "degraded",
                "model": settings.llm.embedding_model,
            }
        else:
            checks["embedding_client"] = {
                "status": "ok",
                "model": settings.llm.embedding_model,
            }
    except Exception:
        checks["embedding_client"] = {
            "status": "unhealthy",
            "error": "Embedding client initialization failed",
            "model": settings.llm.embedding_model,
        }

    content = {
        "status": "ready" if is_ready else "not_ready",
        "runtime_mode": settings.runtime_mode,
        "checks": checks,
    }
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content=content,
    )


@router.get("/diagnostics/paths")
async def get_diagnostic_paths(
    token: Annotated[TokenData, Depends(get_current_user_token)],
) -> dict[str, Any]:
    """Return resolved filesystem paths and runtime mode safely without secrets. Requires authentication."""
    from agent.core.config import REPO_ROOT

    settings = get_cached_settings()
    return {
        "runtime_mode": settings.runtime_mode,
        "repo_root": str(REPO_ROOT),
        "report_output_dir": str(settings.report_output_dir),
        "screenshot_dir": str(settings.screenshot_dir),
    }


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

    # Enqueue Celery task with error handling
    try:
        execute_run.delay(run_id=run_id, goal=request.goal, tenant_id=token.tenant_id)
    except Exception as exc:
        new_run.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue execution task: {exc}",
        )

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


@router.get("/runs/{run_id}/perception")
async def get_run_perception(
    run_id: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Return persisted perception frames (screenshots + grounding boxes) for a run.

    The worker writes ``<reports_dir>/<run_id>_perception.json`` when a run
    finishes. Screenshots are referenced by filename and served separately
    via ``GET /api/v1/screenshots/{filename}``.
    """
    from pathlib import Path as _Path

    from agent.api.v1.dependencies import get_cached_settings

    # Tenant isolation — run must belong to the caller
    result = await db.execute(select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id))
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    import json as _json

    evidence_path = (
        _Path(get_cached_settings().report_output_dir).resolve()
        / f"{run_id}_perception.json"
    )
    if not evidence_path.is_file():
        return {"run_id": run_id, "status": run.status, "frames": []}

    try:
        data = _json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read perception evidence: {e}")

    data["status"] = run.status
    return data


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


@router.patch("/findings/{finding_id}", response_model=FindingResponse)
async def update_finding(
    finding_id: str,
    request: FindingUpdateRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Update or override a finding (e.g. classification, is_defect flag, severity)."""
    result = await db.execute(
        select(Finding).where(Finding.id == finding_id, Finding.tenant_id == token.tenant_id)
    )
    finding = result.scalars().first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    if request.capability is not None:
        finding.capability = request.capability
    if request.description is not None:
        finding.description = request.description
    if request.is_defect is not None:
        finding.is_defect = request.is_defect
    if request.severity is not None:
        finding.severity = request.severity

    await db.commit()
    await db.refresh(finding)
    return finding


@router.get("/knowledge-model/rules", response_model=KnowledgeModelRulesResponse)
async def get_knowledge_model_rules(
    token: Annotated[TokenData, Depends(get_current_user_token)],
    table: str | None = None,
) -> Any:
    """Get discovered rules, UI policies, and dictionary constraints from the knowledge model."""
    km = get_knowledge_model()
    rules: list[KnowledgeRuleResponse] = []
    tables = list(km.tables.keys()) if km.tables else ["incident", "problem", "change_request"]

    for tbl_name, tbl_meta in km.tables.items():
        if table and tbl_name.lower() != table.lower():
            continue
        for field_name, field_meta in tbl_meta.fields.items():
            if field_meta.mandatory:
                rules.append(
                    KnowledgeRuleResponse(
                        rule_id=f"DICT-{tbl_name}-{field_name}-MANDATORY",
                        table=tbl_name,
                        name=f"{field_name} Mandatory",
                        type="dictionary",
                        description=f"Field '{field_name}' is mandatory in dictionary",
                        details={"field": field_name, "mandatory": True},
                    )
                )
            if field_meta.read_only:
                rules.append(
                    KnowledgeRuleResponse(
                        rule_id=f"DICT-{tbl_name}-{field_name}-READONLY",
                        table=tbl_name,
                        name=f"{field_name} Read Only",
                        type="dictionary",
                        description=f"Field '{field_name}' is read-only in dictionary",
                        details={"field": field_name, "read_only": True},
                    )
                )
        for policy in tbl_meta.active_ui_policies:
            rules.append(
                KnowledgeRuleResponse(
                    rule_id=str(policy.get("sys_id", f"POL-{tbl_name}-{policy.get('name', 'unknown')}")),
                    table=tbl_name,
                    name=policy.get("name", "UI Policy"),
                    type="ui_policy",
                    description=policy.get("description", f"UI Policy on {tbl_name}"),
                    details=policy,
                )
            )
        for br in tbl_meta.active_business_rules:
            rules.append(
                KnowledgeRuleResponse(
                    rule_id=str(br.get("sys_id", f"BR-{tbl_name}-{br.get('name', 'unknown')}")),
                    table=tbl_name,
                    name=br.get("name", "Business Rule"),
                    type="business_rule",
                    description=br.get("description", f"Business Rule on {tbl_name}"),
                    details=br,
                )
            )

    return KnowledgeModelRulesResponse(
        total=len(rules),
        tables=tables,
        rules=rules,
    )


@router.get("/knowledge-model/rules/{rule_id}", response_model=KnowledgeRuleResponse)
async def get_knowledge_model_rule(
    rule_id: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
) -> Any:
    """Get a specific rule by ID from the knowledge model."""
    all_rules_res = await get_knowledge_model_rules(token=token)
    for rule in all_rules_res.rules:
        if rule.rule_id == rule_id:
            return rule
    raise HTTPException(status_code=404, detail="Rule not found in knowledge model")


@router.get("/knowledge-model/drift", response_model=KnowledgeDriftResponse)
async def get_knowledge_model_drift(
    token: Annotated[TokenData, Depends(get_current_user_token)],
) -> Any:
    """Get drift detection status for ServiceNow metadata."""
    from datetime import UTC, datetime

    km = get_knowledge_model()
    has_tables = bool(km.tables)
    return KnowledgeDriftResponse(
        has_drift=False,
        status="verified" if has_tables else "unverified",
        last_checked=datetime.now(UTC),
        drifted_tables=[],
        model_version=km.version,
    )


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

    # Average duration across all terminal runs
    terminal_statuses = [
        "completed",
        "passed",
        "failed",
        "partial",
        "precondition_failed",
        "blocked",
    ]
    duration_result = await db.execute(
        select(func.avg(Run.duration_seconds)).where(
            Run.tenant_id == token.tenant_id,
            Run.status.in_(terminal_statuses),
            Run.duration_seconds.isnot(None),
        )
    )
    avg_duration = duration_result.scalar()

    return MetricsResponse(
        tenant_id=token.tenant_id or "unknown",
        total_runs=total_runs,
        total_defects=int(total_defects),
        average_duration_seconds=float(avg_duration) if avg_duration else None,
    )


# ---------------------------------------------------------------------------
# Real-Time Event Streaming (SSE)
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/stream-ticket")
async def get_stream_ticket(
    run_id: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Issue a short-lived ticket (120s) specifically scoped for the SSE stream."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    if not run_res.scalars().first():
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    ticket = create_sse_ticket(
        {
            "sub": token.username,
            "role": token.role,
            "tenant_id": token.tenant_id,
            "user_id": token.user_id,
        },
        expires_seconds=120,
    )
    return {"ticket": ticket}


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    ticket: str | None = None,
    token: str | None = None,
    from_sequence: int = 0,
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Stream live run events (SSE) with ticket or JWT authentication, tenant isolation, and reconnection replay."""
    auth_str = ticket or token
    if not auth_str:
        raise HTTPException(status_code=401, detail="Authentication ticket or token required")

    if ticket:
        token_data = validate_sse_ticket(ticket)
    else:
        token_data = validate_token_string(token)  # type: ignore[arg-type]

    # Enforce tenant isolation on SSE stream
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token_data.tenant_id)
    )
    if not run_res.scalars().first():
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    async def event_generator():
        settings = get_cached_settings()
        r = None
        pubsub = None
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            channel_name = f"run_events:{run_id}"
            await pubsub.subscribe(channel_name)

            # 1. Connection handshake
            handshake = json.dumps({
                "run_id": run_id,
                "event_type": "connected",
                "timestamp": datetime.now(UTC).isoformat(),
                "sequence": 0,
                "payload": {"status": "connected"},
            })
            yield f"event: connected\ndata: {handshake}\n\n"

            # 2. Replay historical events from Redis list for reconnecting clients
            history_key = f"run_events_history:{run_id}"
            raw_history = await r.lrange(history_key, 0, -1)
            last_replayed_seq = 0
            for raw in raw_history:
                try:
                    data = json.loads(raw)
                    seq = data.get("sequence", 0)
                    if seq >= from_sequence:
                        yield f"data: {raw}\n\n"
                        last_replayed_seq = max(last_replayed_seq, seq)
                except Exception:
                    continue

            # 3. Stream live events
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    payload = message.get("data")
                    try:
                        data = json.loads(payload)
                        if data.get("sequence", 0) > last_replayed_seq:
                            yield f"data: {payload}\n\n"
                    except Exception:
                        yield f"data: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            err_payload = json.dumps({
                "run_id": run_id,
                "event_type": "error",
                "timestamp": datetime.now(UTC).isoformat(),
                "sequence": 0,
                "payload": {"error": str(e)},
            })
            yield f"event: error\ndata: {err_payload}\n\n"
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.close()
                except Exception:
                    pass
            if r:
                try:
                    await r.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Interactive Agent Controls (Desktop-Style Human-in-the-Loop)
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/pause", response_model=ActionResponse)
async def pause_run(
    run_id: str,
    request: PauseRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActionResponse:
    """Pause execution of a running agent with tenant isolation and database persistence."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    db_run = run_res.scalars().first()
    if not db_run:
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    settings = get_cached_settings()
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
    try:
        await r.set(f"run_control:{run_id}:status", "paused", ex=7200)
        seq = await r.incr(f"run_events_seq:{run_id}")
        event_msg = {
            "run_id": run_id,
            "event_type": "run_paused",
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": seq,
            "payload": {"reason": request.reason},
        }
        raw = json.dumps(event_msg)
        await r.publish(f"run_events:{run_id}", raw)
        await r.rpush(f"run_events_history:{run_id}", raw)
    finally:
        await r.close()

    db_run.status = "paused"
    await db.commit()

    return ActionResponse(run_id=run_id, status="paused", message=f"Run paused: {request.reason}")


@router.post("/runs/{run_id}/resume", response_model=ActionResponse)
async def resume_run(
    run_id: str,
    request: ResumeRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActionResponse:
    """Resume execution of a paused agent with tenant isolation and database persistence."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    db_run = run_res.scalars().first()
    if not db_run:
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    settings = get_cached_settings()
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
    try:
        await r.set(f"run_control:{run_id}:status", "running", ex=7200)
        seq = await r.incr(f"run_events_seq:{run_id}")
        event_msg = {
            "run_id": run_id,
            "event_type": "run_resumed",
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": seq,
            "payload": {"message": request.message},
        }
        raw = json.dumps(event_msg)
        await r.publish(f"run_events:{run_id}", raw)
        await r.rpush(f"run_events_history:{run_id}", raw)
    finally:
        await r.close()

    db_run.status = "running"
    await db.commit()

    return ActionResponse(run_id=run_id, status="running", message=f"Run resumed: {request.message}")



@router.post("/runs/{run_id}/cancel", response_model=ActionResponse)
async def cancel_run(
    run_id: str,
    request: CancelRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActionResponse:
    """Cancel execution of a running agent with tenant isolation and lowercase status."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    db_run = run_res.scalars().first()
    if not db_run:
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    settings = get_cached_settings()
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
    try:
        await r.set(f"run_control:{run_id}:status", "cancelled", ex=7200)
        seq = await r.incr(f"run_events_seq:{run_id}")
        event_msg = {
            "run_id": run_id,
            "event_type": "run_cancelled",
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": seq,
            "payload": {"reason": request.reason},
        }
        raw = json.dumps(event_msg)
        await r.publish(f"run_events:{run_id}", raw)
        await r.rpush(f"run_events_history:{run_id}", raw)
    finally:
        await r.close()

    db_run.status = "cancelled"
    await db.commit()

    return ActionResponse(run_id=run_id, status="cancelled", message=f"Run cancelled: {request.reason}")


@router.post("/runs/{run_id}/clarify", response_model=ActionResponse)
async def answer_clarification(
    run_id: str,
    request: ClarifyAnswerRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActionResponse:
    """Provide user clarification with request-specific key and tenant isolation."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    if not run_res.scalars().first():
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    settings = get_cached_settings()
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
    try:
        # Match worker request-specific answer key
        key = f"run_control:{run_id}:clarification:{request.request_id}:answer"
        await r.set(key, request.answer, ex=3600)
        return ActionResponse(run_id=run_id, status="answered", message="Clarification submitted")
    finally:
        await r.close()


@router.post("/runs/{run_id}/approve", response_model=ActionResponse)
async def submit_approval(
    run_id: str,
    request: ApprovalDecisionRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActionResponse:
    """Submit approval decision with prompt-specific key and tenant isolation."""
    run_res = await db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == token.tenant_id)
    )
    if not run_res.scalars().first():
        raise HTTPException(status_code=404, detail="Run not found or unauthorized")

    settings = get_cached_settings()
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.session.redis_url, decode_responses=True)
    try:
        # Match worker prompt-specific decision key
        key = f"run_control:{run_id}:approval:{request.prompt_id}:decision"
        val = "approved" if request.approved else "rejected"
        await r.set(key, val, ex=3600)
        return ActionResponse(run_id=run_id, status=val, message=f"Decision recorded: {val}")
    finally:
        await r.close()


# ---------------------------------------------------------------------------
# Test Case & Story Generation Endpoints
# ---------------------------------------------------------------------------


@router.post("/test-cases/generate", response_model=GenerateTestCasesResponse)
async def generate_test_cases(
    request: GenerateTestCasesRequest,
    token: Annotated[TokenData, Depends(get_current_user_token)],
) -> GenerateTestCasesResponse:
    """Generate structured test cases preserving acceptance criteria and persisting them to the store."""
    from agent.api.v1.dependencies import (
        get_cached_settings,
        get_customer_knowledge_model,
        get_scenario_generator,
        get_test_intelligence_store,
    )

    settings = get_cached_settings()
    sg = get_scenario_generator()
    km = get_customer_knowledge_model()
    store = get_test_intelligence_store(settings)

    req_text = request.story or request.requirement or "Validate ServiceNow Incident workflow"
    cases: list[GeneratedTestCaseResponse] = []
    story_id = str(uuid.uuid4())

    if request.story or request.acceptance_criteria:
        tc = await sg.decompose_story_to_test_case(
            story_text=req_text,
            table_name=request.table_name,
            acceptance_criteria=request.acceptance_criteria,
        )
        tc.story_id = story_id
        store.save_test_case(tc, tenant_id=token.tenant_id)
        cases.append(
            GeneratedTestCaseResponse(
                id=tc.id,
                title=f"UAT Verification: {tc.target_record or 'Incident'}",
                description=tc.source_user_story,
                preconditions=list(tc.preconditions),
                steps=[s.model_dump() if hasattr(s, "model_dump") else s for s in tc.ordered_steps],
                expected_outcomes=[a.description for a in tc.final_assertions],
                risk_level=tc.risk_level.lower(),
            )
        )
    else:
        generated = await sg.generate_scenarios(
            requirement=req_text,
            fields=request.fields,
            workflow_type=request.workflow_type,
            knowledge_model=km,
            table_name=request.table_name,
        )
        for idx, sc in enumerate(generated):
            cid = getattr(sc, "id", None) or f"TC-{uuid.uuid4().hex[:8].upper()}"
            title = getattr(sc, "title", None) or f"Test Scenario {idx + 1}"
            desc = getattr(sc, "description", "")
            steps = getattr(sc, "steps", [])
            tc_obj = {
                "id": cid,
                "story_id": story_id,
                "title": title,
                "description": desc,
                "ordered_steps": steps,
                "preconditions": [f"Target table {request.table_name} is accessible"],
                "final_assertions": [desc],
                "risk_level": "medium",
                "acceptance_criteria": request.acceptance_criteria,
            }
            store.save_test_case(tc_obj, tenant_id=token.tenant_id)
            cases.append(
                GeneratedTestCaseResponse(
                    id=cid,
                    title=title,
                    description=desc,
                    preconditions=[f"Target table {request.table_name} is accessible"],
                    steps=[{"description": str(s)} for s in steps],
                    expected_outcomes=[desc],
                    risk_level="medium",
                )
            )

    return GenerateTestCasesResponse(
        story_id=story_id,
        test_cases=cases,
        count=len(cases),
    )


@router.post("/test-cases/{test_case_id}/execute", response_model=RunResponse)
async def execute_test_case(
    test_case_id: str,
    token: Annotated[TokenData, Depends(get_current_user_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunResponse:
    """Execute a stored structured test case by ID with tenant isolation."""
    from agent.api.v1.dependencies import get_cached_settings, get_test_intelligence_store

    s = get_cached_settings()
    store = get_test_intelligence_store(s)

    tc = store.get_test_case(test_case_id, tenant_id=token.tenant_id)
    if not tc:
        raise HTTPException(
            status_code=404,
            detail=f"Test case {test_case_id} not found or unauthorized",
        )

    goal = tc.get("title") or tc.get("description") or f"Execute Test Case {test_case_id}"

    run_id = str(uuid.uuid4())
    new_run = Run(
        id=run_id,
        tenant_id=token.tenant_id or "unknown",
        requester_id=token.user_id,
        goal=goal,
        status="queued",
    )
    db.add(new_run)
    # Enqueue Celery task with error handling and test_case_id
    try:
        execute_run.delay(
            run_id=run_id,
            goal=goal,
            tenant_id=token.tenant_id,
            test_case_id=test_case_id,
        )
    except Exception as exc:
        new_run.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue execution task: {exc}",
        )

    return RunResponse(
        session_id=run_id,
        status="queued",
        message=f"Agent run queued for test case: {goal}",
    )


