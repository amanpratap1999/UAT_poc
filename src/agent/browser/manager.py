"""Browser manager — Playwright browser/context/page lifecycle management.

Handles launching the browser, managing the page, capturing screenshots,
extracting accessibility trees, and collecting console/JS error logs.
This is the lowest layer — no LLM logic here, only browser infrastructure.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Page,
    Playwright,
    async_playwright,
)

from agent.core.config import BrowserConfig, ServiceNowConfig
from agent.core.exceptions import BrowserError, BrowserLaunchError
from agent.core.logging import get_logger

logger = get_logger(__name__)


class BrowserManager:
    """Manages the Playwright browser lifecycle and provides page access.

    Responsibilities:
    - Launch and close the browser
    - Provide the active page
    - Navigate to URLs
    - Capture screenshots
    - Extract accessibility tree snapshots
    - Collect console and JS error logs
    """

    def __init__(
        self,
        browser_config: BrowserConfig,
        servicenow_config: ServiceNowConfig,
        screenshot_dir: Path = Path("screenshots"),
    ) -> None:
        self._browser_config = browser_config
        self._servicenow_config = servicenow_config
        self._screenshot_dir = screenshot_dir

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        # Log capture
        self._console_logs: list[dict[str, str]] = []
        self._page_errors: list[str] = []

    async def launch(self) -> None:
        """Launch the browser with configured settings."""
        try:
            logger.info("launching_browser", headless=self._browser_config.headless)
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._browser_config.headless,
                slow_mo=self._browser_config.slow_mo,
            )
            self._context = await self._browser.new_context(
                viewport={
                    "width": self._browser_config.viewport_width,
                    "height": self._browser_config.viewport_height,
                },
                ignore_https_errors=True,
            )
            self._page = await self._context.new_page()

            # Set default timeout
            self._page.set_default_timeout(self._browser_config.timeout)

            # Attach log listeners
            self._page.on("console", self._on_console_message)
            self._page.on("pageerror", self._on_page_error)

            logger.info("browser_launched")
        except Exception as e:
            raise BrowserLaunchError(
                f"Failed to launch browser: {e}",
                details={"headless": self._browser_config.headless},
            ) from e

    async def close(self) -> None:
        """Close browser and clean up resources."""
        logger.info("closing_browser")
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning("browser_close_error", error=str(e))
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def get_page(self) -> Page:
        """Get the active Playwright page.

        Raises:
            BrowserError: If browser is not launched.
        """
        if self._page is None:
            raise BrowserError("Browser not launched. Call launch() first.")
        return self._page

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for load.

        Args:
            url: The full URL to navigate to.
        """
        page = self.get_page()
        logger.info("navigating", url=url)
        await page.goto(url, wait_until="domcontentloaded")
        await self.wait_for_load()

    async def take_screenshot(self, name: str = "screenshot") -> str:
        """Capture a screenshot and save to disk.

        Args:
            name: Filename prefix for the screenshot.

        Returns:
            The absolute file path of the saved screenshot.
        """
        page = self.get_page()
        timestamp = asyncio.get_event_loop().time()
        filename = f"{name}_{int(timestamp)}.png"
        filepath = self._screenshot_dir / filename
        await page.screenshot(path=str(filepath), full_page=False)
        logger.debug("screenshot_captured", path=str(filepath))
        return str(filepath)

    async def get_accessibility_tree(self) -> dict[str, Any]:
        """Extract the accessibility tree snapshot from the current page.

        This is the primary method for understanding page structure.
        Uses native page.accessibility when available, or CDP Accessibility tree fallback.

        Returns:
            The accessibility tree as a nested dictionary.
        """
        page = self.get_page()
        try:
            if hasattr(page, "accessibility"):
                snapshot = await page.accessibility.snapshot()
                if snapshot:
                    return snapshot  # type: ignore[no-any-return]
        except Exception:
            pass

        # CDP Fallback for Playwright versions where page.accessibility was removed
        try:
            cdp = await page.context.new_cdp_session(page)
            tree = await cdp.send("Accessibility.getFullAXTree")
            nodes = tree.get("nodes", [])
            return {"role": "WebArea", "children": nodes}
        except Exception as e:
            logger.warning("cdp_accessibility_fallback_error", error=str(e))
            return {}

    async def get_page_content(self) -> str:
        """Get the full HTML content of the current page."""
        page = self.get_page()
        return await page.content()

    async def get_url(self) -> str:
        """Get the current page URL."""
        return self.get_page().url

    async def get_title(self) -> str:
        """Get the current page title."""
        return await self.get_page().title()

    async def wait_for_load(self) -> None:
        """Wait for the page to reach a loaded state.

        Uses domcontentloaded as the baseline, then waits for
        ServiceNow-specific loading indicators across main page and frames to disappear.
        """
        page = self.get_page()
        try:
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(500)

            # Wait for ServiceNow loading indicator to disappear
            loading_indicator = page.locator(
                ".loading, .busy, #loading, .loading-container, #is_loading, .sn-loading-loader"
            )
            with suppress(Exception):
                await loading_indicator.wait_for(state="hidden", timeout=5000)
            # Loading indicator may not exist — that's fine

            # Also wait for active frames (e.g., gsft_main) to settle domcontentloaded
            try:
                frames = getattr(page, "frames", [])
                if callable(frames):
                    frames = frames()
                for frame in frames:
                    main_frame = getattr(page, "main_frame", None)
                    if frame != main_frame and hasattr(frame, "wait_for_load_state"):
                        with contextlib.suppress(Exception):
                            await frame.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass

        except Exception as e:
            logger.warning("wait_for_load_timeout", error=str(e))

    async def wait_for_network_idle(self, timeout: int = 10000) -> None:
        """Wait until network activity settles."""
        page = self.get_page()
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception as e:
            logger.warning("network_idle_timeout", error=str(e), timeout=timeout)

    def get_console_logs(self) -> list[dict[str, str]]:
        """Return all captured console log messages."""
        return list(self._console_logs)

    def get_page_errors(self) -> list[str]:
        """Return all captured JavaScript page errors."""
        return list(self._page_errors)

    def clear_logs(self) -> None:
        """Clear captured logs."""
        self._console_logs.clear()
        self._page_errors.clear()

    # -----------------------------------------------------------------------
    # Private event handlers
    # -----------------------------------------------------------------------

    def _on_console_message(self, msg: ConsoleMessage) -> None:
        """Capture console messages from the browser."""
        entry = {
            "level": msg.type,
            "message": msg.text,
        }
        self._console_logs.append(entry)
        if msg.type == "error":
            logger.debug("console_error", message=msg.text)

    def _on_page_error(self, error: Exception) -> None:
        """Capture uncaught JavaScript errors."""
        error_msg = str(error)
        self._page_errors.append(error_msg)
        logger.warning("js_page_error", error=error_msg)

    # -----------------------------------------------------------------------
    # Context manager support
    # -----------------------------------------------------------------------

    async def __aenter__(self) -> BrowserManager:
        await self.launch()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
