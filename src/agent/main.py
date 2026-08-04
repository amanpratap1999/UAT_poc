"""Main application entry point — FastAPI app and Agent Orchestrator.

The AgentOrchestrator is the central cognitive runtime that ties all engines
and cognitive layers together into the autonomous reasoning loop:

    User Goal → Intent Manager → Planner & Skill Framework → World Model
    → Reflection & Confidence Engine → Decision Engine → Tool Registry
    → Execution Controller → Playwright → Observation Engine → World Model
    → Reflection Engine → Knowledge Memory → Reasoning Trace
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from agent import __version__
from agent.api.v1.dependencies import (
    get_browser_manager,
    get_cached_settings,
    get_confidence_engine,
    get_decision_engine,
    get_intent_manager,
    get_knowledge_memory,
    get_knowledge_store,
    get_observation_engine,
    get_planner,
    get_recovery_engine,
    get_reflection_engine,
    get_reporting_engine,
    get_skill_registry,
    get_tool_registry,
    get_validation_engine,
    get_world_model,
)
from agent.api.v1.router import router
from agent.browser.manager import BrowserManager
from agent.browser.page_interactor import PageInteractor
from agent.confidence.engine import ConfidenceEngine
from agent.core.config import Settings
from agent.core.exceptions import AgentMaxStepsExceededError
from agent.core.logging import get_logger, setup_logging
from agent.core.state_machine import AgentStateMachine
from agent.core.types import AgentState
from agent.decision.engine import DecisionEngine
from agent.domain.reflection import ReflectionResult
from agent.domain.report import TestReport
from agent.execution.controller import ExecutionController
from agent.intent.manager import IntentManager
from agent.knowledge.store import KnowledgeStore
from agent.memory.long_term import KnowledgeMemory
from agent.memory.session import SessionMemory
from agent.observation.engine import ObservationEngine
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reflection.engine import ReflectionEngine
from agent.reporting.engine import ReportingEngine
from agent.skills.registry import SkillRegistry
from agent.tools.registry import ToolRegistry
from agent.validation.engine import ValidationEngine
from agent.world.model import WorldModel

logger = get_logger(__name__)


class AgentOrchestrator:
    """The autonomous cognitive agent runtime.

    Orchestrates all engines through the cognitive loop:
        Intent → Skill Resolution → Planning → World Modeling → Confidence
        → Decision → Tool Invocation → Observation → Validation
        → Reflection → Learning → Reasoning Trace
    """

    def __init__(
        self,
        settings: Settings,
        planner: Planner,
        browser_manager: BrowserManager,
        observation_engine: ObservationEngine,
        validation_engine: ValidationEngine,
        recovery_engine: RecoveryEngine,
        reporting_engine: ReportingEngine,
        knowledge_store: KnowledgeStore,
        intent_manager: IntentManager | None = None,
        world_model: WorldModel | None = None,
        skill_registry: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        reflection_engine: ReflectionEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        knowledge_memory: KnowledgeMemory | None = None,
        decision_engine: DecisionEngine | None = None,
    ) -> None:
        self._settings = settings
        self._planner = planner
        self._browser_manager = browser_manager
        self._observation_engine = observation_engine
        self._validation_engine = validation_engine
        self._recovery_engine = recovery_engine
        self._reporting_engine = reporting_engine
        self._knowledge_store = knowledge_store

        # Cognitive components
        self._intent_manager = intent_manager or IntentManager()
        self._world_model = world_model or WorldModel()
        self._skill_registry = skill_registry or SkillRegistry()
        self._tool_registry = tool_registry or ToolRegistry()
        self._reflection_engine = reflection_engine or ReflectionEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._knowledge_memory = knowledge_memory or KnowledgeMemory()
        self._decision_engine = decision_engine or DecisionEngine(
            confidence_engine=self._confidence_engine,
            reflection_engine=self._reflection_engine,
            tool_registry=self._tool_registry,
        )

        # State Machine & Memory
        self._state_machine = AgentStateMachine(initial_state=AgentState.IDLE)
        self._memory = SessionMemory(
            observation_window=settings.agent.observation_window,
        )
        self._stop_requested = False
        self._report: TestReport | None = None
        self._report_file: str | None = None

        # Built during run
        self._page_interactor: PageInteractor | None = None
        self._execution_controller: ExecutionController | None = None

    @property
    def session_id(self) -> str:
        return self._memory.session_id

    @property
    def memory(self) -> SessionMemory:
        return self._memory

    @property
    def state_machine(self) -> AgentStateMachine:
        return self._state_machine

    @property
    def report(self) -> TestReport | None:
        return self._report

    @property
    def report_file(self) -> str | None:
        return self._report_file

    def request_stop(self, reason: str = "User requested stop") -> None:
        """Signal the agent to stop after the current step."""
        logger.info("stop_requested", reason=reason)
        self._stop_requested = True

    async def run(self, goal: str) -> TestReport:
        """Execute the full autonomous cognitive agent loop."""
        logger.info("agent_run_started", goal=goal, session_id=self.session_id)

        self._memory.goal = goal

        try:
            # 1. INTENT ANALYSIS
            self._transition(AgentState.INTENT_ANALYSIS, "Parsing user prompt into structured intent")
            structured_intent = await self._intent_manager.parse_intent(goal)
            self._memory.structured_intent = structured_intent

            # Resolve domain skill if registered
            skill = self._skill_registry.resolve_skill(structured_intent)
            if skill:
                logger.info("skill_resolved_for_intent", skill=skill.manifest.name)

            # 2. LAUNCH BROWSER
            await self._browser_manager.launch()
            page = self._browser_manager.get_page()
            self._page_interactor = PageInteractor(page)
            self._execution_controller = ExecutionController(
                browser_manager=self._browser_manager,
                page_interactor=self._page_interactor,
                recovery_engine=self._recovery_engine,
                servicenow_config=self._settings.servicenow,
            )

            # Navigate to ServiceNow
            instance_url = self._settings.servicenow.instance_url
            self._memory.add_timeline_entry(action="Navigate to ServiceNow", result="started")
            await self._browser_manager.navigate(instance_url)

            # 3. PLANNING
            self._transition(AgentState.PLANNING, "Creating execution plan")
            knowledge = await self._knowledge_store.retrieve(goal)
            long_term_context = self._knowledge_memory.get_prompt_summary(goal)
            combined_context = f"{knowledge}\n{long_term_context}".strip()

            if skill:
                plan = await skill.plan(structured_intent)
            else:
                plan = await self._planner.create_plan(goal, combined_context)

            self._memory.plan = plan
            self._memory.add_timeline_entry(
                action=f"Plan created with {len(plan.steps)} steps",
                result="success",
            )

            # 4. EXECUTE COGNITIVE LOOP
            await self._execute_cognitive_loop()

        except AgentMaxStepsExceededError:
            logger.warning("max_steps_exceeded", steps=self._memory.total_actions_executed)
            self._transition_safe(AgentState.FAILED, "Max steps exceeded")
        except Exception as e:
            logger.error("agent_run_error", error=str(e), error_type=type(e).__name__)
            self._transition_safe(AgentState.FAILED, f"Error: {e}")
            self._memory.add_failure(
                error_type=type(e).__name__,
                error_message=str(e),
            )
        finally:
            # Generate report
            try:
                self._report = await self._generate_report()
            except Exception as e:
                logger.error("report_generation_failed", error=str(e))

            await self._browser_manager.close()

        logger.info(
            "agent_run_completed",
            session_id=self.session_id,
            state=self._memory.state.value,
            actions=self._memory.total_actions_executed,
        )

        return self._report  # type: ignore[return-value]

    async def _execute_cognitive_loop(self) -> None:
        """The cognitive reasoning loop:
        Observe -> World Model -> Reasoning -> Decision -> Execution -> Validate -> Reflect -> Learn -> Transition
        """
        max_steps = self._settings.agent.max_steps
        latest_reflection: ReflectionResult | None = None

        while self._memory.total_actions_executed < max_steps:
            if self._stop_requested:
                logger.info("agent_stopped_by_user")
                self._transition(AgentState.COMPLETED, "User requested stop")
                break

            # A. OBSERVATION
            self._transition(AgentState.OBSERVING, "Observing browser state")
            page = self._browser_manager.get_page()
            raw_obs = await self._observation_engine.observe(page)
            self._memory.add_observation(raw_obs)

            # B. WORLD MODELING & REASONING
            self._transition(AgentState.REASONING, "Building world model & evaluating cognitive hypotheses")
            world_state = self._world_model.build_semantic_state(raw_obs)

            # C. DECISION MAKING
            self._transition(AgentState.DECISION, "Selecting immediate action & scoring confidence")
            intent = self._memory.structured_intent or (
                await self._intent_manager.parse_intent(self._memory.goal)
            )

            decision = await self._decision_engine.decide_next_action(
                intent=intent,
                world_state=world_state,
                memory=self._memory,
                latest_reflection=latest_reflection,
            )

            action = decision.action
            confidence_assessment = decision.confidence_assessment

            # Record reasoning cycle in trace
            self._memory.reasoning_trace.record_cycle(
                step_index=self._memory.current_step_index,
                state_name=self._state_machine.current_state.value,
                observation_summary=world_state.to_compact_cognitive_summary(),
                hypotheses=latest_reflection.hypotheses if latest_reflection else [],
                decision_rationale=decision.reasoning,
                chosen_action=action,
                confidence_score=confidence_assessment.score,
            )

            # Low confidence guardrail
            if not confidence_assessment.is_above_threshold and confidence_assessment.suggested_pre_action:
                logger.warning(
                    "confidence_below_threshold_pre_action",
                    score=confidence_assessment.score,
                    suggested=confidence_assessment.suggested_pre_action,
                )
                if confidence_assessment.suggested_pre_action == "observe":
                    await page.wait_for_timeout(1000)
                    continue

            # D. EXECUTION
            self._transition(AgentState.EXECUTING, f"Executing action: {action.action_type}")
            if self._memory.plan and self._memory.plan.current_step:
                self._memory.plan.current_step.mark_in_progress()

            result = await self._execution_controller.execute(action)  # type: ignore[union-attr]

            self._memory.add_timeline_entry(
                action=f"{action.action_type}: {action.target}",
                result="success" if result.success else f"failed: {result.error}",
                duration_ms=result.duration_ms,
                screenshot_path=result.screenshot_path,
            )

            # E. POST-ACTION OBSERVATION & VALIDATION
            self._transition(AgentState.OBSERVING, "Post-action observation")
            raw_obs_after = await self._observation_engine.observe(page)
            self._memory.add_observation(raw_obs_after)
            world_state_after = self._world_model.build_semantic_state(raw_obs_after)

            self._transition(AgentState.VALIDATING, "Validating post-action outcome")
            console_errors = self._browser_manager.get_page_errors()
            self._browser_manager.clear_logs()

            validation = await self._validation_engine.validate_action(
                action=action,
                result=result,
                before=raw_obs,
                after=raw_obs_after,
                console_errors=console_errors,
            )

            skill = self._skill_registry.resolve_skill(intent)
            if skill:
                skill_val = await skill.validate(action, world_state, world_state_after)
                validation.checks.extend(skill_val.checks)

            self._memory.add_completed_step(
                action=action,
                result=result,
                observation_before=raw_obs,
                observation_after=raw_obs_after,
                validation=validation,
            )

            if self._memory.plan and self._memory.plan.current_step:
                if result.success and validation.overall_passed:
                    self._memory.plan.current_step.mark_success()
                elif not result.success:
                    self._memory.plan.current_step.mark_failed(result.error or "Action failed")

            # F. REFLECTION
            self._transition(AgentState.REFLECTION, "Reflecting on action outcome")
            latest_reflection = await self._reflection_engine.reflect(
                action=action,
                result=result,
                world_state=world_state_after,
                expected_outcome=decision.expected_outcome,
            )

            # G. LEARNING
            self._transition(AgentState.LEARNING, "Recording long-term instance learning")
            if world_state_after.missing_mandatory_fields:
                self._knowledge_memory.record_learning(
                    topic=f"{world_state_after.raw_page_type.value}.mandatory",
                    insight=f"Mandatory fields on {world_state_after.page_semantic_type}: {', '.join(world_state_after.missing_mandatory_fields)}",
                    category="form_rules",
                )

            # Check for recovery if validation failed
            if not validation.overall_passed and not result.success:
                self._transition(AgentState.RECOVERING, "Attempting planner-level recovery")
                try:
                    await self._planner.suggest_recovery(
                        error=Exception(result.error or "Validation failed"),
                        action=action,
                        observation=raw_obs_after,
                    )
                except Exception as e:
                    logger.warning("recovery_suggestion_failed", error=str(e))

            # H. CHECK COMPLETION
            should_check = (
                self._memory.total_actions_executed % 5 == 0
                or (self._memory.plan and self._memory.plan.current_step is None)
                or (self._memory.plan and self._memory.plan.progress_pct >= 100.0)
            )

            if should_check:
                self._transition(AgentState.REASONING, "Checking goal completion status")
                try:
                    is_complete = await self._planner.is_goal_complete(self._memory)
                    if is_complete:
                        logger.info("goal_complete")
                        self._transition(AgentState.COMPLETED, "Goal achieved")
                        break
                except Exception as e:
                    logger.warning("completion_check_failed", error=str(e))

        else:
            raise AgentMaxStepsExceededError(
                f"Agent exceeded maximum {max_steps} steps",
                details={"steps": self._memory.total_actions_executed},
            )

    def _transition(self, to_state: AgentState, reason: str = "") -> None:
        """Execute state transition via AgentStateMachine and sync SessionMemory."""
        self._state_machine.transition_to(to_state, reason=reason)
        self._memory.state = to_state

    def _transition_safe(self, to_state: AgentState, reason: str = "") -> None:
        """Safely transition to terminal state (COMPLETED/FAILED)."""
        try:
            self._transition(to_state, reason)
        except Exception:
            self._memory.state = to_state

    async def _generate_report(self) -> TestReport:
        """Generate final QA report."""
        logger.info("generating_final_report")
        summary_data = None
        try:
            summary_data = await self._planner.generate_report_summary(self._memory)
        except Exception as e:
            logger.warning("report_summary_generation_failed", error=str(e))

        report = await self._reporting_engine.generate_report(
            memory=self._memory,
            summary_data=summary_data,
        )

        try:
            self._report_file = await self._reporting_engine.save_report(report, format="markdown")
            await self._reporting_engine.save_report(report, format="json")
        except Exception as e:
            logger.warning("report_save_failed", error=str(e))

        return report


def create_orchestrator(settings: Settings | None = None) -> AgentOrchestrator:
    """Factory function to create a fully-wired AgentOrchestrator."""
    s = settings or get_cached_settings()

    return AgentOrchestrator(
        settings=s,
        planner=get_planner(s),
        browser_manager=get_browser_manager(s),
        observation_engine=get_observation_engine(),
        validation_engine=get_validation_engine(),
        recovery_engine=get_recovery_engine(s),
        reporting_engine=get_reporting_engine(s),
        knowledge_store=get_knowledge_store(s),
        intent_manager=get_intent_manager(s),
        world_model=get_world_model(),
        skill_registry=get_skill_registry(),
        tool_registry=get_tool_registry(),
        reflection_engine=get_reflection_engine(s),
        confidence_engine=get_confidence_engine(),
        knowledge_memory=get_knowledge_memory(),
        decision_engine=get_decision_engine(s),
    )


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — setup and teardown."""
    settings = get_cached_settings()
    setup_logging(level=settings.log_level, log_format=settings.log_format)
    logger.info("application_started", version=__version__)
    yield
    logger.info("application_stopped")


app = FastAPI(
    title="ServiceNow QA Agent",
    description="Autonomous AI-powered QA Agent for ServiceNow Incident Management",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(router)
