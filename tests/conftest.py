"""Shared test fixtures and mock factories."""

from __future__ import annotations

from typing import Any

import pytest

from agent.core.config import (
    AgentConfig,
    BrowserConfig,
    LLMConfig,
    ServiceNowConfig,
    Settings,
)
from agent.core.types import ActionType, PageType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.observation import (
    ButtonInfo,
    FieldInfo,
    PageObservation,
)
from agent.domain.plan import ExecutionPlan
from agent.memory.session import SessionMemory
from agent.planner.llm_client import BaseLLMClient

# ---------------------------------------------------------------------------
# Configuration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings() -> Settings:
    """Settings configured for testing."""
    return Settings(
        llm=LLMConfig(provider="openai", api_key="test-key", model="gpt-4o-mini"),
        servicenow=ServiceNowConfig(
            instance_url="https://test.service-now.com",
            username="admin",
            password="test",
        ),
        browser=BrowserConfig(headless=True, keep_browser_open=False),
        agent=AgentConfig(max_steps=10, max_retries=2, observation_window=5),
        log_level="DEBUG",
    )


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient(BaseLLMClient):
    """Mock LLM client that returns pre-configured responses."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self._responses = responses or []
        self._call_count = 0
        self._messages_history: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self._messages_history.append(messages)
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = {"content": "No more mock responses configured."}
        self._call_count += 1
        return response

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self._messages_history.append(messages)
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = {}
        self._call_count += 1
        return response


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """A mock LLM client with no pre-configured responses."""
    return MockLLMClient()


# ---------------------------------------------------------------------------
# Observation fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_observation() -> PageObservation:
    """A sample page observation for an incident form."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc123",
        title="Incident | INC0010001",
        page_type=PageType.FORM,
        current_state="New",
        record_number="INC0010001",
        visible_fields=[
            FieldInfo(
                name="Short Description",
                field_type="text",
                value="Test incident",
                is_mandatory=True,
            ),
            FieldInfo(
                name="Caller",
                field_type="reference",
                value="Abel Tuter",
                is_mandatory=True,
            ),
            FieldInfo(
                name="Assignment Group",
                field_type="reference",
                value="",
                is_mandatory=False,
            ),
            FieldInfo(
                name="Priority",
                field_type="select",
                value="4 - Low",
                is_readonly=True,
            ),
        ],
        mandatory_fields=["Short Description", "Caller"],
        buttons=[
            ButtonInfo(label="Update", is_enabled=True),
            ButtonInfo(label="Save", is_enabled=True),
            ButtonInfo(label="Delete", is_enabled=True),
            ButtonInfo(label="Resolve Incident", is_enabled=True),
        ],
        validation_messages=[],
    )


@pytest.fixture
def sample_observation_with_errors() -> PageObservation:
    """A sample observation with validation errors."""
    return PageObservation(
        url="https://test.service-now.com/incident.do?sys_id=abc123",
        title="Incident | INC0010001",
        page_type=PageType.FORM,
        current_state="New",
        record_number="INC0010001",
        visible_fields=[
            FieldInfo(
                name="Short Description",
                field_type="text",
                value="",
                is_mandatory=True,
            ),
        ],
        mandatory_fields=["Short Description"],
        buttons=[ButtonInfo(label="Update", is_enabled=True)],
        validation_messages=["Short Description is required"],
    )


@pytest.fixture
def login_page_observation() -> PageObservation:
    """A sample login page observation."""
    return PageObservation(
        url="https://test.service-now.com/login.do",
        title="ServiceNow - Login",
        page_type=PageType.LOGIN,
        visible_fields=[
            FieldInfo(name="User name", field_type="text", value=""),
            FieldInfo(name="Password", field_type="password", value=""),
        ],
        buttons=[ButtonInfo(label="Log in", is_enabled=True)],
    )


# ---------------------------------------------------------------------------
# Action fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_click_action() -> AgentAction:
    """A sample click action."""
    return AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click the Update button to save changes",
    )


@pytest.fixture
def sample_fill_action() -> AgentAction:
    """A sample fill action."""
    return AgentAction(
        action_type=ActionType.FILL,
        target="label:Short Description",
        value="Network outage in building A",
        reasoning="Fill in the short description field",
        metadata={"field_label": "Short Description"},
    )


# ---------------------------------------------------------------------------
# Session memory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_memory() -> SessionMemory:
    """A session memory with some history."""
    memory = SessionMemory(goal="Test incident creation")
    memory.plan = ExecutionPlan(goal="Test incident creation")
    memory.plan.add_step("Navigate to incident form", "Form is displayed")
    memory.plan.add_step("Fill required fields", "Fields are populated")
    memory.plan.add_step("Submit the form", "Incident is created")
    return memory


# ---------------------------------------------------------------------------
# Action result fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def success_result(sample_click_action: AgentAction) -> ActionResult:
    """A successful action result."""
    return ActionResult(
        success=True,
        action=sample_click_action,
        duration_ms=150.0,
        screenshot_path="screenshots/action_click_123.png",
    )


@pytest.fixture
def failure_result(sample_click_action: AgentAction) -> ActionResult:
    """A failed action result."""
    return ActionResult(
        success=False,
        action=sample_click_action,
        duration_ms=5000.0,
        error="Element not found: text:Update",
        error_type="SelectorNotFoundError",
    )
