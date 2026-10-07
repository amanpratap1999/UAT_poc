"""Scenario Generator for Test Intelligence.

Generates testing scenarios, risk scores, and exploratory branch steps
based on selected strategies and current domain knowledge.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.core.untrusted import UNTRUSTED_DATA_POLICY, wrap_untrusted, scan_for_injection
from agent.domain.knowledge_model import CustomerKnowledgeModel
from agent.domain.story import (
    AcceptanceCriterion,
    ExpectedAssertion,
    GeneratedTestCase,
    TestStep,
)
from agent.learning.service import LearningService
from agent.planner.llm_client import OpenAILLMClient
from agent.testing.safety import ExploratorySafetyPolicy, SafetyViolationError
from agent.testing.strategy_selector import StrategySelector

logger = get_logger(__name__)


class TestScenario(BaseModel):
    """A generated test scenario."""

    id: str
    title: str
    description: str
    steps: list[str]
    expected_outcome: str
    is_exploratory: bool = False
    risk_score: int = 5
    risk_reasoning: str = ""
    strategies_applied: list[str] = Field(default_factory=list)


class ScenarioGenerationResult(BaseModel):
    """Result of a scenario generation pass."""

    scenarios: list[TestScenario]
    reasoning: str


class ScenarioGenerator:
    """Generates test scenarios via LLM reasoning and deterministic story decomposition."""

    def __init__(
        self,
        llm_client: OpenAILLMClient,
        strategy_selector: StrategySelector,
        learning_service: LearningService | None = None,
    ) -> None:
        self._llm = llm_client
        self._selector = strategy_selector
        self._learning = learning_service

    async def generate_scenarios(
        self,
        requirement: str,
        fields: list[dict[str, Any]],
        workflow_type: str | None = None,
        knowledge_model: CustomerKnowledgeModel | None = None,
        table_name: str | None = None,
        target_module: str = "incident",
    ) -> list[TestScenario]:
        """Generate test scenarios for a requirement."""
        strategies = await self._selector.select_strategies(fields, workflow_type)

        domain_facts = ""
        if knowledge_model and table_name:
            table_metadata = knowledge_model.get_table(table_name)
            if table_metadata:
                domain_facts = "\n## Authoritative Domain Facts (DO NOT INVENT CONFIGURATION):\n"
                for field_name, meta in table_metadata.fields.items():
                    domain_facts += f"- Field '{field_name}' (Label: {meta.label}): Type={meta.type}, Mandatory={meta.mandatory}\n"
                if table_metadata.active_ui_policies:
                    domain_facts += (
                        f"UI Policies: {len(table_metadata.active_ui_policies)} active policies.\n"
                    )

        experience_context = ""
        if self._learning:
            experiences = await self._learning.query_experiences(table_name or "unknown")
            if experiences:
                experience_context = (
                    "\n## Verified Historical Experience (Decision Support Context):\n"
                )
                for e in experiences:
                    experience_context += f"- Observation: {e.observation}\n  Outcome: {e.outcome}\n  Confidence: {e.confidence:.2f}\n"
                experience_context += "\nUse this historical experience to influence the prioritization and focus of your exploratory scenarios.\n"

        req_safe = wrap_untrusted("requirement", requirement)
        if scan_for_injection(requirement):
            logger.warning("prompt_injection_detected_in_generator")

        prompt = f"""
        You are a senior QA engineer. Generate test scenarios for the following requirement:
        '{req_safe}'
        {domain_facts}
        The following test strategies MUST be applied, based on our rules:
        {json.dumps(strategies, indent=2)}
        {experience_context}

        {
            "If the requirement explicitly requests exploratory testing, include a safe exploratory deviation."
            if "exploratory" in requirement.lower()
            else "Follow the requirement strictly and deterministically. Do not insert unscripted deviations into targeted UAT test cases."
        }
        """

        logger.info("generating_scenarios", strategies_count=len(strategies))

        try:
            response = await self._llm.complete_json(
                messages=[
                    {"role": "system", "content": f"You are a senior QA Test Strategist.\n\n{UNTRUSTED_DATA_POLICY}"},
                    {"role": "user", "content": prompt},
                ]
            )

            if "scenarios" in response:
                result = ScenarioGenerationResult(**response)
            else:
                if isinstance(response, list):
                    scenarios = [TestScenario(**s) for s in response]
                    result = ScenarioGenerationResult(
                        scenarios=scenarios, reasoning="Parsed from list"
                    )
                else:
                    raise ValueError("Unexpected JSON format from LLM")

            valid_scenarios = []
            for scenario in result.scenarios:
                if scenario.is_exploratory:
                    try:
                        for step in scenario.steps:
                            ExploratorySafetyPolicy.validate_step(step)
                    except SafetyViolationError as e:
                        logger.warning(
                            "exploratory_scenario_rejected", scenario=scenario.title, error=str(e)
                        )
                        continue

                scenario.risk_score, scenario.risk_reasoning = self._calculate_risk_score(
                    scenario, fields, workflow_type, knowledge_model, table_name
                )
                valid_scenarios.append(scenario)

            logger.info("scenarios_generated", count=len(valid_scenarios))
            scored_scenarios = []
            for s in valid_scenarios:
                prio = 1.0
                if s.is_exploratory and self._learning:
                    prio = await self._learning.get_exploration_priority(
                        target_module, "exploratory_branch"
                    )
                scored_scenarios.append((prio, s))

            scored_scenarios.sort(key=lambda x: x[0], reverse=True)
            return [s for _, s in scored_scenarios]

        except Exception as e:
            logger.error("scenario_generation_failed", error=str(e))
            return [
                TestScenario(
                    id="fallback-1",
                    title="Fallback Execution",
                    description="Execute the basic requirement",
                    steps=["Execute requirement"],
                    expected_outcome="Success",
                    is_exploratory=True,
                    risk_score=5,
                    risk_reasoning="Fallback scenario",
                    strategies_applied=strategies,
                )
            ]

    def _calculate_risk_score(
        self,
        scenario: TestScenario,
        fields: list[dict[str, Any]],
        workflow_type: str | None,
        knowledge_model: CustomerKnowledgeModel | None,
        table_name: str | None,
    ) -> tuple[int, str]:
        """Calculate a deterministic risk score (1-10) based on objective inputs."""
        score = 2
        reasoning = ["Baseline nominal risk (+2)"]

        if scenario.is_exploratory:
            score += 2
            reasoning.append("Exploratory deviation (+2)")

        if workflow_type == "approval":
            score += 3
            reasoning.append("Approval workflow involvement (+3)")
        elif workflow_type == "sla":
            score += 2
            reasoning.append("SLA workflow involvement (+2)")

        if knowledge_model and table_name:
            table_metadata = knowledge_model.get_table(table_name)
            if table_metadata:
                for field in fields:
                    f_name = field.get("name")
                    if f_name and f_name in table_metadata.fields:
                        meta = table_metadata.fields[f_name]
                        if meta.mandatory:
                            score += 1
                            reasoning.append(f"Involves mandatory field '{f_name}' (+1)")
                            break

        for strategy in scenario.strategies_applied:
            if "Negative Testing" in strategy or "Injection" in strategy or "Boundary" in strategy:
                score += 1
                reasoning.append(f"Complex QA strategy applied '{strategy[:20]}...' (+1)")
                break

        final_score = max(1, min(10, score))
        return final_score, ", ".join(reasoning)

    async def decompose_story_to_test_case(
        self,
        story_text: str,
        table_name: str = "incident",
        actor_role: str = "itil",
        acceptance_criteria: list[str] | None = None,
        target_record: str | None = None,
        explicit_preconditions: list[str] | None = None,
    ) -> GeneratedTestCase:
        """Decompose a natural language user story or test goal into a structured GeneratedTestCase.

        Follows the strict schema:
        User story -> structured test case -> preconditions -> test data -> ordered steps -> assertions.
        Preserves deterministic execution for targeted user stories and preserves all acceptance criteria.
        """
        # 1. Deterministic extraction for standard ServiceNow UAT patterns
        if not target_record:
            rec_match = re.search(r"\b(INC\d{5,10}|CHG\d{5,10}|PRB\d{5,10})\b", story_text, re.IGNORECASE)
            target_record = rec_match.group(1).upper() if rec_match else None

        # Look for initial state specification
        initial_state_match = re.search(
            r"(?:initial\s+state|current\s+state|state\s+is)\s*(?:is|to|as)?\s*([A-Za-z\s]+?)(?:\.|\sand|\sChange|,|$)",
            story_text,
            re.IGNORECASE,
        )
        initial_state = initial_state_match.group(1).strip() if initial_state_match else None
        if initial_state and initial_state.lower() in ("on hold", "in progress", "new", "resolved", "closed", "canceled"):
            initial_state = " ".join(word.capitalize() for word in initial_state.split())

        # Look for target state mutation
        target_state_match = re.search(
            r"(?:change|set|transition)\s+(?:the\s+)?state\s+to\s+([A-Za-z\s]+?)(?:\.|\sand|\sclick|,|$)",
            story_text,
            re.IGNORECASE,
        )
        target_state = target_state_match.group(1).strip() if target_state_match else None
        if target_state and target_state.lower() in ("on hold", "in progress", "new", "resolved", "closed", "canceled"):
            target_state = " ".join(word.capitalize() for word in target_state.split())

        # Build steps
        steps: list[TestStep] = []
        step_num = 1

        # Step 1: Navigate to target record
        if target_record:
            steps.append(
                TestStep(
                    step_number=step_num,
                    action_type="navigate",
                    target=f"{table_name}.do?sysparm_query=number={target_record}",
                    expected_outcome=f"Form for {target_record} is loaded and visible",
                    is_precondition_check=True,
                )
            )
            step_num += 1

        # Step 2: Verify record and initial state precondition
        if target_record or initial_state:
            steps.append(
                TestStep(
                    step_number=step_num,
                    action_type="validate",
                    target="incident.number,incident.state",
                    value=initial_state or "",
                    expected_outcome=f"Incident number is {target_record or 'matched'} and initial state is {initial_state or 'verified'}",
                    state_before={"record": target_record, "state": initial_state},
                    is_precondition_check=True,
                )
            )
            step_num += 1

        # Step 3: State mutation
        if target_state:
            steps.append(
                TestStep(
                    step_number=step_num,
                    action_type="select",
                    target="incident.state",
                    value=target_state,
                    expected_outcome=f"State field dropdown updated to '{target_state}'",
                    state_before={"state": initial_state},
                    state_after={"state": target_state},
                )
            )
            step_num += 1

        # Step 4: Click Update/Save
        steps.append(
            TestStep(
                step_number=step_num,
                action_type="click",
                target="button#sysverb_update",
                expected_outcome="Incident changes are submitted and saved to ServiceNow",
            )
        )
        step_num += 1

        # Step 5: Re-open record
        if target_record:
            steps.append(
                TestStep(
                    step_number=step_num,
                    action_type="navigate",
                    target=f"{table_name}.do?sysparm_query=number={target_record}",
                    expected_outcome=f"Re-opened {target_record} form successfully",
                )
            )
            step_num += 1

        # Step 6: Verify persisted state
        final_expected = target_state or initial_state or "verified"
        steps.append(
            TestStep(
                step_number=step_num,
                action_type="validate",
                target="incident.state",
                value=final_expected,
                expected_outcome=f"Persisted state in ServiceNow is verified as '{final_expected}'",
            )
        )

        assertions: list[ExpectedAssertion] = []
        if target_record:
            assertions.append(
                ExpectedAssertion(
                    assertion_id="A-REC-1",
                    field="number",
                    expected_value=target_record,
                    operator="equals",
                    description=f"Record number remains {target_record}",
                )
            )
        if target_state:
            assertions.append(
                ExpectedAssertion(
                    assertion_id="A-STATE-1",
                    field="state",
                    expected_value=target_state,
                    operator="equals",
                    description=f"Final persisted state is {target_state}",
                )
            )

        # Preconditions
        preconditions: list[str] = []
        if target_record:
            preconditions.append(f"Target record {target_record} exists in ServiceNow database table {table_name}")
        if initial_state:
            preconditions.append(f"Initial lifecycle state of {target_record or 'the record'} must be '{initial_state}'")
        if explicit_preconditions:
            for ep in explicit_preconditions:
                if ep not in preconditions:
                    preconditions.append(ep)

        # Preserve and structure Acceptance Criteria with typed assertions
        ac_models: list[AcceptanceCriterion] = []
        if acceptance_criteria:
            for idx, ac_text in enumerate(acceptance_criteria):
                ac_lower = ac_text.lower()
                derived_state = None
                for candidate_st in ("in progress", "on hold", "resolved", "closed", "new", "canceled"):
                    if candidate_st in ac_lower:
                        derived_state = " ".join(w.capitalize() for w in candidate_st.split())
                        break

                if derived_state and not any(a.field == "state" and a.expected_value == derived_state for a in assertions):
                    assertions.append(
                        ExpectedAssertion(
                            assertion_id=f"A-AC-{idx + 1}",
                            field="state",
                            expected_value=derived_state,
                            operator="equals",
                            description=f"Acceptance criterion: state is '{derived_state}'",
                        )
                    )

                ac_models.append(
                    AcceptanceCriterion(
                        id=f"AC-{idx + 1}",
                        statement=ac_text,
                        expected_state=derived_state,
                        assertions=[ac_text],
                    )
                )

        cleanup_reqs: list[str] = []
        if initial_state and target_state and initial_state != target_state and target_record:
            cleanup_reqs.append(f"Revert state of {target_record} back to {initial_state}")

        story_digest = hashlib.sha256(story_text.strip().encode("utf-8")).hexdigest()[:8].upper()
        test_case_id = f"TC-{target_record or 'UAT'}-{story_digest}"

        return GeneratedTestCase(
            id=test_case_id,
            source_user_story=story_text,
            module=table_name,
            table=table_name,
            target_record=target_record,
            actor_role=actor_role,
            preconditions=preconditions,
            expected_initial_state=initial_state,
            test_data={"record_number": target_record, "target_state": target_state},
            ordered_steps=steps,
            acceptance_criteria=ac_models,
            final_assertions=assertions,
            negative_scenario=None,
            risk_level="Medium",
            risk_reason="State transition with persistence verification",
            documentation_references=["servicenow_docs/incident_management.md#state-transitions"],
            evidence_requirements=["screenshot_before", "screenshot_after", "dom_state_hash"],
            cleanup_requirements=cleanup_reqs,
            is_exploratory=False,
        )
