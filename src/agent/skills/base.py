"""BaseSkill interface for Deliverable 3.

All domain skills (IncidentSkill, ProblemSkill, ChangeSkill) inherit from BaseSkill.
Exposes:
- can_handle(intent)
- plan(intent, world_model)
- validate(action, before, after)
- recover(error, context)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.capabilities.registry import CapabilityDefinition
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.plan import ExecutionPlan
from agent.domain.skill import SkillManifest
from agent.domain.validation import ValidationResult
from agent.domain.world import SemanticWorldState


class BaseSkill(ABC):
    """Abstract base class for all domain skills."""

    @property
    @abstractmethod
    def manifest(self) -> SkillManifest:
        """Return the manifest describing this skill."""

    @abstractmethod
    def get_capability_definition(self) -> CapabilityDefinition:
        """Return the capability definition for registry discovery."""

    @abstractmethod
    def get_domain_selectors(self) -> dict[str, str | list[str]]:
        """Return a mapping of domain-specific semantic concepts to CSS selectors.

        Example: {"record_number": ["input[name='change_request.number']"]}
        """

    @abstractmethod
    def get_lifecycle_states(self) -> list[str]:
        """Return the expected valid lifecycle states for this domain."""

    @abstractmethod
    def can_handle(self, intent: StructuredIntent) -> bool:
        """Check if this skill can handle the given structured intent."""

    @abstractmethod
    async def plan(
        self, intent: StructuredIntent, world_state: SemanticWorldState | None = None
    ) -> ExecutionPlan:
        """Generate a macro plan for the structured intent."""

    @abstractmethod
    async def validate(
        self,
        action: AgentAction,
        before: SemanticWorldState,
        after: SemanticWorldState,
    ) -> ValidationResult:
        """Domain-specific validation after action execution."""

    @abstractmethod
    async def recover(self, error: Exception, context: dict[str, Any]) -> AgentAction | None:
        """Domain-specific recovery strategy."""
