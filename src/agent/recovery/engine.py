"""Recovery engine — automated error recovery with intelligent retries.

When an action fails, the recovery engine tries a series of strategies
before escalating to the planner. Strategies are tried in order of
least-disruptive to most-disruptive. Each attempt is logged for
the session memory.
"""

from __future__ import annotations
import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

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
    # Concrete locator recovery found. The execution controller uses this
    # value on retry instead of replaying the original broken selector.
    resolved_target: str | None = None


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

    def __init__(self, max_retries: int = 3, max_recovery_depth: int = 3, max_backoff: float = 10.0) -> None:
        self._max_retries = max_retries
        self._max_recovery_depth = max_recovery_depth
        self._max_backoff = max_backoff
        # Per-action_key failure counter — reset to 0 on successful recovery.
        # Used to detect "stuck" actions that keep failing within a short window.
        # Audit issue I18 (P1): previously this counter was never reset, so a
        # transient 3-failure burst permanently poisoned the action_key and any
        # future failure on the same action_type:target raised
        # RecoveryExhaustedError on the very first attempt, blocking legitimate
        # retries for the rest of the run.
        self._action_failures: dict[str, int] = {}
        # Lifetime failure count per action_key — never reset, used for hard
        # ceiling detection (action that has failed many times across multiple
        # recovery cycles likely indicates a real bug, not a transient issue).
        self._lifetime_failures: dict[str, int] = {}
        # Hard ceiling: if lifetime failures exceed this, the action is
        # considered permanently broken and recovery is skipped.
        self._max_lifetime_failures = max_recovery_depth * 5

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
            ],
            ElementStaleError: [
                RecoveryStrategy.RELOCATE_ELEMENT,
                RecoveryStrategy.WAIT_AND_RETRY,
            ],
            NavigationTimeoutError: [
                RecoveryStrategy.REFRESH_PAGE,
                RecoveryStrategy.WAIT_AND_RETRY,
            ],
        }

    async def attempt_recovery(
        self,
        error: Exception,
        action: AgentAction,
        page: Page,
    ) -> RecoveryResult:
        error_type = type(error)
        action_key = f"{action.action_type}:{action.target}"
        self._action_failures[action_key] = self._action_failures.get(action_key, 0) + 1
        # Also track lifetime failures — these are NOT reset on success and
        # serve as a hard ceiling so an action that consistently fails across
        # many recovery cycles is eventually given up on.
        self._lifetime_failures[action_key] = self._lifetime_failures.get(action_key, 0) + 1

        # Hard ceiling: lifetime failures exceed the maximum allowed.
        if self._lifetime_failures[action_key] > self._max_lifetime_failures:
            logger.error(
                "recovery_lifetime_ceiling_hit",
                action=action_key,
                lifetime=self._lifetime_failures[action_key],
                ceiling=self._max_lifetime_failures,
            )
            raise RecoveryExhaustedError(
                f"Terminal failure: Action {action_key} hit lifetime failure ceiling "
                f"of {self._max_lifetime_failures} (likely a real bug, not transient).",
                original_error=error,
                attempts=self._lifetime_failures[action_key],
                details={"action_key": action_key, "lifetime": self._lifetime_failures[action_key]},
            )

        # Soft ceiling: depth within the current recovery cycle exceeded.
        # (Was previously permanent — now reset on success below.)
        if self._action_failures[action_key] > self._max_recovery_depth:
            logger.error("recovery_depth_exceeded", action=action_key, depth=self._action_failures[action_key])
            raise RecoveryExhaustedError(
                f"Terminal failure: Action {action_key} exceeded max recovery depth of {self._max_recovery_depth}",
                original_error=error,
                attempts=self._action_failures[action_key],
                details={"action_key": action_key, "depth": self._action_failures[action_key]},
            )

        strategies = self._strategy_map.get(
            error_type,
            [RecoveryStrategy.WAIT_AND_RETRY, RecoveryStrategy.REFRESH_PAGE],
        )

        logger.info(
            "attempting_recovery",
            error_type=error_type.__name__,
            strategies=[s.value for s in strategies],
        )

        last_details = ""
        for attempt, strategy in enumerate(strategies[: self._max_retries], 1):
            logger.info(
                "trying_recovery_strategy",
                strategy=strategy.value,
                attempt=attempt,
            )

            backoff = min(self._max_backoff, float(2 ** attempt))
            await asyncio.sleep(backoff)

            result: RecoveryResult | None = None
            try:
                result = await self._execute_strategy(strategy, action, page)
            except Exception as e:
                logger.debug("strategy_failed", strategy=strategy.value, error=str(e))
                result = RecoveryResult(
                    success=False,
                    strategy=strategy.value,
                    details=f"Strategy raised: {e}",
                )

            if result and result.success:
                logger.info("recovery_successful", strategy=strategy.value)
                # Audit issue I18 (P1): reset the per-cycle depth counter so a
                # transient failure burst doesn't permanently poison this
                # action_key. The lifetime counter (_lifetime_failures) is
                # NOT reset — it serves as a hard ceiling for genuinely broken
                # actions that consistently fail across many cycles.
                self._action_failures[action_key] = 0
                result.attempts = attempt
                return result
            if result:
                last_details = result.details

        raise RecoveryExhaustedError(
            f"All {len(strategies)} recovery strategies failed for {error_type.__name__}"
            + (f" (last: {last_details})" if last_details else ""),
            original_error=error,
            attempts=len(strategies[: self._max_retries]),
            details={"last_strategy_details": last_details},
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

    @staticmethod
    def _get_active_context(page: Page) -> Any:
        """Return ServiceNow's content frame when present, otherwise the page."""
        try:
            frames = getattr(page, "frames", [])
            if callable(frames):
                frames = frames()
            for frame in frames:
                name = str(getattr(frame, "name", "") or "")
                frame_url = str(getattr(frame, "url", "") or "")
                if name == "gsft_main" or "gsft_main" in name or "gsft_main" in frame_url:
                    return frame
            main_frame = getattr(page, "main_frame", None)
            for frame in frames:
                frame_url = str(getattr(frame, "url", "") or "")
                if frame != main_frame and ".do" in frame_url.lower():
                    return frame
        except Exception:
            # Some test doubles and pages without frames do not expose a normal
            # iterable frames collection. Falling back to the page is safe.
            pass
        return page

    @staticmethod
    def _locator_for_target(context: Any, target: str) -> Any:
        """Resolve the repository's locator-prefix syntax against a page or frame."""
        selector = (target or "").strip()
        if " >> nth=" in selector:
            base, nth = selector.rsplit(" >> nth=", 1)
            try:
                return RecoveryEngine._locator_for_target(context, base).nth(int(nth))
            except (ValueError, IndexError):
                return context.locator(selector)

        if selector.startswith("role:"):
            parts = selector[5:].split(":", 1)
            role = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else ""
            return context.get_by_role(role, name=name) if name else context.get_by_role(role)
        if selector.startswith("label:"):
            return context.get_by_label(selector[6:].strip(), exact=False)
        if selector.startswith("text:"):
            return context.get_by_text(selector[5:].strip(), exact=False)
        if selector.startswith("placeholder:"):
            return context.get_by_placeholder(selector[12:].strip(), exact=False)
        if selector.startswith("title:"):
            return context.get_by_title(selector[6:].strip(), exact=False)
        if selector.startswith("css:"):
            return context.locator(f"css={selector[4:].strip()}")
        if selector.startswith("xpath:"):
            return context.locator(f"xpath={selector[6:].strip()}")
        return context.locator(selector)

    @staticmethod
    def _candidate_targets(target: str, action_type: Any = None) -> list[str]:
        """Build bounded alternatives appropriate for the action being retried.

        SELECT recovery must not treat a generic visible caption as the
        target control when the actual dropdown has a valid DOM selector.
        """
        selector = (target or "").strip()
        if not selector:
            return []
        action_kind = str(getattr(action_type, "value", action_type) or "").lower()
        if " >> nth=" in selector:
            base, nth = selector.rsplit(" >> nth=", 1)
            try:
                int(nth)
            except ValueError:
                return [selector]
            return list(dict.fromkeys(
                f"{candidate} >> nth={nth}"
                for candidate in RecoveryEngine._candidate_targets(base, action_type)
            ))
        if selector.startswith(("css:", "xpath:")):
            return [selector]

        if selector.startswith(("text:", "label:", "placeholder:", "title:")):
            hint = selector.split(":", 1)[1].strip()
        elif selector.startswith("role:"):
            parts = selector[5:].split(":", 1)
            hint = parts[1].strip() if len(parts) > 1 else ""
        else:
            hint = selector
        if not hint:
            return [selector]

        normalized = " ".join(
            hint.lower().replace("_", " ").replace("-", " ").replace(".", " ").split()
        )
        field_fallbacks = {
            "state": r"select[id$='.state'], select[name$='.state'], select#incident\.state",
            "incident state": r"select[id$='.state'], select[name$='.state'], select#incident\.state",
            "category": "select[id$='.category'], select[name$='.category']",
            "incident category": "select[id$='.category'], select[name$='.category']",
            "urgency": "select[id$='.urgency'], select[name$='.urgency']",
            "incident urgency": "select[id$='.urgency'], select[name$='.urgency']",
            "impact": "select[id$='.impact'], select[name$='.impact']",
            "incident impact": "select[id$='.impact'], select[name$='.impact']",
            "hold reason": "select[id$='.hold_reason'], select[name$='.hold_reason']",
            "on hold reason": "select[id$='.hold_reason'], select[name$='.hold_reason']",
        }
        fallback_selector = field_fallbacks.get(normalized)

        if action_kind == "select":
            candidates = [selector, f"label:{hint}", f"role:combobox:{hint}"]
            if fallback_selector:
                candidates.append(f"css:{fallback_selector}")
            return list(dict.fromkeys(candidates))

        candidates = [selector]
        if action_kind == "click":
            candidates.extend([f"role:button:{hint}", f"role:link:{hint}"])
        candidates.extend([
            f"text:{hint}",
            f"label:{hint}",
            f"role:button:{hint}",
            f"role:link:{hint}",
            f"role:textbox:{hint}",
            f"placeholder:{hint}",
            f"title:{hint}",
        ])
        if fallback_selector:
            candidates.append(f"css:{fallback_selector}")
        return list(dict.fromkeys(candidates))

    async def _wait_and_retry(self, action: AgentAction, page: Page) -> RecoveryResult:
        """Wait for the page to stabilize, then locate the target in its active context."""
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=10000)
        await page.wait_for_timeout(2000)

        context = self._get_active_context(page)
        for candidate in self._candidate_targets(action.target, action.action_type):
            try:
                locator = self._locator_for_target(context, candidate)
                if await locator.count() > 0 and await locator.first.is_visible():
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.WAIT_AND_RETRY.value,
                        details=f"Element found after waiting via {candidate}",
                        resolved_target=candidate,
                    )
            except Exception:
                continue

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.WAIT_AND_RETRY.value,
            details="Target still not found and visible after waiting",
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

    async def _scroll_into_view(self, action: AgentAction, page: Page) -> RecoveryResult:
        """Scroll to bring the target element into the viewport."""
        if not action.target:
            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
                details="No target to scroll to",
            )

        context = self._get_active_context(page)
        for candidate in self._candidate_targets(action.target, action.action_type):
            try:
                locator = self._locator_for_target(context, candidate)
                if await locator.count() > 0 and await locator.first.is_visible():
                    await locator.first.scroll_into_view_if_needed(timeout=5000)
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
                        details=f"Scrolled element into view via {candidate}",
                        resolved_target=candidate,
                    )
            except Exception as e:
                logger.debug(
                    "scroll_into_view_candidate_failed",
                    candidate=candidate,
                    error=str(e),
                )

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.SCROLL_INTO_VIEW.value,
            details="Could not find target in the active context to scroll into view",
        )

    async def _relocate_element(self, action: AgentAction, page: Page) -> RecoveryResult:
        """Locate the failed target via alternatives in the active ServiceNow frame.

        The selected target is returned in RecoveryResult.resolved_target so
        the execution controller can retry with the locator that actually
        matched, rather than replaying the original failed target unchanged.
        """
        context = self._get_active_context(page)
        for candidate in self._candidate_targets(action.target, action.action_type):
            try:
                locator = self._locator_for_target(context, candidate)
                if await locator.count() > 0 and await locator.first.is_visible():
                    return RecoveryResult(
                        success=True,
                        strategy=RecoveryStrategy.RELOCATE_ELEMENT.value,
                        details=f"Relocated target via {candidate}",
                        resolved_target=candidate,
                    )
            except Exception as e:
                logger.debug(
                    "relocate_candidate_failed",
                    candidate=candidate,
                    error=str(e),
                )

        return RecoveryResult(
            success=False,
            strategy=RecoveryStrategy.RELOCATE_ELEMENT.value,
            details=f"Could not relocate element in active context: {action.target}",
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



