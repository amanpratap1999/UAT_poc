"""Incident domain models for Deliverable 1.

Strongly typed domain representation of ServiceNow Incident entities, states,
priorities, assignment info, resolution details, and validation outcomes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IncidentState(str, Enum):
    """ServiceNow Incident State values."""

    NEW = "1"
    IN_PROGRESS = "2"
    ON_HOLD = "3"
    RESOLVED = "6"
    CLOSED = "7"
    CANCELED = "8"

    @classmethod
    def from_string(cls, val: str) -> IncidentState:
        """Parse string/label into IncidentState enum."""
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
        return cls.NEW


class Impact(str, Enum):
    """ServiceNow Impact values."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class Urgency(str, Enum):
    """ServiceNow Urgency values."""

    HIGH = "1"
    MEDIUM = "2"
    LOW = "3"


class IncidentPriority(str, Enum):
    """ServiceNow Priority values (calculated from Impact x Urgency)."""

    CRITICAL = "1"
    HIGH = "2"
    MODERATE = "3"
    LOW = "4"
    PLANNING = "5"


class Assignment(BaseModel):
    """Assignment details for an Incident."""

    group: str = Field(default="", description="Assignment Group name")
    assigned_to: str = Field(default="", description="Assigned individual user name")


class Resolution(BaseModel):
    """Resolution details for an Incident."""

    code: str = Field(default="", description="Resolution Code (e.g., Solved (Permanently))")
    notes: str = Field(default="", description="Resolution Notes")
    resolved_by: str = Field(default="", description="User who resolved the incident")
    resolved_at: datetime | None = None


class WorkNotes(BaseModel):
    """Work notes and customer comments."""

    work_notes: list[str] = Field(default_factory=list, description="Internal IT work notes")
    additional_comments: list[str] = Field(default_factory=list, description="Customer visible comments")


class Incident(BaseModel):
    """Strongly typed domain object representing a ServiceNow Incident record."""

    number: str = Field(default="", description="Incident Number (e.g. INC0012345)")
    sys_id: str | None = None
    state: IncidentState = IncidentState.NEW
    state_label: str = Field(default="New")
    priority: IncidentPriority = IncidentPriority.LOW
    priority_label: str = Field(default="4 - Low")
    impact: Impact = Impact.LOW
    urgency: Urgency = Urgency.LOW
    caller: str = Field(default="", description="Caller name")
    category: str = Field(default="")
    subcategory: str = Field(default="")
    short_description: str = Field(default="")
    description: str = Field(default="")
    assignment: Assignment = Field(default_factory=Assignment)
    resolution: Resolution = Field(default_factory=Resolution)
    work_notes: WorkNotes = Field(default_factory=WorkNotes)
    is_readonly: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IncidentValidationResult(BaseModel):
    """Domain-level validation outcome for an Incident business step."""

    business_step: str = Field(description="Business outcome verified (e.g. State Transition, Priority Matrix)")
    passed: bool = True
    incident_number: str = ""
    expected_state: str = ""
    actual_state: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
