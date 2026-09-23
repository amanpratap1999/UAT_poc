"""Action Policy Validator — safety and URL allowlist enforcement.

Validates browser actions against security policies before Playwright
executes them. Enforces allowed navigation hosts, blocks dangerous actions,
and controls JavaScript script evaluation permissions.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from agent.core.config import SafetyBudgetConfig, SecurityConfig, get_settings
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
    """Enforces execution safety policies and budgets on agent actions."""

    def __init__(
        self,
        config: SecurityConfig | None = None,
        safety_budgets: SafetyBudgetConfig | None = None,
        run_id: str = "",
    ) -> None:
        self._config = config or SecurityConfig()
        settings = get_settings()
        self._budgets: SafetyBudgetConfig = safety_budgets or getattr(settings, "safety_budgets", None) or SafetyBudgetConfig()
        self.run_id = run_id

        # Budget tracking state
        self._actions_executed = 0
        self._mutations_executed = 0
        self._destructive_executed = 0
        self._records_touched: set[str] = set()
        self._tables_touched: set[str] = set()
        self._start_time = time.monotonic()

    def check_kill_switch(self) -> str | None:
        """Check whether execution has been killed via environment or durable state."""
        if os.getenv("UAT_KILL_SWITCH") == "1":
            return "UAT_KILL_SWITCH environment variable is enabled."

        # Check durable file kill switch
        kill_file = Path(".runtime/kill_switch")
        if kill_file.exists():
            return "Durable file kill switch (.runtime/kill_switch) is active."

        if self.run_id:
            run_kill_file = Path(f".runtime/kill_switch_{self.run_id}")
            if run_kill_file.exists():
                return f"Durable run kill switch for run {self.run_id} is active."

        # Redis is the durable cross-process kill switch in production.
        try:
            settings = get_settings()
            if settings.session.store_type == "redis":
                import redis as sync_redis

                client = sync_redis.Redis.from_url(
                    settings.session.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.25,
                )
                try:
                    if client.get("uat:kill_switch:global"):
                        return "Durable Redis global kill switch is active."
                    if self.run_id and client.get(f"uat:kill_switch:run:{self.run_id}"):
                        return f"Durable Redis kill switch for run {self.run_id} is active."
                finally:
                    client.close()
        except Exception as exc:
            is_prod = False
            try:
                settings = get_settings()
                is_prod = settings.runtime_mode == "docker" or settings.environment not in (
                    "development", "dev", "local"
                )
            except Exception:
                is_prod = True
            if is_prod:
                return f"Unable to verify durable Redis kill switch: {exc}"
            logger.warning("redis_kill_switch_check_failed", error=str(exc))

        return None

    def get_budget_state(self) -> dict[str, Any]:
        """Expose current budget utilization state."""
        return {
            "actions_executed": self._actions_executed,
            "max_actions": self._budgets.max_actions_per_run,
            "mutations_executed": self._mutations_executed,
            "max_mutations": self._budgets.max_mutations_per_run,
            "destructive_executed": self._destructive_executed,
            "max_destructive": self._budgets.max_destructive_operations,
            "records_touched": len(self._records_touched),
            "max_records": self._budgets.max_records_per_run,
            "tables_touched": len(self._tables_touched),
            "max_tables": self._budgets.max_tables_per_run,
            "time_elapsed": time.monotonic() - self._start_time,
            "max_time": self._budgets.max_run_time_seconds,
            "is_killed": bool(self.check_kill_switch()),
            "kill_reason": self.check_kill_switch(),
        }

    def validate(self, action: AgentAction, current_url: str = "") -> PolicyValidationResult:
        """Validate an action before execution against policies and safety budgets."""
        # 1. Kill switch
        kill_reason = self.check_kill_switch()
        if kill_reason:
            logger.critical("execution_killed_by_switch", reason=kill_reason)
            return PolicyValidationResult(
                is_allowed=False,
                reason=f"Execution aborted: {kill_reason}",
                action_type=action.action_type,
                target=action.target,
            )

        # 2. Time budget
        elapsed = time.monotonic() - self._start_time
        if elapsed > self._budgets.max_run_time_seconds:
            reason = f"Time budget exceeded ({elapsed:.1f}s > {self._budgets.max_run_time_seconds:.1f}s limit)."
            logger.warning("policy_budget_exceeded", metric="time", elapsed=elapsed)
            return PolicyValidationResult(
                is_allowed=False,
                reason=reason,
                action_type=action.action_type,
                target=action.target,
            )

        # 3. Action budget
        self._actions_executed += 1
        if self._actions_executed > self._budgets.max_actions_per_run:
            reason = f"Action budget exceeded ({self._actions_executed} > {self._budgets.max_actions_per_run} actions limit)."
            logger.warning("policy_budget_exceeded", metric="actions", current=self._actions_executed)
            return PolicyValidationResult(
                is_allowed=False,
                reason=reason,
                action_type=action.action_type,
                target=action.target,
            )

        action_type_str = (action.action_type or "").lower().strip()
        target_lower = (action.target or "").lower().strip()

        # 4. Destructive operations budget
        is_destructive = (
            "delete" in action_type_str
            or "sysverb_delete" in target_lower
            or "delete record" in target_lower
            or action.metadata.get("is_destructive") is True
        )
        if is_destructive:
            if self._destructive_executed >= self._budgets.max_destructive_operations:
                reason = (
                    f"Destructive operation budget exceeded ({self._destructive_executed} >= "
                    f"{self._budgets.max_destructive_operations} limit). Action blocked."
                )
                logger.error("policy_destructive_budget_blocked", action=action_type_str, target=action.target)
                return PolicyValidationResult(
                    is_allowed=False,
                    reason=reason,
                    action_type=action_type_str,
                    target=action.target,
                )
            self._destructive_executed += 1

        # 5. Mutation budget
        is_mutating = action_type_str in ("fill", "select", "check", "uncheck") or (
            action_type_str == "click"
            and any(v in target_lower for v in ("sysverb_update", "sysverb_insert", "sysverb_delete", "submit"))
        )
        if is_mutating:
            self._mutations_executed += 1
            if self._mutations_executed > self._budgets.max_mutations_per_run:
                reason = (
                    f"Mutation budget exceeded ({self._mutations_executed} > "
                    f"{self._budgets.max_mutations_per_run} mutations limit)."
                )
                logger.warning("policy_budget_exceeded", metric="mutations", current=self._mutations_executed)
                return PolicyValidationResult(
                    is_allowed=False,
                    reason=reason,
                    action_type=action_type_str,
                    target=action.target,
                )

        # 6. Record and Table budget
        record_id = action.metadata.get("record_id") or action.metadata.get("sys_id") or action.metadata.get("number")
        if record_id:
            self._records_touched.add(str(record_id))
            if len(self._records_touched) > self._budgets.max_records_per_run:
                reason = (
                    f"Record budget exceeded ({len(self._records_touched)} > "
                    f"{self._budgets.max_records_per_run} distinct records limit)."
                )
                logger.warning("policy_budget_exceeded", metric="records", current=len(self._records_touched))
                return PolicyValidationResult(
                    is_allowed=False,
                    reason=reason,
                    action_type=action_type_str,
                    target=action.target,
                )

        table_name = action.metadata.get("table")
        if table_name:
            self._tables_touched.add(str(table_name))
            if len(self._tables_touched) > self._budgets.max_tables_per_run:
                reason = (
                    f"Table budget exceeded ({len(self._tables_touched)} > "
                    f"{self._budgets.max_tables_per_run} distinct tables limit)."
                )
                logger.warning("policy_budget_exceeded", metric="tables", current=len(self._tables_touched))
                return PolicyValidationResult(
                    is_allowed=False,
                    reason=reason,
                    action_type=action_type_str,
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
            return False

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return True  # Relative paths or internal routes are fine

        for allowed in self._config.allowed_hosts:
            allowed_clean = allowed.lower().strip()
            if hostname == allowed_clean or hostname.endswith(f".{allowed_clean}"):
                return True

        return False
