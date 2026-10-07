"""Unit tests for Desktop-Style Interactive Agent capabilities, Circuit Breaker, and Canonical Plan."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock

from agent.core.config import LLMConfig
from agent.core.state_machine import AgentStateMachine
from agent.core.types import AgentState, StepStatus
from agent.domain.plan import ExecutionPlan, PlanStep
from agent.knowledge.embeddings import OpenAIEmbeddingClient
from agent.memory.session import SessionMemory
from agent.reporting.engine import ReportingEngine


@pytest.mark.asyncio
async def test_embedding_circuit_breaker_trips_on_http_410():
    """Permanent error like HTTP 410 trips circuit breaker and returns zero vectors."""
    config = LLMConfig(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        embedding_model="nvidia/nemotron-3-embed-1b",
        embedding_dimensions=2048,
    )
    client = OpenAIEmbeddingClient(config)

    # Mock client embeddings.create raising permanent 410 error
    error = Exception("HTTP 410: Model nvidia/nv-embedqa-e5-v5 is gone")
    setattr(error, "status_code", 410)
    client._client.embeddings.create = AsyncMock(side_effect=error)

    healthy = await client.startup_health_check()
    assert healthy is False
    assert client._circuit_open is True
    assert "Health probe failed" in client._circuit_reason or "410" in client._circuit_reason

    # Subsequent embed calls fail-fast with RuntimeError immediately without network calls
    with pytest.raises(RuntimeError, match="Embedding circuit breaker open"):
        await client.create_embedding("sample query")

    with pytest.raises(RuntimeError, match="Embedding circuit breaker open"):
        await client.create_embeddings(["sample query 1", "sample query 2"])


def test_canonical_plan_skips_remaining_steps_on_precondition_failure():
    """Failing a step skips all downstream steps with exact reason."""
    plan = ExecutionPlan(
        goal="Test Incident Lifecycle",
        steps=[
            PlanStep(step_index=0, description="Navigate to incident INC0000007", expected_outcome="Page loaded"),
            PlanStep(step_index=1, description="Verify initial state is On Hold", expected_outcome="State is On Hold"),
            PlanStep(step_index=2, description="Change state to In Progress", expected_outcome="State changed to In Progress"),
            PlanStep(step_index=3, description="Click update", expected_outcome="Record saved"),
        ],
    )

    # Step 0 succeeds
    plan.steps[0].mark_success()

    # Step 1 fails on precondition
    plan.steps[1].mark_failed("Precondition failed: expected On Hold (3), got In Progress (2)")

    # Skip remaining steps
    plan.skip_remaining_steps(
        from_step_index=2,
        reason="Skipped: Precondition failed on step 1 (expected On Hold, got In Progress)",
    )

    assert plan.steps[0].status == StepStatus.SUCCESS
    assert plan.steps[1].status == StepStatus.FAILED
    assert plan.steps[2].status == StepStatus.SKIPPED
    assert plan.steps[2].error == "Skipped: Precondition failed on step 1 (expected On Hold, got In Progress)"
    assert plan.steps[3].status == StepStatus.SKIPPED
    assert plan.steps[3].error == "Skipped: Precondition failed on step 1 (expected On Hold, got In Progress)"


def test_state_machine_supports_interactive_states():
    """State machine allows valid transitions to and from PAUSED, CANCELLED, and AWAITING_USER_INPUT."""
    sm = AgentStateMachine(initial_state=AgentState.IDLE)
    sm.transition_to(AgentState.INTENT_ANALYSIS)
    sm.transition_to(AgentState.PLANNING)
    sm.transition_to(AgentState.DECISION)
    sm.transition_to(AgentState.EXECUTING)

    # Executing -> Paused -> Executing
    sm.transition_to(AgentState.PAUSED)
    assert sm.current_state == AgentState.PAUSED
    sm.transition_to(AgentState.EXECUTING)
    assert sm.current_state == AgentState.EXECUTING

    # Executing -> Awaiting user input -> Executing
    sm.transition_to(AgentState.AWAITING_USER_INPUT)
    assert sm.current_state == AgentState.AWAITING_USER_INPUT
    sm.transition_to(AgentState.EXECUTING)
    assert sm.current_state == AgentState.EXECUTING

    # Executing -> Precondition failed
    sm.transition_to(AgentState.PRECONDITION_FAILED)
    assert sm.current_state == AgentState.PRECONDITION_FAILED


@pytest.mark.asyncio
async def test_reporting_engine_captures_canonical_steps_and_browser_telemetry(tmp_path):
    """ReportingEngine includes canonical plan steps, browser logs, and 0 defects on precondition failure."""
    engine = ReportingEngine(output_dir=tmp_path)
    memory = SessionMemory(goal="Test incident INC0000007")

    plan = ExecutionPlan(
        goal="Test incident INC0000007",
        steps=[
            PlanStep(step_index=0, description="Step 1", expected_outcome="ok", status=StepStatus.SUCCESS),
            PlanStep(
                step_index=1,
                description="Step 2 - Verify initial state",
                expected_outcome="On Hold",
                status=StepStatus.FAILED,
                error="Expected On Hold (3), got In Progress (2)",
                observed_values={"state": 2},
                expected_values={"state": 3},
            ),
            PlanStep(
                step_index=2,
                description="Step 3 - Mutation",
                expected_outcome="ok",
                status=StepStatus.SKIPPED,
                error="Skipped due to precondition failure",
            ),
        ],
    )
    memory.plan = plan
    memory.precondition_failed = True
    memory.browser_logs = [{"level": "warning", "message": "ServiceNow GlideAjax deprecation"}]
    memory.console_errors = ["Uncaught TypeError: g_form is undefined"]

    report = await engine.generate_report(memory)

    assert report.status == "precondition_failed"
    assert len(report.defects) == 0
    assert report.defect_count == 0
    assert len(report.browser_logs) >= 2
    assert any("[PageError]" in log.message for log in report.browser_logs)
    assert any("ServiceNow GlideAjax" in log.message for log in report.browser_logs)

    # Verify canonical steps are present in step_evidence
    indices = [ev.get("step_index") for ev in report.step_evidence if isinstance(ev, dict)]
    assert 0 in indices
    assert 1 in indices
    assert 2 in indices


@pytest.mark.asyncio
async def test_canonical_event_publisher_protocol():
    """Event publisher emits canonical envelope with sequence and caches history."""
    from agent.events.publisher import RunEventPublisher
    from agent.core.types import RunEventType

    pub = RunEventPublisher(redis_url="redis://localhost:6379", run_id="run-test-123")
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.expire = AsyncMock()
    pub._redis = mock_redis

    e1 = await pub.publish(RunEventType.RUN_STARTED, {"goal": "Test goal"})
    assert e1["run_id"] == "run-test-123"
    assert e1["event_type"] == "run_started"
    assert e1["sequence"] == 1
    assert "timestamp" in e1
    assert e1["payload"]["goal"] == "Test goal"

    e2 = await pub.publish(RunEventType.STEP_STARTED, {"step_index": 0, "description": "Step 0"})
    assert e2["sequence"] == 2
    assert e2["event_type"] == "step_started"

    # Verify Redis list call for reconnect replay
    assert mock_redis.rpush.await_count == 2
    mock_redis.rpush.assert_any_await("run_events_history:run-test-123", json.dumps(e1))
    mock_redis.rpush.assert_any_await("run_events_history:run-test-123", json.dumps(e2))


@pytest.mark.asyncio
async def test_run_control_receiver_fail_closed_and_lowercase():
    """Approval defaults to fail-closed False on Redis failure; statuses are lowercase."""
    from agent.events.publisher import RunControlReceiver

    receiver = RunControlReceiver(redis_url="redis://invalid:9999", run_id="run-offline")
    # Redis unavailable
    receiver._get_redis = AsyncMock(return_value=None)

    # Status defaults to running lowercase
    status = await receiver.get_status()
    assert status == "running"

    # Approval must fail-closed (False), NEVER auto-approve
    approved = await receiver.request_approval("Drop database table", risk_score=10)
    assert approved is False

    # Clarification returns None on offline
    answer = await receiver.request_clarification("Provide username")
    assert answer is None


@pytest.mark.asyncio
async def test_clarification_and_approval_request_specific_keys():
    """Clarification and approval use request-specific and prompt-specific keys."""
    from agent.events.publisher import RunControlReceiver

    receiver = RunControlReceiver(redis_url="redis://localhost:6379", run_id="run-keys")
    mock_redis = AsyncMock()
    stored_keys = {}

    async def mock_set(k, v, ex=None):
        stored_keys[k] = v

    mock_redis.set = mock_set
    mock_redis.get = AsyncMock(return_value=None)
    receiver._redis = mock_redis

    # Call approval with short timeout
    approved = await receiver.request_approval("High risk update", risk_score=9, timeout=0.1)
    assert approved is False

    # Check key structure matches exact requirement
    approval_prompt_keys = [k for k in stored_keys if "approval:" in k and ":prompt" in k]
    assert len(approval_prompt_keys) == 1
    # Key shape: run_control:{run_id}:approval:{prompt_id}:prompt
    parts = approval_prompt_keys[0].split(":")
    assert parts[0] == "run_control"
    assert parts[1] == "run-keys"
    assert parts[2] == "approval"
    assert len(parts[3]) > 0
    assert parts[4] == "prompt"

