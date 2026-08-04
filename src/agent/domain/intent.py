"""Structured Intent domain model for Deliverable 1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StructuredIntent(BaseModel):
    """Structured intent parsed from natural language goal."""

    intent_type: str = Field(
        default="GeneralValidation",
        description="High-level category of intent (e.g., IncidentValidation, RecordCreation)",
    )
    goal: str = Field(description="Normalized business goal")
    raw_prompt: str = Field(default="", description="Original user prompt")
    priority: str = Field(default="Normal", description="Normal, High, Low")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    target_module: str = Field(default="incident", description="Target ServiceNow module")
    extracted_entities: dict[str, Any] = Field(default_factory=dict)
    is_ambiguous: bool = False
    clarification_needed: str | None = None
