"""Reporting engine — generates professional QA reports from session memory.

Produces both HTML and Markdown reports with execution timelines,
validation summaries, defect lists, browser logs, and LLM-generated
executive summaries with root-cause hypotheses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.core.logging import get_logger
from agent.core.types import Severity
from agent.domain.defect_scope import (
    VERIFIED_DEFECT_ERROR_TYPE,
    classify_step_failure,
)
from agent.domain.report import (
    AgentIssueReport,
    BrowserLogEntry,
    DefectReport,
    TestReport,
    TimelineEntry,
)
from agent.memory.session import SessionMemory

logger = get_logger(__name__)


def _step_text(step: Any) -> str:
    """Render a planned step (dict or TestStep) as readable text."""
    if isinstance(step, dict):
        at = step.get("action_type", "")
        target = step.get("target", "")
        value = step.get("value", "")
        expected = step.get("expected_outcome", "")
        text = f"{at} {target}".strip()
        if value:
            text += f" with '{value}'"
        if expected:
            text += f" | {expected}"
        return text
    return str(step)


def _stringify_cell(value: Any) -> str:
    """Render a cell value (dict/list/other) as compact text for XLSX."""
    if isinstance(value, dict):
        try:
            import json as _json

            return _json.dumps(value, default=str)
        except Exception:
            return str(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


class ReportingEngine:
    """Generates comprehensive QA test reports from session memory.

    Produces structured reports with:
    - Execution timeline with screenshots
    - Validation summary (pass/fail breakdown)
    - Defect reports with evidence
    - Browser and console logs
    - Executive summary and recommendations
    """

    def __init__(self, output_dir: Path = Path("reports")) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_report(
        self,
        memory: SessionMemory,
        summary_data: dict[str, Any] | None = None,
    ) -> TestReport:
        """Generate a complete QA report from session memory.

        Args:
            memory: The session memory containing all execution data.
            summary_data: Optional LLM-generated summary data.

        Returns:
            A fully populated TestReport.
        """
        logger.info("generating_report", session_id=memory.session_id)

        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC)

        # Build timeline from memory
        timeline = self._build_timeline(memory)

        # Compute validation stats
        passed = sum(1 for v in memory.completed_validations if v.overall_passed)
        failed = sum(1 for v in memory.completed_validations if not v.overall_passed)
        total = len(memory.completed_validations)

        # Build validation details
        validation_details = [
            {
                "action": v.action_description,
                "passed": v.overall_passed,
                "checks": len(v.checks),
                "failed_checks": [c.check_name for c in v.failed_checks],
            }
            for v in memory.completed_validations
        ]

        # Identify application defects and agent issues (scope-classified)
        (
            defects,
            agent_issues,
            agent_issue_count,
            application_mismatch_count,
        ) = self._identify_defects(memory)

        # Build browser logs
        browser_logs = self._build_browser_logs(memory)

        # Collect all screenshots
        screenshots = [entry.screenshot_path for entry in memory.timeline if entry.screenshot_path]

        # Step evidence
        step_evidence: list[dict[str, Any]] = []
        for step in memory.completed_steps:
            ev: dict[str, Any] = {
                "step_index": step.step_index,
                "action": step.action.action_type if hasattr(step.action, "action_type") else str(step.action),
                "target": getattr(step.action, "target", ""),
                "result": "success" if (hasattr(step.result, "success") and step.result.success) else "failed",
                "screenshot_path": getattr(step.result, "screenshot_path", None),
            }
            if hasattr(step.result, "details") and isinstance(step.result.details, dict):
                if "perception" in step.result.details:
                    ev["perception"] = step.result.details["perception"]
            step_evidence.append(ev)

        # Determine overall status.
        #
        # Strict QA status semantics:
        # - "precondition_failed": Required initial conditions (e.g. record number or initial state) were not met before mutation.
        # - "failed": QA verdict is FAIL because application defects exist, acceptance criteria failed, or validation checks failed.
        # - "blocked": Engine was blocked from starting or executing.
        # - "error": Engine encountered an internal execution or runtime failure.
        # - "passed": ONLY when all executed validations passed (failed == 0, passed > 0), no application defects exist, and no preconditions failed.
        has_application_defects = len(defects) > 0

        precondition_failure = (
            getattr(memory, "precondition_failed", False)
            or any(
                getattr(v, "precondition_failed", False)
                for v in memory.completed_validations
            )
            or any(
                getattr(getattr(step, "validation", None), "precondition_failed", False)
                for step in memory.completed_steps
            )
        )

        if precondition_failure:
            status = "precondition_failed"
            # Hard QA rule: An application defect can ONLY exist if preconditions
            # passed and the action was executed. Precondition failures yield 0 defects.
            defects = []
        elif memory.total_actions_executed == 0 and len(memory.completed_steps) == 0:
            status = "error" if memory.total_failures > 0 else "blocked"
        elif has_application_defects:
            status = "failed" if passed == 0 else "partial"
        elif failed > 0:
            status = "failed" if passed == 0 else "partial"
        elif memory.total_failures > 0:
            status = "failed"
        elif passed > 0:
            status = "passed"
        else:
            status = "blocked"

        # Calculate duration
        duration = (now - memory.started_at).total_seconds()

        # Augment step_evidence with canonical plan steps if present
        if getattr(memory, "plan", None) and memory.plan.steps:
            existing_indices = {se.get("step_index") for se in step_evidence if isinstance(se, dict)}
            for s in memory.plan.steps:
                if s.step_index not in existing_indices:
                    step_evidence.append(
                        {
                            "step_index": s.step_index,
                            "action": "plan_step",
                            "target": s.description,
                            "result": s.status.value if hasattr(s.status, "value") else str(s.status),
                            "error": s.error,
                            "observed_values": s.observed_values,
                            "expected_values": s.expected_values,
                        }
                    )

        report = TestReport(
            report_id=report_id,
            goal=memory.goal,
            test_case=memory.test_case_data or None,
            status=status,
            started_at=memory.started_at,
            completed_at=now,
            duration_seconds=duration,
            timeline=timeline,
            total_validations=total,
            passed_validations=passed,
            failed_validations=failed,
            validation_details=validation_details,
            defects=defects,
            agent_issues=agent_issues,
            browser_logs=browser_logs,
            console_errors=list(getattr(memory, "console_errors", [])) + [
                f.error_message
                for f in memory.failures
                if "js" in f.error_type.lower() or "console" in f.error_type.lower()
            ],
            screenshots=screenshots,
            step_evidence=step_evidence,
            environment={
                "session_id": memory.session_id,
                "url": memory.current_url,
                "persona": getattr(memory, "persona", "") or "",
                "story_id": (memory.test_case_data or {}).get("story_id") or "",
            },
        )

        # Apply LLM-generated summary if available
        if summary_data:
            report.summary = summary_data.get("summary", "")
            report.recommendations = summary_data.get("recommendations", [])
            # Apply root cause hypotheses to defects
            for hypothesis in summary_data.get("root_cause_hypotheses", []):
                defect_id = hypothesis.get("defect_id", "")
                for defect in report.defects:
                    if defect.defect_id == defect_id:
                        defect.root_cause_hypothesis = hypothesis.get("hypothesis", "")

        logger.info(
            "report_generated",
            report_id=report_id,
            status=status,
            defects=len(defects),
        )
        return report

    def _build_timeline(self, memory: SessionMemory) -> list[TimelineEntry]:
        """Build the execution timeline from session memory."""
        return list(memory.timeline)

    def _identify_defects(
        self, memory: SessionMemory
    ) -> tuple[list[DefectReport], list[AgentIssueReport], int, int]:
        """Identify APPLICATION defects and AGENT issues from session evidence.

        Preserves the conceptual separation between application defects and
        agent/execution issues (see ``agent.domain.defect_scope``):

        - **Application defect** — the step's interaction executed and the
          failed checks are about the application's observed behavior, with
          either an investigation verdict confirming a genuine defect, or no
          verdict but application-behavior evidence (routed for review, not
          silently discarded).
        - **Agent issue** — the engine could not perform/observe/verify:
          failed ActionResult, agent-capability checks (action_execution,
          page_responded, behavioral_verification), or runtime errors. Never
          counted as a defect, never discarded — preserved in agent_issues.

        Investigation verdicts (``memory.defect_verdicts``, hypothesis-keyed)
        supersede raw validation failures: confirmed defects are counted once;
        cleared mismatches (false-positive customizations) are withdrawn.

        Returns:
            (defects, agent_issues, agent_issue_count, application_mismatch_count)
        """  # noqa: D401
        defects: list[DefectReport] = []
        agent_issues: list[AgentIssueReport] = []
        application_mismatch_count = 0

        # Authoritative investigation verdicts, keyed by step index (the
        # cognitive loop records verdicts with the completed step's index).
        cleared_steps: set[int] = {
            v.step_index for v in memory.defect_verdicts if not v.is_defect
        }

        defect_counter = 0
        issue_counter = 0
        counted_steps: set[int] = set()

        for step in memory.completed_steps:
            if not (step.validation and not step.validation.overall_passed):
                continue

            scope = classify_step_failure(step.result, step.validation)

            if scope == "precondition":
                # Initial record/environment state did not meet test prerequisites.
                issue_counter += 1
                failed_checks = step.validation.failed_checks
                check_names = ", ".join(c.check_name for c in failed_checks) or "Precondition"
                agent_issues.append(
                    AgentIssueReport(
                        issue_id=f"PRE-{issue_counter:03d}",
                        title=f"Precondition check failed ({check_names})",
                        description=(
                            f"Step {step.step_index}: initial test precondition was not met. "
                            f"{'; '.join(c.error_message or c.actual for c in failed_checks)}. "
                            f"This is a test precondition failure, not an application defect."
                        ),
                        category="precondition_failed",
                        related_step_index=step.step_index,
                        error_type="PreconditionFailedError",
                    )
                )
                continue

            if scope == "agent":
                # The engine could not perform/observe/verify — diagnostic only.
                issue_counter += 1
                failed_checks = step.validation.failed_checks
                check_names = ", ".join(c.check_name for c in failed_checks) or "unknown"
                error_type = getattr(step.result, "error_type", None) or "AgentSideFailure"
                agent_issues.append(
                    AgentIssueReport(
                        issue_id=f"AGI-{issue_counter:03d}",
                        title=f"Agent-side validation failure ({check_names})",
                        description=(
                            f"Step {step.step_index}: the QA agent could not "
                            f"perform, observe, or verify the interaction "
                            f"({error_type}: {getattr(step.result, 'error', None) or 'no error recorded'}). "
                            f"This is an agent/execution issue, not an application defect."
                        ),
                        category=self._categorize_issue(error_type, check_names),
                        related_step_index=step.step_index,
                        error_type=error_type,
                    )
                )
                continue

            if scope is None:
                continue

            # Application-scope mismatch.
            application_mismatch_count += 1

            # Investigation verdict supersedes raw validation failure: a
            # cleared verdict (false-positive customization / learned
            # behavior) withdraws the defect for this step.
            if step.step_index in cleared_steps:
                continue

            defect_counter += 1
            failed_checks = step.validation.failed_checks
            check_names = [c.check_name for c in failed_checks]
            check_details = "; ".join(
                f"{c.check_name}: expected={c.expected}, actual={c.actual}"
                for c in failed_checks
            )

            evidence: list[str] = []
            if step.result.screenshot_path:
                evidence.append(step.result.screenshot_path)

            defects.append(
                DefectReport(
                    defect_id=f"DEF-{defect_counter:03d}",
                    severity=self._assess_severity(failed_checks),
                    title=f"Validation failure: {', '.join(check_names)}",
                    description=check_details,
                    expected_behavior="; ".join(c.expected for c in failed_checks),
                    actual_behavior="; ".join(c.actual for c in failed_checks),
                    evidence=evidence,
                    related_step_index=step.step_index,
                )
            )
            counted_steps.add(step.step_index)

        # Investigated mismatches at steps not covered above (e.g. the verdict
        # exists but the corresponding validation record is agent-scope or
        # absent): investigation-confirmed defects are counted here, once.
        for verdict in memory.defect_verdicts:
            if not verdict.is_defect:
                continue
            if verdict.step_index in counted_steps:
                continue
            defect_counter += 1
            defects.append(
                DefectReport(
                    defect_id=f"DEF-{defect_counter:03d}",
                    severity=Severity.HIGH,
                    title="Investigated application defect",
                    description=(
                        f"{verdict.reasoning or 'Investigation confirmed a defect'}"
                        + (f" (hypothesis {verdict.hypothesis_id})" if verdict.hypothesis_id else "")
                    ),
                    actual_behavior=verdict.reasoning,
                    related_step_index=verdict.step_index,
                )
            )
            counted_steps.add(verdict.step_index)

        # Runtime/planning/browser failures without a verdict — agent issues,
        # never defects. InvestigationVerifiedDefect failures are covered by
        # the verdict loop above (verdicts are the authority); a stale
        # failure without a verdict is treated as an agent-side record to
        # guarantee it can never silently inflate the defect count.
        for failure in memory.failures:
            if failure.error_type == VERIFIED_DEFECT_ERROR_TYPE:
                continue
            issue_counter += 1
            agent_issues.append(
                AgentIssueReport(
                    issue_id=f"AGI-{issue_counter:03d}",
                    title=f"Agent failure: {failure.error_type}",
                    description=failure.error_message,
                    category=self._categorize_issue(failure.error_type, ""),
                    related_step_index=failure.step_index,
                    error_type=failure.error_type,
                )
            )

        return defects, agent_issues, len(agent_issues), application_mismatch_count

    def _categorize_issue(self, error_type: str, check_names: str) -> str:
        """Categorize an agent issue for diagnostics."""
        token = (error_type or "").lower()
        checks = (check_names or "").lower()
        if any(
            k in token
            for k in ("grounding", "perception", "moondream", "gemini", "vision")
        ) or any(k in checks for k in ("perception", "grounding")):
            return "perception"
        if any(k in token for k in ("verification", "verifier")) or "behavioral" in checks:
            return "verification"
        if any(k in token for k in ("planner", "planning", "hypothesis", "llm")):
            return "planning"
        if any(
            k in token
            for k in ("browser", "playwright", "page", "navigation", "protocol")
        ):
            return "runtime"
        return "execution"

    def _assess_severity(self, failed_checks: list) -> Severity:  # type: ignore[type-arg]
        """Assess defect severity based on the types of failed checks."""
        critical_checks = {"action_execution", "state_change", "page_navigation"}
        high_checks = {"field_update", "no_js_errors"}

        check_names = {c.check_name for c in failed_checks}

        if check_names & critical_checks:
            return Severity.CRITICAL
        if check_names & high_checks:
            return Severity.HIGH
        return Severity.MEDIUM

    def _build_browser_logs(self, memory: SessionMemory) -> list[BrowserLogEntry]:
        """Compile browser log entries from browser telemetry, errors, and failure records."""
        logs: list[BrowserLogEntry] = []

        # 1. Playwright console logs
        for entry in getattr(memory, "browser_logs", []):
            lvl = entry.get("level", "info")
            msg = entry.get("message", "")
            if msg:
                logs.append(
                    BrowserLogEntry(
                        level=lvl,
                        message=msg,
                        source="browser",
                    )
                )

        # 2. Page errors
        for err in getattr(memory, "console_errors", []):
            logs.append(
                BrowserLogEntry(
                    level="error",
                    message=f"[PageError] {err}",
                    source="browser",
                )
            )

        # 3. Network errors
        for net_err in getattr(memory, "network_errors", []):
            logs.append(
                BrowserLogEntry(
                    level="warning",
                    message=f"[NetworkError] {net_err}",
                    source="network",
                )
            )

        # 4. Memory failures
        for failure in memory.failures:
            logs.append(
                BrowserLogEntry(
                    level="error",
                    message=f"[{failure.error_type}] {failure.error_message}",
                    source="agent",
                )
            )
        return logs

    async def render_markdown(self, report: TestReport) -> str:
        """Render the report as a Markdown document.

        Args:
            report: The TestReport to render.

        Returns:
            Markdown string.
        """
        lines = [
            f"# QA Test Report: {report.report_id}",
            "",
            f"**Goal:** {report.goal}",
            f"**Status:** {report.status.upper()}",
            f"**Duration:** {report.duration_seconds:.1f}s",
            f"**Started:** {report.started_at.isoformat()}",
            f"**Completed:** {report.completed_at.isoformat() if report.completed_at else 'N/A'}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            report.summary or "_No summary generated._",
            "",
            "---",
            "",
            "## Validation Results",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Total  | {report.total_validations} |",
            f"| Passed | {report.passed_validations} |",
            f"| Failed | {report.failed_validations} |",
            f"| Pass Rate | {report.pass_rate:.1f}% |",
            "",
        ]

        # Defects
        if report.defects:
            lines.extend(
                [
                    "---",
                    "",
                    "## Defects Found",
                    "",
                ]
            )
            for defect in report.defects:
                lines.extend(
                    [
                        f"### {defect.defect_id}: {defect.title}",
                        f"**Severity:** {defect.severity.value}",
                        f"**Description:** {defect.description}",
                        "",
                        f"- **Expected:** {defect.expected_behavior}",
                        f"- **Actual:** {defect.actual_behavior}",
                        "",
                    ]
                )
                if defect.root_cause_hypothesis:
                    lines.append(f"**Root Cause Hypothesis:** {defect.root_cause_hypothesis}")
                    lines.append("")

        # Agent issues (QA engine diagnostics — NOT application defects)
        if report.agent_issues:
            lines.extend(
                [
                    "---",
                    "",
                    "## Agent Issues (QA Engine Diagnostics)",
                    "",
                    "_These are problems encountered by the QA agent itself "
                    "(element location, perception, execution, verification, "
                    "runtime). They are **not** application defects and are "
                    "not counted in the Defects number._",
                    "",
                ]
            )
            for issue in report.agent_issues:
                lines.extend(
                    [
                        f"### {issue.issue_id}: {issue.title} ({issue.category})",
                        f"**Description:** {issue.description}",
                        "",
                    ]
                )

        # Timeline
        lines.extend(
            [
                "---",
                "",
                "## Execution Timeline",
                "",
                "| Step | Action | Result | Duration |",
                "|------|--------|--------|----------|",
            ]
        )
        for entry in report.timeline:
            lines.append(
                f"| {entry.step_index} | {entry.action} | {entry.result} | {entry.duration_ms:.0f}ms |"  # noqa: E501
            )

        # Recommendations
        if report.recommendations:
            lines.extend(
                [
                    "",
                    "---",
                    "",
                    "## Recommendations",
                    "",
                ]
            )
            for rec in report.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)

    async def save_report(self, report: TestReport, format: str = "markdown") -> str:
        """Save the report to disk.

        Args:
            report: The TestReport to save.
            format: Output format ('markdown' or 'json').

        Returns:
            The absolute file path of the saved report.
        """
        if format == "markdown":
            content = await self.render_markdown(report)
            extension = "md"
        else:
            content = report.model_dump_json(indent=2)
            extension = "json"

        filename = f"{report.report_id}_{report.started_at.strftime('%Y%m%d_%H%M%S')}.{extension}"
        filepath = self._output_dir / filename

        filepath.write_text(content, encoding="utf-8")

        logger.info("report_saved", path=str(filepath), format=format)
        return str(filepath)

    async def save_xlsx_report(self, report: TestReport, memory: SessionMemory) -> str:
        """Write the run's result back as an XLSX workbook (single test case)."""
        return await self.export_xlsx_results([(report, memory)], suffix=report.report_id)

    async def export_xlsx_results(
        self,
        results: list[tuple[TestReport, SessionMemory]],
        suffix: str | None = None,
    ) -> str:
        """Export one or multiple test-case results into a usable XLSX file.

        Rows follow the 13-column import workbook schema (plus Test Case ID
        and Test Type) and preserve user story ref, test scenario,
        description, test data, preconditions, steps, expected/actual
        results, status, error details, persona, execution metadata, and
        story/sheet traceability.
        """
        import openpyxl

        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        tag = suffix or f"BATCH-{uuid.uuid4().hex[:8].upper()}"
        filename = f"{tag}_{stamp}.xlsx"
        filepath = self._output_dir / filename

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test Results"

        headers = [
            "Test Case ID", "User Story Ref", "Test Scenario", "Test Case Description",
            "Test Data", "Preconditions", "Steps", "Expected Result", "Actual Result",
            "Status", "Error Details", "Persona", "Test Type",
            "Story Sheet", "Execution Metadata",
        ]
        ws.append(headers)

        for report, memory in results:
            tc = memory.test_case_data or {}
            story_ctx = tc.get("story_context") or {}

            steps_planned = tc.get("ordered_steps") or tc.get("steps") or []
            if steps_planned:
                steps_text = "\n".join(
                    f"{i}. {_step_text(s)}"
                    for i, s in enumerate(steps_planned, 1)
                )
            else:
                steps_text = "\n".join(
                    f"{t.step_index}. {t.action} [{t.result}]" for t in report.timeline
                )

            expected_text = "\n".join(
                str(a.get("description") or a.get("expected_value") or a.get("field") or a)
                if isinstance(a, dict) else str(getattr(a, "description", None) or getattr(a, "expected_value", "") or getattr(a, "field", ""))
                for a in (tc.get("final_assertions") or [])
            )

            actual = (
                "Passed all checks" if report.status == "passed"
                else report.summary or f"Status: {report.status}"
            )

            error_details = "\n".join(
                filter(None, [
                    *[f"{d.severity.value.upper()}: {d.description}" for d in report.defects],
                    *[f"AGENT-ISSUE ({i.category}): {i.description}" for i in report.agent_issues],
                ])
            )

            exec_meta = (
                f"session_id={memory.session_id}; validations={report.total_validations} "
                f"(passed={report.passed_validations}, failed={report.failed_validations}); "
                f"duration={report.duration_seconds:.1f}s"
            )

            row = [
                tc.get("id", ""),
                tc.get("story_id", "") or story_ctx.get("story_ref", ""),
                tc.get("title", ""),
                tc.get("description") or tc.get("source_user_story") or "",
                _stringify_cell(tc.get("test_data") or ""),
                "\n".join(tc.get("preconditions") or []),
                steps_text,
                expected_text,
                actual,
                report.status.upper(),
                error_details,
                getattr(memory, "persona", None) or tc.get("actor_role", ""),
                tc.get("test_type", "Functional"),
                story_ctx.get("sheet_name", ""),
                exec_meta,
            ]
            ws.append(row)

        wb.save(filepath)
        logger.info("xlsx_results_exported", path=str(filepath), rows=len(results))
        return str(filepath)
