"""Complete Incident workflow scenario library (P1-05, D1–D4).

The keyword-driven ``IncidentSkill.plan()`` covers only a subset of the
Incident lifecycle (open / lifecycle / resolve / assignment / mandatory /
default). The rubric requires evidence for the applicable Incident flows,
not just opening and observing a record. This module defines a structured
scenario library that covers:

  • Creation      — open a new Incident with mandatory fields populated
  • Assignment    — assign to a group + assignee, verify notification rule
  • On Hold       — pause an In-Progress Incident with Awaiting Caller
                    reason + check that Additional Comments become required
  • Resolution    — populate close_code + close_notes, transition to 6
  • Closure       — verify Resolved → Closed transition (post-resolution
                    review)
  • Reopen        — Closed → In Progress with justification, verify SLA
                    restart
  • Cancel        — In Progress → Canceled, verify no further mutations
                    are permitted

Each scenario carries an ``acceptance_criteria`` list whose entries match
the schema expected by ``ReportingEngine._map_acceptance_criteria``
(``{criterion_id, field, expected, operator}``). The reporting engine
will then map each criterion to its observed result and pass/fail/block
status — closing the loop between "scenario exists" and "evidence
exists for this scenario".

The scenarios are consumed by:

  • ``ScenarioGenerator`` (which can pull them as starting points for
    LLM-driven variation)
  • ``IncidentBenchmarkRunner`` (via the manifest, when seeded-defect
    benchmark needs a workflow-level suite)
  • The XLSX importer (the scenario structure matches the imported
    test-case schema, so an exported workbook can be re-imported)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowScenario:
    """A complete Incident workflow scenario with structured acceptance criteria."""

    scenario_id: str
    title: str
    description: str
    workflow_type: str  # creation | assignment | on_hold | resolution | closure | reopen | cancel
    target_module: str = "incident"
    persona: str = "itil_user"
    steps: list[dict[str, Any]] = field(default_factory=list)
    # Each AC entry: {criterion_id, field, expected, operator, description}
    # Operators match what _map_acceptance_criteria supports: equals,
    # not_equals, contains, not_empty, is_empty, state_matches.
    acceptance_criteria: list[dict[str, Any]] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    cleanup_steps: list[str] = field(default_factory=list)
    risk_level: str = "Medium"
    expected_final_state: dict[str, str] = field(default_factory=dict)
    # Whether this scenario requires a mutation (vs. read-only inspection)
    requires_mutation: bool = True

    def to_test_case_dict(self) -> dict[str, Any]:
        """Convert to the dict shape expected by TestIntelligenceStore and
        ReportingEngine (matches the imported-XLSX test-case schema).
        """
        return {
            "id": self.scenario_id,
            "title": self.title,
            "description": self.description,
            "module": self.target_module,
            "persona": self.persona,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "final_assertions": [
                {"field": ac["field"], "expected": ac["expected"], "operator": ac["operator"]}
                for ac in self.acceptance_criteria
            ],
            "acceptance_criteria": self.acceptance_criteria,
            "cleanup_steps": self.cleanup_steps,
            "risk_level": self.risk_level,
            "test_type": f"workflow_{self.workflow_type}",
            "story_context": {
                "story_ref": self.scenario_id,
                "sheet_name": "incident_workflows",
                "business_rules": [],
                "dependencies": [],
                "preconditions": self.preconditions,
                "acceptance_criteria": self.acceptance_criteria,
            },
        }


# ── Complete Incident workflow scenario library ──

WORKFLOW_SCENARIOS: list[WorkflowScenario] = [
    WorkflowScenario(
        scenario_id="INC-WF-01",
        title="Create new Incident with mandatory fields",
        description=(
            "Open the New Incident form, populate Short Description, Caller, "
            "Impact and Urgency, then submit. Verify the record was created "
            "with state=New (1) and a generated INC number."
        ),
        workflow_type="creation",
        preconditions=[
            "Active itil_user persona session",
            "ServiceNow subproduction instance with mutations allowed",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list page displayed"},
            {"action_type": "click", "target": "New", "expected_outcome": "New Incident form displayed"},
            {"action_type": "fill", "target": "short_description", "value": "[WF-01] Test incident creation", "expected_outcome": "Short description populated"},
            {"action_type": "fill", "target": "caller_id", "value": "Abel Tuter", "expected_outcome": "Caller populated"},
            {"action_type": "select", "target": "impact", "value": "3", "expected_outcome": "Impact set to 3-Low"},
            {"action_type": "select", "target": "urgency", "value": "3", "expected_outcome": "Urgency set to 3-Low"},
            {"action_type": "click", "target": "sysverb_insert", "expected_outcome": "Incident created"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF01-01", "field": "state", "expected": "1", "operator": "state_matches", "description": "New Incident state is New (1)"},
            {"criterion_id": "AC-WF01-02", "field": "short_description", "expected": "[WF-01] Test incident creation", "operator": "equals", "description": "Short description persisted"},
            {"criterion_id": "AC-WF01-03", "field": "number", "expected": "", "operator": "not_empty", "description": "Incident number was generated"},
        ],
        cleanup_steps=["Delete or close the created Incident after verification"],
        expected_final_state={"state": "1"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-02",
        title="Assign an In-Progress Incident and verify notification",
        description=(
            "Open an existing Incident in In-Progress state, set Assignment "
            "Group and Assigned To, then click Update. Verify the assignment "
            "change triggers a notification event in sysevent."
        ),
        workflow_type="assignment",
        preconditions=[
            "An Incident exists in In Progress state (use INC-WF-01 output)",
            "Assignment notification rule is configured for the target group",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "fill", "target": "search", "value": "<target_incident_number>", "expected_outcome": "Target incident filtered"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "fill", "target": "assignment_group", "value": "Network", "expected_outcome": "Assignment group populated"},
            {"action_type": "fill", "target": "assigned_to", "value": "ITIL User", "expected_outcome": "Assigned To populated"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "Assignment saved"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF02-01", "field": "assignment_group", "expected": "Network", "operator": "equals", "description": "Assignment group persisted"},
            {"criterion_id": "AC-WF02-02", "field": "assigned_to", "expected": "ITIL User", "operator": "equals", "description": "Assigned To persisted"},
            {"criterion_id": "AC-WF02-03", "field": "state", "expected": "2", "operator": "state_matches", "description": "State remains In Progress"},
            {"criterion_id": "AC-WF02-04", "field": "notification_sent", "expected": "incident.assigned", "operator": "equals", "description": "Assignment notification fired"},
        ],
        cleanup_steps=["Reset assignment_group and assigned_to to original values"],
        expected_final_state={"state": "2", "assignment_group": "Network"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-03",
        title="Move an In-Progress Incident to On Hold (Awaiting Caller)",
        description=(
            "Transition an In-Progress Incident to On Hold with hold_reason "
            "set to Awaiting Caller. Verify Additional Comments become "
            "conditionally mandatory and the SLA clock pauses."
        ),
        workflow_type="on_hold",
        preconditions=[
            "An Incident exists in In Progress state",
            "SLA definition is attached to the Incident",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "select", "target": "incident_state", "value": "3", "expected_outcome": "State set to On Hold"},
            {"action_type": "select", "target": "on_hold_reason", "value": "1", "expected_outcome": "Hold reason set to Awaiting Caller"},
            {"action_type": "fill", "target": "comments", "value": "Awaiting caller confirmation", "expected_outcome": "Additional comments populated"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "On Hold transition saved"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF03-01", "field": "state", "expected": "3", "operator": "state_matches", "description": "State is On Hold (3)"},
            {"criterion_id": "AC-WF03-02", "field": "on_hold_reason", "expected": "Awaiting Caller", "operator": "equals", "description": "Hold reason populated"},
            {"criterion_id": "AC-WF03-03", "field": "sla_stage", "expected": "paused", "operator": "equals", "description": "SLA clock paused on On Hold"},
        ],
        cleanup_steps=["Reset state to In Progress and clear on_hold_reason"],
        expected_final_state={"state": "3", "on_hold_reason": "1"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-04",
        title="Resolve an Incident with close_code and close_notes",
        description=(
            "Open an In-Progress Incident, populate close_code and "
            "close_notes, then transition state to Resolved (6). Verify "
            "the SLA completes and incident.resolved notification fires."
        ),
        workflow_type="resolution",
        preconditions=[
            "An Incident exists in In Progress state",
            "Resolution SLA definition is attached",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "select", "target": "close_code", "value": "Solved (Permanently)", "expected_outcome": "Resolution code populated"},
            {"action_type": "fill", "target": "close_notes", "value": "Root cause identified and fixed", "expected_outcome": "Close notes populated"},
            {"action_type": "select", "target": "incident_state", "value": "6", "expected_outcome": "State set to Resolved"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "Resolution saved"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF04-01", "field": "state", "expected": "6", "operator": "state_matches", "description": "State is Resolved (6)"},
            {"criterion_id": "AC-WF04-02", "field": "close_code", "expected": "Solved (Permanently)", "operator": "equals", "description": "close_code persisted"},
            {"criterion_id": "AC-WF04-03", "field": "close_notes", "expected": "", "operator": "not_empty", "description": "close_notes populated"},
            {"criterion_id": "AC-WF04-04", "field": "notification_sent", "expected": "incident.resolved", "operator": "equals", "description": "Resolution notification fired"},
            {"criterion_id": "AC-WF04-05", "field": "sla_stage", "expected": "completed", "operator": "equals", "description": "Resolution SLA completed"},
        ],
        cleanup_steps=["Reset state to In Progress, clear close_code and close_notes"],
        expected_final_state={"state": "6"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-05",
        title="Close a Resolved Incident (post-resolution review)",
        description=(
            "From a Resolved Incident, transition to Closed (7) after "
            "verifying the caller-confirmed resolution. No additional "
            "mandatory fields are required beyond what Resolved set."
        ),
        workflow_type="closure",
        preconditions=[
            "An Incident exists in Resolved state (use INC-WF-04 output)",
            "Resolution has been confirmed by the caller",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "select", "target": "incident_state", "value": "7", "expected_outcome": "State set to Closed"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "Closure saved"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF05-01", "field": "state", "expected": "7", "operator": "state_matches", "description": "State is Closed (7)"},
            {"criterion_id": "AC-WF05-02", "field": "close_code", "expected": "", "operator": "not_empty", "description": "close_code retained from resolution"},
        ],
        cleanup_steps=["Reopen or reset state to In Progress"],
        expected_final_state={"state": "7"},
        risk_level="Low",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-06",
        title="Reopen a Closed Incident with justification",
        description=(
            "From a Closed Incident, transition back to In Progress and "
            "verify that the SLA restarts and a reopen notification fires."
        ),
        workflow_type="reopen",
        preconditions=[
            "An Incident exists in Closed state (use INC-WF-05 output)",
            "Reopen justification is required by business rule",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "fill", "target": "comments", "value": "Caller reports issue has recurred", "expected_outcome": "Reopen justification captured"},
            {"action_type": "select", "target": "incident_state", "value": "2", "expected_outcome": "State set back to In Progress"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "Reopen saved"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF06-01", "field": "state", "expected": "2", "operator": "state_matches", "description": "State is In Progress (2)"},
            {"criterion_id": "AC-WF06-02", "field": "sla_stage", "expected": "in_progress", "operator": "equals", "description": "SLA clock restarted"},
            {"criterion_id": "AC-WF06-03", "field": "notification_sent", "expected": "incident.reopened", "operator": "equals", "description": "Reopen notification fired"},
        ],
        cleanup_steps=["Reset state to Closed if applicable"],
        expected_final_state={"state": "2"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-07",
        title="Cancel an In-Progress Incident",
        description=(
            "From an In-Progress Incident, transition to Canceled (8) and "
            "verify that no further mutations are permitted on the record."
        ),
        workflow_type="cancel",
        preconditions=[
            "An Incident exists in In Progress state",
            "Cancellation is permitted by business rule",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "select", "target": "incident_state", "value": "8", "expected_outcome": "State set to Canceled"},
            {"action_type": "click", "target": "sysverb_update", "expected_outcome": "Cancellation saved"},
            {"action_type": "validate", "target": "form_readonly", "expected_outcome": "Form fields are read-only after cancellation"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF07-01", "field": "state", "expected": "8", "operator": "state_matches", "description": "State is Canceled (8)"},
            {"criterion_id": "AC-WF07-02", "field": "form_readonly", "expected": "true", "operator": "equals", "description": "Form is read-only after cancel"},
        ],
        cleanup_steps=["Reset state to In Progress if needed for downstream tests"],
        expected_final_state={"state": "8"},
        risk_level="Medium",
    ),
    WorkflowScenario(
        scenario_id="INC-WF-08",
        title="Read-only Incident observation (smoke check)",
        description=(
            "Open an Incident and inspect its state and priority WITHOUT "
            "modifying any fields. This scenario provides a baseline that "
            "should always pass when the form is healthy, and serves as the "
            "control case for benchmark scoring."
        ),
        workflow_type="inspection",
        requires_mutation=False,
        preconditions=[
            "An Incident exists with known state and priority",
        ],
        steps=[
            {"action_type": "navigate", "target": "incident_list", "expected_outcome": "Incident list displayed"},
            {"action_type": "click", "target": "row", "expected_outcome": "Incident form opened"},
            {"action_type": "validate", "target": "state", "expected_outcome": "State observed without modification"},
        ],
        acceptance_criteria=[
            {"criterion_id": "AC-WF08-01", "field": "state", "expected": "2", "operator": "state_matches", "description": "State observed and matches expected"},
            {"criterion_id": "AC-WF08-02", "field": "priority", "expected": "4", "operator": "equals", "description": "Priority observed and matches expected"},
        ],
        cleanup_steps=["No cleanup — read-only inspection"],
        expected_final_state={"state": "2", "priority": "4"},
        risk_level="Low",
    ),
]


def get_workflow_scenarios() -> list[WorkflowScenario]:
    """Return the complete Incident workflow scenario library."""
    return list(WORKFLOW_SCENARIOS)


def get_workflow_scenarios_as_test_cases() -> list[dict[str, Any]]:
    """Return the workflow scenarios as test-case dicts (matches imported XLSX shape)."""
    return [s.to_test_case_dict() for s in WORKFLOW_SCENARIOS]


def get_workflow_scenario(scenario_id: str) -> WorkflowScenario | None:
    """Look up a single workflow scenario by ID."""
    for s in WORKFLOW_SCENARIOS:
        if s.scenario_id == scenario_id:
            return s
    return None
