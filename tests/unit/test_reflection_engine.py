"""Unit tests for Reflection Engine (Deliverable 5)."""

from __future__ import annotations

import pytest

from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import PageObservation
from agent.reflection.engine import ReflectionEngine
from agent.world.model import WorldModel
from tests.conftest import MockLLMClient


@pytest.mark.asyncio
async def test_reflection_heuristic_fallback(sample_observation: PageObservation) -> None:
    """Test heuristic reflection when LLM is unavailable."""
    engine = ReflectionEngine(llm_client=None)
    world_model = WorldModel()

    action = AgentAction(
        action_type=ActionType.CLICK, target="text:Resolve", reasoning="Try resolve"
    )
    result = ActionResult(
        success=False,
        action=action,
        error="Element not found: text:Resolve",
        error_type="SelectorNotFoundError",
    )

    sample_observation.mandatory_fields.append("Assignment Group")

    world_state = world_model.build_semantic_state(sample_observation)
    reflection = await engine.reflect(
        action, result, world_state, expected_outcome="Incident is resolved"
    )

    assert reflection.is_as_expected is False
    assert len(reflection.hypotheses) > 0
    assert reflection.recommended_plan_adaptation is not None


@pytest.mark.asyncio
async def test_reflection_llm(sample_observation: PageObservation) -> None:
    """Test LLM reflection."""
    client = MockLLMClient(
        responses=[
            {
                "is_as_expected": False,
                "hypotheses": ["Page network request timed out", "Form mandatory field missing"],
                "recommended_plan_adaptation": "Fill Assignment Group field",
                "confidence": 0.88,
            }
        ]
    )
    engine = ReflectionEngine(llm_client=client)
    world_model = WorldModel()
    world_state = world_model.build_semantic_state(sample_observation)

    action = AgentAction(action_type=ActionType.CLICK, target="Resolve", reasoning="Resolve")
    result = ActionResult(success=True, action=action)

    reflection = await engine.reflect(action, result, world_state)

    assert reflection.is_as_expected is False
    assert "Form mandatory field missing" in reflection.hypotheses
    assert reflection.confidence == 0.88
