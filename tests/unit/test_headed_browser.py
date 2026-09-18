"""Unit tests for headed browser mode, visual cursor indicator, and persistence."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent.browser.manager import VISUAL_CURSOR_SCRIPT, BrowserManager, reset_browser_globals
from agent.browser.page_interactor import PageInteractor
from agent.core.config import BrowserConfig, ServiceNowConfig, Settings
from agent.core.exceptions import BrowserLaunchError
from agent.main import AgentOrchestrator, app


def test_headed_browser_config_defaults() -> None:
    """Verify BrowserConfig defaults to headed mode with visual cursor."""
    cfg = BrowserConfig.model_construct(
        headless=False,
        slow_mo=0,
        show_mouse_cursor=True,
        keep_browser_open=False,
    )
    assert cfg.headless is False
    assert cfg.show_mouse_cursor is True
    assert cfg.keep_browser_open is False


def test_headed_browser_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment variables override BrowserConfig settings."""
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    monkeypatch.setenv("BROWSER_SLOW_MO", "250")
    monkeypatch.setenv("BROWSER_SHOW_MOUSE_CURSOR", "true")
    monkeypatch.setenv("BROWSER_KEEP_BROWSER_OPEN", "true")

    cfg = BrowserConfig(_env_file=None)
    assert cfg.headless is False
    assert cfg.slow_mo == 250
    assert cfg.show_mouse_cursor is True
    assert cfg.keep_browser_open is True


@pytest.mark.asyncio
async def test_browser_manager_passes_headed_params_to_playwright() -> None:
    """Test that BrowserManager passes headless=False and slow_mo to Chromium."""
    browser_cfg = BrowserConfig.model_construct(
        headless=False,
        slow_mo=250,
        show_mouse_cursor=True,
    )
    sn_cfg = ServiceNowConfig.model_construct()

    mock_playwright = AsyncMock()
    mock_chromium = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = MagicMock()
    mock_page.set_default_timeout = MagicMock()
    mock_page.on = MagicMock()
    mock_page.evaluate = AsyncMock()

    mock_playwright.chromium = mock_chromium
    mock_chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    with patch("agent.browser.manager.async_playwright") as mock_pw_start:
        mock_pw_builder = MagicMock()
        mock_pw_builder.start = AsyncMock(return_value=mock_playwright)
        mock_pw_start.return_value = mock_pw_builder

        manager = BrowserManager(browser_config=browser_cfg, servicenow_config=sn_cfg)
        await manager.launch()

        mock_chromium.launch.assert_awaited_once_with(
            headless=False,
            slow_mo=250,
            args=[
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        mock_context.add_init_script.assert_awaited_once_with(VISUAL_CURSOR_SCRIPT)
        assert manager.get_page() == mock_page


@pytest.mark.asyncio
async def test_browser_manager_persistent_context_headed_params() -> None:
    """Test that persistent context launch receives headless=False and slow_mo."""
    browser_cfg = BrowserConfig.model_construct(
        headless=False,
        slow_mo=250,
        show_mouse_cursor=True,
        user_data_dir="test_profile_dir",
    )
    sn_cfg = ServiceNowConfig.model_construct()

    mock_playwright = AsyncMock()
    mock_chromium = AsyncMock()
    mock_context = AsyncMock()
    mock_page = MagicMock()
    mock_page.set_default_timeout = MagicMock()
    mock_page.on = MagicMock()
    mock_page.evaluate = AsyncMock()

    mock_playwright.chromium = mock_chromium
    mock_context.pages = [mock_page]
    mock_chromium.launch_persistent_context.return_value = mock_context

    with patch("agent.browser.manager.async_playwright") as mock_pw_start:
        mock_pw_builder = MagicMock()
        mock_pw_builder.start = AsyncMock(return_value=mock_playwright)
        mock_pw_start.return_value = mock_pw_builder

        manager = BrowserManager(browser_config=browser_cfg, servicenow_config=sn_cfg)
        await manager.launch()

        assert mock_chromium.launch_persistent_context.await_count == 1
        call_kwargs = mock_chromium.launch_persistent_context.await_args[1]
        assert call_kwargs["headless"] is False
        assert call_kwargs["slow_mo"] == 250
        mock_context.add_init_script.assert_awaited_once_with(VISUAL_CURSOR_SCRIPT)


@pytest.mark.asyncio
async def test_browser_manager_display_error_on_headless_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that headed mode on Linux without DISPLAY raises clear BrowserLaunchError."""
    browser_cfg = BrowserConfig.model_construct(headless=False)
    sn_cfg = ServiceNowConfig.model_construct()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    manager = BrowserManager(browser_config=browser_cfg, servicenow_config=sn_cfg)
    with pytest.raises(BrowserLaunchError) as exc_info:
        await manager.launch()

    assert "no graphical display server found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_browser_manager_take_screenshot_hides_cursor(tmp_path: Path) -> None:
    """Test that take_screenshot temporarily hides the visual cursor."""
    browser_cfg = BrowserConfig.model_construct(headless=True, show_mouse_cursor=True)
    sn_cfg = ServiceNowConfig.model_construct()

    mock_page = MagicMock()
    mock_page.screenshot = AsyncMock()
    mock_page.evaluate = AsyncMock()

    manager = BrowserManager(
        browser_config=browser_cfg,
        servicenow_config=sn_cfg,
        screenshot_dir=tmp_path / "screenshots",
    )
    manager._page = mock_page

    await manager.take_screenshot("test_screen")

    assert mock_page.screenshot.await_count == 1
    eval_calls = [str(call[0][0]) for call in mock_page.evaluate.await_args_list]
    assert any("pw-cursor-hidden" in call for call in eval_calls)


@pytest.mark.asyncio
async def test_page_interactor_moves_mouse_before_actions() -> None:
    """Test that PageInteractor moves the mouse with steps before click, fill, select."""
    mock_page = MagicMock()
    mock_mouse = AsyncMock()
    mock_keyboard = AsyncMock()
    mock_page.mouse = mock_mouse
    mock_page.keyboard = mock_keyboard
    mock_page.frames = []

    mock_locator = MagicMock()
    mock_locator.bounding_box = AsyncMock(
        return_value={
            "x": 100,
            "y": 200,
            "width": 80,
            "height": 40,
        }
    )
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.first = mock_locator
    mock_locator.nth = MagicMock(return_value=mock_locator)
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_locator.select_option = AsyncMock()
    mock_locator.wait_for = AsyncMock()

    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.get_by_role = MagicMock(return_value=mock_locator)
    mock_page.get_by_label = MagicMock(return_value=mock_locator)
    mock_page.get_by_text = MagicMock(return_value=mock_locator)
    mock_page.get_by_title = MagicMock(return_value=mock_locator)
    mock_page.get_by_placeholder = MagicMock(return_value=mock_locator)

    interactor = PageInteractor(mock_page)

    # 1. Click
    await interactor.click("#btn-submit")
    mock_mouse.move.assert_awaited_with(140.0, 220.0, steps=5)
    mock_locator.click.assert_awaited_once()

    # 2. Click coordinate
    mock_mouse.reset_mock()
    await interactor.click_coordinate(300, 400)
    mock_mouse.move.assert_awaited_with(300, 400, steps=5)
    mock_mouse.click.assert_awaited_with(300, 400)

    # 3. Fill
    mock_mouse.reset_mock()
    await interactor.fill("#input-user", "test_user")
    mock_mouse.move.assert_awaited_with(140.0, 220.0, steps=5)
    mock_locator.fill.assert_awaited_once_with("test_user", timeout=10000)

    # 4. Fill coordinate
    mock_mouse.reset_mock()
    await interactor.fill_coordinate(50, 60, "val")
    mock_mouse.move.assert_awaited_with(50, 60, steps=5)
    mock_mouse.click.assert_awaited_with(50, 60)


@pytest.mark.asyncio
async def test_orchestrator_browser_persistence_behavior() -> None:
    """Test that keep_browser_open=True preserves the browser only when headed."""
    # Case 1: Headed + keep_browser_open=True -> DO NOT close browser
    settings_headed_persist = Settings(
        browser=BrowserConfig.model_construct(headless=False, keep_browser_open=True)
    )
    mock_bm_persist = AsyncMock()
    mock_bm_persist.get_console_logs.return_value = []
    mock_bm_persist.get_new_console_errors.return_value = []
    mock_bm_persist.get_network_errors.return_value = []
    mock_page = MagicMock()
    mock_page.locator.return_value.count = AsyncMock(return_value=0)
    mock_bm_persist.get_page.return_value = mock_page
    mock_planner = AsyncMock()
    mock_planner.create_plan.return_value = MagicMock(steps=[])
    mock_reporting = AsyncMock()
    mock_reporting.generate_report.return_value = MagicMock(status="passed")
    mock_reporting.save_report.return_value = "report.md"

    orchestrator1 = AgentOrchestrator(
        settings=settings_headed_persist,
        planner=mock_planner,
        browser_manager=mock_bm_persist,
        observation_engine=AsyncMock(),
        validation_engine=AsyncMock(),
        recovery_engine=AsyncMock(),
        reporting_engine=mock_reporting,
        knowledge_store=AsyncMock(),
        session_store=AsyncMock(),
        learning_service=AsyncMock(),
    )
    orchestrator1._cognitive_orchestrator = AsyncMock()
    await orchestrator1.run("Test Goal")
    mock_bm_persist.close.assert_not_awaited()

    # Case 2: Headless + keep_browser_open=True -> MUST close browser
    settings_headless = Settings(
        browser=BrowserConfig.model_construct(headless=True, keep_browser_open=True)
    )
    mock_bm_headless = AsyncMock()
    mock_bm_headless.get_console_logs.return_value = []
    mock_bm_headless.get_new_console_errors.return_value = []
    mock_bm_headless.get_network_errors.return_value = []
    mock_bm_headless.get_page.return_value = mock_page
    orchestrator2 = AgentOrchestrator(
        settings=settings_headless,
        planner=mock_planner,
        browser_manager=mock_bm_headless,
        observation_engine=AsyncMock(),
        validation_engine=AsyncMock(),
        recovery_engine=AsyncMock(),
        reporting_engine=mock_reporting,
        knowledge_store=AsyncMock(),
        session_store=AsyncMock(),
        learning_service=AsyncMock(),
    )
    orchestrator2._cognitive_orchestrator = AsyncMock()
    await orchestrator2.run("Test Goal")
    mock_bm_headless.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cors_headers_on_api() -> None:
    """Verify CORS preflight OPTIONS request returns 200 and required CORS headers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/api/v1/screenshots/sample.png",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173")


@pytest.fixture(autouse=True)
def reset_globals_fixture():
    reset_browser_globals()
