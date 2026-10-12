"""Regression test for bounded browser screenshot waits."""

from __future__ import annotations

from pathlib import Path

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
