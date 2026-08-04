"""Semantic World State domain model for Deliverable 2."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.core.types import PageType


class ActionCapability(BaseModel):
    """Semantic representation of an available action on the page."""

    action_name: str = Field(description="High-level action name (e.g. Save, Resolve, Submit)")
    target: str = Field(description="Target selector or label")
    is_available: bool = True
    is_blocked: bool = False
    block_reason: str | None = None


class SemanticWorldState(BaseModel):
    """Semantic representation of the world state built from observations."""

    page_semantic_type: str = Field(default="unknown", description="Semantic page classification")
    raw_page_type: PageType = PageType.UNKNOWN
    url: str = ""
    title: str = ""
    record_number: str | None = None
    record_state: str | None = None
    user_permissions: str = Field(default="editable", description="editable, readonly, restricted")
    mandatory_fields: list[str] = Field(default_factory=list)
    missing_mandatory_fields: list[str] = Field(default_factory=list)
    available_actions: list[ActionCapability] = Field(default_factory=list)
    blocked_actions: list[ActionCapability] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    notifications: list[str] = Field(default_factory=list)
    form_completeness_score: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def to_compact_cognitive_summary(self) -> str:
        """Produce a semantic summary for LLM cognitive reasoning."""
        lines = [
            f"Current Page: {self.page_semantic_type} ({self.title})",
            f"Record State: {self.record_state or 'N/A'}",
            f"Record Number: {self.record_number or 'N/A'}",
            f"User Permissions: {self.user_permissions}",
        ]
        if self.mandatory_fields:
            lines.append(f"Mandatory Fields: {', '.join(self.mandatory_fields)}")
        if self.missing_mandatory_fields:
            lines.append(f"Missing Mandatory Fields: {', '.join(self.missing_mandatory_fields)}")

        avail = [a.action_name for a in self.available_actions if a.is_available and not a.is_blocked]
        if avail:
            lines.append(f"Available Actions: {', '.join(avail)}")

        blocked = [f"{a.action_name} ({a.block_reason or 'blocked'})" for a in self.blocked_actions if a.is_blocked]
        if blocked:
            lines.append(f"Blocked Actions: {', '.join(blocked)}")

        if self.validation_errors:
            lines.append(f"Validation Errors: {'; '.join(self.validation_errors)}")

        return "\n".join(lines)
