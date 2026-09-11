"""API request and response schemas.

Pydantic models for the REST API contract. Kept separate from domain
models to avoid leaking internal data structures to API consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunDetailResponse(BaseModel):
    id: str
    tenant_id: str
    requester_id: str | None
    goal: str
    status: str
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int | None
    defect_count: int


class FindingResponse(BaseModel):
    id: str
    tenant_id: str
    run_id: str
    capability: str
    description: str
    is_defect: bool
    severity: str | None
    created_at: datetime


class FindingUpdateRequest(BaseModel):
    """Request to update or override a finding."""

    capability: str | None = None
    description: str | None = None
    is_defect: bool | None = None
    severity: str | None = None


class MetricsResponse(BaseModel):
    tenant_id: str
    total_runs: int
    total_defects: int
    average_duration_seconds: float | None


class KnowledgeRuleResponse(BaseModel):
    rule_id: str
    table: str
    name: str
    type: str  # business_rule, ui_policy, client_script, dictionary
    description: str
    is_active: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class KnowledgeModelRulesResponse(BaseModel):
    total: int
    tables: list[str]
    rules: list[KnowledgeRuleResponse]


class KnowledgeDriftResponse(BaseModel):
    has_drift: bool
    status: str = "ok"
    last_checked: datetime
    drifted_tables: list[str]
    model_version: str


# ---------------------------------------------------------------------------
# Interactive Control & Live Streaming Schemas
# ---------------------------------------------------------------------------


class PauseRequest(BaseModel):
    reason: str = Field(default="User requested pause")


class ResumeRequest(BaseModel):
    message: str = Field(default="User resumed run")


class CancelRequest(BaseModel):
    reason: str = Field(default="User cancelled run")


class ClarifyAnswerRequest(BaseModel):
    request_id: str
    answer: str


class ApprovalDecisionRequest(BaseModel):
    prompt_id: str
    approved: bool
    feedback: str | None = None


class ActionResponse(BaseModel):
    status: str = "success"
    message: str
    run_id: str


class GenerateTestCasesRequest(BaseModel):
    story: str | None = None
    requirement: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    table_name: str = "incident"
    workflow_type: str = "incident"
    fields: list[dict[str, Any]] = Field(default_factory=list)


class GeneratedTestCaseResponse(BaseModel):
    id: str
    title: str
    description: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_outcomes: list[str] = Field(default_factory=list)
    risk_level: str = "low"


class GenerateTestCasesResponse(BaseModel):
    story_id: str | None = None
    test_cases: list[GeneratedTestCaseResponse]
    count: int

