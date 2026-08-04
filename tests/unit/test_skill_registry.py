"""Unit tests for Skill Framework & Registry (Deliverable 3)."""

from __future__ import annotations

import pytest

from agent.domain.intent import StructuredIntent
from agent.skills.incident_skill import IncidentSkill
from agent.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_skill_registration_and_resolution() -> None:
    """Test registering and resolving skills."""
    registry = SkillRegistry()
    skill = IncidentSkill()
    registry.register(skill)

    assert "IncidentSkill" in registry.list_skills()

    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Test incident resolution",
        target_module="incident",
    )

    resolved = registry.resolve_skill(intent)
    assert resolved is not None
    assert resolved.manifest.name == "IncidentSkill"


@pytest.mark.asyncio
async def test_incident_skill_planning() -> None:
    """Test IncidentSkill planning method."""
    skill = IncidentSkill()
    intent = StructuredIntent(
        intent_type="IncidentCreation",
        goal="Create incident",
        target_module="incident",
    )

    plan = await skill.plan(intent)
    assert len(plan.steps) >= 2
    assert plan.goal == "Create incident"
