"""Tests for the LAYA-only browser action decision boundary."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.types import ActionType
from agent.decision.engine import DecisionEngine, DecisionUnavailableError
from agent.decision.laya_action_policy import LayaActionDecision
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.plan import ExecutionPlan
from agent.memory.session import SessionMemory
from agent.world.model import WorldModel
from tests.conftest import MockLLMClient


@pytest.mark.asyncio
async def test_decision_engine_uses_laya_and_never_calls_llm(sample_observation):
    llm = MockLLMClient(
        responses=[{"action_type": "click", "target": "WRONG", "value": ""}]
    )
    policy = MagicMock()
    policy.is_configured.return_value = True
    policy.choose_action = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(
                action_type=ActionType.CLICK,
                target="role:button:Update",
                value="",
                reasoning="LAYA selected Update",
                metadata={},
            ),
            operation="click",
            target_index=1,
            confidence=0.95,
            model_version="test:v1",
        )
    )
    engine = DecisionEngine(llm_client=llm, laya_action_policy=policy)

    world_state = WorldModel().build_semantic_state(sample_observation)
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Click Update",
        target_module="incident",
    )
    memory = SessionMemory(goal="Click Update")
    plan = ExecutionPlan(goal="Click Update")
    plan.add_step("Click Update", "Update succeeds")
    memory.plan = plan
    memory.add_observation(sample_observation)

    decision = await engine.decide_next_action(intent, world_state, memory)

    assert decision.action.target == "role:button:Update"
    assert decision.action.metadata["action_source"] == "laya"
    assert llm._call_count == 0


@pytest.mark.asyncio
async def test_laya_failure_is_fail_closed_and_llm_is_not_called(sample_observation):
    llm = MockLLMClient(
        responses=[{"action_type": "click", "target": "WRONG", "value": ""}]
    )
    policy = MagicMock()
    policy.is_configured.return_value = True
    policy.choose_action = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(action_type=ActionType.WAIT),
            operation="fallback",
            target_index=None,
            confidence=0.0,
            fallback_reason="inference_timeout",
        )
    )
    engine = DecisionEngine(llm_client=llm, laya_action_policy=policy)
    world_state = WorldModel().build_semantic_state(sample_observation)
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Click Update",
        target_module="incident",
    )
    memory = SessionMemory(goal="Click Update")
    memory.add_observation(sample_observation)

    with pytest.raises(DecisionUnavailableError):
        await engine.decide_next_action(intent, world_state, memory)
    assert llm._call_count == 0


@pytest.mark.asyncio
async def test_missing_laya_is_fail_closed_even_when_llm_exists(sample_observation):
    llm = MockLLMClient(responses=[{"action_type": "click", "target": "WRONG"}])
    engine = DecisionEngine(llm_client=llm, laya_action_policy=None)
    world_state = WorldModel().build_semantic_state(sample_observation)
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Click Update",
        target_module="incident",
    )
    memory = SessionMemory(goal="Click Update")
    memory.add_observation(sample_observation)

    with pytest.raises(DecisionUnavailableError):
        await engine.decide_next_action(intent, world_state, memory)
    assert llm._call_count == 0


@pytest.mark.asyncio
async def test_laya_policy_receives_planned_values(sample_observation):
    policy = MagicMock()
    policy.is_configured.return_value = True
    policy.choose_action = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(
                action_type=ActionType.FILL,
                target="label:Short Description",
                value="Network outage",
                reasoning="LAYA selected the field",
                metadata={},
            ),
            operation="fill",
            target_index=1,
            confidence=0.9,
        )
    )
    engine = DecisionEngine(llm_client=None, laya_action_policy=policy)
    world_state = WorldModel().build_semantic_state(sample_observation)
    intent = StructuredIntent(
        intent_type="IncidentCreation",
        goal="Create incident",
        target_module="incident",
        extracted_entities={"short_description": "Network outage"},
    )
    memory = SessionMemory(goal="Create incident")
    plan = ExecutionPlan(goal="Create incident")
    step = plan.add_step("Fill Short description", "Field populated")
    step.expected_values = {"short_description": "Network outage"}
    memory.plan = plan
    memory.add_observation(sample_observation)

    await engine.decide_next_action(intent, world_state, memory)

    payload = policy.choose_action.await_args.args[0]
    assert payload.planned_values["short_description"] == "Network outage"


@pytest.mark.asyncio
async def test_step_cache_cannot_bypass_laya(sample_observation):
    """A prior cached action must never become the browser action source."""
    policy = MagicMock()
    policy.is_configured.return_value = True
    policy.choose_action = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(
                action_type=ActionType.CLICK,
                target="role:button:Update",
                reasoning="LAYA selected Update",
            ),
            operation="click",
            target_index=1,
            confidence=0.9,
        )
    )
    engine = DecisionEngine(laya_action_policy=policy)
    world_state = WorldModel().build_semantic_state(sample_observation)
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Click Update",
        target_module="incident",
    )
    memory = SessionMemory(goal="Click Update")
    plan = ExecutionPlan(goal="Click Update")
    plan.add_step("Click Update", "Update succeeds")
    memory.plan = plan
    memory.add_observation(sample_observation)
    assert not hasattr(engine, "_step_cache")

    decision = await engine.decide_next_action(intent, world_state, memory)
    assert decision.action.metadata["action_source"] == "laya"
