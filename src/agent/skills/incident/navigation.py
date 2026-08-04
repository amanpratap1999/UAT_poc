"""Navigation Intelligence for Deliverable 4.

Builds structured AgentActions for Incident module navigation:
- Open Incident list view
- Open specific Incident record (by number or sys_id)
- Create new Incident form
- Refresh record
- Return to list view

Uses standard AgentActions executed via ExecutionController. No direct Playwright calls.
"""

from __future__ import annotations

from agent.core.types import ActionType
from agent.domain.actions import AgentAction


class IncidentNavigator:
    """Strategy builder for Incident Management navigation actions."""

    def __init__(self, base_url: str = "https://dev12345.service-now.com") -> None:
        self._base_url = base_url.rstrip("/")

    def navigate_to_incident_list(self) -> AgentAction:
        """Create action to navigate to the Incident list view."""
        return AgentAction(
            action_type=ActionType.NAVIGATE,
            target="Incident List",
            value=f"{self._base_url}/incident_list.do",
            reasoning="Navigate to ServiceNow Incident Management list view",
            metadata={"url": f"{self._base_url}/incident_list.do"},
        )

    def navigate_to_create_new(self) -> AgentAction:
        """Create action to navigate to New Incident form."""
        return AgentAction(
            action_type=ActionType.NAVIGATE,
            target="Create New Incident",
            value=f"{self._base_url}/incident.do?sys_id=-1",
            reasoning="Open new ServiceNow Incident form",
            metadata={"url": f"{self._base_url}/incident.do?sys_id=-1"},
        )

    def navigate_to_incident_number(self, incident_number: str) -> AgentAction:
        """Create action to navigate to specific Incident by number or query."""
        url = f"{self._base_url}/incident_list.do?sysparm_query=number={incident_number}"
        return AgentAction(
            action_type=ActionType.NAVIGATE,
            target=f"Incident {incident_number}",
            value=url,
            reasoning=f"Open specific Incident record {incident_number}",
            metadata={"url": url, "incident_number": incident_number},
        )

    def refresh_current_record(self) -> AgentAction:
        """Create action to wait and refresh current record."""
        return AgentAction(
            action_type=ActionType.WAIT,
            target="Refresh Record",
            value="1000",
            reasoning="Wait for page load and refresh current incident record",
            metadata={"wait_for": "load", "duration_ms": 1000},
        )
