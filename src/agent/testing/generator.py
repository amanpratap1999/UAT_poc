"""Scenario Generator for Test Intelligence.

Generates testing scenarios, risk scores, and exploratory branch steps
based on selected strategies and current domain knowledge.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.domain.knowledge_model import CustomerKnowledgeModel
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
    """Generates test scenarios via LLM reasoning."""

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
                    domain_facts += f"- Field '{field_name}' (Label: {meta.label}): Type={meta.type}, Mandatory={meta.mandatory}\n"  # noqa: E501
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
                    experience_context += f"- Observation: {e.observation}\n  Outcome: {e.outcome}\n  Confidence: {e.confidence:.2f}\n"  # noqa: E501
                experience_context += "\nUse this historical experience to influence the prioritization and focus of your exploratory scenarios.\n"  # noqa: E501

        prompt = f"""
        You are a senior QA engineer. Generate test scenarios for the following requirement:
        '{requirement}'
        {domain_facts}
        The following test strategies MUST be applied, based on our rules:
        {json.dumps(strategies, indent=2)}
        {experience_context}

        Include at least one unscripted exploratory deviation (e.g. invalid input, double-submit,
action outside expected permissions).
        """

        logger.info("generating_scenarios", strategies_count=len(strategies))

        # We assume OpenAILLMClient has complete_json returning the parsed Pydantic-like dict or we can use raw dict  # noqa: E501
        # Since complete_json returns dict, we parse it into ScenarioGenerationResult
        try:
            response = await self._llm.complete_json(
                messages=[
                    {"role": "system", "content": "You are a senior QA Test Strategist."},
                    {"role": "user", "content": prompt},
                ]
            )

            # Simple parsing fallback
            if "scenarios" in response:
                result = ScenarioGenerationResult(**response)
            else:
                # Attempt to parse if it's a list
                if isinstance(response, list):
                    scenarios = [TestScenario(**s) for s in response]
                    result = ScenarioGenerationResult(
                        scenarios=scenarios, reasoning="Parsed from list"
                    )
                else:
                    raise ValueError("Unexpected JSON format from LLM")

            # Apply deterministic risk scoring and safety checks
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
                        continue  # Skip this scenario because it violates safety

                scenario.risk_score, scenario.risk_reasoning = self._calculate_risk_score(
                    scenario, fields, workflow_type, knowledge_model, table_name
                )
                valid_scenarios.append(scenario)

            logger.info("scenarios_generated", count=len(valid_scenarios))
            # Score and order scenarios using exploratory learning priorities
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
            # Return a safe fallback so tests and execution don't completely halt
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
        score = 2  # Baseline nominal risk
        reasoning = ["Baseline nominal risk (+2)"]

        # 1. Exploratory actions carry higher baseline risk
        if scenario.is_exploratory:
            score += 2
            reasoning.append("Exploratory deviation (+2)")

        # 2. Workflow criticality
        if workflow_type == "approval":
            score += 3
            reasoning.append("Approval workflow involvement (+3)")
        elif workflow_type == "sla":
            score += 2
            reasoning.append("SLA workflow involvement (+2)")

        # 3. Customer customization involvement
        if knowledge_model and table_name:
            table_metadata = knowledge_model.get_table(table_name)
            if table_metadata:
                for field in fields:
                    f_name = field.get("name")
                    if f_name and f_name in table_metadata.fields:
                        meta = table_metadata.fields[f_name]
                        # If a field is part of UI policies or specifically marked mandatory/read-only  # noqa: E501
                        if meta.mandatory:
                            score += 1
                            reasoning.append(f"Involves mandatory field '{f_name}' (+1)")
                            # Don't add multiple times for multiple fields to keep it bounded
                            break

        # 4. Strategy multiplier
        for strategy in scenario.strategies_applied:
            if "Negative Testing" in strategy or "Injection" in strategy or "Boundary" in strategy:
                score += 1
                reasoning.append(f"Complex QA strategy applied '{strategy[:20]}...' (+1)")
                break

        final_score = max(1, min(10, score))
        return final_score, ", ".join(reasoning)
