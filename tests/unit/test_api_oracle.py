"""Unit tests for the independent Table-API verification oracle (QA-005)."""

from __future__ import annotations

from agent.skills.incident.api_oracle import (
    IncidentApiOracle,
    IncidentApiSnapshot,
)


def _snapshot(**overrides: str) -> IncidentApiSnapshot:
    defaults = {
        "number": "INC0000007",
        "sys_id": "8d6353eac0a8016400d8a125ca14fc1f",
        "state": "2",
        "priority": "4",
        "impact": "3",
        "urgency": "3",
        "hold_reason": "Awaiting Caller",
        "short_description": "Need access to sales DB",
        "sys_updated_on": "2026-09-18 10:00:00",
    }
    defaults.update(overrides)
    return IncidentApiSnapshot(**defaults)


def test_check_assertion_state_accepts_value_and_label() -> None:
    snap = _snapshot()
    assert IncidentApiOracle.check_assertion("state", "2", snap) is True
    assert IncidentApiOracle.check_assertion("state", "In Progress", snap) is True
    assert IncidentApiOracle.check_assertion("state", "3", snap) is False
    assert IncidentApiOracle.check_assertion("state", "On Hold", snap) is False


def test_check_assertion_priority_and_text_fields() -> None:
    snap = _snapshot()
    assert IncidentApiOracle.check_assertion("priority", "4 - Low", snap) is True
    assert IncidentApiOracle.check_assertion("priority", "1 - Critical", snap) is False
    assert (
        IncidentApiOracle.check_assertion("hold_reason", "Awaiting Caller", snap) is True
    )
    assert (
        IncidentApiOracle.check_assertion("short_description", "need access to sales db", snap)
        is True
    )


def test_check_assertion_non_api_field_returns_none() -> None:
    snap = _snapshot()
    assert IncidentApiOracle.check_assertion("caller", "Abel Tuter", snap) is None


def test_verify_assertions_statuses() -> None:
    snap = _snapshot()
    result = IncidentApiOracle.verify_assertions(
        [("state", "In Progress"), ("caller", "Someone")], snap
    )
    assert result.status == "verified"
    assert result.evidence["fields_checked"] == 1
    assert result.evidence["sys_updated_on"] == snap.sys_updated_on

    mismatch = IncidentApiOracle.verify_assertions([("state", "On Hold")], snap)
    assert mismatch.status == "mismatch"
    assert mismatch.mismatches

    empty = IncidentApiOracle.verify_assertions([("caller", "Someone")], snap)
    assert empty.status == "not_found"