"""World Model — semantic world state builder for Deliverable 2.

Transforms low-level PageObservation JSON into high-level cognitive concepts:
- Semantic page classification
- Record state tracking
- Missing mandatory field analysis
- Available vs. Blocked actions with reasons
- User permission & editability assessment
"""

from __future__ import annotations

from agent.core.logging import get_logger
from agent.core.types import PageType
from agent.domain.observation import PageObservation
from agent.domain.world import ActionCapability, SemanticWorldState

logger = get_logger(__name__)


class WorldModel:
    """Converts low-level page observations into cognitive semantic world states."""

    def build_semantic_state(self, observation: PageObservation) -> SemanticWorldState:
        """Build a SemanticWorldState from a PageObservation.

        Args:
            observation: Low-level PageObservation snapshot.

        Returns:
            A SemanticWorldState model.
        """
        logger.debug("building_semantic_world_state", page_type=observation.page_type.value)

        # 1. Semantic page classification
        page_semantic = self._classify_semantic_page(observation)

        # 2. Mandatory field analysis
        mandatory = observation.mandatory_fields
        missing_mandatory = []
        for field_info in observation.visible_fields:
            if field_info.is_mandatory and not field_info.value:
                missing_mandatory.append(field_info.name)

        # 3. Form completeness score
        completeness = 1.0
        if mandatory:
            filled_mandatory = len(mandatory) - len(missing_mandatory)
            completeness = max(0.0, filled_mandatory / len(mandatory))

        # 4. Analyze available vs. blocked actions
        available_actions, blocked_actions = self._analyze_actions(
            observation=observation,
            missing_mandatory=missing_mandatory,
        )

        # 5. User permissions assessment
        permissions = "editable"
        if all(f.is_readonly for f in observation.visible_fields) and observation.visible_fields:
            permissions = "readonly"

        state = SemanticWorldState(
            page_semantic_type=page_semantic,
            raw_page_type=observation.page_type,
            url=observation.url,
            title=observation.title,
            record_number=observation.incident_number,
            record_state=observation.current_state,
            user_permissions=permissions,
            mandatory_fields=mandatory,
            missing_mandatory_fields=missing_mandatory,
            available_actions=available_actions,
            blocked_actions=blocked_actions,
            validation_errors=observation.validation_messages,
            notifications=observation.notification_messages,
            form_completeness_score=completeness,
        )

        logger.info(
            "world_state_built",
            page_semantic=page_semantic,
            record_state=state.record_state,
            available_actions=len(available_actions),
            blocked_actions=len(blocked_actions),
        )
        return state

    def _classify_semantic_page(self, obs: PageObservation) -> str:
        if obs.page_type == PageType.LOGIN:
            return "Authentication Gateway"
        if obs.page_type == PageType.FORM:
            if obs.incident_number:
                return f"Incident Record ({obs.incident_number})"
            return "New Record Form"
        if obs.page_type == PageType.LIST:
            return "Incident Queue List"
        if obs.page_type == PageType.DIALOG:
            return "Modal Dialog Overlay"
        if obs.page_type == PageType.HOMEPAGE or obs.page_type == PageType.DASHBOARD:
            return "ServiceNow Workspace"
        return "ServiceNow Workspace"

    def _analyze_actions(
        self,
        observation: PageObservation,
        missing_mandatory: list[str],
    ) -> tuple[list[ActionCapability], list[ActionCapability]]:
        available: list[ActionCapability] = []
        blocked: list[ActionCapability] = []

        for btn in observation.buttons:
            action_name = btn.label
            target = f"text:{btn.label}"

            if not btn.is_enabled:
                blocked.append(
                    ActionCapability(
                        action_name=action_name,
                        target=target,
                        is_available=False,
                        is_blocked=True,
                        block_reason="Button disabled in UI",
                    )
                )
            elif action_name.lower() in ("resolve", "resolve incident", "submit", "update") and missing_mandatory:
                blocked.append(
                    ActionCapability(
                        action_name=action_name,
                        target=target,
                        is_available=True,
                        is_blocked=True,
                        block_reason=f"Missing mandatory fields: {', '.join(missing_mandatory)}",
                    )
                )
            else:
                available.append(
                    ActionCapability(
                        action_name=action_name,
                        target=target,
                        is_available=True,
                        is_blocked=False,
                    )
                )

        return available, blocked
