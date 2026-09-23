"""Execution controller — the bridge between LLM reasoning and the browser.

This is the critical architectural boundary. The planner emits structured
AgentAction objects. The execution controller dispatches each action to
the appropriate browser operation via the PageInteractor and BrowserManager.
On failure, it delegates to the RecoveryEngine before raising.

The LLM NEVER touches Playwright. This controller is the only path from
planner decisions to browser operations.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

from agent.core.config import ServiceNowConfig, get_settings
from agent.core.exceptions import (
    ElementNotInteractableError,
    ElementStaleError,
    NavigationTimeoutError,
    SelectorNotFoundError,
)
from agent.core.logging import get_logger
from agent.core.prompt_boundary import LLMInputBoundary
from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.execution.policy import ActionPolicy

if TYPE_CHECKING:
    from agent.browser.manager import BrowserManager
    from agent.browser.page_interactor import PageInteractor
    from agent.recovery.engine import RecoveryEngine

logger = get_logger(__name__)


class ExecutionController:
    """Translates structured AgentAction objects into browser operations.

    Dispatch table maps ActionType → handler method. Each handler wraps
    the browser interaction with error handling, timing, and screenshot
    capture.
    """

    def __init__(
        self,
        browser_manager: BrowserManager,
        page_interactor: PageInteractor,
        recovery_engine: RecoveryEngine | None = None,
        servicenow_config: ServiceNowConfig | None = None,
        action_policy: ActionPolicy | None = None,
    ) -> None:
        self._browser = browser_manager
        self._interactor = page_interactor
        self._recovery = recovery_engine
        self._servicenow_config = servicenow_config or get_settings().servicenow
        self._policy = action_policy or ActionPolicy(config=get_settings().security)

        # Action dispatch table
        self._handlers = {
            ActionType.CLICK: self._handle_click,
            ActionType.FILL: self._handle_fill,
            ActionType.SELECT: self._handle_select,
            ActionType.NAVIGATE: self._handle_navigate,
            ActionType.WAIT: self._handle_wait,
            ActionType.KEY_PRESS: self._handle_key_press,
            ActionType.SCROLL: self._handle_scroll,
            ActionType.SCREENSHOT: self._handle_screenshot,
            ActionType.VALIDATE: self._handle_validate,
            ActionType.VALIDATE_FIELD: self._handle_validate,
            ActionType.VALIDATE_STATE: self._handle_validate,
            ActionType.VALIDATE_ERRORS: self._handle_validate,
            ActionType.EXTRACT: self._handle_extract,
        }

    async def execute(self, action: AgentAction) -> ActionResult:
        """Execute an agent action via the browser.

        Dispatches to the appropriate handler based on action_type.
        Captures timing and screenshots. On failure, attempts recovery
        before returning the error result.

        Args:
            action: The structured action from the planner.

        Returns:
            An ActionResult with success/failure, timing, and evidence.
        """
        try:
            action_enum = ActionType(action.action_type)
            handler = self._handlers.get(action_enum)
        except ValueError:
            handler = None
        if not handler:
            return ActionResult(
                success=False,
                action=action,
                error=f"Unknown action type: {action.action_type}",
                error_type="UnknownActionType",
            )

        # P0 QA-007: Prod Mutation Gate
        is_mutating = action.action_type in ("fill", "select", "check", "uncheck") or (
            action.action_type == "click" and action.target and (
                "sysverb_update" in str(action.target).lower() or 
                "sysverb_insert" in str(action.target).lower() or
                "sysverb_delete" in str(action.target).lower()
            )
        )
        if is_mutating:
            if not getattr(self._servicenow_config, "is_subproduction", False):
                return ActionResult(
                    success=False,
                    action=action,
                    error="Mutations are denied on production instances. Set SERVICENOW_IS_SUBPRODUCTION=true.",
                    duration_ms=0,
                )
            if not getattr(self._servicenow_config, "allow_mutations", False):
                return ActionResult(
                    success=False,
                    action=action,
                    error="Mutations are denied by default. Set SERVICENOW_ALLOW_MUTATIONS=true.",
                    duration_ms=0,
                )

            allowed = getattr(self._servicenow_config, "allowed_instances", [])
            if not allowed:
                return ActionResult(
                    success=False,
                    action=action,
                    error="Mutations are denied: SERVICENOW_ALLOWED_INSTANCES is empty. An explicit hostname allowlist is mandatory.",
                    duration_ms=0,
                )

            from urllib.parse import urlparse
            url = getattr(self._servicenow_config, "instance_url", "")
            hostname = (urlparse(url).hostname or "").strip().lower()

            canonical_allowed: set[str] = set()
            for inst in allowed:
                inst_clean = str(inst).strip().lower()
                if not inst_clean or "*" in inst_clean or inst_clean.startswith("."):
                    logger.warning("invalid_allowlist_entry_ignored", entry=inst)
                    continue
                canonical_allowed.add(inst_clean)

            if not hostname or hostname not in canonical_allowed:
                return ActionResult(
                    success=False,
                    action=action,
                    error=(
                        f"Instance '{hostname}' is not in verified SERVICENOW_ALLOWED_INSTANCES "
                        f"({sorted(canonical_allowed)}) for mutations."
                    ),
                    duration_ms=0,
                )

        # Policy validation check
        current_url = ""
        try:
            current_url = await self._browser.get_url()
        except Exception:
            pass

        # Deterministic boundary for every planner-produced action.  This is
        # intentionally enforced here, immediately before browser dispatch,
        # so a malformed or prompt-injected action cannot bypass policy.
        boundary_ok, boundary_reason = LLMInputBoundary.validate_generated_action(
            action,
            allowed_tables=["incident"],
            allowed_hosts=getattr(get_settings().security, "allowed_hosts", None),
        )
        if not boundary_ok:
            logger.warning("action_blocked_by_llm_boundary", reason=boundary_reason)
            return ActionResult(
                success=False,
                action=action,
                error=f"LLM action boundary blocked action: {boundary_reason}",
                error_type="LLMActionBoundaryError",
            )

        policy_check = self._policy.validate(action, current_url=current_url)
        if not policy_check.is_allowed:
            logger.warning(
                "action_blocked_by_policy",
                action_type=action.action_type,
                reason=policy_check.reason,
            )
            return ActionResult(
                success=False,
                action=action,
                error=f"Security policy blocked action: {policy_check.reason}",
                error_type="PolicyBlockedError",
            )

        target_clean = action.target.strip().lower().rstrip(":")
        log_val = action.value[:50] if action.value else ""
        if "password" in target_clean:
            log_val = "********"

        logger.info(
            "executing_action",
            action_type=action.action_type,
            target=action.target,
            value=log_val,
        )

        start_time = time.perf_counter()

        try:
            await handler(action)

            # Wait for load / navigation / redirect settlement after interactive actions
            if action_enum in (ActionType.CLICK, ActionType.NAVIGATE, ActionType.KEY_PRESS):
                with contextlib.suppress(Exception):
                    await self._browser.wait_for_load()

            duration_ms = (time.perf_counter() - start_time) * 1000

            # Take a post-action screenshot for the timeline
            screenshot_path = await self._safe_screenshot(f"action_{action.action_type}")

            result = ActionResult(
                success=True,
                action=action,
                duration_ms=duration_ms,
                screenshot_path=screenshot_path,
            )
            logger.info(
                "action_succeeded",
                action_type=action.action_type,
                duration_ms=f"{duration_ms:.0f}",
            )
            return result

        except (
            SelectorNotFoundError,
            ElementNotInteractableError,
            ElementStaleError,
            NavigationTimeoutError,
        ) as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            screenshot_path = await self._safe_screenshot(f"error_{action.action_type}")

            logger.warning(
                "action_failed",
                action_type=action.action_type,
                error_type=type(e).__name__,
                error=str(e),
            )

            # Attempt recovery if engine is available
            if self._recovery:
                try:
                    recovery_result = await self._recovery.attempt_recovery(
                        error=e,
                        action=action,
                        page=self._browser.get_page(),
                    )
                    if recovery_result.success:
                        logger.info("recovery_succeeded", strategy=recovery_result.strategy)
                        try:
                            # Re-execute the original action now that the element is ready
                            await handler(action)
                            return ActionResult(
                                success=True,
                                action=action,
                                duration_ms=(time.perf_counter() - start_time) * 1000,
                                screenshot_path=await self._safe_screenshot("recovered"),
                                details={"recovered": True, "strategy": recovery_result.strategy},
                            )
                        except Exception as retry_e:
                            logger.warning("retry_after_recovery_failed", error=str(retry_e))
                            return ActionResult(
                                success=False,
                                action=action,
                                error=f"{type(e).__name__}: {str(e)} (Recovery tried but retry failed: {str(retry_e)})",
                                duration_ms=(time.perf_counter() - start_time) * 1000,
                                screenshot_path=screenshot_path,
                            )
                except Exception as recovery_error:
                    logger.warning("recovery_failed", error=str(recovery_error))

            return ActionResult(
                success=False,
                action=action,
                duration_ms=duration_ms,
                screenshot_path=screenshot_path,
                error=str(e),
                error_type=type(e).__name__,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            screenshot_path = await self._safe_screenshot(f"error_{action.action_type}")

            logger.error(
                "action_unexpected_error",
                action_type=action.action_type,
                error_type=type(e).__name__,
                error=str(e),
            )

            return ActionResult(
                success=False,
                action=action,
                duration_ms=duration_ms,
                screenshot_path=screenshot_path,
                error=str(e),
                error_type=type(e).__name__,
            )

    # -----------------------------------------------------------------------
    # Action handlers
    # -----------------------------------------------------------------------

    async def _handle_click(self, action: AgentAction) -> None:
        """Handle click actions.

        Uses coordinate-based clicking when visual grounding (e.g. Moondream)
        provided bounding-box coordinates, otherwise falls back to the
        standard text/CSS locator path.
        """
        if action.metadata.get("is_coordinate"):
            x = int(action.metadata["x"])
            y = int(action.metadata["y"])
            await self._interactor.click_coordinate(x, y)
        elif getattr(action, "coordinates", None):
            coords = getattr(action, "coordinates")
            await self._interactor.click_coordinate(int(coords[0]), int(coords[1]))
        else:
            await self._interactor.click(action.target)

    async def _handle_fill(self, action: AgentAction) -> None:
        """Handle fill actions — fill a form field with a value."""
        target = action.metadata.get(
            "resolved_locator",
            action.metadata.get("field_label", action.target),
        )
        target_clean = target.strip().lower().rstrip(":")

        # Secure credential substitution for login fields
        username_targets = {
            "username",
            "user name",
            "user id",
            "login id",
            "user_name",
            "user",
            "sys_user",
            "user_id",
            "login_id",
            "username field",
        }
        password_targets = {
            "password",
            "password field",
            "user_password",
            "sys_password",
            "password:",
            "user password",
        }

        if (
            target_clean in username_targets
            or "username" in target_clean
            or "user name" in target_clean
        ):
            value = self._servicenow_config.username or action.value
        elif target_clean in password_targets or "password" in target_clean:
            value = self._servicenow_config.password or action.value
        else:
            value = action.value

        await self._interactor.fill(target, value)

    async def _handle_select(self, action: AgentAction) -> None:
        """Handle select actions — select an option from a dropdown."""
        target = action.metadata.get(
            "resolved_locator",
            action.metadata.get("field_label", action.target),
        )
        if await self._interactor.is_select_value(target, action.value):
            action.metadata["no_op"] = True
            logger.info(
                "select_noop_skipped",
                target=target,
                value=action.value,
            )
            return
        await self._interactor.select_option(target, action.value)

    async def _handle_navigate(self, action: AgentAction) -> None:
        """Handle navigate actions — navigate to a URL."""
        url = action.metadata.get("url", action.value or action.target)
        if not url.startswith("http"):
            base_url = self._servicenow_config.instance_url.rstrip("/")
            url = f"{base_url}/{url.lstrip('/')}"
        await self._browser.navigate(url)

    async def _handle_wait(self, action: AgentAction) -> None:
        """Handle wait actions — wait for load, network, element, or duration."""
        wait_for = action.metadata.get("wait_for", "load")
        duration_ms = action.metadata.get("duration_ms", 2000)

        if wait_for == "load":
            await self._browser.wait_for_load()
        elif wait_for == "network_idle":
            await self._browser.wait_for_network_idle()
        elif wait_for == "element":
            await self._interactor.wait_for_element(action.target)
        elif wait_for == "duration":
            page = self._browser.get_page()
            await page.wait_for_timeout(duration_ms)

    async def _handle_key_press(self, action: AgentAction) -> None:
        """Handle key press actions."""
        key = action.metadata.get("key", action.value or "Enter")
        await self._interactor.press_key(key)

    async def _handle_scroll(self, action: AgentAction) -> None:
        """Handle scroll actions."""
        direction = action.metadata.get("direction", "down")
        amount = action.metadata.get("amount", 300)
        await self._interactor.scroll(direction, amount)

    async def _handle_screenshot(self, action: AgentAction) -> None:
        """Handle explicit screenshot requests."""
        name = action.metadata.get("name", action.value or "manual")
        await self._browser.take_screenshot(name)

    async def _handle_validate(self, action: AgentAction) -> None:
        """Handle validate actions — no browser operation, just observe."""
        # Validation is a planner-side concern; the execution controller
        # just needs to ensure the page is stable
        await self._browser.wait_for_load()

    async def _handle_extract(self, action: AgentAction) -> None:
        """Handle extract actions — read data from the page."""
        # Extraction is done through observation; this is a passthrough
        await self._browser.wait_for_load()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _safe_screenshot(self, name: str) -> str | None:
        """Take a screenshot, returning None on failure."""
        try:
            return await self._browser.take_screenshot(name)
        except Exception as e:
            logger.debug("screenshot_failed", error=str(e))
            return None
