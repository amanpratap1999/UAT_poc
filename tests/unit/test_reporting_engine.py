"""Unit tests for the Reporting Engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.domain.plan import ExecutionPlan
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.memory.session import SessionMemory
from agent.reporting.engine import ReportingEngine


@pytest.fixture
def engine(tmp_path: Path) -> ReportingEngine:
    return ReportingEngine(output_dir=tmp_path)


@pytest.fixture
def populated_memory() -> SessionMemory:
    """Session memory with realistic test data."""
    memory = SessionMemory(goal="Test incident creation")
    memory.plan = ExecutionPlan(goal="Test incident creation")
    memory.plan.add_step("Navigate to form", "Form displayed")
    memory.plan.add_step("Fill fields", "Fields populated")

    # Add completed steps
    action = AgentAction(
        action_type=ActionType.CLICK,
        target="text:Create New",
        reasoning="Navigate to form",
    )
    result = ActionResult(
        success=True,
        action=action,
        duration_ms=150.0,
        screenshot_path="screenshots/step1.png",
    )
    validation = ValidationResult(action_description="click: Create New")
    validation.add_check(
        ValidationCheck(
            check_name="action_execution",
            description="Action executed",
            passed=True,
            expected="success",
            actual="success",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)

    memory.add_timeline_entry(
        action="Click: Create New",
        result="success",
        duration_ms=150.0,
        screenshot_path="screenshots/step1.png",
    )

    return memory


@pytest.mark.asyncio
async def test_generate_report(
    engine: ReportingEngine,
    populated_memory: SessionMemory,
) -> None:
    """Test basic report generation."""
    report = await engine.generate_report(populated_memory)

    assert report.report_id.startswith("RPT-")
    assert report.goal == "Test incident creation"
    assert report.total_validations == 1
    assert report.passed_validations == 1


@pytest.mark.asyncio
async def test_report_with_summary(
    engine: ReportingEngine,
    populated_memory: SessionMemory,
) -> None:
    """Test report generation with LLM summary."""
    summary_data = {
        "summary": "All tests passed successfully.",
        "recommendations": ["Add more negative test cases"],
        "root_cause_hypotheses": [],
    }

    report = await engine.generate_report(populated_memory, summary_data)

    assert report.summary == "All tests passed successfully."
    assert len(report.recommendations) == 1


@pytest.mark.asyncio
async def test_render_markdown(
    engine: ReportingEngine,
    populated_memory: SessionMemory,
) -> None:
    """Test Markdown report rendering."""
    report = await engine.generate_report(populated_memory)
    markdown = await engine.render_markdown(report)

    assert "# QA Test Report" in markdown
    assert "Validation Results" in markdown
    assert "Execution Timeline" in markdown
    assert report.report_id in markdown


@pytest.mark.asyncio
async def test_save_report_markdown(
    engine: ReportingEngine,
    populated_memory: SessionMemory,
) -> None:
    """Test saving report as Markdown file."""
    report = await engine.generate_report(populated_memory)
    filepath = await engine.save_report(report, format="markdown")

    assert Path(filepath).exists()
    assert filepath.endswith(".md")


@pytest.mark.asyncio
async def test_save_report_json(
    engine: ReportingEngine,
    populated_memory: SessionMemory,
) -> None:
    """Test saving report as JSON file."""
    report = await engine.generate_report(populated_memory)
    filepath = await engine.save_report(report, format="json")

    assert Path(filepath).exists()
    assert filepath.endswith(".json")


@pytest.mark.asyncio
async def test_defect_identification(
    engine: ReportingEngine,
) -> None:
    """Agent-scope validation failures are diagnostics, not application defects."""
    memory = SessionMemory(goal="Test")

    # A failed action_execution check means the AGENT could not perform the
    # interaction — this must NOT be an application defect.
    action = AgentAction(action_type=ActionType.CLICK, target="btn", reasoning="t")
    result = ActionResult(success=False, action=action, error="Element not found", error_type="SelectorNotFoundError")
    validation = ValidationResult(action_description="click: btn")
    validation.add_check(
        ValidationCheck(
            check_name="action_execution",
            passed=False,
            expected="success",
            actual="failed",
            error_message="Button click had no effect",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)

    report = await engine.generate_report(memory)

    assert not report.has_defects
    assert len(report.agent_issues) == 1
    assert report.agent_issues[0].error_type == "SelectorNotFoundError"


@pytest.mark.asyncio
async def test_defect_identification_application_scope(
    engine: ReportingEngine,
) -> None:
    """Application-behavior validation failures ARE application defects."""
    memory = SessionMemory(goal="Test")

    # The interaction executed; the app demonstrably kept the wrong value.
    action = AgentAction(action_type=ActionType.SELECT, target="State", value="2", reasoning="t")
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(action_description="select: State")
    validation.add_check(
        ValidationCheck(
            check_name="action_execution",
            passed=True,
            expected="success",
            actual="success",
        )
    )
    validation.add_check(
        ValidationCheck(
            check_name="field_update",
            passed=False,
            expected="2",
            actual="1",
            error_message="Field value mismatch",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)

    report = await engine.generate_report(memory)

    assert report.has_defects
    assert len(report.defects) == 1
    assert report.defects[0].defect_id.startswith("DEF-")
    assert report.defects[0].title.startswith("Validation failure: field_update")


@pytest.mark.asyncio
async def test_defect_withdrawn_by_investigation_verdict(
    engine: ReportingEngine,
) -> None:
    """An investigation verdict clearing the mismatch withdraws the defect."""
    memory = SessionMemory(goal="Test")

    action = AgentAction(action_type=ActionType.SELECT, target="State", value="2", reasoning="t")
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(action_description="select: State")
    validation.add_check(
        ValidationCheck(
            check_name="field_update",
            passed=False,
            expected="2",
            actual="1",
            error_message="Field value mismatch",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)

    # Investigation cleared the mismatch: the knowledge model explains the
    # observed behavior (expected customization), so it is NOT a defect.
    memory.add_defect_verdict(
        step_index=0,
        hypothesis_id="hyp-1",
        is_defect=False,
        classification="false_positive_customization",
        reasoning="Knowledge model explains this",
    )
    # The cognitive loop also maps the step to the hypothesis via the failure
    memory.add_failure(
        error_type="InvestigationVerifiedDefect",
        error_message="Hypothesis hyp-1: cleared in this test fixture",
    )

    report = await engine.generate_report(memory)
    assert not report.has_defects


@pytest.mark.asyncio
async def test_report_status_determination(
    engine: ReportingEngine,
) -> None:
    """Report status separates QA verdict from engine execution problems."""
    # Memory with executed action and validation = passed
    memory = SessionMemory(goal="Test")
    action = AgentAction(action_type=ActionType.CLICK, target="btn")
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(action_description="click: btn")
    validation.add_check(
        ValidationCheck(
            check_name="action_execution",
            description="Action executed",
            passed=True,
            expected="success",
            actual="success",
        )
    )
    memory.add_completed_step(action=action, result=result, validation=validation)
    report = await engine.generate_report(memory)
    assert report.status == "passed"

    # Engine failure with zero actions executed = error (engine couldn't run),
    # not "failed" (which is the QA verdict for application defects)
    memory_error = SessionMemory(goal="Test")
    memory_error.add_failure(error_type="PlanningFailure", error_message="No hypothesis")
    report_error = await engine.generate_report(memory_error)
    assert report_error.status == "error"

    # Application defect with zero passing validations = failed (QA verdict)
    memory_failed = SessionMemory(goal="Test")
    action = AgentAction(action_type=ActionType.CLICK, target="btn")
    result = ActionResult(success=True, action=action)
    validation = ValidationResult(action_description="click: btn")
    validation.add_check(
        ValidationCheck(
            check_name="field_update",
            passed=False,
            expected="X",
            actual="Y",
        )
    )
    memory_failed.add_completed_step(action=action, result=result, validation=validation)
    report_failed = await engine.generate_report(memory_failed)
    assert report_failed.status == "failed"
