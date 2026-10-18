"""Regression tests for final report-to-runtime state reconciliation."""
from __future__ import annotations

import pytest

from agent.core.types import AgentState
from agent.domain.report import TestReport
from agent.reporting.terminal_state import report_terminal_state


def _report(status: str, verdict: str | None = None) -> TestReport:
    return TestReport(
        report_id="RPT-TERMINAL-TEST",
        goal="Test terminal state mapping",
        status=status,
        exit_criteria={"verdict": verdict} if verdict is not None else None,
    )


@pytest.mark.parametrize(
    ("status", "verdict", "failures", "expected"),
    [
        ("cleanup_failed", "FAIL", 1, AgentState.CLEANUP_FAILED),
        ("precondition_failed", "INCONCLUSIVE", 0, AgentState.PRECONDITION_FAILED),
        ("blocked", "BLOCKED", 0, AgentState.BLOCKED),
        ("passed", "INCONCLUSIVE", 0, AgentState.BLOCKED),
        ("failed", "FAIL", 1, AgentState.FAILED),
        ("error", "INFRA_ERROR", 1, AgentState.FAILED),
        ("partial", "CONDITIONAL_PASS", 0, AgentState.COMPLETED),
        ("partial", "CONDITIONAL_PASS", 1, AgentState.FAILED),
        ("passed", "PASS", 0, AgentState.COMPLETED),
        ("passed", None, 0, AgentState.COMPLETED),
        ("passed", "FAIL", 0, AgentState.FAILED),
        ("passed", "PASS", 1, AgentState.FAILED),
        ("unknown", None, 0, AgentState.FAILED),
    ],
)
def test_report_terminal_state_is_fail_closed(
    status: str,
    verdict: str | None,
    failures: int,
    expected: AgentState,
) -> None:
    state, reason = report_terminal_state(_report(status, verdict), failures)
    assert state == expected
    assert reason
