"""Cognitive orchestration models.

Provides structured representations for test hypotheses and investigation outcomes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TestHypothesis(BaseModel):
    """A structured representation of a test hypothesis."""

    id: str = Field(description="Unique identifier for the hypothesis")
    capability: str = Field(description="The primary target capability (e.g., incident, change)")
    statement: str = Field(description="What we believe may happen (the core assertion)")
    rationale: str = Field(description="Why we believe it (LLM reasoning)")
    supporting_facts: list[str] = Field(
        default_factory=list, description="Authoritative facts supporting this"
    )
    strategy: str = Field(description="Which strategy will test it")
    expected_outcome: str = Field(description="What evidence would confirm it")
    falsification_condition: str = Field(description="What evidence would reject it")
    risk: int = Field(default=5, description="Deterministic risk score")
    provenance: dict[str, Any] = Field(
        default_factory=dict, description="References to knowledge or learning"
    )


class InvestigationResult(BaseModel):
    """Result of an investigation into an expectation mismatch."""

    is_defect: bool = Field(description="Whether the mismatch is classified as an actual defect")
    classification: str = Field(
        description="Classification of the mismatch (e.g., 'false_positive_customization', 'verified_defect')"  # noqa: E501
    )
    reasoning: str = Field(description="Explanation of the investigation outcome")
    evidence: str = Field(default="", description="Collected evidence during investigation")
    requires_fallback_action: bool = Field(
        default=False, description="Whether further actions are needed to recover/investigate"
    )
    knowledge_reference: str | None = Field(
        default=None, description="Reference to the knowledge rule that explains this"
    )
