"""Step-level evidence chain models for UAT test execution.

Captures comprehensive evidence for every test step:
- Before and after screenshots
- Page state observations & DOM diff
- Action parameters and execution telemetry
- Behavioral verification findings
- Console errors and network requests
- Perception routing decisions (DOM, Moondream, Gemini)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StepEvidence(BaseModel):
    """Complete evidence bundle for a single UAT step."""

    step_number: int
    step_description: str
    action_type: str
    target: str
    value: str | None = None

    # Perception evidence
    perception_route: str = Field(
        default="DOM",
        description="Route used: DOM, MOONDREAM, GEMINI_FALLBACK, etc.",
    )
    perception_confidence: float | None = None

    # Visual evidence
    before_screenshot: str | None = None
    after_screenshot: str | None = None

    # DOM & State evidence
    dom_diff_summary: str | None = None
    url_before: str = ""
    url_after: str = ""

    # Telemetry evidence
    duration_ms: float = 0.0
    console_errors: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)

    # Verification evidence
    verification_passed: bool = True
    verification_reasoning: str = ""
    findings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dictionary for JSON reporting."""
        return self.model_dump(mode="json")
