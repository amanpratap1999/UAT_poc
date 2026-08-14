"""Incident Recovery for Deliverable 8.

Provides domain-specific recovery recommendations for Incident Management:
- Missing mandatory field -> populate field
- Read-only form -> navigate back / create new form
- Validation error banner -> address banner message
"""

from __future__ import annotations

from typing import Any

from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.skills.incident.domain.models import Incident

logger = get_logger(__name__)


class IncidentRecoveryHandler:
    """Domain-specific recovery strategy builder for Incident Management."""

    def suggest_incident_recovery(
        self,
        error_message: str,
        current_incident: Incident | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentAction | None:
        """Suggest domain-specific recovery action for Incident Management errors.

        Args:
            error_message: Error string or validation failure message.
            current_incident: Current Incident domain model.
            context: Additional context parameters.

        Returns:
            An AgentAction to recover, or None if no domain strategy exists.
        """
        logger.info("suggesting_incident_recovery", error=error_message[:60])
        err_lower = error_message.lower()

        # Missing assignment group
        if "assignment group" in err_lower:
            return AgentAction(
                action_type=ActionType.FILL,
                target="label:Assignment Group",
                value="Service Desk",
                reasoning="Domain Recovery: Fill mandatory Assignment Group field before proceeding",  # noqa: E501
                metadata={"field_label": "Assignment Group"},
            )

        # Missing resolution details
        if "resolution code" in err_lower or "resolution notes" in err_lower:
            return AgentAction(
                action_type=ActionType.FILL,
                target="label:Resolution Notes",
                value="Resolved by autonomous QA agent testing",
                reasoning="Domain Recovery: Populate Resolution Notes before moving to Resolved state",  # noqa: E501
                metadata={"field_label": "Resolution Notes"},
            )

        # Mandatory Short Description missing
        if "short description" in err_lower:
            return AgentAction(
                action_type=ActionType.FILL,
                target="label:Short Description",
                value="System issue - Autonomous QA test",
                reasoning="Domain Recovery: Populate mandatory Short Description",
                metadata={"field_label": "Short Description"},
            )

        # Read-only form
        if current_incident and current_incident.is_readonly:
            return AgentAction(
                action_type=ActionType.NAVIGATE,
                target="Create New Incident",
                value="https://dev12345.service-now.com/incident.do?sys_id=-1",
                reasoning="Domain Recovery: Current incident is read-only; open new incident form",
            )

        return None
