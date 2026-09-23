"""Validation engine — post-action verification of browser state.

After every action, the validation engine compares the before and after
page observations to determine whether the action achieved its intent.
It runs a set of applicable checks and produces a ValidationResult.
"""

from __future__ import annotations

import re
from typing import ClassVar

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
        validation.add_check(self._check_action_success(result))

        # Always check: no new validation messages
        validation.add_check(self._check_no_new_errors(before, after))

        # Always check: no NEW JavaScript errors introduced during action
        before_errors = set(before.console_errors) if before else set()
        after_errors = set(after.console_errors) if after else set()
        if console_errors is not None:
            after_errors.update(console_errors)
        new_errors = list(after_errors - before_errors)
        validation.add_check(
            self._check_no_new_js_errors(new_errors, baseline_count=len(before_errors))
        )

        # Check for NEW failed network requests introduced during action
        before_network = set(before.network_errors) if before else set()
        after_network = set(after.network_errors) if after else set()
        raw_new_network_errors = list(after_network - before_network)
        # QA-015: suppression uses versioned exact endpoint/status signatures
        # instead of substring matching, and the suppressed evidence is
        # preserved so reports remain auditable.
        new_network_errors, suppressed_network = self._filter_network_noise(
            raw_new_network_errors
        )
        if new_network_errors:
            validation.add_check(self._check_no_network_errors(new_network_errors))
        elif suppressed_network:
            # Everything was suppressed as platform noise — record the
            # suppressed evidence explicitly rather than silently passing.
            validation.add_check(
                ValidationCheck(
                    check_name="network_noise_suppressed",
                    description=(
                        "Failed platform background requests suppressed by "
                        f"signature set {self.SUPPRESSION_SIGNATURES_VERSION}"
                    ),
                    passed=True,
                    expected="platform background noise only",
                    actual=f"{len(suppressed_network)} suppressed requests",
                    evidence={"suppressed_requests": suppressed_network},
                )
            )

        # Action-type-specific checks
        action_type = ActionType(action.action_type)

        if action_type == ActionType.NAVIGATE:
            validation.add_check(self._check_page_navigation(action, after))

        if action_type == ActionType.FILL:
            validation.add_check(self._check_field_update(action, after))

        if action_type == ActionType.CLICK:
            validation.add_check(self._check_page_changed(before, after, action))

        if action_type == ActionType.SELECT:
            validation.add_check(self._check_field_update(action, after))

        logger.info(
            "validation_complete",
            passed=validation.overall_passed,
            checks=len(validation.checks),
            failed=len(validation.failed_checks),
        )
        return validation

    def _check_no_network_errors(self, network_errors: list[str]) -> ValidationCheck:
        """Check that no critical network errors occurred."""
        return ValidationCheck(
            check_name="no_network_errors",
            description="No failed API or network requests",
            passed=len(network_errors) == 0,
            expected="clean network",
            actual=f"{len(network_errors)} failed requests" if network_errors else "clean",
            error_message="; ".join(network_errors[:3]) if network_errors else None,
        )

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
        before_msgs = set(before.validation_messages) if before else set()
        after_msgs = set(after.validation_messages) if after else set()
        new_msgs = after_msgs - before_msgs

        return ValidationCheck(
            check_name="no_new_errors",
            description="No new validation or error messages appeared",
            passed=len(new_msgs) == 0,
            expected="no new errors",
            actual=f"{len(new_msgs)} new errors" if new_msgs else "no new errors",
            error_message=", ".join(new_msgs) if new_msgs else None,
        )

    #: Versioned suppression signature set (QA-015). Substring lists were too
    #: broad (e.g. "failed to load resource" or "sp_" hid relevant failures).
    #: Signatures match the (method, endpoint-path, status) triple parsed out
    #: of the request evidence — a failure is suppressed only when the exact
    #: endpoint path AND status both match a signature.
    SUPPRESSION_SIGNATURES_VERSION = "2026-09-18.1"

    #: (method-or-"*", exact endpoint path suffix, status-or-"*")
    NETWORK_NOISE_SIGNATURES: ClassVar[tuple[tuple[str, str, str], ...]] = (
        # ServiceNow chat/consumer-widget background API — emits 404s on
        # portal pages when the chat plugin is absent. Platform noise.
        ("*", "/api/now/v1/cs/consumerAccount/unreadConversation", "*"),
        ("*", "/api/now/v1/cs/conversation", "*"),
        ("*", "/api/now/v1/cs/consumerAccount", "*"),
        # ServiceNow portal framework background widgets.
        ("*", "/api/now/sp/page", "*"),
        ("*", "/api/now/sp/widget", "*"),
    )

    #: Console-error signatures: word-boundary regexes over exact platform
    #: module/function names — never broad generic phrases.
    CONSOLE_NOISE_SIGNATURES: ClassVar[tuple[str, ...]] = (
        r"\bscriptloader\b",
        r"\bunifiednavcomponent\b",
        r"\bcomponent_bootstrapped\b",
        r"\bcomponent_dom_ready\b",
        r"\bqg\s+is\s+not\s+a\s+function\b",
        r"\baddeventlistener\b.*\b(null|undefined)\b",
        r"reading\s+'dispatch'",
        r"unexpected\s+token\s+'export'",
    )

    @classmethod
    def _parse_request_evidence(cls, entry: str) -> tuple[str, str, str]:
        """Parse a network-error evidence string into (method, path, status).

        Network evidence is a freeform string (e.g.
        ``"404 GET /api/now/v1/cs/conversation ..."``). Returns ("", "", "")
        when nothing can be parsed — such entries are never suppressed.
        """
        lower = entry.strip().lower()
        method = ""
        status = ""
        url = ""

        url_match = re.search(r"https?://\S+|(?<![\w@./])/\S+", lower)
        remainder = lower
        if url_match:
            url = url_match.group(0).rstrip(").,;'\"")
            remainder = lower[: url_match.start()] + " " + lower[url_match.end():]

        method_match = re.search(r"\b(get|post|put|patch|delete)\b", remainder)
        if method_match:
            method = method_match.group(1)
        statuses = re.findall(r"\b[1-5]\d{2}\b", remainder)
        if statuses:
            status = statuses[-1]
        # Strip query strings: signatures match stable endpoint paths only.
        path = url.split("?", 1)[0] if url else ""
        return method, path, status

    @classmethod
    def _filter_network_noise(
        cls, entries: list[str]
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Split request failures into actionable errors and suppressed noise.

        Returns:
            (actionable_errors, suppressed) — suppressed entries keep the
            original evidence plus the matching signature for the report.
        """
        actionable: list[str] = []
        suppressed: list[dict[str, str]] = []
        for entry in entries:
            method, path, status = cls._parse_request_evidence(entry)
            matched = False
            if path:
                for sig_method, sig_path, sig_status in cls.NETWORK_NOISE_SIGNATURES:
                    sig_path_lower = sig_path.lower()
                    if (
                        path.endswith(sig_path_lower)
                        and (sig_method == "*" or method == sig_method)
                        and (sig_status == "*" or status == sig_status)
                    ):
                        matched = True
                        suppressed.append(
                            {
                                "evidence": entry,
                                "signature": f"{sig_method} {sig_path} {sig_status}",
                            }
                        )
                        break
            if not matched:
                actionable.append(entry)
        return actionable, suppressed

    def _check_no_new_js_errors(
        self, new_errors: list[str], baseline_count: int = 0
    ) -> ValidationCheck:
        """Check that no NEW JavaScript errors were introduced during the action."""
        compiled = [re.compile(p) for p in self.CONSOLE_NOISE_SIGNATURES]
        action_errors = [
            e for e in new_errors if not any(p.search(e.lower()) for p in compiled)
        ]
        suppressed_count = len(new_errors) - len(action_errors)
        passed = len(action_errors) == 0
        actual = (
            f"{len(action_errors)} new JS errors ({baseline_count} pre-existing baseline)"
            if action_errors
            else f"clean (0 new errors, {baseline_count} pre-existing baseline"
            + (
                f", {suppressed_count} suppressed by {self.SUPPRESSION_SIGNATURES_VERSION})"
                if suppressed_count
                else ")"
            )
        )
        return ValidationCheck(
            check_name="no_new_js_errors",
            description="No new JavaScript errors introduced during action",
            passed=passed,
            expected="no new JS errors",
            actual=actual,
            error_message="; ".join(action_errors[:3]) if action_errors else None,
            evidence=(
                {"suppression_signature_version": self.SUPPRESSION_SIGNATURES_VERSION}
                if suppressed_count
                else {}
            ),
        )

    def _check_page_navigation(
        self,
        action: AgentAction,
        after: PageObservation,
    ) -> ValidationCheck:
        """Verify navigation reached the expected page."""
        expected_url = action.metadata.get("url", action.value or action.target)
        url_matches = (expected_url.strip().lower() == after.url.strip().lower()) if expected_url else True

        return ValidationCheck(
            check_name="page_navigation",
            description="Navigated to expected page",
            passed=url_matches,
            expected=expected_url,
            actual=after.url,
            error_message="URL mismatch" if not url_matches else None,
        )

    def _check_field_update(
        self,
        action: AgentAction,
        after: PageObservation,
    ) -> ValidationCheck:
        """Verify a field was updated with the expected value."""
        target_label = action.metadata.get("field_label", action.target).strip().lower()
        expected_value = (action.value or "").strip()

        state_map = {
            "1": "new", "new": "1",
            "2": "in progress", "in progress": "2",
            "3": "on hold", "on hold": "3",
            "6": "resolved", "resolved": "6",
            "7": "closed", "closed": "7",
            "8": "canceled", "canceled": "8",
        }

        # Find the field in the after observation
        for field in after.visible_fields:
            fname = field.name.strip().lower()
            if (
                fname == target_label
                or fname == f"incident.{target_label}"
                or target_label == f"incident.{fname}"
            ):
                fval = field.value.strip().lower()
                exp_clean = expected_value.lower()
                value_matches = (
                    exp_clean == fval
                    or state_map.get(exp_clean) == fval
                    or state_map.get(fval) == exp_clean
                ) if (exp_clean or fval) else True

                return ValidationCheck(
                    check_name="field_update",
                    description=f"Field '{action.target}' updated to expected value",
                    passed=value_matches,
                    expected=expected_value,
                    actual=field.value,
                    error_message=("Field value mismatch" if not value_matches else None),
                )

        # A missing field is not evidence of success.  Treat it as an
        # unverified failure so the report cannot claim a step passed merely
        # because the observer failed to expose the target field.
        return ValidationCheck(
            check_name="field_update",
            description=f"Field '{action.target}' updated to expected value",
            passed=False,
            expected=expected_value,
            actual="(field not found in observation)",
            error_message=f"Field '{action.target}' was not present in the post-action observation",
        )

    def _check_page_changed(
        self,
        before: PageObservation,
        after: PageObservation,
        action: AgentAction | None = None,
    ) -> ValidationCheck:
        """Check that clicking something caused a page change or update."""
        target = (
            action.target.strip().lower()
            if action and hasattr(action, "target")
            else ""
        )
        if action and target in ("sysverb_update", "save record", "update"):
            messages = [
                *after.validation_messages,
                *after.notification_messages,
            ]
            
            # Exact mapping or specific status checks instead of broad substring
            failure_messages = [
                m for m in messages
                if "error" in m.lower().split() or "failed" in m.lower().split() or "invalid" in m.lower().split() or "required" in m.lower().split()
            ]
            return ValidationCheck(
                check_name="update_response",
                description="Update was accepted without a validation error",
                passed=not failure_messages,
                expected="record saved without validation errors",
                actual="validation error displayed" if failure_messages else "no validation error displayed",
                error_message="; ".join(failure_messages[:3]) if failure_messages else None,
            )

        # Multiple signals indicate the page responded
        url_changed = before.url != after.url
        title_changed = before.title != after.title
        state_changed = before.current_state != after.current_state
        buttons_changed = set(b.label for b in before.buttons) != set(
            b.label for b in after.buttons
        )
        fields_changed = before.visible_fields != after.visible_fields

        page_responded = any(
            [
                url_changed,
                title_changed,
                state_changed,
                buttons_changed,
                fields_changed,
            ]
        )

        return ValidationCheck(
            check_name="page_responded",
            description="Page responded to the click action",
            passed=page_responded,
            expected="page changed or updated",
            actual="changed" if page_responded else "no visible change",
            error_message=(
                "Click did not produce any visible change" if not page_responded else None
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

    def validate_precondition(
        self,
        expected_initial_state: str | None = None,
        actual_initial_state: str | None = None,
        expected_record: str | None = None,
        actual_record: str | None = None,
        observation: PageObservation | None = None,
    ) -> ValidationResult:
        """Verify initial record preconditions before performing mutations.

        If actual initial state does not match expected initial state, marks
        the result as PRECONDITION_FAILED so that the engine halts and
        does not count the mismatch as an application defect.
        """
        state_map = {
            "1": "new",
            "new": "new",
            "2": "in progress",
            "in progress": "in progress",
            "3": "on hold",
            "on hold": "on hold",
            "6": "resolved",
            "resolved": "resolved",
            "7": "closed",
            "closed": "closed",
            "8": "canceled",
            "canceled": "canceled",
        }

        validation = ValidationResult(
            action_description="Precondition verification",
            is_precondition_check=True,
        )

        # 1. Verify target record identifier if specified
        if expected_record:
            rec_actual = actual_record or (observation.record_number if observation else None)
            # QA-017: exact comparison only. Substring matching allowed values
            # like "INC1" to match "INC1000" — a false-pass path.
            rec_match = bool(
                rec_actual
                and expected_record.strip().lower() == rec_actual.strip().lower()
            )
            validation.add_check(
                ValidationCheck(
                    check_name="record_precondition",
                    description=f"Target record matches '{expected_record}'",
                    passed=rec_match,
                    expected=expected_record,
                    actual=str(rec_actual or "unknown"),
                    error_message=(
                        f"Target record mismatch: expected '{expected_record}', found '{rec_actual}'"
                        if not rec_match
                        else None
                    ),
                )
            )
            if not rec_match:
                validation.precondition_failed = True
                validation.precondition_details["record_error"] = (
                    f"Target record mismatch: expected '{expected_record}', found '{rec_actual}'"
                )

        # 2. Verify initial lifecycle state if specified
        if expected_initial_state:
            raw_actual = actual_initial_state or (observation.current_state if observation else None)
            exp_norm = state_map.get(expected_initial_state.strip().lower(), expected_initial_state.strip().lower())
            act_norm = state_map.get(str(raw_actual).strip().lower(), str(raw_actual).strip().lower()) if raw_actual else "unknown"

            # QA-017: exact comparison of canonical values only. Bidirectional
            # substring matching let e.g. "Closed" match "Not Closed".
            state_match = bool(raw_actual and exp_norm == act_norm)
            validation.add_check(
                ValidationCheck(
                    check_name="initial_state_precondition",
                    description=f"Initial state matches expected '{expected_initial_state}'",
                    passed=state_match,
                    expected=expected_initial_state,
                    actual=str(raw_actual or "unknown"),
                    error_message=(
                        f"Precondition failed: Expected initial state '{expected_initial_state}' "
                        f"but actual initial state is '{raw_actual}'"
                        if not state_match
                        else None
                    ),
                )
            )
            if not state_match:
                validation.precondition_failed = True
                validation.precondition_details["state_error"] = (
                    f"Precondition failed: Expected initial state '{expected_initial_state}' "
                    f"but actual initial state is '{raw_actual}'"
                )
                validation.precondition_details["reason"] = (
                    f"Expected initial state '{expected_initial_state}' but actual is '{raw_actual}'"
                )

        validation._recompute_overall()
        if validation.precondition_failed:
            validation.overall_passed = False

        return validation
