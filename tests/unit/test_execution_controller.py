"""Unit tests for the Execution Controller."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.browser.manager import BrowserManager
from agent.browser.page_interactor import PageInteractor
from agent.core.exceptions import SelectorNotFoundError
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.execution.controller import ExecutionController
from agent.recovery.engine import RecoveryEngine, RecoveryResult


@pytest.fixture
def mock_browser_manager() -> MagicMock:
    """Mock browser manager."""
    manager = MagicMock(spec=BrowserManager)
    manager.take_screenshot = AsyncMock(return_value="screenshots/test.png")
    manager.navigate = AsyncMock()
    manager.wait_for_load = AsyncMock()
    manager.wait_for_network_idle = AsyncMock()
    manager.get_page = MagicMock()
    manager.get_page_errors = MagicMock(return_value=[])
    return manager


@pytest.fixture
def mock_page_interactor() -> MagicMock:
    """Mock page interactor."""
    interactor = MagicMock(spec=PageInteractor)
    interactor.click = AsyncMock()
    interactor.fill = AsyncMock()
    interactor.select_option = AsyncMock()
    interactor.press_key = AsyncMock()
    interactor.scroll = AsyncMock()
    interactor.wait_for_element = AsyncMock(return_value=True)
    return interactor


@pytest.fixture
def mock_recovery_engine() -> MagicMock:
    """Mock recovery engine."""
    engine = MagicMock(spec=RecoveryEngine)
    engine.attempt_recovery = AsyncMock()
    return engine


@pytest.fixture
def controller(
    mock_browser_manager: MagicMock,
    mock_page_interactor: MagicMock,
    mock_recovery_engine: MagicMock,
) -> ExecutionController:
    """Execution controller with all mocks."""
    return ExecutionController(
        browser_manager=mock_browser_manager,
        page_interactor=mock_page_interactor,
        recovery_engine=mock_recovery_engine,
    )


@pytest.mark.asyncio
async def test_execute_click(
    controller: ExecutionController,
    mock_page_interactor: MagicMock,
) -> None:
    """Test successful click execution."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click update",
    )

    result = await controller.execute(action)

    assert result.success is True
    assert result.duration_ms > 0
    mock_page_interactor.click.assert_called_once_with("text:Update")


@pytest.mark.asyncio
async def test_execute_fill(
    controller: ExecutionController,
    mock_page_interactor: MagicMock,
) -> None:
    """Test successful fill execution."""
    action = AgentAction(
        action_type=ActionType.FILL,
        target="label:Short Description",
        value="Test incident",
        reasoning="Fill description",
        metadata={"field_label": "Short Description"},
    )

    result = await controller.execute(action)

    assert result.success is True
    mock_page_interactor.fill.assert_called_once_with(
        "Short Description", "Test incident"
    )


@pytest.mark.asyncio
async def test_execute_navigate(
    controller: ExecutionController,
    mock_browser_manager: MagicMock,
) -> None:
    """Test successful navigation execution."""
    action = AgentAction(
        action_type=ActionType.NAVIGATE,
        target="",
        value="https://test.service-now.com/incident.do",
        reasoning="Navigate to incident form",
        metadata={"url": "https://test.service-now.com/incident.do"},
    )

    result = await controller.execute(action)

    assert result.success is True
    mock_browser_manager.navigate.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_failure_and_recovery(
    controller: ExecutionController,
    mock_page_interactor: MagicMock,
    mock_recovery_engine: MagicMock,
) -> None:
    """Test that failed actions trigger recovery."""
    mock_page_interactor.click.side_effect = SelectorNotFoundError(
        "Element not found"
    )
    mock_recovery_engine.attempt_recovery.return_value = RecoveryResult(
        success=True,
        strategy="wait_and_retry",
        details="Found after waiting",
    )

    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click update",
    )

    result = await controller.execute(action)

    assert result.success is True
    assert result.details.get("recovered") is True
    mock_recovery_engine.attempt_recovery.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_failure_no_recovery(
    controller: ExecutionController,
    mock_page_interactor: MagicMock,
    mock_recovery_engine: MagicMock,
) -> None:
    """Test failed action when recovery also fails."""
    mock_page_interactor.click.side_effect = SelectorNotFoundError(
        "Element not found"
    )
    mock_recovery_engine.attempt_recovery.side_effect = Exception("Recovery failed")

    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click update",
    )

    result = await controller.execute(action)

    assert result.success is False
    assert result.error is not None
    assert result.error_type == "SelectorNotFoundError"


@pytest.mark.asyncio
async def test_execute_unknown_action(controller: ExecutionController) -> None:
    """Test handling of unknown action types."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="test",
        reasoning="test",
    )
    # Intentionally bypass type check for negative test case
    object.__setattr__(action, "action_type", "unknown_type")

    result = await controller.execute(action)

    assert result.success is False
    assert "Unknown action type" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_screenshot_capture(
    controller: ExecutionController,
    mock_browser_manager: MagicMock,
) -> None:
    """Test that screenshots are captured on success."""
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="button",
        reasoning="test",
    )

    result = await controller.execute(action)

    assert result.screenshot_path is not None
    mock_browser_manager.take_screenshot.assert_called()
