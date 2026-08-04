"""Reporting engine — generates professional QA reports from session memory.

Produces both HTML and Markdown reports with execution timelines,
validation summaries, defect lists, browser logs, and LLM-generated
executive summaries with root-cause hypotheses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.logging import get_logger
from agent.core.types import Severity
from agent.domain.report import (
    BrowserLogEntry,
    DefectReport,
    TestReport,
    TimelineEntry,
)
from agent.memory.session import SessionMemory

logger = get_logger(__name__)


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
        now = datetime.utcnow()

        # Build timeline from memory
        timeline = self._build_timeline(memory)

        # Compute validation stats
        passed = sum(
            1 for v in memory.completed_validations if v.overall_passed
        )
        failed = sum(
            1 for v in memory.completed_validations if not v.overall_passed
        )
        total = len(memory.completed_validations)

        # Build validation details
        validation_details = [
            {
                "action": v.action_description,
                "passed": v.overall_passed,
                "checks": len(v.checks),
                "failed_checks": [
                    c.check_name for c in v.failed_checks
                ],
            }
            for v in memory.completed_validations
        ]

        # Identify defects from failures
        defects = self._identify_defects(memory)

        # Build browser logs
        browser_logs = self._build_browser_logs(memory)

        # Collect all screenshots
        screenshots = [
            entry.screenshot_path
            for entry in memory.timeline
            if entry.screenshot_path
        ]

        # Determine overall status
        if memory.total_failures == 0 and failed == 0:
            status = "passed"
        elif memory.total_failures > 0 and passed > 0:
            status = "partial"
        elif memory.total_failures > 0 and passed == 0:
            status = "failed"
        else:
            status = "completed"

        # Calculate duration
        duration = (now - memory.started_at).total_seconds()

        report = TestReport(
            report_id=report_id,
            goal=memory.goal,
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
            browser_logs=browser_logs,
            console_errors=[
                f.error_message for f in memory.failures
                if "js" in f.error_type.lower() or "console" in f.error_type.lower()
            ],
            screenshots=screenshots,
            environment={
                "session_id": memory.session_id,
                "url": memory.current_url,
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
                        defect.root_cause_hypothesis = hypothesis.get(
                            "hypothesis", ""
                        )

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

    def _identify_defects(self, memory: SessionMemory) -> list[DefectReport]:
        """Identify defects from validation failures and errors.

        Groups related failures and creates structured defect reports.
        """
        defects: list[DefectReport] = []
        defect_counter = 0

        # Defects from validation failures
        for step in memory.completed_steps:
            if step.validation and not step.validation.overall_passed:
                defect_counter += 1
                defect_id = f"DEF-{defect_counter:03d}"

                failed_checks = step.validation.failed_checks
                check_names = [c.check_name for c in failed_checks]
                check_details = "; ".join(
                    f"{c.check_name}: expected={c.expected}, actual={c.actual}"
                    for c in failed_checks
                )

                severity = self._assess_severity(failed_checks)

                evidence: list[str] = []
                if step.result.screenshot_path:
                    evidence.append(step.result.screenshot_path)

                defects.append(
                    DefectReport(
                        defect_id=defect_id,
                        severity=severity,
                        title=f"Validation failure: {', '.join(check_names)}",
                        description=check_details,
                        expected_behavior="; ".join(
                            c.expected for c in failed_checks
                        ),
                        actual_behavior="; ".join(
                            c.actual for c in failed_checks
                        ),
                        evidence=evidence,
                        related_step_index=step.step_index,
                    )
                )

        # Defects from unrecovered failures
        for failure in memory.failures:
            if not failure.recovered:
                defect_counter += 1
                defect_id = f"DEF-{defect_counter:03d}"

                defects.append(
                    DefectReport(
                        defect_id=defect_id,
                        severity=Severity.HIGH,
                        title=f"Execution failure: {failure.error_type}",
                        description=failure.error_message,
                        actual_behavior=failure.error_message,
                        related_step_index=failure.step_index,
                    )
                )

        return defects

    def _assess_severity(self, failed_checks: list) -> Severity:
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
        """Compile browser log entries from failure records."""
        logs: list[BrowserLogEntry] = []
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
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total  | {report.total_validations} |",
            f"| Passed | {report.passed_validations} |",
            f"| Failed | {report.failed_validations} |",
            f"| Pass Rate | {report.pass_rate:.1f}% |",
            "",
        ]

        # Defects
        if report.defects:
            lines.extend([
                "---",
                "",
                "## Defects Found",
                "",
            ])
            for defect in report.defects:
                lines.extend([
                    f"### {defect.defect_id}: {defect.title}",
                    f"**Severity:** {defect.severity.value}",
                    f"**Description:** {defect.description}",
                    "",
                    f"- **Expected:** {defect.expected_behavior}",
                    f"- **Actual:** {defect.actual_behavior}",
                    "",
                ])
                if defect.root_cause_hypothesis:
                    lines.append(f"**Root Cause Hypothesis:** {defect.root_cause_hypothesis}")
                    lines.append("")

        # Timeline
        lines.extend([
            "---",
            "",
            "## Execution Timeline",
            "",
            "| Step | Action | Result | Duration |",
            "|------|--------|--------|----------|",
        ])
        for entry in report.timeline:
            lines.append(
                f"| {entry.step_index} | {entry.action} | {entry.result} | {entry.duration_ms:.0f}ms |"
            )

        # Recommendations
        if report.recommendations:
            lines.extend([
                "",
                "---",
                "",
                "## Recommendations",
                "",
            ])
            for rec in report.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)

    async def save_report(
        self, report: TestReport, format: str = "markdown"
    ) -> str:
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
