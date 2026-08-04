"""Validation models — post-action verification results.

After every action, the validation engine runs applicable checks and
produces a ValidationResult. These feed back into the planner's reasoning
and are captured in the final report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ValidationCheck(BaseModel):
    """A single validation check with expected vs actual comparison."""

    check_name: str = Field(description="Name of the validation check")
    description: str = Field(default="", description="What this check verifies")
    passed: bool = False
    expected: str = Field(default="", description="Expected value or state")
    actual: str = Field(default="", description="Observed value or state")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting evidence: screenshots, DOM snippets, etc.",
    )
    error_message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationResult(BaseModel):
    """Aggregated result of all validation checks for a single action.

    Contains the collection of individual checks and an overall pass/fail
    determination.
    """

    action_description: str = Field(
        default="", description="Description of the action that was validated"
    )
    checks: list[ValidationCheck] = Field(default_factory=list)
    overall_passed: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def add_check(self, check: ValidationCheck) -> None:
        """Add a validation check and recompute overall status."""
        self.checks.append(check)
        self._recompute_overall()

    def _recompute_overall(self) -> None:
        """Recompute overall_passed from individual checks."""
        if not self.checks:
            self.overall_passed = False
            return
        self.overall_passed = all(c.passed for c in self.checks)

    @property
    def passed_checks(self) -> list[ValidationCheck]:
        """Return all checks that passed."""
        return [c for c in self.checks if c.passed]

    @property
    def failed_checks(self) -> list[ValidationCheck]:
        """Return all checks that failed."""
        return [c for c in self.checks if not c.passed]

    def to_summary(self) -> str:
        """Produce a compact text summary for LLM context."""
        total = len(self.checks)
        passed = len(self.passed_checks)
        lines = [
            f"Validation: {'PASSED' if self.overall_passed else 'FAILED'} "
            f"({passed}/{total} checks passed)"
        ]
        for check in self.checks:
            icon = "✅" if check.passed else "❌"
            lines.append(f"  {icon} {check.check_name}: {check.description}")
            if not check.passed and check.error_message:
                lines.append(f"      Error: {check.error_message}")
        return "\n".join(lines)
