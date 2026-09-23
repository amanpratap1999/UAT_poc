"""Browser manager — Playwright browser/context/page lifecycle management.

Handles launching the browser, managing the page, capturing screenshots,
extracting accessibility trees, and collecting console/JS error logs.
This is the lowest layer — no LLM logic here, only browser infrastructure.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Page,
    Playwright,
    Response,
    async_playwright,
)

from agent.browser.network import NetworkEntry
from agent.core.config import BrowserConfig, ServiceNowConfig
from agent.core.exceptions import BrowserError, BrowserLaunchError
from agent.core.logging import get_logger

logger = get_logger(__name__)

VISUAL_CURSOR_SCRIPT = """
(() => {
  if (document.getElementById('playwright-mouse-pointer')) return;
  const cursor = document.createElement('div');
  cursor.id = 'playwright-mouse-pointer';
  cursor.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid rgba(239, 68, 68, 0.9);
    background: rgba(239, 68, 68, 0.3);
    pointer-events: none;
    z-index: 2147483647;
    transform: translate(-50%, -50%);
    transition: transform 0.05s ease-out;
    display: none;
  `;
  const style = document.createElement('style');
  style.id = 'playwright-mouse-pointer-style';
  style.textContent = `
    body.pw-cursor-hidden #playwright-mouse-pointer {
      display: none !important;
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(cursor);
  document.addEventListener('mousemove', (e) => {
    cursor.style.left = e.clientX + 'px';
    cursor.style.top = e.clientY + 'px';
    if (!document.body.classList.contains('pw-cursor-hidden')) {
      cursor.style.display = 'block';
    }
  }, { passive: true });
})();
"""


_GLOBAL_PLAYWRIGHT: Playwright | None = None
_GLOBAL_BROWSER: Browser | None = None
_GLOBAL_CONTEXT: BrowserContext | None = None


def reset_browser_globals() -> None:
    """Reset global browser instances (useful for testing)."""
    global _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER, _GLOBAL_CONTEXT
    _GLOBAL_PLAYWRIGHT = None
    _GLOBAL_BROWSER = None
    _GLOBAL_CONTEXT = None


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

        self._context: BrowserContext | None = None
        self._page: Page | None = None

        # Log capture
        self._console_logs: list[dict[str, str]] = []
        self._console_errors: list[str] = []
        self._page_errors: list[str] = []
        self._network_entries: list[NetworkEntry] = []
        self._network_errors: list[str] = []
        self._last_console_index: int = 0

    @property
    def _playwright(self) -> Playwright | None:
        return _GLOBAL_PLAYWRIGHT

    @property
    def _browser(self) -> Browser | None:
        return _GLOBAL_BROWSER

    async def launch(self) -> None:
        """Launch the browser with configured settings, keeping process warm across runs."""
        global _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER, _GLOBAL_CONTEXT
        try:
            logger.info("launching_browser", headless=self._browser_config.headless)
            if not self._browser_config.headless and sys.platform == "linux":
                if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                    raise BrowserLaunchError(
                        "Cannot launch headed browser: no graphical display server found (DISPLAY or WAYLAND_DISPLAY environment variable is not set)."
                    )

            self._screenshot_dir.mkdir(parents=True, exist_ok=True)

            if not _GLOBAL_PLAYWRIGHT:
                _GLOBAL_PLAYWRIGHT = await async_playwright().start()

            launch_args: list[str] = []
            if not self._browser_config.headless:
                launch_args = [
                    "--start-maximized",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]

            if self._browser_config.user_data_dir:
                if not _GLOBAL_CONTEXT:
                    persistent_kwargs: dict[str, Any] = {
                        "user_data_dir": str(self._browser_config.user_data_dir),
                        "headless": self._browser_config.headless,
                        "slow_mo": self._browser_config.slow_mo,
                        "viewport": {
                            "width": self._browser_config.viewport_width,
                            "height": self._browser_config.viewport_height,
                        },
                        "ignore_https_errors": True,
                    }
                    if launch_args:
                        persistent_kwargs["args"] = launch_args
                    assert self._playwright is not None
                    _GLOBAL_CONTEXT = await self._playwright.chromium.launch_persistent_context(**persistent_kwargs)
                self._context = _GLOBAL_CONTEXT
                pages = self._context.pages
                self._page = pages[0] if pages else await self._context.new_page()
            else:
                launch_kwargs: dict[str, Any] = {
                    "headless": self._browser_config.headless,
                    "slow_mo": self._browser_config.slow_mo,
                }
                if launch_args:
                    launch_kwargs["args"] = launch_args
                
                if not _GLOBAL_BROWSER:
                    assert self._playwright is not None
                    _GLOBAL_BROWSER = await self._playwright.chromium.launch(**launch_kwargs)
                
                assert self._browser is not None
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

            # Inject visual cursor if show_mouse_cursor is True
            if self._browser_config.show_mouse_cursor:
                await self._context.add_init_script(VISUAL_CURSOR_SCRIPT)

            # Attach log and network listeners
            self._page.on("console", self._on_console_message)
            self._page.on("pageerror", self._on_page_error)
            self._page.on("response", self._on_response)

            # Ensure headed browser window is visible and on top on Windows
            if not self._browser_config.headless:
                self._bring_to_foreground()

            logger.info("browser_launched")
        except BrowserLaunchError:
            raise
        except Exception as e:
            raise BrowserLaunchError(
                f"Failed to launch browser: {e}",
                details={"headless": self._browser_config.headless},
            ) from e

    async def close(self) -> None:
        """Close browser context/page, keeping process warm."""
        logger.info("closing_browser_context")
        try:
            if self._page:
                await self._page.close()
            if self._context:
                if self._context != _GLOBAL_CONTEXT:
                    await self._context.close()
            # Do NOT close _GLOBAL_BROWSER or _GLOBAL_PLAYWRIGHT to keep them warm
        except Exception as e:
            logger.warning("browser_close_error", error=str(e))
        finally:
            self._page = None
            self._context = None

    async def wait_until_closed(
        self, timeout_seconds: float | None = None, poll_interval_ms: int = 500
    ) -> None:
        """Keep a headed browser session alive until the user closes it or timeout is reached."""
        if not self._page or not self._browser_config.keep_browser_open or self._browser_config.headless:
            return

        logger.info("keeping_browser_open", timeout_seconds=timeout_seconds)
        start_time = asyncio.get_event_loop().time()
        while self._page and not self._page.is_closed():
            if timeout_seconds is not None:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout_seconds:
                    logger.info("keep_browser_open_timeout_reached")
                    break
            try:
                await asyncio.sleep(poll_interval_ms / 1000.0)
            except (asyncio.CancelledError, KeyboardInterrupt):
                break

    def _bring_to_foreground(self) -> None:
        """On Windows, ensure the headed browser window is visible, restored, and brought to front."""
        if sys.platform != "win32" or self._browser_config.headless:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32

            def enum_cb(hwnd: int, extra: int) -> bool:
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.lower()
                        if any(
                            k in title
                            for k in (
                                "chrome for testing",
                                "chromium",
                                "service-now",
                                "servicenow",
                                "about:blank",
                            )
                        ):
                            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                            user32.ShowWindow(hwnd, 5)  # SW_SHOW
                            user32.SetForegroundWindow(hwnd)
                            user32.BringWindowToTop(hwnd)
                return True

            wnd_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_cb)
            user32.EnumWindows(wnd_proc, 0)
        except Exception as e:
            logger.debug("bring_to_foreground_failed", error=str(e))

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

        Attempts domcontentloaded first; retries once with networkidle if the
        page times out.  ServiceNow's SPA can be slow on cold starts.

        Args:
            url: The full URL to navigate to.
        """
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        page = self.get_page()
        nav_timeout = self._browser_config.timeout  # e.g. 90 000 ms
        logger.info("navigating", url=url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
        except PlaywrightTimeoutError:
            logger.warning(
                "navigation_timeout_retry",
                url=url,
                strategy="networkidle",
                timeout_ms=nav_timeout,
            )
            # Retry: networkidle is more forgiving for heavy SPAs
            await page.goto(url, wait_until="networkidle", timeout=nav_timeout)
        await self.wait_for_load()
        if not self._browser_config.headless:
            self._bring_to_foreground()

    async def take_screenshot(self, name: str = "screenshot", hide_cursor: bool = True) -> str:
        """Capture a screenshot and save to disk.

        Args:
            name: Filename prefix for the screenshot.
            hide_cursor: Whether to temporarily hide the visual cursor indicator.

        Returns:
            The absolute file path of the saved screenshot.
        """
        page = self.get_page()
        timestamp = asyncio.get_event_loop().time()
        filename = f"{name}_{int(timestamp)}.png"
        filepath = self._screenshot_dir / filename

        if hide_cursor:
            with suppress(Exception):
                await page.evaluate("document.body.classList.add('pw-cursor-hidden')")
        # Mask sensitive inputs (passwords, tokens, keys) before screenshot
        with suppress(Exception):
            await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input[type="password"], input[autocomplete="current-password"], input[autocomplete="new-password"], input[data-sensitive="true"], input[name*="password" i], input[id*="password" i], input[name*="secret" i], input[id*="secret" i], input[name*="token" i], input[id*="token" i], input[name*="api_key" i], input[id*="api_key" i], input[name*="credential" i], input[id*="credential" i], textarea[name*="secret" i], textarea[id*="secret" i]');
                inputs.forEach(el => {
                    el.setAttribute('data-uat-orig-filter', el.style.filter || '');
                    el.style.filter = 'blur(10px)';
                });
            }""")
        try:
            await page.screenshot(path=str(filepath), full_page=False)
        finally:
            with suppress(Exception):
                await page.evaluate("""() => {
                    const inputs = document.querySelectorAll('[data-uat-orig-filter]');
                    inputs.forEach(el => {
                        el.style.filter = el.getAttribute('data-uat-orig-filter') || '';
                        el.removeAttribute('data-uat-orig-filter');
                    });
                }""")
            if hide_cursor:
                with suppress(Exception):
                    await page.evaluate("document.body.classList.remove('pw-cursor-hidden')")

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

    def get_new_console_errors(self) -> list[str]:
        """Return console error messages logged since the last call."""
        errors = [
            log["message"]
            for log in self._console_logs[self._last_console_index:]
            if log.get("level") == "error"
        ]
        self._last_console_index = len(self._console_logs)
        return errors

    def get_page_errors(self) -> list[str]:
        """Return all captured JavaScript page errors."""
        return list(self._page_errors)

    def get_network_entries(self) -> list[NetworkEntry]:
        """Return captured network request entries."""
        return list(self._network_entries)

    def get_network_errors(self) -> list[str]:
        """Return captured HTTP/network error messages."""
        return list(self._network_errors)

    def clear_logs(self) -> None:
        """Clear captured logs."""
        self._console_logs.clear()
        self._page_errors.clear()
        self._network_entries.clear()
        self._network_errors.clear()
        self._last_console_index = 0

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

    def _on_response(self, response: Response) -> None:
        """Capture HTTP responses for network telemetry and error tracking."""
        try:
            url = response.url
            status = response.status
            method = response.request.method if response.request else "GET"
            is_api = NetworkEntry.is_servicenow_api(url)
            req_type = NetworkEntry.classify_request(url)

            entry = NetworkEntry(
                url=url,
                method=method,
                status=status,
                is_api_call=is_api,
                request_type=req_type,
            )
            if len(self._network_entries) < 200:
                self._network_entries.append(entry)

            if status >= 400:
                err_str = f"{method} {url} returned HTTP {status}"
                self._network_errors.append(err_str)
                logger.debug("network_error_captured", url=url, status=status)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Context manager support
    # -----------------------------------------------------------------------

    async def __aenter__(self) -> BrowserManager:
        await self.launch()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
