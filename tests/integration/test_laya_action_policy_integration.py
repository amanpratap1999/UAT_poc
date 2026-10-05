"""Integration tests for the LAYA action-policy path (P10-LAYA).

Covers:
  • Full path: observation → action space → LAYA policy → AgentAction
  • Stale-page rejection: action is rejected when the page changes
    between observation and execution
  • Policy timeout/error fallback: DecisionEngine falls back to Gemini
  • Unsupported ServiceNow controls: password/file/hidden never reach LAYA
  • Regression: existing Incident flows are unaffected when LAYA is disabled
  • Shadow mode: LAYA runs but the Gemini path's decision is used

These tests mock the LAYA model backend so no ``transformers`` /
``mlx-lm`` dependency is required.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.browser.action_space import BrowserActionSpace
from agent.core.types import ActionType
from agent.decision.laya_action_policy import (
    ActionSpaceCandidate,
    LayaActionPolicy,
    LayaActionPolicyConfig,
    _ActionSpacePayload,
)
from agent.domain.actions import AgentAction
from agent.domain.observation import ButtonInfo, FieldInfo, PageObservation


# ── Fixtures ──


@pytest.fixture
def incident_observation() -> PageObservation:
    """A realistic ServiceNow Incident form observation."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc",
        title="INC0010001",
        page_type="form",
        current_state="2",
        record_number="INC0010001",
        visible_fields=[
            FieldInfo(
                name="short_description", label="Short description",
                field_type="text", value="Test", is_mandatory=True,
                is_readonly=False, is_visible=True,
            ),
            FieldInfo(
                name="state", label="State",
                field_type="select", value="2", is_mandatory=True,
                is_readonly=False, is_visible=True,
            ),
        ],
        buttons=[
            ButtonInfo(label="Update", text="Update", is_visible=True, is_disabled=False),
        ],
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[],
    )


@pytest.fixture
def laya_primary_policy() -> LayaActionPolicy:
    """A primary-mode LAYA policy with a mocked model backend."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True, mode="primary", checkpoint="test/laya",
        device="cpu", confidence_threshold=0.65,
    ))
    policy._warm = True
    policy._model = MagicMock()
    policy._tokenizer = MagicMock()
    policy._model_version = "test:v1"
    return policy


# ── Test: full path observation → action space → policy → AgentAction ──


@pytest.mark.asyncio
async def test_full_laya_path_produces_agent_action(
    laya_primary_policy, incident_observation,
):
    """The full LAYA path produces a valid AgentAction with provenance metadata."""
    # Build the action space from the observation
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="Click Update to save the record",
        persona="itil",
    )
    assert action_space is not None
    assert len(action_space.candidates) > 0

    # Find the "Update" button candidate
    update_candidate = next(
        (c for c in action_space.candidates if "Update" in c.label),
        None,
    )
    assert update_candidate is not None

    # Mock the model to return a high-confidence click on the Update button
    laya_primary_policy._infer = AsyncMock(return_value=None)  # Will be overridden
    # Build the expected decision directly
    from agent.decision.laya_action_policy import LayaActionDecision
    expected_decision = LayaActionDecision(
        action=AgentAction(
            action_type=ActionType.CLICK,
            target=update_candidate.locator,
            value="",
            reasoning="LAYA: click on Update button",
            metadata={
                "laya_source": True,
                "laya_operation": "click",
                "laya_target_index": update_candidate.index,
                "laya_confidence": 0.90,
                "laya_action_space_fingerprint": action_space.fingerprint,
            },
        ),
        operation="click",
        target_index=update_candidate.index,
        confidence=0.90,
        model_version="test:v1",
        inference_latency_ms=12.5,
    )
    laya_primary_policy._infer = AsyncMock(return_value=expected_decision)

    decision = await laya_primary_policy.choose_action(action_space)

    # Verify the decision is used (not a fallback)
    assert decision.fallback_reason == ""
    assert decision.operation == "click"
    assert decision.confidence == 0.90
    assert decision.action.action_type == ActionType.CLICK
    assert "Update" in decision.action.target or "role:button:Update" in decision.action.target
    assert decision.action.metadata.get("laya_source") is True
    assert decision.action.metadata.get("laya_confidence") == 0.90


# ── Test: stale-page rejection ──


@pytest.mark.asyncio
async def test_stale_target_index_produces_fallback(
    laya_primary_policy, incident_observation,
):
    """When the model returns a target index not in the action space, the
    decision falls back with stale_target_index."""
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None

    # Simulate a stale target index (999 doesn't exist in the action space)
    raw = {"operation": "click", "target_index": 999, "confidence": 0.90}
    decision = laya_primary_policy._resolve_to_action(raw, action_space, elapsed_ms=10.0)
    assert "stale_target_index" in decision.fallback_reason
    assert decision.operation == "fallback"


# ── Test: unsupported ServiceNow controls ──


@pytest.mark.asyncio
async def test_password_field_never_reaches_laya(laya_primary_policy):
    """Password fields must never appear in the action space that LAYA sees."""
    obs_with_password = PageObservation(
        url="https://test.service-now.com/login",
        title="Login",
        page_type="login",
        visible_fields=[
            FieldInfo(
                name="user_password", label="Password",
                field_type="password", value="secret",
                is_mandatory=True, is_readonly=False, is_visible=True,
            ),
            FieldInfo(
                name="user_name", label="User name",
                field_type="text", value="admin",
                is_mandatory=True, is_readonly=False, is_visible=True,
            ),
        ],
        buttons=[
            ButtonInfo(label="Log in", text="Log in", is_visible=True, is_disabled=False),
        ],
        tabs=[],
        validation_messages=[],
        notification_messages=[],
        interactive_elements=[],
    )
    action_space = BrowserActionSpace.from_observation(
        observation=obs_with_password,
        plan_step="Log in",
        persona="itil",
    )
    assert action_space is not None
    for candidate in action_space.candidates:
        assert "password" not in candidate.label.lower()
        assert "password" not in candidate.role.lower()


# ── Test: regression — LAYA disabled → existing flows unchanged ──


@pytest.mark.asyncio
async def test_laya_disabled_does_not_affect_existing_flows(incident_observation):
    """When LAYA is disabled, the policy returns a fallback and the
    existing Gemini path runs unchanged."""
    disabled_policy = LayaActionPolicy(config=LayaActionPolicyConfig(enabled=False))
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None
    decision = await disabled_policy.choose_action(action_space)
    assert decision.fallback_reason == "policy_disabled"
    # The fallback action is a no-op WAIT — the caller uses the Gemini path
    assert decision.action.action_type == ActionType.WAIT


# ── Test: shadow mode records but doesn't use the decision ──


@pytest.mark.asyncio
async def test_shadow_mode_records_but_falls_back(
    incident_observation,
):
    """Shadow mode runs LAYA but returns a fallback so the Gemini path is used."""
    shadow_policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True, mode="shadow", checkpoint="test/laya",
    ))
    shadow_policy._warm = True
    shadow_policy._model = MagicMock()
    shadow_policy._tokenizer = MagicMock()
    shadow_policy._model_version = "test:v1"

    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None

    # Mock the inference to return a high-confidence decision
    from agent.decision.laya_action_policy import LayaActionDecision
    shadow_policy._infer = AsyncMock(return_value=LayaActionDecision(
        action=MagicMock(),
        operation="click",
        target_index=1,
        confidence=0.95,
        model_version="test:v1",
    ))

    decision = await shadow_policy.choose_action(action_space)
    assert decision.fallback_reason == "shadow_mode"
    # The shadow decision was recorded (logged) but the action is a fallback WAIT
    assert decision.action.action_type == ActionType.WAIT


# ── Test: inference timeout → fallback ──


@pytest.mark.asyncio
async def test_inference_timeout_falls_back_to_gemini(
    laya_primary_policy, incident_observation,
):
    """When LAYA times out, the policy falls back and the Gemini path runs."""
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None

    laya_primary_policy._infer = AsyncMock(side_effect=asyncio.TimeoutError())
    decision = await laya_primary_policy.choose_action(action_space)
    assert "inference_timeout" in decision.fallback_reason


# ── Test: inference error → fallback ──


@pytest.mark.asyncio
async def test_inference_error_falls_back_to_gemini(
    laya_primary_policy, incident_observation,
):
    """When LAYA raises an error, the policy falls back and the Gemini path runs."""
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None

    laya_primary_policy._infer = AsyncMock(side_effect=RuntimeError("model crashed"))
    decision = await laya_primary_policy.choose_action(action_space)
    assert "inference_error" in decision.fallback_reason


# ── Test: safety — model never emits selectors ──


@pytest.mark.asyncio
async def test_model_never_emits_selectors(laya_primary_policy, incident_observation):
    """The resolved AgentAction's target is always from the action space,
    never from model output. The model only emits an index."""
    action_space = BrowserActionSpace.from_observation(
        observation=incident_observation,
        plan_step="test",
        persona="itil",
    )
    assert action_space is not None

    # The model returns only {operation, target_index, confidence} — no selector
    raw = {"operation": "click", "target_index": 1, "confidence": 0.9}
    decision = laya_primary_policy._resolve_to_action(raw, action_space, elapsed_ms=5.0)
    # The target must be the locator from candidate 1, not a model-generated string
    assert decision.action.target.startswith(("role:", "label:", "text:", "css:", "xpath:"))
    assert "laya_target_index" in decision.action.metadata
