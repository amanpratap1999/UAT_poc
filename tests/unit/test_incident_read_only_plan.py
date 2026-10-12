"""Regression tests for read-only Incident planning."""

from __future__ import annotations

import pytest

from agent.domain.intent import StructuredIntent
from agent.skills.incident.skill import IncidentSkill


@pytest.mark.asyncio
async def test_incident_skill_honors_read_only_constraint_from_raw_prompt() -> None:
    skill = IncidentSkill()
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Inspect incident INC0000007 fields and report evidence.",
        raw_prompt=(
            "Inspect ServiceNow incident INC0000007. "
            "Do not modify the incident, save fields, or create records."
        ),
        target_module="incident",
    )

    plan = await skill.plan(intent)

    descriptions = " ".join(step.description.lower() for step in plan.steps)
    assert "update state" not in descriptions
    assert "click update" not in descriptions
    assert "persist" not in descriptions
    assert "save" not in descriptions
    assert "create" not in descriptions

    assert len(plan.steps) == 3
    assert plan.steps[0].description == "Open Target Incident Record"
    assert plan.steps[1].description == "Observe Requested Incident Fields"
    assert plan.steps[2].description == "Re-observe Without Saving"
