"""Unit tests for Confidence Engine (Deliverable 6)."""

from __future__ import annotations

from agent.confidence.engine import ConfidenceEngine
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.domain.observation import FieldInfo, PageObservation
from agent.world.model import WorldModel


def test_confidence_evaluation(sample_observation: PageObservation) -> None:
    """Test confidence evaluation for normal vs blocked actions."""
    engine = ConfidenceEngine(default_threshold=0.70)
    world_model = WorldModel()

    # Normal action
    valid_action = AgentAction(
        action_type=ActionType.CLICK, target="text:Update", reasoning="Update"
    )
    world_state = world_model.build_semantic_state(sample_observation)

    assessment = engine.evaluate_confidence(valid_action, world_state)
    assert assessment.score >= 0.70
    assert assessment.is_above_threshold is True

    # Blocked action missing mandatory field
    sample_observation.visible_fields.append(
        FieldInfo(name="Category", field_type="select", value="", is_mandatory=True)
    )
    sample_observation.mandatory_fields.append("Category")
    world_state_blocked = world_model.build_semantic_state(sample_observation)

    resolve_action = AgentAction(
        action_type=ActionType.CLICK, target="text:Resolve Incident", reasoning="Resolve"
    )
    assessment_blocked = engine.evaluate_confidence(resolve_action, world_state_blocked)

    assert assessment_blocked.score < 0.70
    assert assessment_blocked.is_above_threshold is False
    assert assessment_blocked.suggested_pre_action is not None
