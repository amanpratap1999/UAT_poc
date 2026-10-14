"""Integration contract tests for the LAYA action-selection path."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.browser.action_space import BrowserActionSpace
from agent.core.types import ActionType
from agent.decision.engine import DecisionEngine, DecisionUnavailableError
from agent.decision.laya_action_policy import (
    LayaActionDecision,
    LayaActionPolicy,
    LayaActionPolicyConfig,
)
from agent.domain.actions import AgentAction
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation
from agent.domain.intent import StructuredIntent
from agent.memory.session import SessionMemory
from agent.world.model import WorldModel


@pytest.fixture
def observation() -> PageObservation:
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="INC0010001",
        page_type="form",
        current_state="1",
        record_number="INC0010001",
        visible_fields=[
            FieldInfo(
                name="short_description",
                label="Short description",
                field_type="text",
                value="Old",
                is_mandatory=True,
                is_readonly=False,
                is_visible=True,
            ),
            FieldInfo(
                name="state",
                label="State",
                field_type="select",
                value="1",
                is_mandatory=True,
                is_readonly=False,
                is_visible=True,
                options=["1", "2"],
            ),
        ],
        mandatory_fields=["short_description", "state"],
        buttons=[ButtonInfo(label="Update", is_visible=True, is_enabled=True)],
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[],
    )


@pytest.mark.asyncio
async def test_observation_to_laya_to_action(observation):
    policy = LayaActionPolicy(
        config=LayaActionPolicyConfig(
            enabled=True,
            mode="primary",
            checkpoint="test/laya",
        )
    )
    policy._warm = True
    policy._model = MagicMock()
    policy._model_version = "test:v1"

    space = BrowserActionSpace.from_observation(
        observation=observation,
        plan_step="Click Update",
        persona="itil_user",
    )
    assert space is not None
    update = next(c for c in space.candidates if c.label == "Update")
    policy._infer = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(
                action_type=ActionType.CLICK,
                target=update.locator,
                reasoning="LAYA selected Update",
                metadata={},
            ),
            operation="click",
            target_index=update.index,
            confidence=0.9,
        )
    )
    decision = await policy.choose_action(space)
    assert decision.fallback_reason == ""
    assert decision.action.target == update.locator
    assert decision.provider == "laya"


@pytest.mark.asyncio
async def test_decision_engine_blocks_when_laya_fails(observation):
    policy = MagicMock()
    policy.is_configured.return_value = True
    policy.choose_action = AsyncMock(
        return_value=LayaActionDecision(
            action=AgentAction(action_type=ActionType.WAIT),
            operation="fallback",
            confidence=0.0,
            fallback_reason="inference_timeout",
        )
    )
    engine = DecisionEngine(laya_action_policy=policy)
    world_state = WorldModel().build_semantic_state(observation)
    intent = StructuredIntent(
        intent_type="IncidentValidation",
        goal="Click Update",
        target_module="incident",
    )
    memory = SessionMemory(goal="Click Update")
    memory.add_observation(observation)

    with pytest.raises(DecisionUnavailableError):
        await engine.decide_next_action(intent, world_state, memory)


@pytest.mark.asyncio
async def test_non_primary_laya_mode_is_rejected(observation):
    policy = LayaActionPolicy(
        config=LayaActionPolicyConfig(
            enabled=True,
            mode="shadow",
            checkpoint="test/laya",
        )
    )
    policy._warm = True
    policy._model = MagicMock()
    space = BrowserActionSpace.from_observation(
        observation,
        plan_step="Click Update",
        persona="itil_user",
    )
    decision = await policy.choose_action(space)
    assert decision.fallback_reason.startswith("non_primary_mode:")
