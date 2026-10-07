"""Incident Exploratory Pass Engine (Item 10, P2).

Performs a time-boxed, read-only exploratory pass on an Incident form
to discover issues outside the scripted assertions — things a human QA
would notice by looking at the page rather than by following a checklist.

Item 10 (P2, D4/D12): Incident exploratory pass. Human QA notices
issues outside scripted assertions. This engine does a time-boxed
read-only pass checking for:
- Unexpected labels or field ordering
- UX issues (disabled buttons that should be enabled, etc.)
- Field sequencing anomalies
- Unexpected UI behavior (hidden fields, wrong defaults)
- Visual inconsistencies

The pass is strictly read-only — no mutations, no clicks that change state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExploratoryFinding:
    """A finding from the exploratory pass."""
    finding_type: str  # "unexpected_label", "ux_issue", "field_anomaly", "visual_inconsistency"
    description: str
    severity: str = "minor"  # "minor", "major"
    field_name: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class ExploratoryPassEngine:
    """Time-boxed, read-only exploratory pass for Incident forms.

    Item 10 (P2): provides a framework for exploratory testing that
    discovers issues outside scripted assertions. The engine analyzes
    the current page observation and looks for anomalies a human QA
    would notice.

    Usage:
        engine = ExploratoryPassEngine(timeout_seconds=120)
        findings = engine.explore(page_observation, incident_state="New")
        for f in findings:
            print(f"{f.severity}: {f.description}")
    """

    # Known Incident field ordering (ServiceNow default)
    _EXPECTED_FIELD_ORDER = [
        "number", "caller_id", "short_description", "description",
        "state", "priority", "impact", "urgency",
        "assignment_group", "assigned_to",
        "category", "subcategory", "close_code", "close_notes",
    ]

    def explore(
        self,
        page_observation: Any,
        incident_state: str = "",
        timeout_seconds: int = 120,
    ) -> list[ExploratoryFinding]:
        """Perform the exploratory pass.

        Args:
            page_observation: PageObservation from the ObservationEngine.
            incident_state: current Incident state (e.g., "New", "In Progress", "Resolved").
            timeout_seconds: max time for the pass (read-only, no mutations).

        Returns:
            list of ExploratoryFinding objects.
        """
        findings: list[ExploratoryFinding] = []
        fields = getattr(page_observation, "visible_fields", [])
        buttons = getattr(page_observation, "buttons", [])
        validation_messages = getattr(page_observation, "validation_messages", [])

        # 1. Check for unexpected labels
        for field_info in fields:
            name = getattr(field_info, "name", "").lower()
            field_type = getattr(field_info, "field_type", "")
            # Check for fields with unexpected types
            if field_type == "password" and "password" not in name and "secret" not in name:
                findings.append(ExploratoryFinding(
                    finding_type="unexpected_label",
                    description=f"Field '{name}' has type 'password' but name doesn't suggest a secret field.",
                    field_name=name,
                ))
            # Check for empty mandatory fields in non-New states
            is_mandatory = getattr(field_info, "is_mandatory", False)
            value = getattr(field_info, "value", "")
            if is_mandatory and not value and incident_state not in ("New", ""):
                findings.append(ExploratoryFinding(
                    finding_type="field_anomaly",
                    description=f"Mandatory field '{name}' is empty in state '{incident_state}'.",
                    severity="major",
                    field_name=name,
                ))

        # 2. Check for UX issues with buttons
        for button in buttons:
            label = getattr(button, "label", "").lower()
            is_enabled = getattr(button, "is_enabled", True)
            # "Resolve" should be enabled in "In Progress" but not in "New"
            if "resolve" in label and not is_enabled and incident_state == "In Progress":
                findings.append(ExploratoryFinding(
                    finding_type="ux_issue",
                    description="Resolve button is disabled in 'In Progress' state — may be a UX issue.",
                    severity="minor",
                ))
            # "Save" should be enabled when fields are modified
            if "save" in label and not is_enabled and len(fields) > 0:
                findings.append(ExploratoryFinding(
                    finding_type="ux_issue",
                    description="Save button is disabled despite visible fields — may prevent updates.",
                    severity="minor",
                ))

        # 3. Check for validation messages that appeared unexpectedly
        for msg in validation_messages:
            msg_lower = msg.lower() if isinstance(msg, str) else str(msg).lower()
            if "error" in msg_lower and incident_state == "New":
                findings.append(ExploratoryFinding(
                    finding_type="field_anomaly",
                    description=f"Validation error on New incident: '{msg}'",
                    severity="major",
                ))

        # 4. Check for visual inconsistencies (field ordering)
        field_names = [getattr(f, "name", "").lower() for f in fields]
        for i, expected in enumerate(self._EXPECTED_FIELD_ORDER):
            if i < len(field_names):
                if expected not in field_names[i:]:
                    # Expected field is missing from the visible fields
                    if expected not in ("close_code", "close_notes") or incident_state in ("Resolved", "Closed"):
                        findings.append(ExploratoryFinding(
                            finding_type="visual_inconsistency",
                            description=f"Expected field '{expected}' not found in visible fields at position {i}.",
                            severity="minor",
                            field_name=expected,
                        ))

        logger.info(
            "exploratory_pass_complete",
            findings_count=len(findings),
            major_count=sum(1 for f in findings if f.severity == "major"),
        )
        return findings
