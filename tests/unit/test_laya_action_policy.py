"""Unit tests for the LAYA browser action selector."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def policy() -> LayaActionPolicy:
    p = LayaActionPolicy(
        config=LayaActionPolicyConfig(
            enabled=True,
            mode="primary",
            confidence_threshold=0.65,
            checkpoint="test/laya",
            device="cpu",
        )
    )
    p._warm = True
    p._model = MagicMock()
    p._tokenizer = MagicMock()
    p._model_version = "test:v1"
    return p


@pytest.fixture
def action_space() -> _ActionSpacePayload:
    return _ActionSpacePayload(
        fingerprint="abc123",
        page_url="https://test.service-now.com/incident.do?sys_id=abc",
        page_title="INC0010001",
        candidates=[
            ActionSpaceCandidate(
                index=1,
                kind="click",
                role="button",
                label="Update",
                value="",
                locator="role:button:Update",
            ),
            ActionSpaceCandidate(
                index=2,
                kind="fill",
                role="textbox",
                label="Short description",
                value="old",
                locator="label:Short description",
            ),
            ActionSpaceCandidate(
                index=3,
                kind="select",
                role="combobox",
                label="State",
                value="1",
                locator="label:State",
                options=["1", "2"],
            ),
        ],
        plan_step="Set the short description",
        persona="itil_user",
        planned_values={"short_description": "Network outage"},
        allowed_operations=sorted(LAYA_OPERATIONS),
    )


@pytest.mark.asyncio
async def test_router_inference_uses_typed_decisions_model(policy, action_space):
    """The browser selector must pin Router inference to the typed-decisions checkpoint."""
    policy._model = MagicMock()
    policy._model.system_one.return_value = {
        "answers": {
            "operation": {"choice": "click", "answer_confidence": 0.95},
            "click_target": {"choice": "1", "answer_confidence": 0.95},
        },
        "usage": {},
    }

    raw = await policy._run_model(action_space)

    assert raw is not None
    assert raw["operation"] == "click"
    policy._model.system_one.assert_called_once()
    kwargs = policy._model.system_one.call_args.kwargs
    assert kwargs["model"] == "typed-decisions"


@pytest.mark.asyncio
async def test_primary_high_confidence_is_executable(policy, action_space):
    policy._infer = AsyncMock(
        return_value=LayaActionDecision(
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
            inference_latency_ms=12.0,
        )
    )
    decision = await policy.choose_action(action_space)
    assert decision.fallback_reason == ""
    assert decision.provider == "laya"


@pytest.mark.asyncio
async def test_low_confidence_is_blocked(policy, action_space):
    policy._infer = AsyncMock(
        return_value=LayaActionDecision(
            action=MagicMock(action_type=ActionType.CLICK),
            operation="click",
            target_index=1,
            confidence=0.40,
        )
    )
    decision = await policy.choose_action(action_space)
    assert "low_confidence" in decision.fallback_reason


@pytest.mark.asyncio
async def test_timeout_is_blocked_not_routed_to_llm(policy, action_space):
    policy._infer = AsyncMock(side_effect=asyncio.TimeoutError())
    decision = await policy.choose_action(action_space)
    assert "inference_timeout" in decision.fallback_reason


@pytest.mark.asyncio
async def test_model_error_is_blocked_not_routed_to_llm(policy, action_space):
    policy._infer = AsyncMock(side_effect=RuntimeError("model crashed"))
    decision = await policy.choose_action(action_space)
    assert "inference_error" in decision.fallback_reason


@pytest.mark.asyncio
async def test_non_primary_mode_is_rejected(policy, action_space):
    policy._config.mode = "shadow"
    decision = await policy.choose_action(action_space)
    assert decision.fallback_reason.startswith("non_primary_mode:")


def test_runtime_dependency_version_guard_accepts_required_versions(policy, monkeypatch):
    versions = {"laya": "0.3.29", "torch": "2.14.1+cpu"}
    monkeypatch.setattr(
        "agent.decision.laya_action_policy.package_version",
        lambda name: versions[name],
    )
    policy._verify_runtime_dependencies()


def test_runtime_dependency_version_guard_rejects_old_torch(policy, monkeypatch):
    versions = {"laya": "0.3.29", "torch": "2.14.0"}
    monkeypatch.setattr(
        "agent.decision.laya_action_policy.package_version",
        lambda name: versions[name],
    )
    with pytest.raises(RuntimeError, match="torch>=2.14.1"):
        policy._verify_runtime_dependencies()


def test_config_defaults_require_primary_laya():
    cfg = LayaActionPolicyConfig()
    assert cfg.enabled is True
    assert cfg.mode == "primary"


def test_click_target_is_resolved_only_from_action_space(policy, action_space):
    decision = policy._resolve_to_action(
        {"operation": "click", "target_index": 1, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert decision.fallback_reason == ""
    assert decision.action.target == "role:button:Update"


def test_fill_uses_precomputed_planned_value(policy, action_space):
    decision = policy._resolve_to_action(
        {"operation": "fill", "target_index": 2, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert decision.fallback_reason == ""
    assert decision.action.action_type == ActionType.FILL
    assert decision.action.value == "Network outage"


def test_fill_without_planned_value_fails_closed(policy, action_space):
    action_space.planned_values = {}
    decision = policy._resolve_to_action(
        {"operation": "fill", "target_index": 2, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert decision.fallback_reason == "planned_value_missing:fill"


def test_stale_target_fails_closed(policy, action_space):
    decision = policy._resolve_to_action(
        {"operation": "click", "target_index": 999, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert "stale_target_index" in decision.fallback_reason


def test_done_is_a_terminal_laya_selection(policy, action_space):
    decision = policy._resolve_to_action(
        {"operation": "done", "target_index": None, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert decision.fallback_reason == ""
    assert decision.action.action_type == ActionType.VALIDATE


def test_blocked_terminal_signal_fails_closed(policy, action_space):
    decision = policy._resolve_to_action(
        {"operation": "blocked", "target_index": None, "confidence": 0.9},
        action_space,
        elapsed_ms=5.0,
    )
    assert decision.fallback_reason == "laya_blocked_terminal_signal"


@pytest.mark.asyncio
async def test_disabled_policy_reports_unavailable(action_space):
    p = LayaActionPolicy(config=LayaActionPolicyConfig(enabled=False))
    decision = await p.choose_action(action_space)
    assert decision.fallback_reason == "policy_disabled"


@pytest.mark.asyncio
async def test_empty_target_list_can_still_choose_wait(policy):
    empty = _ActionSpacePayload(
        fingerprint="empty",
        page_url="https://test.service-now.com/loading",
        page_title="Loading",
        candidates=[],
        plan_step="Wait for the page to finish loading",
        persona="itil_user",
        planned_values={},
        allowed_operations=["wait", "scroll_down", "scroll_up", "done", "blocked"],
    )
    policy._infer = AsyncMock(
        return_value=LayaActionDecision(
            action=MagicMock(action_type=ActionType.WAIT),
            operation="wait",
            target_index=None,
            confidence=0.95,
        )
    )
    decision = await policy.choose_action(empty)
    assert decision.fallback_reason == ""
    assert decision.operation == "wait"
