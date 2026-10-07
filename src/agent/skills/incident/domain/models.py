"""Incident domain models for Deliverable 1.

Strongly typed domain representation of ServiceNow Incident entities, states,
priorities, assignment info, resolution details, and validation outcomes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IncidentState(StrEnum):
    """ServiceNow Incident State values."""

    NEW = "1"
    IN_PROGRESS = "2"
    ON_HOLD = "3"
    RESOLVED = "6"
    CLOSED = "7"
    CANCELED = "8"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, val: str) -> "IncidentState":
        """Parse string/label into IncidentState enum."""
        if not val:
            return cls.UNKNOWN
        v_lower = val.lower().strip()
        if "new" in v_lower or v_lower == "1":
            return cls.NEW
        if "in progress" in v_lower or v_lower == "2":
            return cls.IN_PROGRESS
        if "hold" in v_lower or v_lower == "3":
            return cls.ON_HOLD
        if "resolve" in v_lower or v_lower == "6":
            return cls.RESOLVED
        if "close" in v_lower or v_lower == "7":
            return cls.CLOSED
        if "cancel" in v_lower or v_lower == "8":
            return cls.CANCELED
        return cls.UNKNOWN


class Impact(StrEnum):
    """ServiceNow Impact values."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"
    UNKNOWN = "unknown"


class Urgency(StrEnum):
    """ServiceNow Urgency values."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"
    UNKNOWN = "unknown"


class IncidentPriority(StrEnum):
    """ServiceNow Priority values (calculated from Impact x Urgency)."""

    CRITICAL = "1"
    HIGH = "2"
    MODERATE = "3"
    LOW = "4"
    PLANNING = "5"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, val: str) -> "IncidentPriority":
        if not val:
            return cls.UNKNOWN
        v_lower = val.lower().strip()
        if "1" in v_lower or "critical" in v_lower:
            return cls.CRITICAL
        if "2" in v_lower or "high" in v_lower:
            return cls.HIGH
        if "3" in v_lower or "moderate" in v_lower:
            return cls.MODERATE
        if "4" in v_lower or "low" in v_lower:
            return cls.LOW
        if "5" in v_lower or "planning" in v_lower:
            return cls.PLANNING
        return cls.UNKNOWN


class Assignment(BaseModel):
    """Assignment details for an Incident."""

    group: str = Field(default="", description="Assignment Group name")
    assigned_to: str = Field(default="", description="Assigned individual user name")


class Resolution(BaseModel):
    """Resolution details for an Incident."""

    """Resolution details."""

    code: str = ""
    notes: str = ""
    resolved_by: str = ""


class WorkNotes(BaseModel):
    """Activity stream and work notes."""

    entries: list[dict[str, Any]] = Field(default_factory=list)
    additional_comments: list[str] = Field(default_factory=list)
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)


class Incident(BaseModel):
    """Strongly typed domain object representing a ServiceNow Incident record."""

    number: str = Field(default="", description="Incident Number (e.g. INC0012345)")
    sys_id: str | None = None
    state: IncidentState = IncidentState.UNKNOWN
    state_label: str = Field(default="Unknown")
    priority: IncidentPriority = IncidentPriority.UNKNOWN
    priority_label: str = Field(default="Unknown")
    impact: Impact = Impact.UNKNOWN
    urgency: Urgency = Urgency.UNKNOWN
    hold_reason: str = Field(default="", description="On Hold Reason (e.g. Awaiting Caller)")
    close_code: str = Field(default="", description="Close Code (e.g. Solved (Permanently))")
    close_notes: str = Field(default="", description="Close Notes")
    caller: str = Field(default="", description="Caller name")
    category: str = Field(default="")
    subcategory: str = Field(default="")
    short_description: str = Field(default="")
    description: str = Field(default="")
    assignment: Assignment = Field(default_factory=Assignment)
    resolution: Resolution = Field(default_factory=Resolution)
    work_notes: WorkNotes = Field(default_factory=WorkNotes)
    sla_states: list[dict[str, str]] = Field(default_factory=list, description="SLA states (e.g., in progress, breached)")
    escalation_level: str = Field(default="Normal", description="Escalation level")
    sys_updated_on: str = Field(default="")
    resolved_at: str = Field(default="")
    closed_at: str = Field(default="")
    is_readonly: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IncidentValidationResult(BaseModel):
    """Domain-level validation outcome for an Incident business step."""

    business_step: str = Field(
        description="Business outcome verified (e.g. State Transition, Priority Matrix)"
    )
    passed: bool = True
    incident_number: str = ""
    expected_state: str = ""
    actual_state: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
