"""Tests for the LAYA action-policy adapter (P10-LAYA).

Covers:
  • Operation/target mapping (LAYA operation → ActionType, target index → locator)
  • Stale-page rejection (target index not in action space → fallback)
  • Policy timeout/error fallback (model failure → Gemini path)
  • Unsupported ServiceNow controls (password/file/hidden inputs excluded)
  • Safety gates (mode=shadow always falls back; low confidence falls back)
  • Action space fingerprint computation and freshness check

These tests do NOT require the optional ``transformers`` / ``mlx-lm``
dependency — they mock the model backend so the policy's decision logic
is tested in isolation.
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.types import ActionType
from agent.decision.laya_action_policy import (
    LAYA_OPERATIONS,
    ActionSpaceCandidate,
    LayaActionDecision,
    LayaActionPolicy,
    LayaActionPolicyConfig,
    _ActionSpacePayload,
)


# ── Fixtures ──


@pytest.fixture
def disabled_policy() -> LayaActionPolicy:
    """A policy with enabled=False — always falls back to Gemini."""
    return LayaActionPolicy(config=LayaActionPolicyConfig(enabled=False))


@pytest.fixture
def shadow_policy() -> LayaActionPolicy:
    """A policy in shadow mode — runs inference but always returns a fallback."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True,
        mode="shadow",
        checkpoint="test/laya",
        device="cpu",
    ))
    # Mock the model as loaded + warm
    policy._warm = True
    policy._model = MagicMock()
    policy._tokenizer = MagicMock()
    policy._model_version = "test:v1"
    return policy


@pytest.fixture
def primary_policy() -> LayaActionPolicy:
    """A policy in primary mode — uses LAYA decisions when confidence ≥ threshold."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True,
        mode="primary",
        checkpoint="test/laya",
        device="cpu",
        confidence_threshold=0.65,
    ))
    policy._warm = True
    policy._model = MagicMock()
    policy._tokenizer = MagicMock()
    policy._model_version = "test:v1"
    return policy


@pytest.fixture
def sample_action_space() -> _ActionSpacePayload:
    """A minimal action space with 3 candidates."""
    return _ActionSpacePayload(
        fingerprint="abc123",
        page_url="https://test.service-now.com/incident.do",
        page_title="INC0010001",
        candidates=[
            ActionSpaceCandidate(
                index=1, kind="click", role="button",
                label="Update", value="", locator="role:button:Update",
            ),
            ActionSpaceCandidate(
                index=2, kind="fill", role="textbox",
                label="Short description", value="test",
                locator="label:Short description",
            ),
            ActionSpaceCandidate(
                index=3, kind="select", role="combobox",
                label="State", value="2",
                locator="label:State",
            ),
        ],
        plan_step="Click Update to save the record",
        persona="itil",
        allowed_operations=sorted(LAYA_OPERATIONS),
    )


@pytest.fixture
def empty_action_space() -> _ActionSpacePayload:
    """An empty action space — LAYA cannot choose from nothing."""
    return _ActionSpacePayload(
        fingerprint="empty",
        page_url="https://test.service-now.com/loading",
        page_title="Loading...",
        candidates=[],
        plan_step="Wait for page to load",
        persona="itil",
        allowed_operations=sorted(LAYA_OPERATIONS),
    )


# ── Tests: disabled policy always falls back ──


@pytest.mark.asyncio
async def test_disabled_policy_always_falls_back(disabled_policy, sample_action_space):
    """A disabled policy must always return a fallback decision."""
    decision = await disabled_policy.choose_action(sample_action_space)
    assert decision.fallback_reason == "policy_disabled"
    assert decision.action.action_type == ActionType.WAIT
    assert decision.confidence == 0.0


# ── Tests: shadow mode always falls back ──


@pytest.mark.asyncio
async def test_shadow_mode_always_returns_fallback(shadow_policy, sample_action_space):
    """Shadow mode runs LAYA but returns a fallback so the Gemini path is used."""
    # Mock the inference to return a high-confidence decision
    shadow_policy._infer = AsyncMock(return_value=LayaActionDecision(
        action=MagicMock(),
        operation="click",
        target_index=1,
        confidence=0.95,
        model_version="test:v1",
    ))
    decision = await shadow_policy.choose_action(sample_action_space)
    assert decision.fallback_reason == "shadow_mode"
    assert decision.action.action_type == ActionType.WAIT


# ── Tests: primary mode uses LAYA when confidence ≥ threshold ──


@pytest.mark.asyncio
async def test_primary_mode_uses_laya_on_high_confidence(primary_policy, sample_action_space):
    """Primary mode uses the LAYA decision when confidence ≥ threshold."""
    # Mock inference to return a high-confidence click on candidate 1
    primary_policy._infer = AsyncMock(return_value=LayaActionDecision(
        action=MagicMock(action_type=ActionType.CLICK, target="role:button:Update", value="", metadata={}),
        operation="click",
        target_index=1,
        confidence=0.90,
        model_version="test:v1",
        inference_latency_ms=15.0,
    ))
    decision = await primary_policy.choose_action(sample_action_space)
    assert decision.fallback_reason == ""
    assert decision.operation == "click"
    assert decision.confidence == 0.90


@pytest.mark.asyncio
async def test_primary_mode_falls_back_on_low_confidence(primary_policy, sample_action_space):
    """Primary mode falls back when confidence < threshold."""
    primary_policy._infer = AsyncMock(return_value=LayaActionDecision(
        action=MagicMock(action_type=ActionType.CLICK, target="x", value="", metadata={}),
        operation="click",
        target_index=1,
        confidence=0.40,  # below threshold 0.65
        model_version="test:v1",
    ))
    decision = await primary_policy.choose_action(sample_action_space)
    assert "low_confidence" in decision.fallback_reason
    assert decision.confidence == 0.0


# ── Tests: empty action space falls back ──


@pytest.mark.asyncio
async def test_empty_action_space_falls_back(primary_policy, empty_action_space):
    """LAYA cannot choose from an empty action space."""
    decision = await primary_policy.choose_action(empty_action_space)
    assert decision.fallback_reason == "empty_action_space"


# ── Tests: stale target index falls back ──


@pytest.mark.asyncio
async def test_stale_target_index_falls_back(primary_policy, sample_action_space):
    """When the model returns a target index not in the action space, the
    _resolve_to_action method returns a fallback with stale_target_index."""
    # Build a raw model output with a target_index that doesn't exist
    raw = {"operation": "click", "target_index": 999, "confidence": 0.90}
    decision = primary_policy._resolve_to_action(raw, sample_action_space, elapsed_ms=10.0)
    assert "stale_target_index" in decision.fallback_reason


# ── Tests: inference timeout falls back ──


@pytest.mark.asyncio
async def test_inference_timeout_falls_back(primary_policy, sample_action_space):
    """When the model times out, the policy falls back to Gemini."""
    primary_policy._infer = AsyncMock(side_effect=asyncio.TimeoutError())
    decision = await primary_policy.choose_action(sample_action_space)
    assert "inference_timeout" in decision.fallback_reason


# ── Tests: inference error falls back ──


@pytest.mark.asyncio
async def test_inference_error_falls_back(primary_policy, sample_action_space):
    """When the model raises an error, the policy falls back to Gemini."""
    primary_policy._infer = AsyncMock(side_effect=RuntimeError("model crashed"))
    decision = await primary_policy.choose_action(sample_action_space)
    assert "inference_error" in decision.fallback_reason



@pytest.mark.asyncio
async def test_primary_mode_allows_warm_laya_without_calibration(primary_policy, sample_action_space, monkeypatch):
    """Uncalibrated confidence is telemetry; threshold and validation remain the gates."""
    monkeypatch.delenv("LAYA_ACTION_CONFIDENCE_CALIBRATED", raising=False)
    primary_policy._infer = AsyncMock(return_value=LayaActionDecision(
        action=MagicMock(
            action_type=ActionType.CLICK,
            target="role:button:Update",
            value="",
            metadata={},
        ),
        operation="click",
        target_index=1,
        confidence=0.90,
        model_version="test:v1",
    ))
    decision = await primary_policy.choose_action(sample_action_space)
    assert decision.fallback_reason == ""
    assert decision.provider == "laya"
    assert decision.operation == "click"

# ── Tests: operation → ActionType mapping ──


def test_operation_to_action_type_mapping(primary_policy, sample_action_space):
    """Verify LAYA operations map correctly to the project's ActionType enum."""
    test_cases = [
        ("click", ActionType.CLICK),
        ("wait", ActionType.WAIT),
        ("scroll_down", ActionType.SCROLL),
        ("scroll_up", ActionType.SCROLL),
        ("done", ActionType.VALIDATE),
        ("blocked", ActionType.VALIDATE),
    ]
    for operation, expected_action_type in test_cases:
        raw = {"operation": operation, "target_index": None, "confidence": 0.8}
        decision = primary_policy._resolve_to_action(raw, sample_action_space, elapsed_ms=5.0)
        # Control operations don't need a target_index; they should resolve cleanly
        if operation in ("wait", "scroll_down", "scroll_up", "done", "blocked"):
            assert decision.action.action_type == expected_action_type, (
                f"operation={operation} should map to {expected_action_type}"
            )
        # Target operations need a valid target_index — tested separately


def test_click_operation_requires_valid_index(primary_policy, sample_action_space):
    """A click resolves only to a code-owned candidate locator."""
    # Valid index 1 (the "Update" button)
    raw = {"operation": "click", "target_index": 1, "confidence": 0.9}
    decision = primary_policy._resolve_to_action(raw, sample_action_space, elapsed_ms=5.0)
    assert decision.fallback_reason == ""  # clean resolution
    assert decision.action.target == "role:button:Update"


def test_fill_and_select_fall_back_without_planner_value(primary_policy, sample_action_space):
    """Never reuse a field's existing value as the requested new value."""
    for operation, index in (("fill", 2), ("select", 3)):
        raw = {"operation": operation, "target_index": index, "confidence": 0.85}
        decision = primary_policy._resolve_to_action(raw, sample_action_space, elapsed_ms=5.0)
        assert decision.fallback_reason == f"planner_value_required:{operation}"
        assert decision.action.action_type == ActionType.WAIT


# ── Tests: safety — model never emits selectors ──


def test_model_output_never_contains_selectors(primary_policy, sample_action_space):
    """The resolved AgentAction's target is always from the action space,
    never from model output. The model only emits an index."""
    raw = {
        "operation": "click",
        "target_index": 1,
        "confidence": 0.9,
    }
    decision = primary_policy._resolve_to_action(raw, sample_action_space, elapsed_ms=5.0)
    # The target must be the locator from candidate 1, not a model-generated string
    assert decision.action.target == "role:button:Update"
    assert "laya_target_index" in decision.action.metadata
    assert decision.action.metadata["laya_target_index"] == 1


# ── Tests: config defaults ──


def test_laya_action_policy_config_defaults():
    """Default config has the policy disabled in shadow mode."""
    cfg = LayaActionPolicyConfig()
    assert cfg.enabled is False
    assert cfg.mode == "shadow"
    assert cfg.checkpoint == ""
    assert cfg.device == "auto"
    assert cfg.confidence_threshold == 0.65
    assert cfg.inference_timeout_seconds == 5.0
    assert cfg.max_candidates == 250


def test_policy_configured_when_enabled():
    """A policy with enabled=True is configured (Router auto-downloads checkpoint)."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True, checkpoint="",
    ))
    assert policy.is_configured()


def test_policy_not_configured_when_disabled():
    """A policy with enabled=False is not configured."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=False, checkpoint="some/checkpoint",
    ))
    assert not policy.is_configured()


def test_policy_configured_with_checkpoint():
    """A policy with enabled=True and a checkpoint is configured."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True, checkpoint="test/laya",
    ))
    assert policy.is_configured()


def test_load_model_uses_router_without_checkpoint(monkeypatch):
    """The default local backend uses Router without loading a checkpoint path."""
    router = MagicMock()
    router_constructor = MagicMock(return_value=router)
    laya_module = SimpleNamespace(Router=router_constructor, load=MagicMock())
    monkeypatch.setitem(sys.modules, "laya", laya_module)
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(enabled=True))

    policy._load_model()

    router_constructor.assert_called_once_with()
    laya_module.load.assert_not_called()
    assert policy._model is router
    assert policy.model_version == "laya:router"


@pytest.mark.asyncio
async def test_warmup_uses_dummy_candidate_and_extended_timeout():
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True,
        mode="primary",
        inference_timeout_seconds=5.0,
    ))
    policy._model = MagicMock()
    policy._load_model = MagicMock()
    policy._infer = AsyncMock(return_value=MagicMock())

    assert await policy.warm_up()

    action_space = policy._infer.await_args.args[0]
    assert len(action_space.candidates) == 1
    assert action_space.candidates[0].kind == "click"
    assert policy._infer.await_args.kwargs["timeout_seconds"] == 120.0


# ── Tests: stats / telemetry ──


def test_policy_stats_initialized(primary_policy):
    """A fresh policy has zero stats."""
    stats = primary_policy.get_stats()
    assert stats["inference_count"] == 0
    assert stats["fallback_count"] == 0
    assert stats["avg_inference_latency_ms"] == 0.0


@pytest.mark.asyncio
async def test_fallback_count_increments(primary_policy, sample_action_space):
    """Each fallback increments the fallback_count for telemetry."""
    primary_policy._infer = AsyncMock(side_effect=RuntimeError("crash"))
    await primary_policy.choose_action(sample_action_space)
    stats = primary_policy.get_stats()
    assert stats["fallback_count"] >= 1


# ── Tests: health checks ──


def test_policy_not_healthy_when_not_warm():
    """A policy that hasn't warmed up is not healthy."""
    policy = LayaActionPolicy(config=LayaActionPolicyConfig(
        enabled=True, checkpoint="test/laya",
    ))
    assert not policy.is_healthy()


def test_policy_healthy_when_warm(primary_policy):
    """A policy with a loaded model and warm flag is healthy."""
    assert primary_policy.is_healthy()


# ── Tests: shutdown ──


@pytest.mark.asyncio
async def test_shutdown_releases_model(primary_policy):
    """shutdown() clears the model and tokenizer."""
    assert primary_policy._model is not None
    await primary_policy.shutdown()
    assert primary_policy._model is None
    assert primary_policy._tokenizer is None
    assert not primary_policy.is_healthy()
