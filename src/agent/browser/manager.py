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
import time
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


def _should_ignore_https_errors() -> bool:
    """INC-UAT-14 (Minor): only ignore HTTPS errors in local development mode.

    In production/docker mode, HTTPS errors must NOT be ignored — that
    weakens transport verification and could allow MITM attacks on the
    ServiceNow subproduction instance.
    """
    try:
        from agent.core.config import get_settings
        s = get_settings()
        return s.runtime_mode == "local" and s.environment in ("development", "dev", "local")
    except Exception:
        return False  # fail-closed: don't ignore HTTPS errors


async def _health_check_globals() -> bool:
    """Health-check the global browser state.

    Audit issue I32 (P1): the comment at line 228 (now relocated) said
    'Do NOT close _GLOBAL_BROWSER or _GLOBAL_PLAYWRIGHT to keep them warm'
    — meaning a crashed Chromium process was never recreated, so all
    subsequent runs reused a dead Browser handle and failed with
    TargetClosedError. This function detects a dead browser and resets
    the globals so the next launch() recreates them.

    Returns True if the globals are healthy (or were just reset because
    they were stale), False if they were already None (no health to check).
    """
    global _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER, _GLOBAL_CONTEXT
    if _GLOBAL_BROWSER is not None:
        try:
            # is_connected() returns False if the browser process has died.
            # Browser.is_connected is a method on the Playwright Browser class.
            if not _GLOBAL_BROWSER.is_connected():
                logger.warning(
                    "global_browser_disconnected_resetting",
                    action="recreate_on_next_launch",
                )
                # Try to clean up the dead handles gracefully (best-effort).
                try:
                    if _GLOBAL_CONTEXT is not None:
                        await _GLOBAL_CONTEXT.close()
                except Exception as e:
                    logger.debug("dead_context_close_failed", error=str(e))
                try:
                    await _GLOBAL_BROWSER.close()
                except Exception as e:
                    logger.debug("dead_browser_close_failed", error=str(e))
                try:
                    if _GLOBAL_PLAYWRIGHT is not None:
                        await _GLOBAL_PLAYWRIGHT.stop()
                except Exception as e:
                    logger.debug("dead_playwright_stop_failed", error=str(e))
                _GLOBAL_PLAYWRIGHT = None
                _GLOBAL_BROWSER = None
                _GLOBAL_CONTEXT = None
                return True  # globals were stale, now reset
            return True  # globals are healthy
        except Exception as e:
            # is_connected() itself raised — definitely stale.
            logger.warning("global_browser_health_check_failed", error=str(e))
            _GLOBAL_PLAYWRIGHT = None
            _GLOBAL_BROWSER = None
            _GLOBAL_CONTEXT = None
            return True
    return False  # nothing to check (globals were None)


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
        # Audit issue I32 (P1): health-check the global browser before reusing it.
        # If the Chromium process has died (crash, OOM kill, container restart),
        # _GLOBAL_BROWSER.is_connected() returns False and the previous code
        # would silently reuse the dead handle, causing TargetClosedError on
        # every subsequent run. Now: detect and reset, so launch() recreates.
        await _health_check_globals()
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
                        # INC-UAT-14 (Minor): ignore_https_errors disabled except local dev.
                        # Was True unconditionally — weakened transport verification.
                        "ignore_https_errors": _should_ignore_https_errors(),
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
                    # INC-UAT-14 (Minor): ignore_https_errors disabled except local dev.
                    ignore_https_errors=_should_ignore_https_errors(),
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
        # Audit issue I33 (P2): asyncio.get_event_loop() is deprecated since Python
        # 3.10 and emits DeprecationWarning in 3.12+ when no running loop exists.
        # time.monotonic() is exactly what Loop.time() returns under the hood —
        # removes the asyncio dependency for timestamp code.
        start_time = time.monotonic()
        while self._page and not self._page.is_closed():
            if timeout_seconds is not None:
                elapsed = time.monotonic() - start_time
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

    async def new_persona_context(self, persona_name: str) -> Page:
        """Create a fresh, isolated browser context for a specific persona.

        INC-UAT-06 (Major, D9): ensures persona/session isolation across
        consecutive runs. Each persona gets its own BrowserContext with
        independent cookies, local storage, and session state — preventing
        contamination between persona A (e.g., requester) and persona B
        (e.g., fulfiller) runs.

        The old context is closed before creating the new one. The new
        context uses the same viewport/headless config but a separate
        storage state.

        Args:
            persona_name: The persona identifier (used for logging + isolation).

        Returns:
            A new Page in the isolated context.
        """
        assert self._browser is not None, "Browser not launched"
        # Close the old context if it's not the global one (to avoid
        # closing the warm global browser).
        if self._context and self._context is not _GLOBAL_CONTEXT:
            try:
                await self._context.close()
            except Exception as e:
                logger.warning("persona_context_close_failed", persona=persona_name, error=str(e))

        # Create a fresh, isolated context
        self._context = await self._browser.new_context(
            viewport={
                "width": self._browser_config.viewport_width,
                "height": self._browser_config.viewport_height,
            },
            ignore_https_errors=_should_ignore_https_errors(),
        )
        self._page = await self._context.new_page()
        logger.info(
            "persona_context_created",
            persona=persona_name,
            context_id=id(self._context),
        )
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
        # Audit issue I33 (P2): time.monotonic() is exactly what Loop.time() returns.
        timestamp = time.monotonic()
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
        """Return console error messages logged since the last call.

        DESTRUCTIVE READ: advances the internal cursor so the next call returns
        only errors logged since THIS call (not since the start). Calling twice
        in a row returns an empty list the second time.

        Audit issue I34 (P2): the previous method was non-idempotent — concurrent
        SSE/REST consumers racing on this method silently dropped errors. For
        non-destructive reads, use peek_new_console_errors(since_index) which
        takes an explicit cursor and does not mutate state.
        """
        errors = [
            log["message"]
            for log in self._console_logs[self._last_console_index:]
            if log.get("level") == "error"
        ]
        self._last_console_index = len(self._console_logs)
        return errors

    def peek_new_console_errors(self, since_index: int) -> list[str]:
        """Non-destructive read of console errors since `since_index`.

        Audit issue I34 (P2): added for callers that need an idempotent read.
        Does NOT advance the internal cursor — multiple consumers can call
        this with the same `since_index` and all get the same result.

        Returns:
            List of console error messages captured since `since_index`.
            Pass `len(self._console_logs)` from a previous observation to get
            only the errors logged since that observation.
        """
        if since_index < 0:
            since_index = 0
        if since_index > len(self._console_logs):
            return []
        return [
            log["message"]
            for log in self._console_logs[since_index:]
            if log.get("level") == "error"
        ]

    @property
    def console_log_count(self) -> int:
        """Total number of console logs captured (for use as a cursor with peek_new_console_errors)."""
        return len(self._console_logs)

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
