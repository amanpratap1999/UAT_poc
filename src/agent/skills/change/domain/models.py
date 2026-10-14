"""Change Management domain models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChangeState(StrEnum):
    """Deterministic expected state model for Normal Change."""

    NEW = "New"
    ASSESS = "Assess"
    AUTHORIZE = "Authorize"
    SCHEDULED = "Scheduled"
    IMPLEMENT = "Implement"
    REVIEW = "Review"
    CLOSED = "Closed"
    CANCELED = "Canceled"


class ChangeType(StrEnum):
    """Types of Change Requests."""

    NORMAL = "Normal"
    STANDARD = "Standard"
    EMERGENCY = "Emergency"


class RiskLevel(StrEnum):
    """Risk levels for Change Requests."""

    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"
    NONE = "None"


class ChangeRequest(BaseModel):
    """Structured representation of a ServiceNow Change Request."""

    number: str = Field(default="", description="CHG number")
    type: ChangeType = Field(default=ChangeType.NORMAL)
    state: ChangeState | None = Field(default=None)
    risk: RiskLevel | None = Field(default=None)
    short_description: str = Field(default="")
    assignment_group: str = Field(default="")
    assigned_to: str = Field(default="")
    justification: str = Field(default="")
    implementation_plan: str = Field(default="")
    risk_impact_analysis: str = Field(default="")
    backout_plan: str = Field(default="")
    test_plan: str = Field(default="")


class ChangeValidationResult(BaseModel):
    """Semantic business validation for Change Requests."""

    is_valid: bool
    business_step: str
    change_number: str
    errors: list[str] = Field(default_factory=list)
