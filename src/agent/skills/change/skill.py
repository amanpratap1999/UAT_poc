"""ChangeSkill Core implementation for Phase 6.

The ChangeSkill plugin encapsulates all ServiceNow Change Management logic.
"""

from __future__ import annotations

from typing import Any

from agent.capabilities.registry import CapabilityDefinition
from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.plan import ExecutionPlan
from agent.domain.skill import SkillManifest
from agent.domain.validation import ValidationResult
from agent.domain.world import SemanticWorldState
from agent.skills.base import BaseSkill
from agent.skills.change.navigation import ChangeNavigator
from agent.skills.change.observation import ChangeObserver
from agent.skills.change.validation import ChangeValidator

logger = get_logger(__name__)


class ChangeSkill(BaseSkill):
    """Production Domain Skill for ServiceNow Change Management."""

    def __init__(self, base_url: str = "https://dev12345.service-now.com") -> None:
        self._navigator = ChangeNavigator(base_url=base_url)
        self._observer = ChangeObserver()
        self._validator = ChangeValidator()

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="ChangeSkill",
            module="change_request",
            version="1.0.0",
            description="ServiceNow Change Management domain skill plugin",
            supported_intents=[
                "ChangeValidation",
                "ChangeCreation",
                "ChangeLifecycle",
            ],
        )

    def get_capability_definition(self) -> CapabilityDefinition:
        return CapabilityDefinition(
            name="Change",
            module_name="change_request",
            supported_tables=["change_request", "change_task"],
            description="ServiceNow Change Management domain skill plugin",
        )

    def get_domain_selectors(self) -> dict[str, str | list[str]]:
        return {
            "record_number": [
                "input[name$='.number']",
                "input[id$='.number']",
                "[id^='sys_readonly.'][id$='.number']",
            ],
            "record_state": [
                "select[name$='.state']",
                "select[id$='.state']",
                "[id^='sys_readonly.'][id$='.state']",
                "[id*='state'] option[selected]",
            ],
        }

    def get_lifecycle_states(self) -> list[str]:
        return [
            "New",
            "Assess",
            "Authorize",
            "Scheduled",
            "Implement",
            "Review",
            "Closed",
            "Canceled",
        ]

    def can_handle(self, intent: StructuredIntent) -> bool:
        """Check if intent targets change management."""
        if intent.target_module.lower() in ("change", "change_request"):
            return True
        return (
            intent.intent_type in self.manifest.supported_intents or "change" in intent.goal.lower()
        )

    async def plan(
        self, intent: StructuredIntent, world_state: SemanticWorldState | None = None
    ) -> ExecutionPlan:
        """Build a domain-specific execution plan for the change goal."""
        logger.info(
            "building_change_execution_plan", goal=intent.goal, intent_type=intent.intent_type
        )
        plan = ExecutionPlan(goal=intent.goal)

        # Basic deterministic macro-planning
        if "create" in intent.goal.lower() or "new" in intent.goal.lower():
            plan.add_step("Navigate to Change Management", "Change list view displayed")
            plan.add_step("Open New Change Form", "New Change form displayed")
            plan.add_step("Fill Mandatory Fields", "Mandatory fields populated")
            plan.add_step("Submit Change", "Change created successfully")
        else:
            plan.add_step("Navigate to Change List", "Change list page displayed")
            plan.add_step("Search and Open Target Change", "Change record opened")
            plan.add_step("Verify Change Details", "Change details verified")

        return plan

    async def validate(
        self,
        action: AgentAction,
        before: SemanticWorldState,
        after: SemanticWorldState,
    ) -> ValidationResult:
        """Domain-specific validation after action execution."""
        logger.info("change_skill_validating_action", action=action.action_type)

        chg_before = self._observer.parse_change_request(before)
        chg_after = self._observer.parse_change_request(after)

        business_result = self._validator.validate_action(
            action_type=action.action_type,
            expected_step=action.reasoning or "Macro Step Verification",
            before=chg_before,
            after=chg_after,
        )

        return self._validator.to_generic_result(business_result)

    async def recover(self, error: Exception, context: dict[str, Any]) -> AgentAction | None:
        """Domain-specific recovery strategy."""
        logger.info("change_skill_recovery_requested", error=str(error))
        # Simple generic recovery for now to satisfy interface
        return None
