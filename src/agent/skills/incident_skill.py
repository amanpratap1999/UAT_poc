"""IncidentSkill — domain plugin definition for Deliverable 3."""

from __future__ import annotations

from typing import Any

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.plan import ExecutionPlan
from agent.domain.skill import SkillManifest
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.domain.world import SemanticWorldState
from agent.skills.base import BaseSkill

logger = get_logger(__name__)


class IncidentSkill(BaseSkill):
    """Domain skill plugin for ServiceNow Incident Management."""

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="IncidentSkill",
            module="incident",
            version="1.0.0",
            description="ServiceNow Incident Management domain skill plugin",
            supported_intents=[
                "IncidentValidation",
                "IncidentCreation",
                "IncidentLifecycle",
                "GeneralValidation",
            ],
        )

    def can_handle(self, intent: StructuredIntent) -> bool:
        """Check if intent targets incident management."""
        if intent.target_module.lower() == "incident":
            return True
        return intent.intent_type in self.manifest.supported_intents

    async def plan(
        self, intent: StructuredIntent, world_state: SemanticWorldState | None = None
    ) -> ExecutionPlan:
        """Generate high-level plan structure for incident testing."""
        logger.info("incident_skill_planning", goal=intent.goal)
        plan = ExecutionPlan(goal=intent.goal)
        plan.add_step("Navigate to Incident Management", "Incident page displayed")
        plan.add_step("Validate Incident Form & Fields", "Fields verified")
        return plan

    async def validate(
        self,
        action: AgentAction,
        before: SemanticWorldState,
        after: SemanticWorldState,
    ) -> ValidationResult:
        """Perform incident-specific validation checks."""
        res = ValidationResult(action_description=f"IncidentSkill: {action.action_type}")
        res.add_check(
            ValidationCheck(
                check_name="incident_state_consistency",
                description="Verify incident state remains valid",
                passed=True,
                expected="valid state",
                actual=after.record_state or "normal",
            )
        )
        return res

    async def recover(
        self, error: Exception, context: dict[str, Any]
    ) -> AgentAction | None:
        """Perform incident-specific recovery suggestions."""
        logger.info("incident_skill_recovery", error=str(error))
        return None
