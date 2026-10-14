"""Unit tests for Incident Navigation Intelligence (Deliverable 4)."""

from __future__ import annotations

from agent.core.types import ActionType
from agent.skills.incident.navigation import IncidentNavigator


def test_navigation_action_generation() -> None:
    """Test generating navigation actions."""
    nav = IncidentNavigator(base_url="https://test.service-now.com")

    # List view
    action_list = nav.navigate_to_incident_list()
    assert action_list.action_type == ActionType.NAVIGATE
    assert "incident_list.do" in action_list.value

    # Specific incident
    action_inc = nav.navigate_to_incident_number("INC0012345")
    assert action_inc.action_type == ActionType.NAVIGATE
    assert "INC0012345" in action_inc.value

    # Create new
    action_new = nav.navigate_to_create_new()
    assert "sys_id=-1" in action_new.value
