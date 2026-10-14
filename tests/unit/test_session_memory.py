"""Unit tests for Session Memory."""

from __future__ import annotations

from agent.core.types import ActionType, AgentState
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import PageObservation
from agent.domain.plan import ExecutionPlan
from agent.memory.session import SessionMemory


def test_session_memory_defaults() -> None:
    """Test default session memory initialization."""
    memory = SessionMemory(goal="Test goal")

    assert memory.goal == "Test goal"
    assert memory.state == AgentState.IDLE
    assert memory.current_step_index == 0
    assert memory.total_actions_executed == 0
    assert memory.session_id != ""
    assert memory.plan is None
    assert memory.current_record is None


def test_add_observation(sample_observation: PageObservation) -> None:
    """Test adding observations with rolling window."""
    memory = SessionMemory(goal="Test", observation_window=3)

    # Add 5 observations
    for i in range(5):
        obs = sample_observation.model_copy()
        obs.url = f"https://test.service-now.com/page{i}"
        memory.add_observation(obs)

    # Only last 3 should remain
    assert len(memory.observations) == 3
    assert memory.observations[0].url.endswith("page2")
    assert memory.observations[-1].url.endswith("page4")


def test_add_observation_tracks_incident(sample_observation: PageObservation) -> None:
    """Test that observations update incident tracking."""
    memory = SessionMemory(goal="Test")

    memory.add_observation(sample_observation)

    assert memory.current_record is not None
    assert memory.current_record["number"] == "INC0010001"
    assert memory.current_record["state"] == "New"


def test_add_completed_step() -> None:
    """Test recording completed steps."""
    memory = SessionMemory(goal="Test")

    action = AgentAction(
        action_type=ActionType.CLICK,
        target="button",
        reasoning="Click it",
    )
    result = ActionResult(success=True, action=action, duration_ms=100)

    memory.add_completed_step(action=action, result=result)

    assert len(memory.completed_steps) == 1
    assert memory.total_actions_executed == 1
    assert memory.current_step_index == 1


def test_add_failure() -> None:
    """Test recording failures."""
    memory = SessionMemory(goal="Test")

    memory.add_failure(
        error_type="SelectorNotFoundError",
        error_message="Element not found: button",
    )

    assert len(memory.failures) == 1
    assert memory.total_failures == 1
    assert memory.failures[0].error_type == "SelectorNotFoundError"


def test_add_recovery_attempt() -> None:
    """Test recording recovery attempts."""
    memory = SessionMemory(goal="Test")

    memory.add_recovery_attempt(
        strategy="wait_and_retry",
        original_error="Element not found",
        success=True,
        details="Found after waiting",
    )

    assert len(memory.recovery_attempts) == 1
    assert memory.total_recoveries == 1
    assert memory.recovery_attempts[0].success is True


def test_add_timeline_entry() -> None:
    """Test adding timeline entries."""
    memory = SessionMemory(goal="Test")

    memory.add_timeline_entry(
        action="Click Update",
        result="success",
        duration_ms=150.0,
        screenshot_path="screenshots/test.png",
    )

    assert len(memory.timeline) == 1
    assert memory.timeline[0].action == "Click Update"


def test_latest_observation(sample_observation: PageObservation) -> None:
    """Test getting the latest observation."""
    memory = SessionMemory(goal="Test")

    assert memory.latest_observation is None

    memory.add_observation(sample_observation)
    assert memory.latest_observation is not None
    assert memory.latest_observation.url == sample_observation.url


def test_get_context_for_llm() -> None:
    """Test LLM context serialization."""
    memory = SessionMemory(goal="Test incident creation")
    memory.plan = ExecutionPlan(goal="Test incident creation")
    memory.plan.add_step("Step 1", "Expected 1")

    context = memory.get_context_for_llm()

    assert "Test incident creation" in context
    assert "Goal" in context
    assert "Stats" in context


def test_get_summary() -> None:
    """Test machine-readable summary."""
    memory = SessionMemory(goal="Test goal")
    memory.state = AgentState.EXECUTING

    summary = memory.get_summary()

    assert summary["goal"] == "Test goal"
    assert summary["state"] == "executing"
    assert summary["total_actions"] == 0


def test_recent_failures() -> None:
    """Test that recent_failures filters by step proximity."""
    memory = SessionMemory(goal="Test")
    memory.current_step_index = 10

    # Add a failure at step 3 (old)
    memory.failures.append(
        __import__("agent.memory.session", fromlist=["FailureRecord"]).FailureRecord(
            step_index=3,
            error_type="old",
            error_message="old failure",
        )
    )
    # Add a failure at step 8 (recent)
    memory.failures.append(
        __import__("agent.memory.session", fromlist=["FailureRecord"]).FailureRecord(
            step_index=8,
            error_type="recent",
            error_message="recent failure",
        )
    )

    recent = memory.recent_failures
    assert len(recent) == 1
    assert recent[0].error_type == "recent"
