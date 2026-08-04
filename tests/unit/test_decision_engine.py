"""Unit tests for Decision Engine (Deliverable 9)."""

from __future__ import annotations

import pytest

from agent.decision.engine import DecisionEngine
from agent.domain.intent import StructuredIntent
from agent.domain.observation import PageObservation
from agent.memory.session import SessionMemory
from agent.world.model import WorldModel
from tests.conftest import MockLLMClient


@pytest.mark.asyncio
async def test_decision_engine_heuristic(sample_observation: PageObservation) -> None:
    """Test heuristic decision making."""
    engine = DecisionEngine(llm_client=None)
    world_model = WorldModel()
    world_state = world_model.build_semantic_state(sample_observation)

    intent = StructuredIntent(intent_type="IncidentValidation", goal="Test incident form")
    memory = SessionMemory(goal="Test incident form")

    decision = await engine.decide_next_action(intent, world_state, memory)

    assert decision.action is not None
    assert decision.confidence_assessment is not None


@pytest.mark.asyncio
async def test_decision_engine_llm(sample_observation: PageObservation) -> None:
    """Test LLM-based decision making."""
    client = MockLLMClient(responses=[
        {
            "action_type": "fill",
            "target": "label:Short Description",
            "value": "Test Short Description",
            "reasoning": "Populate mandatory field",
            "expected_outcome": "Field is populated",
            "confidence": 0.96,
        }
    ])
    engine = DecisionEngine(llm_client=client)
    world_model = WorldModel()
    world_state = world_model.build_semantic_state(sample_observation)

    intent = StructuredIntent(intent_type="IncidentCreation", goal="Create incident")
    memory = SessionMemory(goal="Create incident")

    decision = await engine.decide_next_action(intent, world_state, memory)

    assert decision.action.action_type == "fill"
    assert decision.action.target == "label:Short Description"
    assert decision.action.value == "Test Short Description"
    assert decision.confidence_assessment.score >= 0.70
