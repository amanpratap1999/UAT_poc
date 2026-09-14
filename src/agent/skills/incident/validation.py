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
from agent.skills.incident.domain.models import Incident, IncidentState, IncidentValidationResult
from agent.skills.incident.knowledge.rules import IncidentBusinessRules

logger = get_logger(__name__)


class IncidentValidator:
    """Evaluates semantic business outcome validations for Incidents."""

    def validate_business_outcome(
        self,
        before: Incident,
        after: Incident,
        expected_step: str = "",
        expected_state: str | None = None,
    ) -> IncidentValidationResult:
        """Validate business outcome between before and after Incident states.

        Args:
            before: Incident model before action.
            after: Incident model after action.
            expected_step: Description of business step being verified.
            expected_state: Explicit expected post-action state. When given
                (e.g. from a select action's value), it is authoritative and
                free-text inference from ``expected_step`` is skipped.

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
            error_msg = f"Priority calculation mismatch: expected {expected_priority.name}, actual {after.priority.name}"  # noqa: E501

        step_lower = expected_step.lower()

        # --- Expected-state determination -------------------------------------
        # 1. An explicit expected_state (from the action's value/metadata) is
        #    authoritative: verify it directly against the observed state.
        # 2. Otherwise, infer from the step text ONLY when a single state
        #    keyword is unambiguously present. Free text like "the current
        #    state is On Hold; change it to In Progress" contains BOTH the
        #    from-state and the to-state — inferring from such text produces
        #    false failures, so when multiple candidate states appear we skip
        #    the keyword inference (the deterministic field_update /
        #    state_change checks in ValidationEngine still cover the action).
        inferred_expected: IncidentState | None = None
        if expected_state:
            inferred_expected = IncidentState.from_string(expected_state)
        else:
            candidates: list[IncidentState] = []
            for kw, st in (
                ("in progress", IncidentState.IN_PROGRESS),
                ("on hold", IncidentState.ON_HOLD),
                ("hold", IncidentState.ON_HOLD),
                ("new", IncidentState.NEW),
                ("resolve", IncidentState.RESOLVED),
                ("close", IncidentState.CLOSED),
                ("cancel", IncidentState.CANCELED),
            ):
                if kw in step_lower and st not in candidates:
                    candidates.append(st)
            if len(candidates) == 1:
                inferred_expected = candidates[0]
            elif len(candidates) > 1:
                logger.info(
                    "ambiguous_expected_state_skipping_inference",
                    candidates=[c.name for c in candidates],
                )

        if "assignment" in step_lower and not after.assignment.group:
            passed = False
            error_msg = "Assignment Group was not populated"

        if inferred_expected is not None and after.state != inferred_expected:
            passed = False
            error_msg = (
                f"State mismatch: expected {inferred_expected.name} "
                f"({inferred_expected.value}), actual {after.state.name} ({after.state.value})"
            )

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

    def validate_precondition(
        self,
        incident: Incident,
        expected_record: str | None = None,
        expected_state: str | None = None,
    ) -> IncidentValidationResult:
        """Validate initial incident preconditions (e.g. record number and initial state) before mutations."""
        details: dict[str, str] = {
            "current_record": incident.number,
            "current_state": incident.state.name,
        }
        passed = True
        error_msg: str | None = None

        if expected_record and incident.number:
            if expected_record.upper() != incident.number.upper():
                passed = False
                error_msg = f"Precondition failed: Expected record {expected_record.upper()}, actual {incident.number.upper()}"

        if passed and expected_state:
            exp_state_enum = IncidentState.from_string(expected_state)
            if incident.state != exp_state_enum:
                passed = False
                error_msg = (
                    f"Precondition failed: Expected initial state '{exp_state_enum.name}', "
                    f"but actual state is '{incident.state.name}'"
                )

        return IncidentValidationResult(
            business_step="Precondition Validation",
            passed=passed,
            incident_number=incident.number,
            expected_state=expected_state or incident.state.name,
            actual_state=incident.state.name,
            details=details,
            error_message=error_msg,
        )

    def to_standard_validation_result(
        self, business_result: IncidentValidationResult, is_precondition: bool = False
    ) -> ValidationResult:
        """Convert IncidentValidationResult into standard agent ValidationResult."""
        res = ValidationResult(
            action_description=f"Incident Business Rule: {business_result.business_step}",
            is_precondition_check=is_precondition,
            precondition_failed=is_precondition and not business_result.passed,
            precondition_details=(
                business_result.details
                if (is_precondition and business_result.details is not None)
                else {}
            ),
        )
        res.add_check(
            ValidationCheck(
                check_name=business_result.business_step,
                description=f"Verify {business_result.business_step}",
                passed=business_result.passed,
                expected=business_result.expected_state or "Business rule satisfied",
                actual=f"State: {business_result.actual_state}",
                error_message=business_result.error_message,
            )
        )
        return res
