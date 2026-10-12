"""Regression test for bounded browser screenshot waits."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.browser.manager import BrowserManager
from agent.core.config import BrowserConfig, ServiceNowConfig


class _FakePage:
    def __init__(self) -> None:
        self.screenshot_kwargs: dict = {}

    async def evaluate(self, *_args, **_kwargs) -> None:
        return None

    async def screenshot(self, **kwargs):
        self.screenshot_kwargs = kwargs
        Path(kwargs["path"]).write_bytes(b"png")
        return None


@pytest.mark.asyncio
async def test_take_screenshot_uses_bounded_timeout(tmp_path: Path) -> None:
    page = _FakePage()
    manager = BrowserManager(
        browser_config=BrowserConfig(timeout=240000),
        servicenow_config=ServiceNowConfig(),
        screenshot_dir=tmp_path,
    )
    manager._page = page  # test-only injection

    result = await manager.take_screenshot("bounded")

    assert Path(result).is_file()
    assert 1000 <= page.screenshot_kwargs["timeout"] <= 8000
    assert page.screenshot_kwargs["full_page"] is False


class _RecoverablePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed

    def set_default_timeout(self, _timeout: int) -> None:
        return None

    def on(self, *_args, **_kwargs) -> None:
        return None

    @property
    def main_frame(self):
        return self

    async def close(self) -> None:
        self._closed = True


@pytest.mark.asyncio
async def test_page_crash_recovery_recreates_page_in_same_context(monkeypatch) -> None:
    import agent.browser.manager as browser_module

    manager = BrowserManager(
        browser_config=BrowserConfig(timeout=240000, headless=True),
        servicenow_config=ServiceNowConfig(),
    )
    old_page = _RecoverablePage("https://instance.service-now.com/incident.do?sys_id=abc")
    new_page = _RecoverablePage(old_page.url)

    class _Context:
        async def new_page(self):
            return new_page

    manager._context = _Context()  # type: ignore[assignment]
    monkeypatch.setattr(
        browser_module,
        "_GLOBAL_BROWSER",
        SimpleNamespace(is_connected=lambda: True),
    )
    manager._page = old_page
    manager._page_crashed = True
    manager._last_known_url = old_page.url
    manager._prepare_page = AsyncMock(side_effect=lambda page: setattr(manager, "_page", page))  # type: ignore[method-assign]

    recovered = await manager.recover_page("unit-test renderer crash")

    assert recovered is new_page
    assert manager._page is new_page
    assert old_page.is_closed()
