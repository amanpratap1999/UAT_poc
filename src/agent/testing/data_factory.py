"""ServiceNow test data factory for preparing, seeding, and cleaning up test records.

Provides authoritative REST-based fixture management for benchmark suites,
reproducibility runs, and automated UAT execution. Guarantees complete cleanup
of all created and mutated records.
"""

from __future__ import annotations

import uuid
from typing import Any, cast
import httpx

from agent.core.config import Settings, get_settings
from agent.core.logging import get_logger

logger = get_logger(__name__)


class ServiceNowDataFactory:
    """Manages creation, verification, mutation, and cleanup of test records in ServiceNow."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._external_client = client
        self._created_records: list[tuple[str, str]] = []  # (table, sys_id)
        self._modified_records: list[tuple[str, str, dict[str, Any]]] = []  # (table, sys_id, original_values)

    async def __aenter__(self) -> ServiceNowDataFactory:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.cleanup()

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        pwd = self._settings.servicenow.password
        pwd_str = pwd.get_secret_value() if hasattr(pwd, "get_secret_value") else str(pwd)
        auth = (
            self._settings.servicenow.username,
            pwd_str,
        )
        return httpx.AsyncClient(
            base_url=self._settings.servicenow.instance_url.rstrip("/"),
            auth=auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
            verify=True,
        )

    async def create_test_incident(
        self,
        short_description: str | None = None,
        category: str = "Software",
        impact: str = "3",
        urgency: str = "3",
        caller_id: str | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an isolated test incident record via Table API."""
        run_tag = uuid.uuid4().hex[:6]
        desc = short_description or f"[UAT-TEST] Automated Incident {run_tag}"
        payload: dict[str, Any] = {
            "short_description": desc,
            "category": category,
            "impact": impact,
            "urgency": urgency,
        }
        if caller_id:
            payload["caller_id"] = caller_id
        if custom_fields:
            payload.update(custom_fields)

        client = self._get_client()
        should_close = self._external_client is None
        try:
            resp = await client.post("/api/now/table/incident", json=payload)
            resp.raise_for_status()
            data = cast(dict[str, Any], resp.json().get("result", {}))
            sys_id = data.get("sys_id", "")
            if sys_id:
                self._created_records.append(("incident", sys_id))
                logger.info(
                    "data_factory_record_created",
                    table="incident",
                    sys_id=sys_id,
                    number=data.get("number"),
                )
            return data
        finally:
            if should_close:
                await client.aclose()

    async def get_record(self, table: str, sys_id: str) -> dict[str, Any]:
        """Fetch current state of a record."""
        client = self._get_client()
        should_close = self._external_client is None
        try:
            resp = await client.get(f"/api/now/table/{table}/{sys_id}")
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json().get("result", {}))
        finally:
            if should_close:
                await client.aclose()

    def get_offline_discovery_records(self, table: str) -> dict[str, Any]:
        """Return offline mocked discovery records for testing without real API."""
        if table == "incident":
            return {
                "dictionary": [
                    {
                        "element": "short_description",
                        "column_label": "Short description",
                        "internal_type": {"value": "string"},
                        "mandatory": "true",
                        "read_only": "false",
                    },
                    {
                        "element": "state",
                        "column_label": "State",
                        "internal_type": {"value": "integer"},
                        "mandatory": "false",
                        "read_only": "false",
                    },
                ],
                "choices": [],
                "transitions": [],
                "mandatory": []
            }
        return {"dictionary": [], "choices": [], "transitions": [], "mandatory": []}

    async def verify_initial_state(
        self,
        table: str,
        sys_id: str,
        expected_fields: dict[str, Any],
    ) -> bool:
        """Verify preconditions: check that fields match expected initial values."""
        record = await self.get_record(table, sys_id)
        for field, expected_val in expected_fields.items():
            actual_val = record.get(field)
            if isinstance(actual_val, dict):
                actual_val = actual_val.get("value")
            if str(actual_val) != str(expected_val):
                logger.warning(
                    "data_factory_precondition_mismatch",
                    table=table,
                    sys_id=sys_id,
                    field=field,
                    expected=expected_val,
                    actual=actual_val,
                )
                return False
        return True

    async def seed_record_mutation(
        self,
        table: str,
        sys_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Mutate an existing record, recording original values for subsequent restore."""
        current = await self.get_record(table, sys_id)
        original_values = {k: current.get(k) for k in updates}
        self._modified_records.append((table, sys_id, original_values))

        client = self._get_client()
        should_close = self._external_client is None
        try:
            resp = await client.patch(f"/api/now/table/{table}/{sys_id}", json=updates)
            resp.raise_for_status()
            logger.info("data_factory_record_mutated", table=table, sys_id=sys_id, fields=list(updates.keys()))
            return cast(dict[str, Any], resp.json().get("result", {}))
        finally:
            if should_close:
                await client.aclose()

    async def cleanup(self) -> None:
        """Execute cleanup in LIFO order: restore modified records, delete created records."""
        client = self._get_client()
        should_close = self._external_client is None
        try:
            # 1. Restore modified records in reverse order
            while self._modified_records:
                table, sys_id, original_values = self._modified_records.pop()
                try:
                    patch_resp = await client.patch(
                        f"/api/now/table/{table}/{sys_id}",
                        json=original_values,
                    )
                    patch_resp.raise_for_status()
                    logger.info("data_factory_record_restored", table=table, sys_id=sys_id)
                except Exception as exc:
                    logger.error(
                        "data_factory_restore_failed",
                        table=table,
                        sys_id=sys_id,
                        error=str(exc),
                    )

            # 2. Delete created records in reverse order
            while self._created_records:
                table, sys_id = self._created_records.pop()
                try:
                    del_resp = await client.delete(f"/api/now/table/{table}/{sys_id}")
                    if del_resp.status_code not in (200, 204, 404):
                        logger.error(
                            "data_factory_delete_unexpected_status",
                            table=table,
                            sys_id=sys_id,
                            status=del_resp.status_code,
                        )
                    # Verify 404
                    check_resp = await client.get(f"/api/now/table/{table}/{sys_id}")
                    if check_resp.status_code != 404:
                        logger.error(
                            "data_factory_delete_verification_failed",
                            table=table,
                            sys_id=sys_id,
                            status=check_resp.status_code,
                        )
                    else:
                        logger.info("data_factory_record_deleted", table=table, sys_id=sys_id)
                except Exception as exc:
                    logger.error(
                        "data_factory_delete_failed",
                        table=table,
                        sys_id=sys_id,
                        error=str(exc),
                    )
        finally:
            if should_close:
                await client.aclose()
