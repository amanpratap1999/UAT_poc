"""Integration test: BrowserManager global-state lifecycle.

Audit issue I46 (P2): verifies that the module-level globals
(_GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER, _GLOBAL_CONTEXT) in
src/agent/browser/manager.py are reusable across multiple
BrowserManager instances in the same process. Previously a crashed
Chromium process was never recreated (the comment at line 228 said
'Do NOT close _GLOBAL_BROWSER or _GLOBAL_PLAYWRIGHT to keep them warm'),
so all subsequent runs reused a dead Browser handle and failed with
TargetClosedError.

This test is skipped when Playwright is not installed or when no
graphical display server is available (for headed mode). Run with:
    pytest tests/integration/test_browser_lifecycle.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agent.core.config import BrowserConfig, ServiceNowConfig


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _playwright_available(),
    reason="playwright not installed (run: pip install playwright && playwright install chromium)",
)
@pytest.mark.skipif(
    sys.platform == "linux" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="no graphical display server (DISPLAY/WAYLAND_DISPLAY) for headed browser test",
)
@pytest.mark.asyncio
async def test_browser_globals_reusable_across_instances(tmp_path: Path) -> None:
    """Launch two BrowserManager instances and verify they share globals."""
    from agent.browser.manager import (
        BrowserManager,
        _GLOBAL_BROWSER,
        _GLOBAL_PLAYWRIGHT,
        reset_browser_globals,
    )

    # Start clean
    reset_browser_globals()

    config = BrowserConfig(
        headless=True,  # headless works without DISPLAY
        keep_browser_open=False,
        viewport_width=1280,
        viewport_height=720,
    )
    sn_config = ServiceNowConfig(
        instance_url="https://test.service-now.com",
        username="admin",
        password="test",
        is_subproduction=True,
        allow_mutations=True,
        allowed_instances=["test.service-now.com"],
    )

    bm1 = BrowserManager(config, sn_config, screenshot_dir=tmp_path / "screens1")
    await bm1.launch()
    page1 = bm1.get_page()
    assert page1 is not None, "first BrowserManager launch should produce a page"
    browser1_id = id(_GLOBAL_BROWSER)

    # Launch a second BrowserManager in the same process — should reuse globals
    bm2 = BrowserManager(config, sn_config, screenshot_dir=tmp_path / "screens2")
    await bm2.launch()
    page2 = bm2.get_page()
    assert page2 is not None, "second BrowserManager launch should produce a page"

    # Verify globals are the SAME object (reused, not recreated)
    assert _GLOBAL_BROWSER is not None
    assert _GLOBAL_PLAYWRIGHT is not None
    assert id(_GLOBAL_BROWSER) == browser1_id, (
        "second BrowserManager should reuse the same _GLOBAL_BROWSER — "
        "if this fails, the warm-keep-alive logic is broken"
    )

    await bm1.close()
    await bm2.close()
    reset_browser_globals()


@pytest.mark.skipif(
    not _playwright_available(),
    reason="playwright not installed",
)
@pytest.mark.asyncio
async def test_health_check_resets_dead_browser(tmp_path: Path) -> None:
    """Simulate a dead browser (is_connected returns False) and verify
    _health_check_globals() resets the globals so the next launch recreates them.
    """
    from agent.browser.manager import (
        BrowserManager,
        _GLOBAL_BROWSER,
        _health_check_globals,
        reset_browser_globals,
    )
    from unittest.mock import AsyncMock, MagicMock

    # Simulate a stale _GLOBAL_BROWSER whose is_connected() returns False
    reset_browser_globals()
    # Inject a mock that simulates a dead browser
    import agent.browser.manager as bm_module
    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = False
    mock_browser.close = AsyncMock()
    bm_module._GLOBAL_BROWSER = mock_browser
    bm_module._GLOBAL_PLAYWRIGHT = MagicMock()
    bm_module._GLOBAL_PLAYWRIGHT.stop = AsyncMock()

    # Run health check — should detect dead browser and reset globals
    result = await _health_check_globals()
    assert result is True, "health check should report reset-after-stale"

    # Globals should be None after reset
    assert bm_module._GLOBAL_BROWSER is None
    assert bm_module._GLOBAL_PLAYWRIGHT is None
    assert bm_module._GLOBAL_CONTEXT is None

    reset_browser_globals()
