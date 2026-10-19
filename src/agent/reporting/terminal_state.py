"""Map final QA report verdicts to the agent's terminal runtime state.

The report's user-facing status and deterministic exit-criteria verdict must
both be considered. A run is never marked complete when its outcome is
blocked, inconclusive, failed, or not adequately verified.
"""
from __future__ import annotations

from agent.core.types import AgentState
from agent.domain.report import TestReport


def report_terminal_state(
    report: TestReport,
    failure_count: int,
) -> tuple[AgentState, str]:
    """Return the terminal agent state and an auditable transition reason."""
    status = str(getattr(report, "status", "") or "").strip().lower()
    exit_criteria = getattr(report, "exit_criteria", None)
    verdict = (
        str(exit_criteria.get("verdict", "") or "").strip().upper()
        if isinstance(exit_criteria, dict)
        else ""
    )
    failures = max(0, int(failure_count))

    if status == "cleanup_failed":
        return AgentState.CLEANUP_FAILED, "Report status is cleanup_failed"
    if status == "precondition_failed":
        return AgentState.PRECONDITION_FAILED, "Report status is precondition_failed"
    if status == "blocked" or verdict in {"BLOCKED", "INCONCLUSIVE"}:
        return (
            AgentState.BLOCKED,
            f"Run cannot be signed off: status={status or 'unknown'}, "
            f"verdict={verdict or 'BLOCKED'}",
        )
    if status in {"failed", "error"} or verdict in {"FAIL", "INFRA_ERROR"}:
        return (
            AgentState.FAILED,
            f"Run did not pass: status={status or 'unknown'}, "
            f"verdict={verdict or 'FAIL'}",
        )

    if status == "partial":
        if verdict == "CONDITIONAL_PASS" and failures == 0:
            return AgentState.COMPLETED, "Report status is partial (CONDITIONAL_PASS)"
        return (
            AgentState.FAILED,
            f"Unverified partial run: verdict={verdict or 'UNVERIFIED'}, "
            f"failures={failures}",
        )

    if (
        status == "passed"
        and verdict in {"", "PASS", "CONDITIONAL_PASS"}
        and failures == 0
    ):
        reason = (
            "Report status is passed (CONDITIONAL_PASS)"
            if verdict == "CONDITIONAL_PASS"
            else "Report status is passed"
        )
        return AgentState.COMPLETED, reason

    return (
        AgentState.FAILED,
        f"Unverified run outcome: status={status or 'missing'}, "
        f"verdict={verdict or 'UNVERIFIED'}, failures={failures}",
    )
