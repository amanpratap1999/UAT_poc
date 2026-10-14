"""Unit tests for the Planner."""

from __future__ import annotations

import pytest

from agent.core.types import ActionType
from agent.domain.observation import PageObservation
from agent.domain.plan import ExecutionPlan
from agent.memory.session import SessionMemory
from agent.planner.planner import Planner
from tests.conftest import MockLLMClient


@pytest.fixture
def planner_with_plan_response() -> Planner:
    """Planner with mock LLM configured to return a plan."""
    client = MockLLMClient(
        responses=[
            {
                "steps": [
                    {
                        "description": "Navigate to incident form",
                        "expected_outcome": "Incident form is displayed",
                    },
                    {
                        "description": "Fill Short Description",
                        "expected_outcome": "Field is populated",
                    },
                    {
                        "description": "Click Submit",
                        "expected_outcome": "Incident is created",
                    },
                ]
            }
        ]
    )
    return Planner(llm_client=client)


@pytest.fixture
def planner_with_action_response() -> Planner:
    """Planner with mock LLM configured to return an action."""
    client = MockLLMClient(
        responses=[
            {
                "action_type": "fill",
                "target": "label:Short Description",
                "value": "Network outage",
                "reasoning": "Need to fill the short description field",
                "field_label": "Short Description",
            }
        ]
    )
    return Planner(llm_client=client)


@pytest.fixture
def planner_with_completion_response() -> Planner:
    """Planner configured to report goal complete."""
    client = MockLLMClient(
        responses=[
            {
                "is_complete": True,
                "reasoning": "All test steps have been executed successfully",
                "summary": "Incident lifecycle tested successfully",
            }
        ]
    )
    return Planner(llm_client=client)


@pytest.mark.asyncio
async def test_create_plan(planner_with_plan_response: Planner) -> None:
    """Test that planner creates an execution plan from a goal."""
    plan = await planner_with_plan_response.create_plan(goal="Test incident creation")

    assert isinstance(plan, ExecutionPlan)
    assert plan.goal == "Test incident creation"
    assert len(plan.steps) == 3
    assert plan.steps[0].description == "Navigate to incident form"
    assert plan.steps[1].description == "Fill Short Description"
    assert plan.steps[2].description == "Click Submit"


@pytest.mark.asyncio
async def test_decide_next_action(
    planner_with_action_response: Planner,
    sample_observation: PageObservation,
    sample_memory: SessionMemory,
) -> None:
    """Test that planner decides a valid next action."""
    action = await planner_with_action_response.decide_next_action(
        observation=sample_observation,
        memory=sample_memory,
    )

    assert action.action_type == ActionType.FILL
    assert action.target == "label:Short Description"
    assert action.value == "Network outage"
    assert action.reasoning != ""


@pytest.mark.asyncio
async def test_is_goal_complete(
    planner_with_completion_response: Planner,
    sample_memory: SessionMemory,
) -> None:
    """Test goal completion check."""
    is_complete = await planner_with_completion_response.is_goal_complete(memory=sample_memory)
    assert is_complete is True


@pytest.mark.asyncio
async def test_planner_sends_system_prompt() -> None:
    """Test that planner includes system prompt in LLM messages."""
    client = MockLLMClient(
        responses=[{"steps": [{"description": "Step 1", "expected_outcome": "Done"}]}]
    )
    planner = Planner(llm_client=client)

    await planner.create_plan("Test goal")

    # Check that messages were sent with system prompt
    assert len(client._messages_history) == 1
    messages = client._messages_history[0]
    assert messages[0]["role"] == "system"
    assert "autonomous QA testing agent" in messages[0]["content"]


@pytest.mark.asyncio
async def test_plan_with_knowledge_context() -> None:
    """Test that knowledge context is passed to the plan prompt."""
    client = MockLLMClient(
        responses=[{"steps": [{"description": "Step 1", "expected_outcome": "Done"}]}]
    )
    planner = Planner(llm_client=client, knowledge_context="Incident states: New, In Progress")

    await planner.create_plan("Test incident lifecycle")

    messages = client._messages_history[0]
    user_message = messages[1]["content"]
    assert "Incident states" in user_message
