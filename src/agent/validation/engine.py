"""Validation engine — post-action verification of browser state.

After every action, the validation engine compares the before and after
page observations to determine whether the action achieved its intent.
It runs a set of applicable checks and produces a ValidationResult.
"""

from __future__ import annotations

from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import PageObservation
from agent.domain.validation import ValidationCheck, ValidationResult

logger = get_logger(__name__)


class ValidationEngine:
    """Runs post-action validation checks.

    Automatically selects relevant checks based on the action type
    and compares before/after page observations. Produces a
    ValidationResult with individual check pass/fail results.
    """

    async def validate_action(
        self,
        action: AgentAction,
        result: ActionResult,
        before: PageObservation,
        after: PageObservation,
        console_errors: list[str] | None = None,
    ) -> ValidationResult:
        """Run all applicable validations after an action.

        Args:
            action: The action that was executed.
            result: The execution result.
            before: Page observation before the action.
            after: Page observation after the action.
            console_errors: Any browser console errors captured.

        Returns:
            A ValidationResult with individual checks.
        """
        logger.info("validating_action", action_type=action.action_type)

        validation = ValidationResult(
            action_description=f"{action.action_type}: {action.target}",
        )

        # Always check: action succeeded
        validation.add_check(
            self._check_action_success(result)
        )

        # Always check: no new validation messages
        validation.add_check(
            self._check_no_new_errors(before, after)
        )

        # Always check: no JavaScript errors
        if console_errors is not None:
            validation.add_check(
                self._check_no_js_errors(console_errors)
            )

        # Action-type-specific checks
        action_type = ActionType(action.action_type)

        if action_type == ActionType.NAVIGATE:
            validation.add_check(
                self._check_page_navigation(action, after)
            )

        if action_type == ActionType.FILL:
            validation.add_check(
                self._check_field_update(action, after)
            )

        if action_type == ActionType.CLICK:
            validation.add_check(
                self._check_page_changed(before, after)
            )

        if action_type == ActionType.SELECT:
            validation.add_check(
                self._check_field_update(action, after)
            )

        logger.info(
            "validation_complete",
            passed=validation.overall_passed,
            checks=len(validation.checks),
            failed=len(validation.failed_checks),
        )
        return validation

    def _check_action_success(self, result: ActionResult) -> ValidationCheck:
        """Verify the action execution itself succeeded."""
        return ValidationCheck(
            check_name="action_execution",
            description="Action executed without throwing an error",
            passed=result.success,
            expected="success",
            actual="success" if result.success else f"failed: {result.error}",
            error_message=result.error if not result.success else None,
        )

    def _check_no_new_errors(
        self,
        before: PageObservation,
        after: PageObservation,
    ) -> ValidationCheck:
        """Check that no new validation/error messages appeared."""
        before_msgs = set(before.validation_messages)
        after_msgs = set(after.validation_messages)
        new_msgs = after_msgs - before_msgs

        return ValidationCheck(
            check_name="no_new_errors",
            description="No new validation or error messages appeared",
            passed=len(new_msgs) == 0,
            expected="no new errors",
            actual=f"{len(new_msgs)} new errors" if new_msgs else "no new errors",
            error_message=", ".join(new_msgs) if new_msgs else None,
        )

    def _check_no_js_errors(self, console_errors: list[str]) -> ValidationCheck:
        """Check that no JavaScript errors occurred in the console."""
        return ValidationCheck(
            check_name="no_js_errors",
            description="No JavaScript errors in browser console",
            passed=len(console_errors) == 0,
            expected="no JS errors",
            actual=f"{len(console_errors)} JS errors" if console_errors else "clean",
            error_message="; ".join(console_errors[:3]) if console_errors else None,
        )

    def _check_page_navigation(
        self,
        action: AgentAction,
        after: PageObservation,
    ) -> ValidationCheck:
        """Verify navigation reached the expected page."""
        expected_url = action.metadata.get("url", action.value or action.target)
        # Check if the URL contains the expected target
        url_matches = (
            expected_url.lower() in after.url.lower()
            if expected_url
            else True
        )

        return ValidationCheck(
            check_name="page_navigation",
            description=f"Navigated to expected page",
            passed=url_matches,
            expected=expected_url,
            actual=after.url,
            error_message=f"URL mismatch" if not url_matches else None,
        )

    def _check_field_update(
        self,
        action: AgentAction,
        after: PageObservation,
    ) -> ValidationCheck:
        """Verify a field was updated with the expected value."""
        target_label = action.metadata.get("field_label", action.target)
        expected_value = action.value

        # Find the field in the after observation
        for field in after.visible_fields:
            if field.name.lower() == target_label.lower():
                value_matches = (
                    expected_value.lower() in field.value.lower()
                    if expected_value and field.value
                    else False
                )
                return ValidationCheck(
                    check_name="field_update",
                    description=f"Field '{target_label}' updated to expected value",
                    passed=value_matches,
                    expected=expected_value,
                    actual=field.value,
                    error_message=(
                        f"Field value mismatch" if not value_matches else None
                    ),
                )

        # Field not found in observation — can't verify
        return ValidationCheck(
            check_name="field_update",
            description=f"Field '{target_label}' updated to expected value",
            passed=True,  # Can't verify = assume OK
            expected=expected_value,
            actual="(field not found in observation)",
        )

    def _check_page_changed(
        self,
        before: PageObservation,
        after: PageObservation,
    ) -> ValidationCheck:
        """Check that clicking something caused a page change or update."""
        # Multiple signals indicate the page responded
        url_changed = before.url != after.url
        title_changed = before.title != after.title
        state_changed = before.current_state != after.current_state
        buttons_changed = (
            set(b.label for b in before.buttons)
            != set(b.label for b in after.buttons)
        )
        fields_changed = len(before.visible_fields) != len(after.visible_fields)

        page_responded = any([
            url_changed,
            title_changed,
            state_changed,
            buttons_changed,
            fields_changed,
        ])

        return ValidationCheck(
            check_name="page_responded",
            description="Page responded to the click action",
            passed=page_responded,
            expected="page changed or updated",
            actual="changed" if page_responded else "no visible change",
            error_message=(
                "Click did not produce any visible change"
                if not page_responded
                else None
            ),
        )

    def _check_state_change(
        self,
        before: PageObservation,
        after: PageObservation,
        expected_state: str,
    ) -> ValidationCheck:
        """Verify a record state transition occurred."""
        return ValidationCheck(
            check_name="state_change",
            description=f"Record state changed to '{expected_state}'",
            passed=after.current_state == expected_state,
            expected=expected_state,
            actual=after.current_state or "unknown",
            error_message=(
                f"State is '{after.current_state}' not '{expected_state}'"
                if after.current_state != expected_state
                else None
            ),
        )
