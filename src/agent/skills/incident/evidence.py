"""Evidence Collection for Deliverable 9.

Captures structured QA evidence items (screenshots, expected vs observed results,
pass/fail status, reasoning summary, confidence scores) and integrates with the ReportingEngine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.core.logging import get_logger

logger = get_logger(__name__)


class IncidentEvidenceItem(BaseModel):
    """Structured QA evidence item for Incident Management validation."""

    evidence_id: str
    incident_number: str = ""
    step_description: str
    expected_result: str
    observed_result: str
    passed: bool = True
    screenshot_path: str | None = None
    reasoning_summary: str = ""
    confidence_score: float = 1.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceCollector:
    """Collects and aggregates structured QA evidence items during Incident runs."""

    def __init__(self) -> None:
        self._items: list[IncidentEvidenceItem] = []

    def record_evidence(
        self,
        step_description: str,
        expected_result: str,
        observed_result: str,
        passed: bool,
        incident_number: str = "",
        screenshot_path: str | None = None,
        reasoning_summary: str = "",
        confidence_score: float = 1.0,
        details: dict[str, Any] | None = None,
    ) -> IncidentEvidenceItem:
        """Record a structured evidence item.

        Returns:
            The IncidentEvidenceItem model.
        """
        evidence_id = f"EV-{len(self._items) + 1:03d}"
        item = IncidentEvidenceItem(
            evidence_id=evidence_id,
            incident_number=incident_number,
            step_description=step_description,
            expected_result=expected_result,
            observed_result=observed_result,
            passed=passed,
            screenshot_path=screenshot_path,
            reasoning_summary=reasoning_summary,
            confidence_score=confidence_score,
            details=details or {},
        )
        self._items.append(item)
        logger.info(
            "evidence_recorded",
            evidence_id=evidence_id,
            step=step_description[:40],
            passed=passed,
            confidence=confidence_score,
        )
        return item

    @property
    def items(self) -> list[IncidentEvidenceItem]:
        """Return all recorded evidence items."""
        return list(self._items)

    def get_summary_dict(self) -> list[dict[str, Any]]:
        """Return machine readable evidence summary."""
        return [item.model_dump(mode="json") for item in self._items]
