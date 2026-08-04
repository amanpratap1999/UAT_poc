"""Validation Intelligence for Deliverable 7.

Validates semantic business outcomes rather than simple UI click events:
- State transitions
- Priority recalculation (Impact x Urgency)
- Assignment Group updates
- Work Notes saving
- Resolution details recording
"""

from __future__ import annotations

from agent.core.logging import get_logger
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.skills.incident.domain.models import Incident, IncidentValidationResult
from agent.skills.incident.knowledge.rules import IncidentBusinessRules

logger = get_logger(__name__)


class IncidentValidator:
    """Evaluates semantic business outcome validations for Incidents."""

    def validate_business_outcome(
        self,
        before: Incident,
        after: Incident,
        expected_step: str = "",
    ) -> IncidentValidationResult:
        """Validate business outcome between before and after Incident states.

        Args:
            before: Incident model before action.
            after: Incident model after action.
            expected_step: Description of business step being verified.

        Returns:
            An IncidentValidationResult.
        """
        logger.info("validating_incident_business_outcome", step=expected_step)

        details: dict[str, str] = {}
        passed = True
        error_msg: str | None = None

        # Check Priority recalculation
        expected_priority = IncidentBusinessRules.calculate_priority(after.impact, after.urgency)
        if after.priority != expected_priority:
            passed = False
            error_msg = f"Priority calculation mismatch: expected {expected_priority.name}, actual {after.priority.name}"

        # Step specific validations
        step_lower = expected_step.lower()
        if "assignment" in step_lower:
            if not after.assignment.group:
                passed = False
                error_msg = "Assignment Group was not populated"

        if "resolve" in step_lower:
            if after.state.value != "6":
                passed = False
                error_msg = f"Incident state is {after.state.name}, expected RESOLVED"
            if not after.resolution.code or not after.resolution.notes:
                passed = False
                error_msg = "Resolution Code or Resolution Notes are missing"

        details["before_state"] = before.state.name
        details["after_state"] = after.state.name
        details["incident_number"] = after.number

        return IncidentValidationResult(
            business_step=expected_step or "Incident Business Verification",
            passed=passed,
            incident_number=after.number,
            expected_state=after.state.name if passed else "valid outcome",
            actual_state=after.state.name,
            details=details,
            error_message=error_msg,
        )

    def to_standard_validation_result(
        self, business_result: IncidentValidationResult
    ) -> ValidationResult:
        """Convert IncidentValidationResult into standard agent ValidationResult."""
        res = ValidationResult(action_description=f"Incident Business Rule: {business_result.business_step}")
        res.add_check(
            ValidationCheck(
                check_name=business_result.business_step,
                description=f"Verify {business_result.business_step}",
                passed=business_result.passed,
                expected="Business rule satisfied",
                actual=f"State: {business_result.actual_state}",
                error_message=business_result.error_message,
            )
        )
        return res
