"""API v1 router — thin routing layer for agent operations.

Routers only parse inputs, call the orchestrator, and return responses.
No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from agent import __version__
from agent.api.v1.schemas import (
    HealthResponse,
    ReportResponse,
    RunRequest,
    RunResponse,
    StatusResponse,
    StopRequest,
)

router = APIRouter(prefix="/api/v1", tags=["agent"])

# In-memory session store (replaced by proper store in production)
_sessions: dict = {}


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=__version__,
    )


@router.post("/agent/run", response_model=RunResponse)
async def run_agent(
    request: RunRequest,
    background_tasks: BackgroundTasks,
) -> RunResponse:
    """Start an autonomous agent run with a business goal.

    The agent runs asynchronously in the background. Use the
    status and report endpoints to monitor progress.
    """
    # Import here to avoid circular imports at module level
    from agent.main import create_orchestrator

    try:
        orchestrator = create_orchestrator()
        session_id = orchestrator.session_id

        # Store session reference
        _sessions[session_id] = orchestrator

        # Run in background
        background_tasks.add_task(orchestrator.run, request.goal)

        return RunResponse(
            session_id=session_id,
            status="started",
            message=f"Agent started with goal: {request.goal}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/status/{session_id}", response_model=StatusResponse)
async def get_agent_status(session_id: str) -> StatusResponse:
    """Get the current status of an agent run."""
    orchestrator = _sessions.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = orchestrator.memory.get_summary()
    return StatusResponse(
        session_id=summary["session_id"],
        state=summary["state"],
        current_step_index=summary["current_step_index"],
        current_url=summary["current_url"],
        goal=summary["goal"],
        total_actions=summary["total_actions"],
        total_validations=summary["total_validations"],
        total_failures=summary["total_failures"],
        plan_progress=summary["plan_progress"],
        current_incident=summary.get("current_incident"),
        started_at=orchestrator.memory.started_at,
    )


@router.get("/agent/report/{session_id}", response_model=ReportResponse)
async def get_agent_report(session_id: str) -> ReportResponse:
    """Get the generated report for a completed agent run."""
    orchestrator = _sessions.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Session not found")

    if not orchestrator.report:
        raise HTTPException(
            status_code=409,
            detail="Report not yet generated. Agent may still be running.",
        )

    report = orchestrator.report
    return ReportResponse(
        report_id=report.report_id,
        goal=report.goal,
        status=report.status,
        duration_seconds=report.duration_seconds,
        total_validations=report.total_validations,
        passed_validations=report.passed_validations,
        failed_validations=report.failed_validations,
        pass_rate=report.pass_rate,
        defects_count=len(report.defects),
        summary=report.summary,
        report_file=orchestrator.report_file,
    )


@router.post("/agent/stop/{session_id}")
async def stop_agent(session_id: str, request: StopRequest | None = None) -> dict:
    """Stop a running agent session."""
    orchestrator = _sessions.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Session not found")

    orchestrator.request_stop(
        reason=request.reason if request else "User requested stop"
    )

    return {
        "session_id": session_id,
        "status": "stop_requested",
        "message": "Stop signal sent to agent",
    }
