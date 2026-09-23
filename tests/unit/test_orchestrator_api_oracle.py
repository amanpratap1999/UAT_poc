"""Unit tests for QA-005: independent Table-API persistence oracle wiring.

Covers the orchestrator helpers (_is_save_click, _mutation_assertion) and the
fail-closed status semantics of _verify_persistence_via_api.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from agent.cognition.orchestrator import CognitiveOrchestrator
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.skills.incident.api_oracle import (
    ApiVerificationResult,
    IncidentApiSnapshot,
)


def _orchestrator(servicenow_cfg: Mock | None) -> CognitiveOrchestrator:
    settings = Mock()
    settings.servicenow = servicenow_cfg
    return CognitiveOrchestrator(
        skill_registry=Mock(),
        decision_engine=AsyncMock(),
        validation_engine=AsyncMock(),
        observation_engine=AsyncMock(),
        browser_manager=Mock(),
        execution_controller=AsyncMock(),
        settings=settings,
        llm_client=AsyncMock(),
    )


def _sn_config(**overrides: object) -> Mock:
    cfg = Mock()
    cfg.instance_url = "https://test.example.com"
    cfg.username = "qa_user"
    cfg.password = "qa_password"
    cfg.api_oracle_enabled = True
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _snapshot() -> IncidentApiSnapshot:
    return IncidentApiSnapshot(
        number="INC0000007",
        sys_id="abc123",
        state="2",
        priority="4",
        sys_updated_on="2026-09-18 10:00:00",
    )


class TestHelpers:
    def test_is_save_click(self) -> None:
        save = AgentAction(action_type=ActionType.CLICK, target="[sysverb_update]")
        not_save = AgentAction(action_type=ActionType.CLICK, target="Some button")
        fill = AgentAction(action_type=ActionType.FILL, target="[sysverb_update]")
        assert CognitiveOrchestrator._is_save_click(save) is True
        assert CognitiveOrchestrator._is_save_click(not_save) is False
        assert CognitiveOrchestrator._is_save_click(fill) is False

    def test_mutation_assertion_extracts_field_and_value(self) -> None:
        fill = AgentAction(
            action_type=ActionType.FILL,
            target="short_description",
            value="Need access",
        )
        assert CognitiveOrchestrator._mutation_assertion(fill) == (
            "short_description",
            "Need access",
        )

    def test_mutation_assertion_ignores_navigation(self) -> None:
        nav = AgentAction(
            action_type=ActionType.NAVIGATE, target="incident.do", value="x"
        )
        assert CognitiveOrchestrator._mutation_assertion(nav) is None

    def test_mutation_assertion_ignores_empty_value(self) -> None:
        fill = AgentAction(action_type=ActionType.FILL, target="state", value="")
        assert CognitiveOrchestrator._mutation_assertion(fill) is None


class TestVerifyPersistenceStatuses:
    @pytest.mark.asyncio
    async def test_no_servicenow_config_is_not_attempted(self) -> None:
        orch = _orchestrator(None)
        status, result = await orch._verify_persistence_via_api("INC1", [])
        assert status == "not_attempted"
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_flag_reports_disabled_not_verified(self) -> None:
        orch = _orchestrator(_sn_config(api_oracle_enabled=False))
        status, result = await orch._verify_persistence_via_api("INC1", [])
        assert status == "disabled"
        assert result is None

    @pytest.mark.asyncio
    async def test_record_not_found_fails_closed(self) -> None:
        """UI shows a record the API cannot see: status must be not_found."""
        orch = _orchestrator(_sn_config())
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(return_value=None),
        ):
            status, result = await orch._verify_persistence_via_api("INC1", [("state", "2")])
        assert status == "not_found"
        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_fails_closed(self) -> None:
        """Unreachable Table API must surface as error (UNVERIFIED), never
        as verified."""
        orch = _orchestrator(_sn_config())
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(side_effect=RuntimeError("connection refused")),
        ):
            status, result = await orch._verify_persistence_via_api(
                "INC1", [("state", "2")]
            )
        assert status == "error"
        assert result is None

    @pytest.mark.asyncio
    async def test_mismatch_surfaces_mismatches(self) -> None:
        orch = _orchestrator(_sn_config())
        snap = _snapshot()
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(return_value=snap),
        ), patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_audit_trail",
            new=AsyncMock(return_value=[]),
        ):
            status, result = await orch._verify_persistence_via_api(
                "INC0000007", [("state", "3")]
            )
        assert status == "mismatch"
        assert result is not None
        assert result.mismatches

    @pytest.mark.asyncio
    async def test_verified_when_all_checked_fields_match(self) -> None:
        orch = _orchestrator(_sn_config())
        snap = _snapshot()
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(return_value=snap),
        ), patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_audit_trail",
            new=AsyncMock(return_value=[
                {"fieldname": "state", "newvalue": "In Progress"},
                {"fieldname": "caller", "newvalue": "Abel"}
            ]),
        ):
            status, result = await orch._verify_persistence_via_api(
                "INC0000007", [("state", "In Progress"), ("caller", "Abel")]
            )
        assert status == "verified"
        assert result is not None
        assert result.evidence["fields_checked"] == 1

    @pytest.mark.asyncio
    async def test_non_verifiable_fields_report_partial_not_verified(self) -> None:
        """Record exists but no asserted field is API-verifiable: the result
        must be 'partial', never 'verified'."""
        orch = _orchestrator(_sn_config())
        snap = _snapshot()
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(return_value=snap),
        ):
            status, result = await orch._verify_persistence_via_api(
                "INC0000007", [("custom_field", "x")]
            )
        assert status == "partial"
        assert result is not None
        assert result.evidence.get("record_exists") is True

    @pytest.mark.asyncio
    async def test_no_assertions_reports_partial(self) -> None:
        orch = _orchestrator(_sn_config())
        snap = _snapshot()
        with patch(
            "agent.skills.incident.api_oracle.IncidentApiOracle.fetch_incident",
            new=AsyncMock(return_value=snap),
        ):
            status, result = await orch._verify_persistence_via_api("INC0000007", [])
        assert status == "partial"
        assert result is not None
        assert result.evidence["record_exists"] is True
