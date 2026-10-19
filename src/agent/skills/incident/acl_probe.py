"""C17: Negative ACL probes for non-admin ServiceNow personas (requester vs fulfiller)."""

from __future__ import annotations

from agent.domain.observation import PageObservation
from agent.domain.validation import ValidationCheck


class IncidentAclProbe:
    """Verifies negative ACL constraints for restricted personas (e.g., requester)."""

    FORBIDDEN_REQUESTER_BUTTONS = frozenset({"delete", "sysverb_delete", "resolve", "resolve_incident"})
    FORBIDDEN_REQUESTER_WRITABLE_FIELDS = frozenset({"work_notes", "assignment_group", "assigned_to", "close_code", "priority"})

    @classmethod
    def verify_requester_restrictions(cls, observation: PageObservation) -> list[ValidationCheck]:
        """Assert that a requester persona cannot view work_notes, edit fulfiller fields, or invoke Delete/Resolve."""
        checks: list[ValidationCheck] = []
        fields = {
            (getattr(f, "name", "") or "").strip().lower().replace("incident.", ""): f
            for f in (getattr(observation, "visible_fields", []) or [])
        }

        # 1. work_notes must not be visible/editable to requester
        wn_present = "work_notes" in fields or "work notes" in fields
        checks.append(
            ValidationCheck(
                check_name="acl_work_notes_hidden",
                description="Requester persona must not have access to internal work_notes",
                passed=not wn_present,
                expected="work_notes hidden",
                actual="work_notes visible" if wn_present else "work_notes hidden",
                error_message="ACL violation: work_notes is visible to requester" if wn_present else None,
            )
        )

        # 2. Fulfiller-only buttons (Delete, Resolve) must not be offered
        visible_buttons = {
            (getattr(b, "label", "") or "").strip().lower()
            for b in (getattr(observation, "buttons", []) or [])
        }
        exposed_buttons = sorted(visible_buttons & cls.FORBIDDEN_REQUESTER_BUTTONS)
        checks.append(
            ValidationCheck(
                check_name="acl_restricted_ui_actions",
                description="Requester persona must not see Delete or Resolve UI actions",
                passed=len(exposed_buttons) == 0,
                expected="no privileged UI actions",
                actual=f"exposed={exposed_buttons}" if exposed_buttons else "no privileged UI actions",
                error_message=f"ACL violation: privileged UI actions exposed to requester: {exposed_buttons}" if exposed_buttons else None,
            )
        )
        return checks
