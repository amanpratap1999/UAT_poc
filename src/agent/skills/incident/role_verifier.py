"""Runtime ServiceNow Role Verification (INC-UAT-04).

Verifies that the logged-in ServiceNow user's actual role matches the
expected role declared in the persona configuration. This is the runtime
equivalent of the static role metadata in ServiceNowConfig.

INC-UAT-04 (Major, D5/D10): Persona configuration stores credentials but
not an authoritative ServiceNow role/role-verification contract. The
'role' field in personas is a local label unless actual role is verified.
This module provides the runtime verification that queries the user's
actual ServiceNow roles after login and compares them to the expected role.
"""
from __future__ import annotations

from typing import Any

import httpx

from agent.core.config import ServiceNowConfig
from agent.core.logging import get_logger

logger = get_logger(__name__)


class RoleVerifier:
    """Verifies the logged-in ServiceNow user's actual role.

    INC-UAT-04 (Major): queries the ServiceNow Table API for the
    logged-in user's roles and compares them to the expected role
    declared in the persona configuration.

    Usage:
        verifier = RoleVerifier(config)
        result = await verifier.verify_role(expected_role="itil")
        if not result["match"]:
            raise SafetyViolationError(f"Role mismatch: expected 'itil', got {result['actual_roles']}")
    """

    def _evaluate_roles(
        self,
        data: dict[str, Any],
        expected_role: str,
        username: str,
    ) -> dict[str, Any]:
        """Parse roles from Table API response and check against expected role."""
        actual_roles: list[str] = []
        for row in data.get("result", []):
            dotted = str(row.get("role.name", "") or "").strip().lower()
            nested = row.get("role")
            nested_name = ""
            if isinstance(nested, dict):
                nested_name = str(
                    nested.get("display_value")
                    or nested.get("name")
                    or ""
                ).strip().lower()
            role_name = dotted or nested_name
            if role_name:
                actual_roles.append(role_name)
        actual_roles = sorted(set(actual_roles))

        privileged_roles = {
            "admin",
            "security_admin",
            "sn_admin",
            "maint",
        }
        privileged_present = sorted(set(actual_roles) & privileged_roles)
        match = expected_role.lower() in actual_roles and not privileged_present
        if privileged_present:
            logger.warning(
                "role_verification_privileged_role_detected",
                username=username,
                privileged_roles=privileged_present,
            )
        logger.info(
            "role_verification_complete",
            username=username,
            expected_role=expected_role,
            actual_roles=actual_roles,
            match=match,
        )
        return {
            "match": match,
            "actual_roles": actual_roles,
            "expected_role": expected_role,
            "username": username,
            "error": (
                f"Privileged ServiceNow role(s) present: {privileged_present}"
                if privileged_present else None
            ),
        }

    async def _verify_via_browser_session(
        self,
        config: ServiceNowConfig,
        username: str,
        password: str,
        expected_role: str,
    ) -> dict[str, Any]:
        """Fallback: verify roles via authenticated Playwright session when Basic Auth REST is unavailable (INC-UAT-04)."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(ignore_https_errors=True)
                page = await context.new_page()
                target_url = f"{config.instance_url.rstrip('/')}/login.do"
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                # Authenticate if login form is displayed
                user_input = page.locator("input#user_name, input[name='user_name']")
                if await user_input.count() > 0:
                    await user_input.first.fill(username)
                    pass_input = page.locator("input#user_password, input[name='user_password']")
                    if await pass_input.count() > 0:
                        await pass_input.first.fill(password)
                    login_btn = page.locator(
                        "button#sysverb_login, button:has-text('Log in'), input[type='submit']"
                    )
                    if await login_btn.count() > 0:
                        await login_btn.first.click()
                        try:
                            await page.wait_for_url(lambda u: "login.do" not in u.lower(), timeout=15000)
                        except Exception:
                            await page.wait_for_timeout(5000)

                g_ck = ""
                for _ in range(10):
                    g_ck = await page.evaluate(
                        "() => (typeof g_ck !== 'undefined' && g_ck ? g_ck : (window.g_ck || (window.NOW && window.NOW.g_ck) || ''))"
                    )
                    if g_ck:
                        break
                    await page.wait_for_timeout(1000)

                headers = {"Accept": "application/json"}
                if g_ck:
                    headers["X-UserToken"] = str(g_ck)

                api_url = (
                    f"{config.instance_url.rstrip('/')}/api/now/table/sys_user_has_role"
                    f"?sysparm_query=user.user_name={username}"
                    f"&sysparm_fields=role,role.name,user,user.name"
                    f"&sysparm_display_value=true"
                    f"&sysparm_limit=100"
                )
                resp = await page.request.get(api_url, headers=headers, timeout=15000)
                if resp.status != 200:
                    body_text = await resp.text()
                    raise RuntimeError(f"ServiceNow Table API returned HTTP {resp.status}: {body_text[:200]}")

                data = await resp.json()
                return self._evaluate_roles(data, expected_role, username)
            finally:
                await browser.close()

    async def verify_role(self, config: ServiceNowConfig, expected_role: str | None) -> dict[str, Any]:
        """Verify the logged-in user's actual ServiceNow roles.

        Args:
            config: ServiceNowConfig with instance_url + credentials.
            expected_role: the expected role (e.g., "itil"). If None,
                verification is skipped (backward compat).

        Returns:
            dict with keys:
            - match: bool (True if expected_role is in actual roles)
            - actual_roles: list[str] (the user's ServiceNow roles)
            - expected_role: str (what was expected)
            - username: str (the verified username)
            - error: str | None (if verification failed)
        """
        if not expected_role:
            return {
                "match": True,  # no expected role → vacuously true
                "actual_roles": [],
                "expected_role": None,
                "username": config.username,
                "error": None,
            }

        username, password = config.get_active_credentials()
        try:
            async with httpx.AsyncClient(
                base_url=config.instance_url,
                auth=(username, password),
                headers={"Accept": "application/json"},
                timeout=10.0,
            ) as client:
                response = await client.get(
                    "/api/now/table/sys_user_has_role",
                    params={
                        "sysparm_query": f"user.user_name={username}",
                        "sysparm_fields": "role,role.name,user,user.name",
                        "sysparm_display_value": "true",
                        "sysparm_limit": "100",
                    },
                )
                response.raise_for_status()
                data = response.json()
                return self._evaluate_roles(data, expected_role, username)
        except Exception as e:
            logger.info("role_verification_basic_auth_fallback", error=str(e))
            try:
                return await self._verify_via_browser_session(config, username, password, expected_role)
            except Exception as session_err:
                logger.warning(
                    "role_verification_failed",
                    error=str(session_err),
                    expected_role=expected_role,
                )
                return {
                    "match": False,
                    "actual_roles": [],
                    "expected_role": expected_role,
                    "username": username,
                    "error": str(session_err),
                }
