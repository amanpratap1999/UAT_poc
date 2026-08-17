"""Report models — the final output of an agent run.

Captures the complete execution timeline, validation results, detected
defects, and professional QA summary. Supports rendering to HTML and Markdown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agent.core.types import Severity


class TimelineEntry(BaseModel):
    """A single entry in the execution timeline."""

    step_index: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action: str = Field(description="Human-readable action description")
    result: str = Field(description="Outcome: success, failed, skipped")
    duration_ms: float = 0.0
    screenshot_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DefectReport(BaseModel):
    """A detected defect or anomaly found during testing."""

    defect_id: str = Field(description="Unique defect identifier (e.g., DEF-001)")
    severity: Severity = Severity.MEDIUM
    title: str = Field(description="Short defect title")
    description: str = Field(description="Detailed defect description")
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected_behavior: str = ""
    actual_behavior: str = ""
    evidence: list[str] = Field(
        default_factory=list,
        description="Screenshot paths or log excerpts",
    )
    root_cause_hypothesis: str = Field(
        default="",
        description="LLM-generated hypothesis for the root cause",
    )
    related_step_index: int | None = None


class BrowserLogEntry(BaseModel):
    """A captured browser console or error log entry."""

    level: str = Field(description="log, warn, error, info")
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = Field(default="console", description="console, network, page_error")


class TestReport(BaseModel):
    """Complete QA test report — the final deliverable of an agent run.

    Aggregates the full execution timeline, all validation results,
    detected defects, browser logs, and a professional summary.
    """

    report_id: str = Field(description="Unique report identifier")
    goal: str = Field(description="The business goal that was tested")
    status: str = Field(description="passed, failed, partial, error")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Timeline
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # Validation
    total_validations: int = 0
    passed_validations: int = 0
    failed_validations: int = 0
    validation_details: list[dict[str, Any]] = Field(default_factory=list)

    # Defects
    defects: list[DefectReport] = Field(default_factory=list)

    # Logs
    browser_logs: list[BrowserLogEntry] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)

    # Summary
    summary: str = Field(default="", description="LLM-generated executive summary")
    recommendations: list[str] = Field(default_factory=list)

    # Metadata
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Test environment details (URL, browser, etc.)",
    )
    screenshots: list[str] = Field(
        default_factory=list,
        description="Paths to all captured screenshots",
    )

    @property
    def has_defects(self) -> bool:
        """Whether any defects were found."""
        return len(self.defects) > 0

    @property
    def pass_rate(self) -> float:
        """Validation pass rate as a percentage."""
        if self.total_validations == 0:
            return 0.0
        return self.passed_validations / self.total_validations * 100
