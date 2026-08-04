"""Reflection and Reasoning Trace domain models for Deliverables 5 & 7."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.domain.actions import AgentAction


class ReflectionResult(BaseModel):
    """Result of a cognitive reflection cycle."""

    action_evaluated: str = Field(description="Action that was evaluated")
    expected_outcome: str = Field(description="What was expected to happen")
    observed_outcome: str = Field(description="What actually happened")
    is_as_expected: bool = True
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Hypotheses explaining discrepancy (e.g. page loading delay, missing mandatory field)",
    )
    recommended_plan_adaptation: str | None = Field(
        default=None,
        description="Recommended adaptation to the execution plan",
    )
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReasoningCycle(BaseModel):
    """A single step in the reasoning audit trail."""

    step_index: int
    state_name: str
    observation_summary: str
    hypotheses: list[str] = Field(default_factory=list)
    decision_rationale: str = ""
    chosen_action: AgentAction | None = None
    confidence_score: float = 1.0
    outcome_summary: str = ""
    reflection: ReflectionResult | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
