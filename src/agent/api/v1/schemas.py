"""API request and response schemas.

Pydantic models for the REST API contract. Kept separate from domain
models to avoid leaking internal data structures to API consumers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    """Request to start an agent run."""

    goal: str = Field(
        description="Business-level testing goal (e.g., 'Test the complete Incident lifecycle')"
    )


class StopRequest(BaseModel):
    """Request to stop a running agent session."""

    reason: str = Field(default="User requested stop")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RunResponse(BaseModel):
    """Response when an agent run is started."""

    session_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    """Response for agent status queries."""

    session_id: str
    state: str
    current_step_index: int
    current_url: str
    goal: str
    total_actions: int
    total_validations: int
    total_failures: int
    plan_progress: float
    current_incident: dict[str, Any] | None = None
    started_at: datetime


class ReportResponse(BaseModel):
    """Response containing the generated test report."""

    report_id: str
    goal: str
    status: str
    duration_seconds: float
    total_validations: int
    passed_validations: int
    failed_validations: int
    pass_rate: float
    defects_count: int
    summary: str
    report_file: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
