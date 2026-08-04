"""Lifecycle Intelligence for Deliverable 6.

Validates ServiceNow Incident state transitions against business rules.
Rejects impossible transitions and provides explicit rationale to the Reflection Engine.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.skills.incident.domain.models import Incident, IncidentState
from agent.skills.incident.knowledge.rules import (
    IncidentBusinessRules,
    IncidentLifecycle,
)

logger = get_logger(__name__)


class TransitionAssessment(BaseModel):
    """Assessment of a proposed Incident state transition."""

    from_state: IncidentState
    to_state: IncidentState
    is_valid_transition: bool = True
    is_blocked: bool = False
    block_reasons: list[str] = Field(default_factory=list)
    missing_mandatory_fields: list[str] = Field(default_factory=list)


class LifecycleEngine:
    """Evaluates Incident state transitions against ServiceNow business rules."""

    def evaluate_transition(
        self,
        current_incident: Incident,
        target_state: IncidentState,
    ) -> TransitionAssessment:
        """Evaluate whether an Incident can transition from current to target state.

        Args:
            current_incident: Current Incident domain model.
            target_state: Proposed target IncidentState.

        Returns:
            A TransitionAssessment model.
        """
        current_state = current_incident.state

        # Check state machine transition validity
        is_valid = IncidentLifecycle.is_valid_transition(current_state, target_state)
        block_reasons: list[str] = []
        missing_fields: list[str] = []

        if not is_valid:
            block_reasons.append(
                f"Transition from {current_state.name} to {target_state.name} is invalid per ServiceNow Incident lifecycle rules."
            )

        # Check required mandatory fields for target state
        mandatory_required = IncidentBusinessRules.get_mandatory_fields_for_state(target_state)

        for field_name in mandatory_required:
            val = self._get_incident_field_value(current_incident, field_name)
            if not val:
                missing_fields.append(field_name)
                block_reasons.append(
                    f"Transition to {target_state.name} requires mandatory field '{field_name}' to be populated."
                )

        is_blocked = len(block_reasons) > 0

        logger.info(
            "evaluated_incident_transition",
            from_state=current_state.value,
            to_state=target_state.value,
            is_valid=is_valid,
            is_blocked=is_blocked,
            missing_fields=missing_fields,
        )

        return TransitionAssessment(
            from_state=current_state,
            to_state=target_state,
            is_valid_transition=is_valid,
            is_blocked=is_blocked,
            block_reasons=block_reasons,
            missing_mandatory_fields=missing_fields,
        )

    def _get_incident_field_value(self, incident: Incident, field_name: str) -> str:
        fn_lower = field_name.lower()
        if fn_lower in ("short description", "short_description"):
            return incident.short_description
        if fn_lower == "caller":
            return incident.caller
        if fn_lower in ("assignment group", "assignment_group"):
            return incident.assignment.group
        if fn_lower in ("assigned to", "assigned_to"):
            return incident.assignment.assigned_to
        if fn_lower in ("resolution code", "resolution_code"):
            return incident.resolution.code
        if fn_lower in ("resolution notes", "resolution_notes"):
            return incident.resolution.notes
        return ""
