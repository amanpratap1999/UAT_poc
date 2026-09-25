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

        try:
            username, password = config.get_active_credentials()
            async with httpx.AsyncClient(
                base_url=config.instance_url,
                auth=(username, password),
                headers={"Accept": "application/json"},
                timeout=10.0,
            ) as client:
                # Query the user's roles via the Table API
                # GET /api/now/table/sys_user_has_role?sysparm_query=user.userName=<username>&sysparm_fields=role.name
                response = await client.get(
                    "/api/now/table/sys_user_has_role",
                    params={
                        "sysparm_query": f"user.user_name={username}",
                        "sysparm_fields": "role.name",
                        "sysparm_limit": "100",
                    },
                )
                response.raise_for_status()
                data = response.json()
                actual_roles = [
                    r.get("role", {}).get("name", "").lower()
                    for r in data.get("result", [])
                    if r.get("role", {}).get("name")
                ]

                match = expected_role.lower() in actual_roles
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
                    "error": None,
                }
        except Exception as e:
            logger.warning(
                "role_verification_failed",
                error=str(e),
                expected_role=expected_role,
            )
            return {
                "match": False,
                "actual_roles": [],
                "expected_role": expected_role,
                "username": config.get_active_credentials()[0],
                "error": str(e),
            }
