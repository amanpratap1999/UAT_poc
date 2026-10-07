"""Observation parsing for Change Management."""

import contextlib

from agent.domain.world import SemanticWorldState
from agent.skills.change.domain.models import ChangeRequest, ChangeState, ChangeType, RiskLevel


class ChangeObserver:
    """Parses generic WorldState into ChangeRequest domain models."""

    def parse_change_request(self, state: SemanticWorldState) -> ChangeRequest:
        """Extract Change details from the semantic world state."""
        chg = ChangeRequest()

        if not state.latest_observation:  # type: ignore[attr-defined]
            return chg

        obs = state.latest_observation  # type: ignore[attr-defined]

        if obs.record_number:
            chg.number = obs.record_number

        if obs.current_state:
            with contextlib.suppress(ValueError):
                chg.state = ChangeState(obs.current_state)

        # Try to parse risk, type, etc. from fields if they exist
        for field in obs.visible_fields:
            if field.name.lower() == "type" and field.value:
                with contextlib.suppress(ValueError):
                    chg.type = ChangeType(field.value)
            elif field.name.lower() == "risk" and field.value:
                with contextlib.suppress(ValueError):
                    chg.risk = RiskLevel(field.value)
            elif field.name.lower() == "short_description" and field.value:
                chg.short_description = field.value
            elif field.name.lower() == "assignment_group" and field.value:
                chg.assignment_group = field.value

        return chg
