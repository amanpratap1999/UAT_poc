"""Unit tests for IncidentSkill Core (Deliverable 3)."""

from __future__ import annotations

import pytest

from agent.domain.intent import StructuredIntent
from agent.skills.incident.skill import IncidentSkill


@pytest.mark.asyncio
async def test_incident_skill_can_handle() -> None:
    """Test skill intent handling capabilities."""
    skill = IncidentSkill()

    intent_valid = StructuredIntent(
        intent_type="IncidentLifecycle",
        goal="Test complete incident lifecycle",
        target_module="incident",
    )
    assert skill.can_handle(intent_valid) is True

    intent_general = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Validate incident assignment group",
        target_module="incident",
    )
    assert skill.can_handle(intent_general) is True

    intent_non_incident = StructuredIntent(
        intent_type="GeneralValidation",
        goal="Click Show Password on login page",
        target_module="auth",
    )
    assert skill.can_handle(intent_non_incident) is False


@pytest.mark.asyncio
async def test_incident_skill_dynamic_plan() -> None:
    """Test dynamic execution plan generation for various intent goals."""
    skill = IncidentSkill()

    # Open intent
    intent_open = StructuredIntent(
        intent_type="IncidentOpen",
        goal="Open Incident INC0012345",
        target_module="incident",
    )
    plan_open = await skill.plan(intent_open)
    assert any("Open Target Incident" in s.description for s in plan_open.steps)

    # Resolution intent
    intent_resolve = StructuredIntent(
        intent_type="IncidentResolutionCheck",
        goal="Check whether this Incident can be resolved",
        target_module="incident",
    )
    plan_resolve = await skill.plan(intent_resolve)
    assert any("Resolution Code" in s.description for s in plan_resolve.steps)
