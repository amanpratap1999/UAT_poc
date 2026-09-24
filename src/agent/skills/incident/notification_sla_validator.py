"""Notification + SLA Validation Framework (INC-UAT-09).

Provides validation for Incident notifications and SLA timelines.

INC-UAT-09 (Major, D3): Notifications/SLA verification is implemented
but not live-proven. This module provides the validation framework that:
1. Checks whether expected notifications were sent
2. Checks whether SLA deadlines were met
3. Honestly reports CANNOT_VERIFY when time dependencies can't be observed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from agent.core.logging import get_logger

logger = get_logger(__name__)

Verdict = Literal["PASS", "FAIL", "CANNOT_VERIFY", "BLOCKED"]


@dataclass
class NotificationValidationResult:
    """Result of validating an Incident notification."""
    notification_type: str  # e.g., "assignment_change", "state_change", "comment_added"
    expected_recipient: str
    actual_recipient: str | None = None
    was_sent: bool = False
    verdict: Verdict = "CANNOT_VERIFY"
    evidence: dict[str, Any] = field(default_factory=dict)
    details: str = ""


@dataclass
class SLAValidationResult:
    """Result of validating an Incident SLA."""
    sla_type: str  # e.g., "resolution", "response"
    deadline_hours: float
    actual_hours: float | None = None
    deadline_breached: bool | None = None
    verdict: Verdict = "CANNOT_VERIFY"
    evidence: dict[str, Any] = field(default_factory=dict)
    details: str = ""


class NotificationValidator:
    """Validates that expected Incident notifications were sent.

    INC-UAT-09 (Major, D3): provides a framework for notification
    validation. When the notification system is observable (e.g., via
    email log, sys_audit table, or event management table), the validator
    checks that the expected notification was sent to the expected recipient.

    When the notification system is NOT observable (e.g., the agent has no
    access to the mail server or the event management table), the validator
    honestly reports CANNOT_VERIFY — it never claims a notification was
    sent without evidence.
    """

    def validate_notification(
        self,
        notification_type: str,
        expected_recipient: str,
        observable: bool = False,
        evidence: dict[str, Any] | None = None,
    ) -> NotificationValidationResult:
        """Validate a single notification.

        Args:
            notification_type: what triggered the notification (e.g., "assignment_change")
            expected_recipient: who should receive it (email or sys_id)
            observable: whether the notification system is observable by the agent
            evidence: optional evidence dict (e.g., {"sys_audit_entry": "...", "email_log": "..."})

        Returns:
            NotificationValidationResult with verdict:
            - PASS: notification was sent to the expected recipient (evidence confirms)
            - FAIL: notification was NOT sent, or sent to wrong recipient
            - CANNOT_VERIFY: notification system is not observable
        """
        evidence = evidence or {}
        if not observable:
            logger.info(
                "notification_cannot_verify",
                notification_type=notification_type,
                reason="notification system not observable",
            )
            return NotificationValidationResult(
                notification_type=notification_type,
                expected_recipient=expected_recipient,
                verdict="CANNOT_VERIFY",
                details="Notification system is not observable by the agent. Cannot verify whether the notification was sent.",
            )

        # Check evidence for confirmation
        audit_entry = evidence.get("sys_audit_entry")
        email_log = evidence.get("email_log")
        actual_recipient = evidence.get("actual_recipient")

        if actual_recipient and actual_recipient == expected_recipient:
            return NotificationValidationResult(
                notification_type=notification_type,
                expected_recipient=expected_recipient,
                actual_recipient=actual_recipient,
                was_sent=True,
                verdict="PASS",
                evidence=evidence,
                details=f"Notification sent to {actual_recipient} (confirmed via {audit_entry or email_log or 'evidence'}).",
            )
        elif actual_recipient and actual_recipient != expected_recipient:
            return NotificationValidationResult(
                notification_type=notification_type,
                expected_recipient=expected_recipient,
                actual_recipient=actual_recipient,
                was_sent=True,
                verdict="FAIL",
                evidence=evidence,
                details=f"Notification sent to {actual_recipient} but expected {expected_recipient}.",
            )
        else:
            return NotificationValidationResult(
                notification_type=notification_type,
                expected_recipient=expected_recipient,
                verdict="FAIL",
                evidence=evidence,
                details="Notification system is observable but no evidence of the expected notification was found.",
            )


class SLAValidator:
    """Validates that Incident SLA deadlines were met.

    INC-UAT-09 (Major, D3): provides a framework for SLA validation.
    When the SLA timeline is observable (e.g., the incident has a
    resolved_at or closed_at timestamp that can be compared to the
    created_at + SLA deadline), the validator checks whether the deadline
    was met or breached.

    When the SLA timeline is NOT observable (e.g., the incident is still
    open and the SLA clock is still running, or the SLA configuration is
    not accessible), the validator honestly reports CANNOT_VERIFY.
    """

    def validate_sla(
        self,
        sla_type: str,
        deadline_hours: float,
        created_at: datetime | None = None,
        resolved_at: datetime | None = None,
        sla_observable: bool = True,
    ) -> SLAValidationResult:
        """Validate a single SLA.

        Args:
            sla_type: "resolution" or "response"
            deadline_hours: the SLA deadline in hours from creation
            created_at: when the incident was created
            resolved_at: when the incident was resolved (None if still open)
            sla_observable: whether the SLA timeline is observable

        Returns:
            SLAValidationResult with verdict:
            - PASS: SLA deadline met (resolved within deadline_hours)
            - FAIL: SLA deadline breached (resolved after deadline_hours)
            - CANNOT_VERIFY: SLA timeline not observable (incident still open,
              or SLA configuration not accessible)
        """
        if not sla_observable:
            logger.info(
                "sla_cannot_verify",
                sla_type=sla_type,
                reason="SLA timeline not observable",
            )
            return SLAValidationResult(
                sla_type=sla_type,
                deadline_hours=deadline_hours,
                verdict="CANNOT_VERIFY",
                details="SLA timeline is not observable. Cannot determine whether the deadline was met.",
            )

        if not created_at:
            return SLAValidationResult(
                sla_type=sla_type,
                deadline_hours=deadline_hours,
                verdict="CANNOT_VERIFY",
                details="Incident creation timestamp is not available.",
            )

        if not resolved_at:
            # Incident is still open — SLA clock is still running
            elapsed = (datetime.now(UTC) - created_at).total_seconds() / 3600
            breached = elapsed > deadline_hours
            if breached:
                return SLAValidationResult(
                    sla_type=sla_type,
                    deadline_hours=deadline_hours,
                    actual_hours=elapsed,
                    deadline_breached=True,
                    verdict="FAIL",
                    details=f"SLA breached: {elapsed:.1f}h elapsed > {deadline_hours}h deadline (incident still open).",
                )
            else:
                return SLAValidationResult(
                    sla_type=sla_type,
                    deadline_hours=deadline_hours,
                    actual_hours=elapsed,
                    deadline_breached=False,
                    verdict="CANNOT_VERIFY",
                    details=f"SLA clock running: {elapsed:.1f}h elapsed < {deadline_hours}h deadline (incident still open). Cannot verify final outcome.",
                )

        # Incident is resolved — compute actual time
        actual_hours = (resolved_at - created_at).total_seconds() / 3600
        breached = actual_hours > deadline_hours
        return SLAValidationResult(
            sla_type=sla_type,
            deadline_hours=deadline_hours,
            actual_hours=actual_hours,
            deadline_breached=breached,
            verdict="FAIL" if breached else "PASS",
            details=(
                f"SLA {'breached' if breached else 'met'}: "
                f"{actual_hours:.1f}h actual vs {deadline_hours}h deadline."
            ),
        )
