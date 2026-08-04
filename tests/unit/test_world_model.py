"""Unit tests for World Model (Deliverable 2)."""

from __future__ import annotations

import pytest

from agent.core.types import PageType
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.world.model import WorldModel


def test_build_semantic_state(sample_observation: PageObservation) -> None:
    """Test transforming low-level observation to SemanticWorldState."""
    model = WorldModel()

    # Modify sample observation to have missing mandatory field
    sample_observation.visible_fields.append(
        FieldInfo(name="Category", field_type="select", value="", is_mandatory=True)
    )
    sample_observation.mandatory_fields.append("Category")

    world_state = model.build_semantic_state(sample_observation)

    assert world_state.page_semantic_type == "Incident Record (INC0010001)"
    assert world_state.record_number == "INC0010001"
    assert world_state.record_state == "New"
    assert "Category" in world_state.missing_mandatory_fields
    assert world_state.form_completeness_score < 1.0

    # Resolve button should be marked blocked due to missing mandatory field
    resolve_actions = [a for a in world_state.blocked_actions if "resolve" in a.action_name.lower()]
    assert len(resolve_actions) > 0
    assert resolve_actions[0].is_blocked is True


def test_semantic_summary(sample_observation: PageObservation) -> None:
    """Test compact cognitive summary output."""
    model = WorldModel()
    world_state = model.build_semantic_state(sample_observation)
    summary = world_state.to_compact_cognitive_summary()

    assert "Current Page:" in summary
    assert "Record State:" in summary
    assert "Available Actions:" in summary
