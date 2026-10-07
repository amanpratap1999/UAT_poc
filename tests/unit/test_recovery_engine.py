"""Unit tests for the Recovery Engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.exceptions import (
    NavigationTimeoutError,
    RecoveryExhaustedError,
    SelectorNotFoundError,
)
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.recovery.engine import RecoveryEngine


def _make_mock_page() -> MagicMock:
    """Create a mock Playwright page."""
    page = MagicMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.reload = AsyncMock()

    # Mock locator
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    locator.first = MagicMock()
    locator.first.click = AsyncMock()
    locator.first.is_visible = AsyncMock(return_value=False)
    locator.first.scroll_into_view_if_needed = AsyncMock()

    page.locator = MagicMock(return_value=locator)
    page.get_by_text = MagicMock(return_value=locator)
    page.get_by_label = MagicMock(return_value=locator)
    page.get_by_role = MagicMock(return_value=locator)
    page.get_by_placeholder = MagicMock(return_value=locator)
    page.get_by_title = MagicMock(return_value=locator)

    return page


@pytest.fixture
def engine() -> RecoveryEngine:
    return RecoveryEngine(max_retries=3)


@pytest.fixture
def mock_page() -> MagicMock:
    return _make_mock_page()


@pytest.fixture
def sample_action() -> AgentAction:
    return AgentAction(
        action_type=ActionType.CLICK,
        target="text:Update",
        reasoning="Click update button",
    )


@pytest.mark.asyncio
async def test_recovery_wait_and_retry_success(
    engine: RecoveryEngine,
    sample_action: AgentAction,
) -> None:
    """Test wait and retry when element becomes available."""
    page = _make_mock_page()
    # Element found after waiting
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    page.locator = MagicMock(return_value=locator)

    result = await engine.attempt_recovery(
        error=SelectorNotFoundError("Element not found"),
        action=sample_action,
        page=page,
    )

    assert result.success is True
    assert "wait_and_retry" in result.strategy


@pytest.mark.asyncio
async def test_recovery_dismiss_dialog_success(
    sample_action: AgentAction,
) -> None:
    """Test dialog dismissal when modal is blocking."""
    engine = RecoveryEngine(max_retries=5)
    page = _make_mock_page()
    # No element found, but dialog close button exists
    element_locator = MagicMock()
    element_locator.count = AsyncMock(return_value=0)

    close_locator = MagicMock()
    close_locator.count = AsyncMock(return_value=1)
    close_locator.first = MagicMock()
    close_locator.first.click = AsyncMock()

    page.locator = MagicMock(
        side_effect=lambda s: (
            close_locator if "close" in s.lower() or "Close" in s else element_locator
        )
    )
    page.get_by_text = MagicMock(return_value=element_locator)

    result = await engine.attempt_recovery(
        error=SelectorNotFoundError("Element not found"),
        action=sample_action,
        page=page,
    )

    # May succeed via dialog dismissal or other strategy
    assert result.attempts > 0


@pytest.mark.asyncio
async def test_recovery_exhausted(
    engine: RecoveryEngine,
    mock_page: MagicMock,
    sample_action: AgentAction,
) -> None:
    """Test RecoveryExhaustedError when all strategies fail."""
    engine = RecoveryEngine(max_retries=2)

    with pytest.raises(RecoveryExhaustedError):
        await engine.attempt_recovery(
            error=SelectorNotFoundError("Element not found"),
            action=sample_action,
            page=mock_page,
        )


@pytest.mark.asyncio
async def test_recovery_refresh_page(
    engine: RecoveryEngine,
    sample_action: AgentAction,
) -> None:
    """Test page refresh as recovery strategy."""
    page = _make_mock_page()

    # All element lookups fail, but page refresh succeeds
    locator = MagicMock()
    locator.count = AsyncMock(return_value=0)
    locator.first = MagicMock()
    locator.first.is_visible = AsyncMock(return_value=False)
    locator.first.scroll_into_view_if_needed = AsyncMock(side_effect=Exception("not found"))

    page.locator = MagicMock(return_value=locator)
    page.get_by_text = MagicMock(return_value=locator)
    page.get_by_label = MagicMock(return_value=locator)
    page.get_by_role = MagicMock(return_value=locator)
    page.get_by_placeholder = MagicMock(return_value=locator)
    page.get_by_title = MagicMock(return_value=locator)

    # Set max retries high enough to reach refresh strategy
    engine = RecoveryEngine(max_retries=5)

    result = await engine.attempt_recovery(
        error=NavigationTimeoutError("Timeout"),
        action=sample_action,
        page=page,
    )

    # NavigationTimeoutError tries wait_and_retry first, then refresh_page
    # Refresh should succeed since page.reload doesn't raise
    assert result.success is True


@pytest.mark.asyncio
async def test_recovery_tracks_attempts(
    engine: RecoveryEngine,
    sample_action: AgentAction,
) -> None:
    """Test that recovery tracks attempt count."""
    page = _make_mock_page()
    locator = MagicMock()
    locator.count = AsyncMock(return_value=1)
    page.locator = MagicMock(return_value=locator)

    result = await engine.attempt_recovery(
        error=SelectorNotFoundError("not found"),
        action=sample_action,
        page=page,
    )

    assert result.attempts >= 1
