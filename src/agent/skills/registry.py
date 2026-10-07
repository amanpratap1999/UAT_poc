"""SkillRegistry — plugin architecture for Deliverable 3."""

from __future__ import annotations

from agent.core.logging import get_logger
from agent.domain.intent import StructuredIntent
from agent.skills.base import BaseSkill

logger = get_logger(__name__)


class SkillRegistry:
    """Plugin registry for discovering and resolving domain skills."""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a domain skill."""
        manifest = skill.manifest
        self._skills[manifest.name] = skill
        logger.info("registered_skill", skill_name=manifest.name, module=manifest.module)

    def get_skill(self, name: str) -> BaseSkill | None:
        """Get a registered skill by name."""
        return self._skills.get(name)

    def resolve_skill(self, intent: StructuredIntent) -> BaseSkill | None:
        """Resolve the appropriate skill for a structured intent.

        Args:
            intent: Structured user intent.

        Returns:
            The matching BaseSkill instance, or None if no skill matched.
        """
        for skill in self._skills.values():
            if skill.can_handle(intent):
                logger.info(
                    "resolved_skill", skill_name=skill.manifest.name, intent=intent.intent_type
                )
                return skill

        logger.warning("no_skill_matched", intent_type=intent.intent_type)
        return None

    def list_skills(self) -> list[str]:
        """List names of all registered skills."""
        return list(self._skills.keys())
