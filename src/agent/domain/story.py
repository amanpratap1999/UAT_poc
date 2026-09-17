"""Story and Test Case Domain Models.

Formalizes the Story-to-Test-Case pipeline:
User Story -> StorySpecification -> AcceptanceCriterion -> GeneratedTestCase
-> Preconditions/Data Validation -> Execution -> Evidence Collection -> TestVerdict
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field


class TestVerdictStatus(StrEnum):
    """Verdict classifications for test case execution."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion derived from user story."""

    id: str = Field(description="Unique criterion ID (e.g., AC-1)")
    statement: str = Field(description="Acceptance criterion statement")
    expected_state: str | None = Field(default=None, description="Expected entity state")
    required_fields: list[str] = Field(default_factory=list, description="Mandatory fields")
    assertions: list[str] = Field(default_factory=list, description="Assertions to verify")


class StorySpecification(BaseModel):
    """Structured decomposition of a natural language user story or test goal."""

    story_id: str = Field(description="Unique story identifier")
    title: str = Field(description="Short descriptive story title")
    description: str = Field(description="Full narrative of the user story / goal")
    module: str = Field(default="incident", description="Target module/table (e.g. incident, change)")
    table: str = Field(default="incident", description="ServiceNow database table")
    actor: str = Field(default="ITIL User", description="Actor or role performing test")
    target_record: str | None = Field(default=None, description="Target record identifier (e.g. INC0000007)")
    preconditions: list[str] = Field(default_factory=list, description="Required starting conditions")
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    risk_assessment: str = Field(default="", description="Risk summary")


class TestStep(BaseModel):
    """An individual ordered step within a generated test case."""

    step_number: int = Field(description="1-based step index")
    action_type: str = Field(description="click, fill, select, navigate, wait, validate, etc.")
    target: str = Field(description="Target element, field, or URL")
    value: str = Field(default="", description="Value to input or select")
    expected_outcome: str = Field(description="Expected result for this step")
    state_before: dict[str, Any] = Field(default_factory=dict, description="Expected state before execution")
    state_after: dict[str, Any] = Field(default_factory=dict, description="Expected state after execution")
    is_precondition_check: bool = Field(default=False, description="Whether this step validates a precondition")


class ExpectedAssertion(BaseModel):
    """Formal assertion to be verified at the conclusion of a test."""

    assertion_id: str = Field(description="Unique assertion ID")
    field: str = Field(description="Field name or attribute being asserted")
    expected_value: Any = Field(description="Expected value or condition")
    operator: str = Field(default="equals", description="equals, contains, not_empty, in_progress, etc.")
    description: str = Field(default="", description="Human-readable explanation of assertion")


class GeneratedTestCase(BaseModel):
    """Complete, structured test case ready for deterministic or cognitive execution."""

    id: str = Field(description='Unique test case identifier')
    title: str = Field(default='', description='Test scenario or title')
    test_type: str = Field(default='Functional', description='Type of test (e.g. Functional, End-to-End, Idempotency, Audit, Error Isolation)')
    source_user_story: str = Field(description="Original user story or natural language goal")
    story_id: str | None = Field(default=None, description="Reference to parent StorySpecification")
    story_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Story-scoped grounding context preserved from the source workbook: "
            "user story ref, sheet name, business rules, dependencies, "
            "preconditions, acceptance criteria, and test data."
        ),
    )
    module: str = Field(default="incident", description="Module/table being tested")
    table: str = Field(default="incident", description="ServiceNow table")
    target_record: str | None = Field(default=None, description="Target record (e.g., INC0000007)")
    actor_role: str = Field(default="admin", description="Role/permissions required")
    preconditions: list[str] = Field(default_factory=list, description="Initial preconditions that MUST hold")
    expected_initial_state: str | None = Field(default=None, description="Expected initial lifecycle state")
    test_data: dict[str, Any] = Field(default_factory=dict, description="Input values and test data fixtures")
    ordered_steps: list[TestStep] = Field(default_factory=list, description="Sequential steps to execute")
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list, description="Explicit criteria preserved from story")
    final_assertions: list[ExpectedAssertion] = Field(default_factory=list, description="Final assertions")
    negative_scenario: str | None = Field(default=None, description="Boundary or negative scenario variant")
    risk_level: str = Field(default="Medium", description="Low, Medium, High, Critical")
    risk_reason: str = Field(default="", description="Justification for risk score")
    documentation_references: list[str] = Field(
        default_factory=list,
        description="References to official ServiceNow docs, e.g. servicenow_docs/incident_management.md",
    )
    evidence_requirements: list[str] = Field(
        default_factory=lambda: ["screenshot_before", "screenshot_after", "dom_state_hash"],
        description="Required evidence artifacts",
    )
    cleanup_requirements: list[str] = Field(
        default_factory=list,
        description="Reset or teardown actions needed after test run",
    )
    is_exploratory: bool = Field(default=False, description="Whether this scenario includes safe exploratory actions")


class TestVerdict(BaseModel):
    """The formal, evidence-backed verdict of a test case."""

    verdict: TestVerdictStatus = Field(description="PASSED, FAILED, PRECONDITION_FAILED, BLOCKED, ERROR")
    summary: str = Field(description="Concise verdict summary")
    precondition_satisfied: bool = True
    precondition_failure_reason: str | None = None
    passed_steps: int = 0
    total_steps: int = 0
    failed_assertions: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    is_application_defect: bool = False
    defect_classification: str | None = None
    documentation_section: str | None = None

