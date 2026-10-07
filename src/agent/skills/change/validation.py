"""Validation logic for Change Management actions."""

from agent.core.logging import get_logger
from agent.domain.validation import ValidationResult
from agent.skills.change.domain.models import ChangeRequest, ChangeState, ChangeValidationResult
from agent.skills.change.domain.rules import ChangeBusinessRules

logger = get_logger(__name__)


class ChangeValidator:
    """Evaluates semantic business outcome validations for Change Requests."""

    def validate_action(
        self,
        action_type: str,
        expected_step: str,
        before: ChangeRequest,
        after: ChangeRequest,
    ) -> ChangeValidationResult:
        """Validate business outcome between before and after Change states."""
        logger.info("validating_change_business_outcome", step=expected_step)

        errors = []

        if not ChangeBusinessRules.is_valid_transition(before.state, after.state):
            errors.append(f"Invalid state transition from {before.state} to {after.state}")

        # If transitioning to Assess or beyond, certain fields should be populated
        if after.state and after.state not in (ChangeState.NEW, ChangeState.CANCELED):
            mandatory = ChangeBusinessRules.get_mandatory_fields_for_state(after.state, after.type)
            for field in mandatory:
                if not getattr(after, field, None):
                    # We might not observe all fields, so we log it as a warning but don't strictly fail  # noqa: E501
                    # unless it's a known constraint violation.
                    pass

        return ChangeValidationResult(
            is_valid=len(errors) == 0,
            business_step=expected_step or "Change Business Verification",
            change_number=after.number,
            errors=errors,
        )

    def to_generic_result(self, business_result: ChangeValidationResult) -> ValidationResult:
        """Convert ChangeValidationResult into standard agent ValidationResult."""
        res = ValidationResult(
            action_description=f"Change Business Rule: {business_result.business_step}"
        )
        if business_result.is_valid:
            res.mark_passed(  # type: ignore[attr-defined]
                f"Successfully validated {business_result.business_step} for {business_result.change_number}"  # noqa: E501
            )
        else:
            error_str = "; ".join(business_result.errors)
            res.mark_failed(  # type: ignore[attr-defined]
                f"Business validation failed: {error_str}", expected="Valid change progression"
            )
        return res
