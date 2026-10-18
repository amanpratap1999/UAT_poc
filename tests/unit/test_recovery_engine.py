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
    locator.first = MagicMock()
    locator.first.is_visible = AsyncMock(return_value=True)
    page.get_by_text = MagicMock(return_value=locator)

    result = await engine.attempt_recovery(
        error=SelectorNotFoundError("Element not found"),
        action=sample_action,
        page=page,
    )

    assert result.success is True
    assert "wait_and_retry" in result.strategy
    assert result.resolved_target == "text:Update"


@pytest.mark.asyncio
async def test_relocate_state_finds_css_fallback_in_gsft_main_frame(
    engine: RecoveryEngine,
) -> None:
    """Recovery must search the active ServiceNow frame and return its target."""
    def make_locator(count: int, visible: bool) -> MagicMock:
        locator = MagicMock()
        locator.count = AsyncMock(return_value=count)
        locator.first = MagicMock()
        locator.first.is_visible = AsyncMock(return_value=visible)
        return locator

    main_frame = MagicMock()
    main_frame.name = ""
    main_frame.url = "https://test.service-now.com/"
    active_frame = MagicMock()
    active_frame.name = "gsft_main"
    active_frame.url = "https://test.service-now.com/incident.do"

    missing_locator = make_locator(0, False)
    visible_state = make_locator(1, True)
    visible_caption = make_locator(1, True)
    # A static text caption exists, but SELECT recovery must still choose the
    # actual dropdown rather than reporting the caption as its target.
    active_frame.get_by_text.return_value = visible_caption
    for method_name in ("get_by_label", "get_by_role", "get_by_placeholder", "get_by_title"):
        getattr(active_frame, method_name).return_value = missing_locator

    def frame_locator(selector: str):
        if "select[id$='.state']" in selector:
            return visible_state
        return missing_locator

    active_frame.locator.side_effect = frame_locator
    page = MagicMock()
    page.frames = [main_frame, active_frame]
    page.main_frame = main_frame
    action = AgentAction(
        action_type=ActionType.SELECT,
        target="label:State",
        value="In Progress",
        reasoning="Select state",
    )

    result = await engine._relocate_element(action, page)

    assert result.success is True
    assert result.strategy == "relocate_element"
    assert result.resolved_target is not None
    assert result.resolved_target.startswith("css:")
    active_frame.get_by_text.assert_not_called()
    active_frame.locator.assert_called()
    main_frame.locator.assert_not_called()


@pytest.mark.asyncio
async def test_scroll_into_view_uses_active_service_now_frame(
    engine: RecoveryEngine,
) -> None:
    """Scroll recovery must inspect and return the locator from gsft_main."""
    missing_locator = MagicMock()
    missing_locator.count = AsyncMock(return_value=0)
    visible_locator = MagicMock()
    visible_locator.count = AsyncMock(return_value=1)
    visible_locator.first = MagicMock()
    visible_locator.first.is_visible = AsyncMock(return_value=True)
    visible_locator.first.scroll_into_view_if_needed = AsyncMock()

    main_frame = MagicMock()
    main_frame.name = ""
    main_frame.url = "https://test.service-now.com/"
    active_frame = MagicMock()
    active_frame.name = "gsft_main"
    active_frame.url = "https://test.service-now.com/incident.do"
    for method_name in ("get_by_label", "get_by_role", "get_by_placeholder", "get_by_title"):
        getattr(active_frame, method_name).return_value = missing_locator

    def frame_locator(selector: str):
        if "select[id$='.state']" in selector:
            return visible_locator
        return missing_locator

    active_frame.locator.side_effect = frame_locator

    page = MagicMock()
    page.frames = [main_frame, active_frame]
    page.main_frame = main_frame
    action = AgentAction(
        action_type=ActionType.SELECT,
        target="label:State",
        value="In Progress",
        reasoning="Select incident state",
    )

    result = await engine._scroll_into_view(action, page)

    assert result.success is True
    assert result.resolved_target is not None
    assert result.resolved_target.startswith("css:")
    active_frame.locator.assert_called()
    main_frame.locator.assert_not_called()
    visible_locator.first.scroll_into_view_if_needed.assert_awaited_once_with(timeout=5000)


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
