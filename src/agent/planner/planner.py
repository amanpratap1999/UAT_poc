"""Planner — the brain of the autonomous agent.

The planner uses an LLM to reason about goals, create execution plans,
decide next actions, assess validations, suggest recovery strategies,
and determine when the goal is complete. It never touches Playwright —
it only emits structured actions that the ExecutionController translates
into browser operations.
"""

from __future__ import annotations

from typing import Any

from agent.core.exceptions import LLMResponseParseError, PlannerError
from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.knowledge_model import CustomerKnowledgeModel
from agent.domain.observation import PageObservation
from agent.domain.plan import ExecutionPlan
from agent.domain.validation import ValidationCheck, ValidationResult
from agent.memory.session import SessionMemory
from agent.planner.llm_client import BaseLLMClient
from agent.planner.prompts import (
    COMPLETION_CHECK_PROMPT,
    NEXT_ACTION_PROMPT,
    PLAN_GENERATION_PROMPT,
    RECOVERY_PROMPT,
    REPORT_SUMMARY_PROMPT,
    SYSTEM_PROMPT,
    VALIDATION_ASSESSMENT_PROMPT,
)
from agent.testing.generator import ScenarioGenerator, TestScenario
from agent.testing.store import TestIntelligenceStore

logger = get_logger(__name__)


class Planner:
    """The LLM-based reasoning engine.

    Responsibilities:
    - Decompose business goals into execution plans
    - Decide the next action based on observations and memory
    - Assess whether actions achieved their intent
    - Suggest recovery strategies for failures
    - Determine when the goal is complete
    - Generate professional report summaries
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        knowledge_context: str = "",
        scenario_generator: ScenarioGenerator | None = None,
        test_store: TestIntelligenceStore | None = None,
        knowledge_model: CustomerKnowledgeModel | None = None,
    ) -> None:
        self._llm = llm_client
        self._knowledge_model = knowledge_model
        km_context = ""
        if knowledge_model and hasattr(knowledge_model, "to_context_str"):
            km_context = knowledge_model.to_context_str()
        self._knowledge_context = knowledge_context or km_context
        self._scenario_generator = scenario_generator
        self._test_store = test_store

    async def generate_test_scenarios(
        self,
        requirement: str,
        fields: list[dict[str, Any]],
        workflow_type: str | None = None,
        knowledge_model: CustomerKnowledgeModel | None = None,
        table_name: str | None = None,
    ) -> list[TestScenario]:
        """Generate test scenarios dynamically based on strategies."""
        if not self._scenario_generator:
            raise PlannerError("ScenarioGenerator is not initialized.")

        scenarios = await self._scenario_generator.generate_scenarios(
            requirement, fields, workflow_type, knowledge_model, table_name
        )

        # Save to store
        if self._test_store:
            for s in scenarios:
                await self._test_store.save_scenario(s)

        return scenarios

    async def create_plan(self, goal: str, context: str = "") -> ExecutionPlan:
        """Decompose a business goal into an ordered execution plan.

        Args:
            goal: The business-level testing goal.
            context: Additional context (ServiceNow knowledge, etc.)

        Returns:
            An ExecutionPlan with ordered steps.

        Raises:
            PlannerError: If plan generation fails.
        """
        logger.info("creating_plan", goal=goal)

        knowledge = context or self._knowledge_context
        prompt = PLAN_GENERATION_PROMPT.format(
            goal=goal,
            knowledge_context=knowledge,
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            steps_data = response.get("steps", [])
            plan = ExecutionPlan(goal=goal)
            for step_data in steps_data:
                plan.add_step(
                    description=step_data.get("description", ""),
                    expected_outcome=step_data.get("expected_outcome", ""),
                )
            logger.info("plan_created", steps=len(plan.steps))
            return plan
        except Exception as e:
            raise PlannerError(
                f"Failed to parse plan from LLM response: {e}",
                details={"response": response},
            ) from e

    async def decide_next_action(
        self,
        observation: PageObservation,
        memory: SessionMemory,
    ) -> AgentAction:
        """Decide the next action based on current observation and memory.

        This is the core reasoning step in the agent loop. The planner
        considers the current page state, the plan, and recent history
        to choose the optimal next action.

        Args:
            observation: Current page observation.
            memory: Session memory with full context.

        Returns:
            The next AgentAction to execute.
        """
        logger.info("deciding_next_action", step=memory.current_step_index)

        current_step = ""
        if memory.plan and memory.plan.current_step:
            step = memory.plan.current_step
            current_step = (
                f"Step {step.step_index}: {step.description}\nExpected: {step.expected_outcome}"
            )
        else:
            current_step = "No specific plan step — use your judgment based on the goal."

        prompt = NEXT_ACTION_PROMPT.format(
            session_context=memory.get_context_for_llm(),
            current_step=current_step,
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            action = self._parse_action(response)
            logger.info(
                "action_decided",
                action_type=action.action_type,
                target=action.target,
                reasoning=action.reasoning[:100],
            )
            return action
        except Exception as e:
            raise PlannerError(
                f"Failed to parse action from LLM response: {e}",
                details={"response": response},
            ) from e

    async def assess_validation(
        self,
        action: AgentAction,
        result: Any,
        before: PageObservation,
        after: PageObservation,
    ) -> ValidationResult:
        """Assess whether an action achieved its intended result.

        Uses the LLM to compare before/after observations and determine
        if the action was successful.

        Args:
            action: The action that was executed.
            result: The ActionResult from execution.
            before: Page observation before the action.
            after: Page observation after the action.

        Returns:
            A ValidationResult with individual checks.
        """
        logger.info("assessing_validation", action=action.action_type)

        prompt = VALIDATION_ASSESSMENT_PROMPT.format(
            action_description=f"{action.action_type}: {action.target} → {action.value}",
            before_observation=before.to_compact_summary(),
            after_observation=after.to_compact_summary(),
            action_success=result.success if hasattr(result, "success") else True,
            action_error=result.error if hasattr(result, "error") else "None",
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            validation = ValidationResult(
                action_description=f"{action.action_type}: {action.target}",
            )
            for check_data in response.get("checks", []):
                check = ValidationCheck(
                    check_name=check_data.get("check_name", "unknown"),
                    description=check_data.get("description", ""),
                    passed=check_data.get("passed", False),
                    expected=check_data.get("expected", ""),
                    actual=check_data.get("actual", ""),
                    error_message=check_data.get("error_message"),
                )
                validation.add_check(check)

            # Ensure overall_passed is set from LLM if no checks
            if not validation.checks:
                validation.overall_passed = response.get("overall_passed", False)

            logger.info(
                "validation_assessed",
                passed=validation.overall_passed,
                checks=len(validation.checks),
            )
            return validation
        except Exception as e:
            raise PlannerError(
                f"Failed to parse validation from LLM response: {e}",
                details={"response": response},
            ) from e

    async def suggest_recovery(
        self,
        error: Exception,
        action: AgentAction,
        observation: PageObservation,
        recovery_history: list[str] | None = None,
    ) -> AgentAction:
        """Suggest a recovery action after a failure.

        The planner analyzes the error context and current page state
        to suggest an alternative action.

        Args:
            error: The exception that occurred.
            action: The action that failed.
            observation: Current page observation.
            recovery_history: Previous recovery attempts.

        Returns:
            A recovery AgentAction to try.
        """
        logger.info("suggesting_recovery", error_type=type(error).__name__)

        history_str = "\n".join(recovery_history) if recovery_history else "None"

        prompt = RECOVERY_PROMPT.format(
            failed_action=f"{action.action_type}: {action.target} → {action.value}",
            error_type=type(error).__name__,
            error_message=str(error),
            current_observation=observation.to_compact_summary(),
            recovery_history=history_str,
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            action = self._parse_action(response)
            logger.info(
                "recovery_suggested",
                action_type=action.action_type,
                reasoning=action.reasoning[:100],
            )
            return action
        except Exception as e:
            raise PlannerError(
                f"Failed to parse recovery action: {e}",
                details={"response": response},
            ) from e

    async def is_goal_complete(self, memory: SessionMemory) -> bool:
        """Determine whether the business goal has been achieved.

        Uses the LLM to analyze the session history and make a
        completion determination.

        Args:
            memory: Session memory with full execution context.

        Returns:
            True if the goal is considered complete.
        """
        logger.info("checking_goal_completion")

        completed_steps_str = "\n".join(
            f"  Step {s.step_index}: {s.action.action_type} → {'✅' if s.result.success else '❌'}"
            for s in memory.completed_steps[-20:]  # Last 20 steps
        )

        prompt = COMPLETION_CHECK_PROMPT.format(
            goal=memory.goal,
            session_context=memory.get_context_for_llm(),
            completed_steps=completed_steps_str,
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        is_complete = response.get("is_complete", False)
        reasoning = response.get("reasoning", "")

        logger.info(
            "goal_completion_check",
            is_complete=is_complete,
            reasoning=reasoning[:200],
        )
        return is_complete  # type: ignore[no-any-return]

    async def generate_report_summary(self, memory: SessionMemory) -> dict[str, Any]:
        """Generate a professional executive summary for the report.

        Args:
            memory: Session memory with full execution context.

        Returns:
            Dict with summary, recommendations, and root_cause_hypotheses.
        """
        logger.info("generating_report_summary")

        defects_str = "None found"
        if memory.failures:
            defects_str = "\n".join(
                f"  - {f.error_type}: {f.error_message}" for f in memory.failures
            )

        passed = sum(1 for v in memory.completed_validations if v.overall_passed)
        failed = sum(1 for v in memory.completed_validations if not v.overall_passed)

        prompt = REPORT_SUMMARY_PROMPT.format(
            goal=memory.goal,
            session_context=memory.get_context_for_llm(),
            total_validations=memory.total_validations_run,
            passed_validations=passed,
            failed_validations=failed,
            defects_summary=defects_str,
        )

        response = await self._llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        return {
            "summary": response.get("summary", "Report generation failed."),
            "recommendations": response.get("recommendations", []),
            "root_cause_hypotheses": response.get("root_cause_hypotheses", []),
        }

    def _parse_action(self, data: dict[str, Any]) -> AgentAction:
        """Parse an LLM response dict into an AgentAction.

        Handles the various action types and their specific fields.

        Args:
            data: The parsed JSON response from the LLM.

        Returns:
            An AgentAction instance.

        Raises:
            LLMResponseParseError: If the data cannot be parsed.
        """
        action_type = data.get("action_type", "")
        if not action_type:
            raise LLMResponseParseError(
                "LLM response missing 'action_type'",
                details={"data": data},
            )

        return AgentAction(
            action_type=action_type,
            target=data.get("target", ""),
            value=data.get("value", ""),
            reasoning=data.get("reasoning", ""),
            metadata={
                k: v
                for k, v in data.items()
                if k not in ("action_type", "target", "value", "reasoning")
            },
        )
