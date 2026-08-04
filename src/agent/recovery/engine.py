"""Recovery engine — automated error recovery with intelligent retries.

When an action fails, the recovery engine tries a series of strategies
before escalating to the planner. Strategies are tried in order of
least-disruptive to most-disruptive. Each attempt is logged for
the session memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.async_api import Page

from agent.core.exceptions import (
    ElementNotInteractableError,
    ElementStaleError,
    NavigationTimeoutError,
    RecoveryExhaustedError,
    SelectorNotFoundError,
)
from agent.core.logging import get_logger
from agent.core.types import RecoveryStrategy
from agent.domain.actions import AgentAction

logger = get_logger(__name__)


@dataclass
class RecoveryResult:
    """Outcome of a recovery attempt."""

    success: bool
    strategy: str
    details: str = ""
    attempts: int = 0


class RecoveryEngine:
    """Automated error recovery with ordered strategy execution.

    Recovery strategies are tried in order:
    1. Wait & Retry — page may still be loading
    2. Dismiss Dialog — unexpected modal blocking interaction
    3. Scroll Into View — element may be off-screen
    4. Relocate Element — try alternative selectors
    5. Refresh Page — last resort before escalation
    6. Escalate to Planner — ask the LLM for help

    Each strategy is attempted at most once per recovery cycle.
    The engine tracks attempts and raises RecoveryExhaustedError
    when all strategies have been tried.
    """

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

        # Map exception types to applicable recovery strategies
        self._strategy_map: dict[type, list[RecoveryStrategy]] = {
            SelectorNotFoundError: [
                RecoveryStrategy.WAIT_AND_RETRY,
                RecoveryStrategy.SCROLL_INTO_VIEW,
                RecoveryStrategy.RELOCATE_ELEMENT,
                RecoveryStrategy.DISMISS_DIALOG,
                RecoveryStrategy.REFRESH_PAGE,
            ],
            ElementNotInteractableError: [
                RecoveryStrategy.WAIT_AND_RETRY,
                RecoveryStrategy.SCROLL_INTO_VIEW,
                RecoveryStrategy.DISMISS_DIALOG,
                RecoveryStrategy.REFRESH_PAGE,
            ],
            ElementStaleError: [
                RecoveryStrategy.WAIT_AND_RETRY,
                RecoveryStrategy.REFRESH_PAGE,
            ],
            NavigationTimeoutError: [
                RecoveryStrategy.WAIT_AND_RETRY,
                RecoveryStrategy.REFRESH_PAGE,
            ],
        }

    async def attempt_recovery(
        self,
        error: Exception,
        action: AgentAction,
        page: Page,
    ) -> RecoveryResult:
        """Attempt to recover from an error using ordered strategies.

        Args:
            error: The exception that triggered recovery.
            action: The action that failed.
            page: The current Playwright page.

        Returns:
            RecoveryResult indicating success/failure.

        Raises:
            RecoveryExhaustedError: When all strategies have been exhausted.
        """
        error_type = type(error)
        strategies = self._strategy_map.get(
            error_type,
            [RecoveryStrategy.WAIT_AND_RETRY, RecoveryStrategy.REFRESH_PAGE],
        )

        logger.info(
            "attempting_recovery",
            error_type=error_type.__name__,
            strategies=[s.value for s in strategies],
        )

        for attempt, strategy in enumerate(strategies[:self._max_retries], 1):
            logger.info(
                "trying_recovery_strategy",
                strategy=strategy.value,
                attempt=attempt,
            )

            try:
                result = await self._execute_strategy(strategy, action, page)
                if result.success:
                    logger.info(
                        "recovery_succeeded",
                        strategy=strategy.value,
                        attempt=attempt,
                    )
                    result.attempts = attempt
                    return result
                logger.info(
                    "recovery_strategy_failed",
                    strategy=strategy.value,
                    details=result.details,
                )
            except Exception as e:
                logger.warning(
                    "recovery_strategy_error",
                    strategy=strategy.value,
                    error=str(e),
                )

        raise RecoveryExhaustedError(
            f"All {len(strategies)} recovery strategies exhausted for {error_type.__name__}",
            original_error=error,
            attempts=len(strategies),
        )

    async def _execute_strategy(
        self,
        strategy: RecoveryStrategy,
        action: AgentAction,
        page: Page,
    ) -> RecoveryResult:
        """Execute a single recovery strategy.

        Args:
            strategy: The strategy to execute.
            action: The original failed action.
            page: The Playwright page.

        Returns:
            RecoveryResult.
        """
        if strategy == RecoveryStrategy.WAIT_AND_RETRY:
            return await self._wait_and_retry(action, page)
        elif strategy == RecoveryStrategy.DISMISS_DIALOG:
            return await self._dismiss_dialog(page)
        elif strategy == RecoveryStrategy.SCROLL_INTO_VIEW:
            return await self._scroll_into_view(action, page)
        elif strategy == RecoveryStrategy.RELOCATE_ELEMENT:
            return await self._relocate_element(action, page)
        elif strategy == RecoveryStrategy.REFRESH_PAGE:
            return await self._refresh_page(page)
        elif strategy == RecoveryStrategy.ESCALATE_TO_PLANNER:
            return RecoveryResult(
                success=False,
                strategy=strategy.value,
                details="Escalated to planner — requires LLM reasoning",
            )
        else:
            return RecoveryResult(
                success=False,
                strategy=strategy.value,
                details=f"Unknown strategy: {strategy}",
            )

    async def _wait_and_retry(
        self, action: AgentAction, page: Page
    ) -> RecoveryResult:
        """Wait for the page to stabilize, then check if the element exists.

        This handles loading delays, AJAX updates, and DOM re-renders.
        """
        # Wait for network idle
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Additional wait for ServiceNow AJAX
        await page.wait_for_timeout(2000)

        # Check if the target element now exists
        if action.target:
            try:
                locator = page.locator(action.target)
                count = await locator.count()
                if count > 0:
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.WAIT_AND_RETRY.value,
                        details="Element found after waiting",
                    )
            except Exception:
                # Try by text
                try:
                    locator = page.get_by_text(action.target, exact=False)
                    if await locator.count() > 0:
                        return RecoveryResult(
                            success=True,
                            strategy=RecoveryStrategy.WAIT_AND_RETRY.value,
                            details="Element found by text after waiting",
                        )
                except Exception:
                    pass

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.WAIT_AND_RETRY.value,
            details="Element still not found after waiting",
        )

    async def _dismiss_dialog(self, page: Page) -> RecoveryResult:
        """Detect and dismiss unexpected dialogs, modals, or alerts."""
        # Handle browser alerts
        try:
            # Check for ServiceNow modals
            modal_selectors = [
                "[role='dialog'] button.close",
                ".modal .close",
                ".glide_popup .close",
                "button[aria-label='Close']",
                ".modal-footer button",
            ]

            for selector in modal_selectors:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(500)
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.DISMISS_DIALOG.value,
                        details=f"Dismissed dialog via: {selector}",
                    )

        except Exception as e:
            logger.debug("dismiss_dialog_error", error=str(e))

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.DISMISS_DIALOG.value,
            details="No dialog found to dismiss",
        )

    async def _scroll_into_view(
        self, action: AgentAction, page: Page
    ) -> RecoveryResult:
        """Scroll to bring the target element into the viewport."""
        if not action.target:
            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
                details="No target to scroll to",
            )

        try:
            # Try to find the element and scroll it into view
            locator = page.get_by_text(action.target, exact=False)
            if await locator.count() > 0:
                await locator.first.scroll_into_view_if_needed(timeout=5000)
                return RecoveryResult(
                    success=True,
                    strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
                    details="Scrolled element into view",
                )

            # Try CSS selector
            locator = page.locator(action.target)
            if await locator.count() > 0:
                await locator.first.scroll_into_view_if_needed(timeout=5000)
                return RecoveryResult(
                    success=True,
                    strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
                    details="Scrolled element into view via CSS",
                )

        except Exception as e:
            logger.debug("scroll_into_view_error", error=str(e))

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
            details="Could not find element to scroll to",
        )

    async def _relocate_element(
        self, action: AgentAction, page: Page
    ) -> RecoveryResult:
        """Try alternative selectors to find the target element.

        ServiceNow elements can be located by:
        - Text content
        - ARIA label
        - Role + name
        - Placeholder
        - data-ref attribute
        """
        target = action.target

        alternative_strategies = [
            ("text", lambda: page.get_by_text(target, exact=False)),
            ("label", lambda: page.get_by_label(target)),
            ("role:button", lambda: page.get_by_role("button", name=target)),
            ("role:link", lambda: page.get_by_role("link", name=target)),
            ("role:textbox", lambda: page.get_by_role("textbox", name=target)),
            ("placeholder", lambda: page.get_by_placeholder(target)),
            ("title", lambda: page.get_by_title(target)),
        ]

        for strategy_name, locator_fn in alternative_strategies:
            try:
                locator = locator_fn()
                if await locator.count() > 0 and await locator.first.is_visible():
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.RELOCATE_ELEMENT.value,
                        details=f"Element found via {strategy_name}: {target}",
                    )
            except Exception:
                continue

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.RELOCATE_ELEMENT.value,
            details=f"Could not relocate element: {target}",
        )

    async def _refresh_page(self, page: Page) -> RecoveryResult:
        """Refresh the page as a last resort."""
        try:
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            return RecoveryResult(
                success=True,
                strategy=RecoveryStrategy.REFRESH_PAGE.value,
                details="Page refreshed successfully",
            )
        except Exception as e:
            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.REFRESH_PAGE.value,
                details=f"Page refresh failed: {e}",
            )
