"""Capability registry module.

Provides a registry for discovering and routing domain skills (e.g. Incident, Change)
without creating massive conditional chains in the generic intelligence layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent.domain.intent import StructuredIntent
    from agent.skills.base import BaseSkill


class CapabilityDefinition(BaseModel):
    """Metadata for a registered domain capability/skill."""

    name: str = Field(description="Display name of the capability")
    module_name: str = Field(
        description="Internal module identifier (e.g. incident, change_request)"
    )
    supported_tables: list[str] = Field(
        default_factory=list, description="Tables supported by this skill"
    )
    description: str = Field(description="Description of what this skill does")


class CapabilityRegistry:
    """Discovers and routes domain skills.

    This acts as a lookup table for the orchestrator, preventing
    skills logic from bleeding into the shared generic architecture.
    """

    def __init__(self) -> None:
        self._skills: dict[str, tuple[BaseSkill, CapabilityDefinition]] = {}
        self._module_map: dict[str, str] = {}

    def register(self, skill: BaseSkill, definition: CapabilityDefinition) -> None:
        """Register a domain skill and its metadata."""
        self._skills[definition.name.lower()] = (skill, definition)
        self._module_map[definition.module_name.lower()] = definition.name.lower()
        for table in definition.supported_tables:
            self._module_map[table.lower()] = definition.name.lower()

    def get_skill_by_name(self, name: str) -> BaseSkill | None:
        """Retrieve a skill by its capability name."""
        match = self._skills.get(name.lower())
        return match[0] if match else None

    def get_skill_for_module(self, module_or_table: str) -> BaseSkill | None:
        """Retrieve the appropriate skill for a given module or table."""
        name = self._module_map.get(module_or_table.lower())
        return self.get_skill_by_name(name) if name else None

    def get_definition(self, name: str) -> CapabilityDefinition | None:
        """Retrieve the metadata for a capability name."""
        match = self._skills.get(name.lower())
        return match[1] if match else None

    def resolve_skill(self, intent: StructuredIntent) -> BaseSkill | None:
        """Resolve the appropriate skill for a structured intent."""
        for skill, _ in self._skills.values():
            if skill.can_handle(intent):
                return skill
        return None

    def list_skills(self) -> list[str]:
        """List names of all registered skills."""
        return list(self._skills.keys())
