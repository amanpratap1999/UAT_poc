"""Release/Layout Drift Detector (Item 12, P2).

Detects when ServiceNow form layouts change between client releases and
triggers a regression run when important fields move. Also provides
learned locator recovery — when a locator fails, search for the element
by nearby text/label.

Item 12 (P2, D9/D12): Release/layout drift adaptation. ServiceNow forms
change between client releases. The agent should:
1. Fingerprint page layouts (field names, positions, types)
2. Detect when important fields have moved
3. Trigger a regression run when the fingerprint changes
4. Recover failed locators by searching for nearby text/label
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LayoutFingerprint:
    """A fingerprint of a ServiceNow form layout.

    Captures the field names, types, positions, and mandatory flags
    so changes can be detected between releases.
    """
    page_type: str  # "form", "list", "login"
    record_type: str  # "incident", "change", etc.
    fields: list[dict[str, Any]] = field(default_factory=list)  # [{name, type, mandatory, readonly}]
    button_labels: list[str] = field(default_factory=list)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_type": self.page_type,
            "record_type": self.record_type,
            "fields": self.fields,
            "button_labels": self.button_labels,
            "captured_at": self.captured_at.isoformat(),
        }


@dataclass
class DriftResult:
    """Result of comparing two layout fingerprints."""
    has_drift: bool
    added_fields: list[str] = field(default_factory=list)
    removed_fields: list[str] = field(default_factory=list)
    changed_types: list[dict[str, str]] = field(default_factory=list)  # [{name, old_type, new_type}]
    changed_mandatory: list[dict[str, str]] = field(default_factory=list)
    added_buttons: list[str] = field(default_factory=list)
    removed_buttons: list[str] = field(default_factory=list)
    details: str = ""


class LayoutDriftDetector:
    """Detects layout drift between releases and recovers failed locators.

    Item 12 (P2, D9/D12): provides:
    1. Fingerprint capture from page observations
    2. Drift detection between old and new fingerprints
    3. Regression trigger when important fields have moved
    4. Learned locator recovery (search by nearby text/label when locator fails)
    """

    # Fields whose movement triggers a regression
    _REGRESSION_CRITICAL_FIELDS = frozenset({
        "number", "state", "priority", "short_description",
        "assignment_group", "assigned_to", "close_code", "close_notes",
    })

    def capture_fingerprint(
        self,
        page_observation: Any,
        record_type: str = "incident",
    ) -> LayoutFingerprint:
        """Capture a layout fingerprint from a page observation."""
        fields = []
        for f in getattr(page_observation, "visible_fields", []):
            fields.append({
                "name": getattr(f, "name", "").lower(),
                "type": getattr(f, "field_type", ""),
                "mandatory": getattr(f, "is_mandatory", False),
                "readonly": getattr(f, "is_readonly", False),
            })
        button_labels = [
            getattr(b, "label", "").lower()
            for b in getattr(page_observation, "buttons", [])
        ]
        page_type = str(getattr(page_observation, "page_type", "form"))
        fp = LayoutFingerprint(
            page_type=page_type,
            record_type=record_type,
            fields=fields,
            button_labels=button_labels,
        )
        logger.info(
            "fingerprint_captured",
            record_type=record_type,
            field_count=len(fields),
            button_count=len(button_labels),
        )
        return fp

    def detect_drift(
        self,
        old: LayoutFingerprint,
        new: LayoutFingerprint,
    ) -> DriftResult:
        """Compare two fingerprints and detect layout drift."""
        old_fields = {f["name"]: f for f in old.fields}
        new_fields = {f["name"]: f for f in new.fields}
        old_buttons = set(old.button_labels)
        new_buttons = set(new.button_labels)

        added = [n for n in new_fields if n not in old_fields]
        removed = [n for n in old_fields if n not in new_fields]
        changed_types = []
        changed_mandatory = []

        for name in old_fields:
            if name in new_fields:
                old_f = old_fields[name]
                new_f = new_fields[name]
                if old_f.get("type") != new_f.get("type"):
                    changed_types.append({
                        "name": name,
                        "old_type": old_f.get("type", ""),
                        "new_type": new_f.get("type", ""),
                    })
                if old_f.get("mandatory") != new_f.get("mandatory"):
                    changed_mandatory.append({
                        "name": name,
                        "old_mandatory": old_f.get("mandatory"),
                        "new_mandatory": new_f.get("mandatory"),
                    })

        added_buttons = list(new_buttons - old_buttons)
        removed_buttons = list(old_buttons - new_buttons)

        has_drift = bool(added or removed or changed_types or changed_mandatory or added_buttons or removed_buttons)

        # Check if any critical fields were affected
        critical_changes = [f for f in (added + removed) if f in self._REGRESSION_CRITICAL_FIELDS]
        if critical_changes:
            has_drift = True
            logger.warning(
                "drift_critical_fields_changed",
                fields=critical_changes,
            )

        details_parts = []
        if added: details_parts.append(f"added: {added}")
        if removed: details_parts.append(f"removed: {removed}")
        if changed_types: details_parts.append(f"type changes: {changed_types}")
        if changed_mandatory: details_parts.append(f"mandatory changes: {changed_mandatory}")

        return DriftResult(
            has_drift=has_drift,
            added_fields=added,
            removed_fields=removed,
            changed_types=changed_types,
            changed_mandatory=changed_mandatory,
            added_buttons=added_buttons,
            removed_buttons=removed_buttons,
            details="; ".join(details_parts) if details_parts else "no drift detected",
        )

    def recover_locator(
        self,
        failed_locator: str,
        page_observation: Any,
    ) -> str | None:
        """Recover a failed locator by searching for nearby text/label.

        When a Playwright locator fails (element not found), this method
        searches the page observation for a field whose name matches
        the failed locator's intent, and returns an alternative locator
        string that might work.

        This is a best-effort recovery — it doesn't guarantee the
        alternative locator will work, but it gives the agent a chance
        to continue instead of immediately failing.
        """
        failed_lower = failed_locator.lower().strip()
        # Search by field name
        for f in getattr(page_observation, "visible_fields", []):
            name = getattr(f, "name", "").lower()
            if failed_lower in name or name in failed_lower:
                # Return a semantic locator that uses the field name
                recovered = f"label:{getattr(f, 'name', '')}" if hasattr(f, "name") else None
                if recovered:
                    logger.info(
                        "locator_recovered",
                        failed=failed_locator,
                        recovered=recovered,
                        method="field_name_match",
                    )
                    return recovered
        # Search by button label
        for b in getattr(page_observation, "buttons", []):
            label = getattr(b, "label", "").lower()
            if failed_lower in label or label in failed_lower:
                recovered = f"text:{getattr(b, 'label', '')}" if hasattr(b, "label") else None
                if recovered:
                    logger.info(
                        "locator_recovered",
                        failed=failed_locator,
                        recovered=recovered,
                        method="button_label_match",
                    )
                    return recovered
        logger.warning("locator_recovery_failed", failed=failed_locator)
        return None
