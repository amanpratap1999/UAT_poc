"""Independent Table-API oracle for incident persistence verification (QA-005).

A browser-only observation of a freshly saved form is NOT sufficient evidence
that a mutation persisted: the UI may show optimistic/local state. This oracle
queries the ServiceNow Table API directly and compares the server-side record
against what the UI (and the test's assertions) expect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from agent.core.config import ServiceNowConfig
from agent.core.logging import get_logger
from agent.core.redaction import redact_dict
from agent.skills.incident.domain.models import (
    IncidentPriority,
    IncidentState,
)

logger = get_logger(__name__)

_API_FIELDS = (
    "sys_id,number,state,priority,impact,urgency,hold_reason,"
    "short_description,sys_updated_on,caller_id,assignment_group,"
    "assigned_to,category,subcategory,description,close_code,close_notes,"
    "resolved_by,resolved_at,closed_at,sys_created_on"
)

# INC-UAT-03 (Major, D3/D5): persona-constrained field sets.
# When oracle_persona_constrained=True, only fields visible to the active
# persona's role are queried — preventing the oracle from inspecting
# server-side audit data or admin-only fields that a normal UAT tester
# cannot see through the UI.
_PERSONA_VISIBLE_FIELDS = {
    "itil": (  # ITIL user (fulfiller) — can see most Incident fields
        "sys_id,number,state,priority,impact,urgency,"
        "short_description,caller_id,assignment_group,"
        "assigned_to,category,subcategory,description,"
        "close_code,close_notes,resolved_by,resolved_at,"
        "closed_at,sys_created_on,sys_updated_on"
    ),
    "requester": (  # Requester — sees only their own tickets + limited fields
        "sys_id,number,state,priority,short_description,"
        "caller_id,category,sys_created_on,sys_updated_on"
    ),
    "default": _API_FIELDS,  # backward compat — no constraint
}


def _get_persona_fields(persona_role: str | None) -> str:
    """Return the comma-separated field list for the given persona role.

    Falls back to the full _API_FIELDS set if no role-specific set is defined.
    """
    if not persona_role:
        return _API_FIELDS
    return _PERSONA_VISIBLE_FIELDS.get(persona_role.lower(), _API_FIELDS)


@dataclass
class IncidentApiSnapshot:
    """Server-side record values fetched from the Table API."""

    number: str = ""
    sys_id: str | None = None
    state: str = ""
    priority: str = ""
    impact: str = ""
    urgency: str = ""
    hold_reason: str = ""
    short_description: str = ""
    sys_updated_on: str = ""
    caller_id: str = ""
    assignment_group: str = ""
    assigned_to: str = ""
    category: str = ""
    subcategory: str = ""
    description: str = ""
    close_code: str = ""
    close_notes: str = ""
    resolved_by: str = ""
    resolved_at: str = ""
    closed_at: str = ""
    sys_created_on: str = ""
    display_values: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApiVerificationResult:
    """Outcome of an independent API verification."""

    status: str  # "verified" | "mismatch" | "not_found" | "error"
    mismatches: list[str] = field(default_factory=list)
    snapshot: IncidentApiSnapshot | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp_verified: bool = False
    audit_entries: list[dict[str, Any]] = field(default_factory=list)


class IncidentApiOracle:
    """Reads incident records and audit history from the ServiceNow Table API as an
    independent verification oracle.

    The oracle is strictly read-only: it never mutates records.
    """

    def __init__(
        self, config: ServiceNowConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        # INC-UAT-03: use persona credentials if active, not default admin creds.
        username, password = config.get_active_credentials()
        self._client = client or httpx.AsyncClient(
            base_url=config.instance_url,
            auth=(username, password),
            headers={"Accept": "application/json"},
            timeout=20.0,
        )

    # Audit issue I16 (P2) proper fix: public read-only accessor so
    # callers don't reach into self._client directly. Used by main.py
    # when invoking MutationJournal.execute_cleanup(client=...).
    def get_client(self) -> httpx.AsyncClient:
        """Return the underlying httpx client (read-only accessor for cross-component wiring)."""
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def fetch_incident(self, number: str) -> IncidentApiSnapshot | None:
        """Fetch the server-side incident record by number."""
        logger.info("api_oracle_fetch_incident", number=number)
        # INC-UAT-03: if oracle_persona_constrained is True, use the
        # persona-visible field set instead of the full _API_FIELDS.
        # This prevents the oracle from inspecting server-side fields
        # outside the normal UI experience.
        fields = _API_FIELDS
        if getattr(self._config, "oracle_persona_constrained", False):
            persona_role = self._config.get_persona_role()
            fields = _get_persona_fields(persona_role)
            logger.info(
                "api_oracle_persona_constrained",
                persona_role=persona_role,
                fields_count=len(fields.split(",")),
            )
        try:
            response = await self._client.get(
                "/api/now/table/incident",
                params={
                    "sysparm_query": f"number={number}",
                    "sysparm_fields": fields,
                    "sysparm_limit": "1",
                    "sysparm_display_value": "all",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("api_oracle_fetch_failed", number=number, error=str(e))
            raise RuntimeError(f"Table API fetch failed: {e}") from e

        results = response.json().get("result", [])
        if not results:
            return None
        record = results[0]

        disp_dict: dict[str, str] = {}

        def _val(k: str) -> str:
            v = record.get(k, "")
            if isinstance(v, dict):
                dv = str(v.get("display_value", "") or "")
                if dv:
                    disp_dict[k] = dv
                return str(v.get("value", "") or "")
            return str(v or "")

        num_val = _val("number") or str(record.get("number", ""))
        sys_id_val = _val("sys_id") or record.get("sys_id")
        if isinstance(sys_id_val, dict):
            sys_id_val = sys_id_val.get("value")

        return IncidentApiSnapshot(
            number=num_val,
            sys_id=str(sys_id_val) if sys_id_val else None,
            state=_val("state"),
            priority=_val("priority"),
            impact=_val("impact"),
            urgency=_val("urgency"),
            hold_reason=_val("hold_reason"),
            short_description=_val("short_description"),
            sys_updated_on=_val("sys_updated_on"),
            caller_id=_val("caller_id"),
            assignment_group=_val("assignment_group"),
            assigned_to=_val("assigned_to"),
            category=_val("category"),
            subcategory=_val("subcategory"),
            description=_val("description"),
            close_code=_val("close_code"),
            close_notes=_val("close_notes"),
            resolved_by=_val("resolved_by"),
            resolved_at=_val("resolved_at"),
            closed_at=_val("closed_at"),
            sys_created_on=_val("sys_created_on"),
            display_values=disp_dict,
            raw=redact_dict(record),
        )

    async def fetch_audit_trail(self, sys_id: str, since: str = "") -> list[dict[str, Any]]:
        """Fetch audit trail history for an incident document from sys_audit."""
        query = f"documentkey={sys_id}"
        if since:
            query += f"^sys_created_on>{since}"
        try:
            response = await self._client.get(
                "/api/now/table/sys_audit",
                params={
                    "sysparm_query": query,
                    "sysparm_fields": "fieldname,oldvalue,newvalue,sys_created_on,user",
                    "sysparm_display_value": "false",
                    "sysparm_limit": "50",
                },
            )
            response.raise_for_status()
            return response.json().get("result", [])  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            logger.warning("api_oracle_fetch_audit_failed", sys_id=sys_id, error=str(e))
            return []

    async def verify_mutation_in_audit(
        self, sys_id: str, field_name: str, expected_new_value: str, since: str = ""
    ) -> bool:
        """Verify that an audit entry exists documenting the field mutation."""
        entries = await self.fetch_audit_trail(sys_id, since=since)
        fn_clean = field_name.strip().lower().replace("incident.", "")
        exp_clean = expected_new_value.strip().lower()
        for e in entries:
            e_field = str(e.get("fieldname", "")).strip().lower()
            e_new = str(e.get("newvalue", "")).strip().lower()
            if e_field == fn_clean and (e_new == exp_clean or not exp_clean):
                return True
        return False

    @staticmethod
    def verify_timestamp_advanced(
        before_timestamp: str, snapshot: IncidentApiSnapshot
    ) -> bool:
        """Verify that sys_updated_on advanced after the mutation."""
        if not snapshot.sys_updated_on:
            return False
        if not before_timestamp:
            return True
        return snapshot.sys_updated_on > before_timestamp

    @staticmethod
    def check_assertion(
        field_name: str, expected: str, snapshot: IncidentApiSnapshot
    ) -> bool | None:
        """Check one assertion field against the server-side snapshot."""
        fname = (field_name or "").strip().lower()
        expected_val = (expected or "").strip()

        if fname in ("state", "incident state", "incident.state"):
            return (
                IncidentState.from_string(snapshot.state)
                == IncidentState.from_string(expected_val)
            )
        if fname in ("priority", "incident.priority"):
            return (
                IncidentPriority.from_string(snapshot.priority)
                == IncidentPriority.from_string(expected_val)
            )
        if fname in ("impact", "incident.impact"):
            exp_code = expected_val.split("-")[0].strip().lower() if "-" in expected_val else expected_val.strip().lower()
            disp = snapshot.display_values.get("impact", "").strip().lower()
            val = snapshot.impact.strip().lower()
            return val == exp_code or val == expected_val.strip().lower() or (bool(disp) and disp == expected_val.strip().lower())
        if fname in ("urgency", "incident.urgency"):
            exp_code = expected_val.split("-")[0].strip().lower() if "-" in expected_val else expected_val.strip().lower()
            disp = snapshot.display_values.get("urgency", "").strip().lower()
            val = snapshot.urgency.strip().lower()
            return val == exp_code or val == expected_val.strip().lower() or (bool(disp) and disp == expected_val.strip().lower())
        if fname in ("hold_reason", "on hold reason", "hold reason", "incident.hold_reason"):
            return snapshot.hold_reason.strip().lower() == expected_val.lower()
        if fname in ("short_description", "short description", "incident.short_description"):
            return snapshot.short_description.strip().lower() == expected_val.lower()
        if fname in ("assignment_group", "assignment group", "incident.assignment_group"):
            exp = expected_val.strip().lower()
            val = snapshot.assignment_group.strip().lower()
            disp = snapshot.display_values.get("assignment_group", "").strip().lower()
            return exp == val or (bool(disp) and exp == disp)
        if fname in ("assigned_to", "assigned to", "incident.assigned_to"):
            exp = expected_val.strip().lower()
            val = snapshot.assigned_to.strip().lower()
            disp = snapshot.display_values.get("assigned_to", "").strip().lower()
            return exp == val or (bool(disp) and exp == disp)
        if fname in ("caller_id", "incident.caller_id"):
            exp = expected_val.strip().lower()
            val = snapshot.caller_id.strip().lower()
            disp = snapshot.display_values.get("caller_id", "").strip().lower()
            return exp == val or (bool(disp) and exp == disp)
        if fname in ("category", "incident.category"):
            return snapshot.category.strip().lower() == expected_val.lower()
        if fname in ("subcategory", "incident.subcategory"):
            return snapshot.subcategory.strip().lower() == expected_val.lower()
        if fname in ("description", "incident.description"):
            return snapshot.description.strip().lower() == expected_val.lower()
        if fname in ("close_code", "resolution code", "incident.close_code"):
            return snapshot.close_code.strip().lower() == expected_val.lower()
        if fname in ("close_notes", "resolution notes", "incident.close_notes"):
            return snapshot.close_notes.strip().lower() == expected_val.lower()
        return None

    @classmethod
    def verify_assertions(
        cls,
        assertions: list[tuple[str, str]],
        snapshot: IncidentApiSnapshot,
    ) -> ApiVerificationResult:
        """Verify a batch of (field, expected) assertions against the API."""
        mismatches: list[str] = []
        checked = 0
        for field_name, expected in assertions:
            outcome = cls.check_assertion(field_name, expected, snapshot)
            if outcome is None:
                continue
            checked += 1
            if not outcome:
                mismatches.append(
                    f"{field_name}: API actual={snapshot.raw.get(field_name.lower(), '?')!r}, "
                    f"asserted={expected!r}"
                )
        return ApiVerificationResult(
            status=(
                "mismatch"
                if mismatches
                else "verified" if checked else "not_found"
            ),
            mismatches=mismatches,
            snapshot=snapshot,
            evidence={
                "fields_checked": checked,
                "sys_updated_on": snapshot.sys_updated_on,
                "sys_id": snapshot.sys_id,
            },
        )
