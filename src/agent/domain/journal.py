"""Mutation Journal for tracking changes and executing authoritative cleanup.

Tracks all database/Table API record creations and field updates made during
a test run, enabling complete restoration of modified fields and deletion
of created records with 404 verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from agent.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MutationEntry:
    """A single record modification or creation event."""

    table: str
    record_id: str  # sys_id or record number
    action_type: str  # "create" | "update"
    sys_id: str | None = None
    pre_state: dict[str, Any] = field(default_factory=dict)
    post_state: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class MutationJournal:
    """Journal tracking all writes and creations during a test session."""

    def __init__(self) -> None:
        self.entries: list[MutationEntry] = []

    def record_create(
        self,
        table: str,
        record_id: str,
        sys_id: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> MutationEntry:
        """Record the creation of a new record in ServiceNow."""
        entry = MutationEntry(
            table=table,
            record_id=record_id,
            sys_id=sys_id,
            action_type="create",
            post_state=fields or {},
        )
        self.entries.append(entry)
        logger.info("journal_recorded_create", table=table, record_id=record_id, sys_id=sys_id)
        return entry

    def record_update(
        self,
        table: str,
        record_id: str,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
        sys_id: str | None = None,
    ) -> MutationEntry:
        """Record an update to an existing record, storing full pre-mutation baseline."""
        entry = MutationEntry(
            table=table,
            record_id=record_id,
            sys_id=sys_id,
            action_type="update",
            pre_state=dict(pre_state),
            post_state=dict(post_state),
        )
        self.entries.append(entry)
        logger.info(
            "journal_recorded_update",
            table=table,
            record_id=record_id,
            fields_changed=list(post_state.keys()),
        )
        return entry

    @property
    def created_records(self) -> list[MutationEntry]:
        return [e for e in self.entries if e.action_type == "create"]

    @property
    def updated_records(self) -> list[MutationEntry]:
        return [e for e in self.entries if e.action_type == "update"]

    async def execute_cleanup(
        self,
        client: httpx.AsyncClient | None = None,
        base_url: str = "",
    ) -> tuple[bool, list[str], list[dict[str, Any]]]:
        """Execute authoritative cleanup for all entries in the journal.

        Returns:
            (success, error_messages, orphaned_records)
        """
        errors: list[str] = []
        orphaned: list[dict[str, Any]] = []

        if not self.entries:
            return True, [], []

        # 1. Delete created records via Table API and verify 404
        for entry in self.created_records:
            target_id = entry.sys_id or entry.record_id
            table = entry.table
            logger.info("journal_cleaning_created_record", table=table, target_id=target_id)

            if client and base_url and target_id:
                try:
                    # DELETE /api/now/table/{table}/{target_id}
                    del_url = f"{base_url.rstrip('/')}/api/now/table/{table}/{target_id}"
                    del_resp = await client.delete(del_url)
                    if del_resp.status_code not in (200, 204, 404):
                        err = f"Failed to delete {table}/{target_id}: status {del_resp.status_code}"
                        errors.append(err)
                        orphaned.append({"table": table, "id": target_id, "error": err})
                        continue

                    # Verify 404
                    verify_resp = await client.get(del_url)
                    if verify_resp.status_code != 404:
                        err = f"Deletion verification failed for {table}/{target_id}: status {verify_resp.status_code}"
                        errors.append(err)
                        orphaned.append({"table": table, "id": target_id, "error": err})
                    else:
                        logger.info("journal_created_record_deleted_and_verified", table=table, target_id=target_id)
                except Exception as ex:
                    err = f"Exception deleting {table}/{target_id}: {ex}"
                    errors.append(err)
                    orphaned.append({"table": table, "id": target_id, "error": err})
            else:
                logger.warning("journal_cleanup_client_unavailable_for_delete", table=table, target_id=target_id)

        # 2. Restore updated records back to their pre_state
        for entry in self.updated_records:
            target_id = entry.sys_id or entry.record_id
            table = entry.table
            pre_state = entry.pre_state
            if not pre_state:
                continue

            logger.info("journal_restoring_updated_record", table=table, target_id=target_id, fields=list(pre_state.keys()))
            if client and base_url and target_id:
                try:
                    # Filter out system read-only metadata fields from pre_state payload
                    restore_payload = {
                        k: v for k, v in pre_state.items()
                        if not k.startswith("sys_") and k not in ("number", "sys_id")
                    }
                    if restore_payload:
                        patch_url = f"{base_url.rstrip('/')}/api/now/table/{table}/{target_id}"
                        patch_resp = await client.patch(patch_url, json=restore_payload)
                        if patch_resp.status_code not in (200, 201):
                            err = f"Failed to restore {table}/{target_id}: status {patch_resp.status_code}"
                            errors.append(err)
                            orphaned.append({"table": table, "id": target_id, "error": err})
                        else:
                            logger.info("journal_updated_record_restored", table=table, target_id=target_id)
                except Exception as ex:
                    err = f"Exception restoring {table}/{target_id}: {ex}"
                    errors.append(err)
                    orphaned.append({"table": table, "id": target_id, "error": err})

        success = len(errors) == 0
        return success, errors, orphaned
