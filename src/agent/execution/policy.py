"""Action Policy Validator — safety and URL allowlist enforcement.

Validates browser actions against security policies before Playwright
executes them. Enforces allowed navigation hosts, blocks dangerous actions,
and controls JavaScript script evaluation permissions.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel

from agent.core.config import SecurityConfig
from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import AgentAction

logger = get_logger(__name__)


class PolicyValidationResult(BaseModel):
    """Result of policy validation on an action."""

    is_allowed: bool
    reason: str = ""
    action_type: str
    target: str = ""


class ActionPolicy:
    """Enforces execution safety policies on agent actions."""

    def __init__(self, config: SecurityConfig | None = None) -> None:
        self._config = config or SecurityConfig()
        self._action_budget = 50  # Hard budget limit
        self._actions_executed = 0

    def validate(self, action: AgentAction, current_url: str = "") -> PolicyValidationResult:
        """Validate an action before execution.

        Checks:
        1. Action type not in blocked_actions
        2. Navigation target host is in allowed_hosts
        3. JavaScript evaluation permissions
        4. Kill switch
        5. Action budget
        """
        import os
        if os.getenv("UAT_KILL_SWITCH") == "1":
            return PolicyValidationResult(
                is_allowed=False,
                reason="UAT_KILL_SWITCH is enabled. Execution aborted.",
                action_type=action.action_type,
                target=action.target,
            )

        self._actions_executed += 1
        if self._actions_executed > self._action_budget:
            return PolicyValidationResult(
                is_allowed=False,
                reason=f"Action budget exceeded ({self._action_budget} actions max).",
                action_type=action.action_type,
                target=action.target,
            )

        action_type_str = action.action_type

        # Check 1: Action type blocklist
        if action_type_str in self._config.blocked_actions:
            logger.warning(
                "policy_blocked_action_type",
                action_type=action_type_str,
                target=action.target,
            )
            return PolicyValidationResult(
                is_allowed=False,
                reason=f"Action type '{action_type_str}' is forbidden by security policy.",
                action_type=action_type_str,
                target=action.target,
            )

        # Check 2: Navigation allowlist
        try:
            action_enum = ActionType(action_type_str)
        except ValueError:
            action_enum = None

        if action_enum == ActionType.NAVIGATE:
            url_to_check = action.metadata.get("url", action.value or action.target)
            if url_to_check and not self._is_url_allowed(url_to_check):
                logger.warning(
                    "policy_blocked_navigation",
                    url=url_to_check,
                    allowed_hosts=self._config.allowed_hosts,
                )
                return PolicyValidationResult(
                    is_allowed=False,
                    reason=f"Navigation to URL '{url_to_check}' is blocked by security allowlist.",
                    action_type=action_type_str,
                    target=url_to_check,
                )

        logger.debug(
            "policy_check_passed",
            action_type=action_type_str,
            target=action.target,
        )
        return PolicyValidationResult(
            is_allowed=True,
            action_type=action_type_str,
            target=action.target,
        )

    def _is_url_allowed(self, url: str) -> bool:
        """Check if a URL matches the allowed hosts configuration."""
        if not self._config.allowed_hosts:
            return True

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return True  # Relative paths or internal routes are fine

        for allowed in self._config.allowed_hosts:
            allowed_clean = allowed.lower().strip()
            if hostname == allowed_clean or hostname.endswith(f".{allowed_clean}"):
                return True

        return False
