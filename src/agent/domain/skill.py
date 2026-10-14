"""Skill framework domain models for Deliverable 3."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    """Manifest describing a domain skill."""

    name: str = Field(description="Skill name (e.g. IncidentSkill)")
    module: str = Field(description="Target ServiceNow module (e.g. incident)")
    version: str = Field(default="1.0.0")
    description: str = Field(default="")
    supported_intents: list[str] = Field(default_factory=list)


class SkillExecutionResult(BaseModel):
    """Result of a skill operation."""

    success: bool
    skill_name: str
    output: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
