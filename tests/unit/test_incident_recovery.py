"""Unit tests for Incident Recovery (Deliverable 8)."""

from __future__ import annotations

from agent.core.types import ActionType
from agent.skills.incident.domain.models import Incident
from agent.skills.incident.recovery import IncidentRecoveryHandler


def test_suggest_incident_recovery_assignment_group() -> None:
    """Test domain recovery for missing Assignment Group."""
    handler = IncidentRecoveryHandler()
    action = handler.suggest_incident_recovery("Missing mandatory field: Assignment Group")

    assert action is not None
    assert action.action_type == ActionType.FILL
    assert action.metadata.get("field_label") == "Assignment Group"


def test_suggest_incident_recovery_resolution_notes() -> None:
    """Test domain recovery for missing Resolution Notes."""
    handler = IncidentRecoveryHandler()
    action = handler.suggest_incident_recovery("Resolution Notes are required to resolve")

    assert action is not None
    assert action.action_type == ActionType.FILL
    assert action.metadata.get("field_label") == "Resolution Notes"


def test_suggest_incident_recovery_readonly() -> None:
    """Test domain recovery for read-only form with a configured instance."""
    handler = IncidentRecoveryHandler(base_url="https://test.service-now.com")
    inc = Incident(number="INC001", is_readonly=True)

    action = handler.suggest_incident_recovery("Cannot edit form", current_incident=inc)

    assert action is not None
    assert action.action_type == ActionType.NAVIGATE
    assert action.value.startswith("https://test.service-now.com/incident.do")


def test_suggest_incident_recovery_readonly_no_instance_fallback() -> None:
    """Read-only recovery must never fall back to a hard-coded instance URL (QA-019)."""
    handler = IncidentRecoveryHandler()
    inc = Incident(number="INC001", is_readonly=True)

    action = handler.suggest_incident_recovery("Cannot edit form", current_incident=inc)

    assert action is None
