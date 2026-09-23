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
from agent.skills.incident.domain.models import (
    IncidentPriority,
    IncidentState,
)

logger = get_logger(__name__)

_API_FIELDS = (
    "sys_id,number,state,priority,impact,urgency,hold_reason,"
    "short_description,sys_updated_on"
)


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
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApiVerificationResult:
    """Outcome of an independent API verification."""

    status: str  # "verified" | "mismatch" | "not_found" | "error"
    mismatches: list[str] = field(default_factory=list)
    snapshot: IncidentApiSnapshot | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class IncidentApiOracle:
    """Reads incident records from the ServiceNow Table API as an independent
    verification oracle.

    The oracle is strictly read-only: it never mutates records.
    """

    def __init__(
        self, config: ServiceNowConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.instance_url,
            auth=(config.username, config.password),
            headers={"Accept": "application/json"},
            timeout=20.0,
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def fetch_incident(self, number: str) -> IncidentApiSnapshot | None:
        """Fetch the server-side incident record by number.

        Returns:
            An IncidentApiSnapshot, or None when the record does not exist.

        Raises:
            RuntimeError: When the Table API is unreachable or rejects the
                request (auth/permission problems).
        """
        logger.info("api_oracle_fetch_incident", number=number)
        try:
            response = await self._client.get(
                "/api/now/table/incident",
                params={
                    "sysparm_query": f"number={number}",
                    "sysparm_fields": _API_FIELDS,
                    "sysparm_limit": "1",
                    "sysparm_display_value": "false",
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
        return IncidentApiSnapshot(
            number=record.get("number", ""),
            sys_id=record.get("sys_id"),
            state=str(record.get("state", "") or ""),
            priority=str(record.get("priority", "") or ""),
            impact=str(record.get("impact", "") or ""),
            urgency=str(record.get("urgency", "") or ""),
            hold_reason=record.get("hold_reason", "") or "",
            short_description=record.get("short_description", "") or "",
            sys_updated_on=record.get("sys_updated_on", "") or "",
            raw=record,
        )

    @staticmethod
    def check_assertion(
        field_name: str, expected: str, snapshot: IncidentApiSnapshot
    ) -> bool | None:
        """Check one assertion field against the server-side snapshot.

        Args:
            field_name: Canonical field name from the assertion (e.g. "state").
            expected: The asserted value (value or label, e.g. "2" or
                "In Progress").
            snapshot: The Table API snapshot.

        Returns:
            True/False when the field is API-verifiable, or None when the
            oracle cannot verify this field (not part of the API snapshot).
        """
        fname = (field_name or "").strip().lower()
        expected_val = (expected or "").strip()

        if fname in ("state", "incident state", "incident.state"):
            return (
                IncidentState.from_string(snapshot.state)
                == IncidentState.from_string(expected_val)
            )
        if fname == "priority":
            return (
                IncidentPriority.from_string(snapshot.priority)
                == IncidentPriority.from_string(expected_val)
            )
        if fname == "impact":
            return snapshot.impact.strip() == expected_val or (
                bool(snapshot.impact.strip())
                and expected_val.startswith(snapshot.impact.strip())
            )
        if fname == "urgency":
            return snapshot.urgency.strip() == expected_val or (
                bool(snapshot.urgency.strip())
                and expected_val.startswith(snapshot.urgency.strip())
            )
        if fname in ("hold_reason", "on hold reason", "hold reason"):
            return snapshot.hold_reason.strip().lower() == expected_val.lower()
        if fname in ("short_description", "short description"):
            return snapshot.short_description.strip().lower() == expected_val.lower()
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