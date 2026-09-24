"""Main application entry point — FastAPI app and Agent Orchestrator.

The AgentOrchestrator is the central cognitive runtime that ties all engines
and cognitive layers together into the autonomous reasoning loop:

    User Goal → Intent Manager → Planner & Skill Framework → World Model
    → Reflection & Confidence Engine → Decision Engine → Tool Registry
    → Execution Controller → Playwright → Observation Engine → World Model
    → Reflection Engine → Knowledge Memory → Reasoning Trace
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import inspect
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent import __version__
from agent.api.v1.auth_router import router as auth_router
from agent.api.v1.dependencies import (
    get_behavioral_verifier,
    get_browser_manager,
    get_cached_settings,
    get_confidence_engine,
    get_customer_knowledge_model,
    get_decision_engine,
    get_grounder_backend,
    get_intent_manager,
    get_knowledge_memory,
    get_knowledge_store,
    get_learning_service,
    get_observation_engine,
    get_planner,
    get_recovery_engine,
    get_reflection_engine,
    get_reporting_engine,
    get_scenario_generator,
    get_session_store,
    get_skill_registry,
    get_test_intelligence_store,
    get_tool_registry,
    get_validation_engine,
    get_world_model,
)
from agent.api.v1.schemas import HealthResponse
from agent.api.v1.router import health_check, readiness_check, router
from agent.browser.manager import BrowserManager
from agent.browser.page_interactor import PageInteractor
from agent.capabilities.registry import CapabilityRegistry
from agent.confidence.engine import ConfidenceEngine
from agent.core.config import Settings
from agent.core.exceptions import AgentMaxStepsExceededError
from agent.core.logging import get_logger, setup_logging
from agent.core.state_machine import AgentStateMachine
from agent.core.types import AgentState
from agent.decision.engine import DecisionEngine
from agent.domain.journal import MutationJournal
from agent.domain.knowledge_model import CustomerKnowledgeModel
from agent.domain.report import TestReport
from agent.execution.controller import ExecutionController
from agent.intent.manager import IntentManager
from agent.knowledge.store import KnowledgeStore
from agent.learning.service import LearningService
from agent.memory.long_term import KnowledgeMemory
from agent.memory.session import SessionMemory
from agent.memory.session_store import SessionStore
from agent.observation.engine import ObservationEngine
from agent.perception.backends import GrounderBackend
from agent.perception.engine import PerceptionDecisionEngine
from agent.perception.store import RecoveryStore
from agent.perception.verifier import BehavioralVerifier
from agent.planner.planner import Planner
from agent.recovery.engine import RecoveryEngine
from agent.reflection.engine import ReflectionEngine
from agent.reporting.engine import ReportingEngine
from agent.testing.generator import ScenarioGenerator
from agent.testing.store import TestIntelligenceStore
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

    Audit issue I17 (P2): previously this class had TWO docstrings — a
    short one at line 92 (\"Coordinates planning, execution, validation
    and reporting for a run.\") and a longer orphan one at line 148 that
    was parsed by Python as a no-op string expression (not a docstring).
    AgentOrchestrator.__doc__ returned the short one; the long one was
    silently lost. Fix: merged the long docstring into the class docstring
    (placed immediately below `class AgentOrchestrator:`).
    """

    @staticmethod
    def _compare_restoration(baseline: Any, final: Any) -> list[str] | None:
        """Compare a re-observed record against the pre-run baseline (QA-012).

        Args:
            baseline: PageObservation captured before the first action.
            final: PageObservation captured after cleanup ran.

        Returns:
            None when no baseline values were captured (restoration cannot be
            verified), an empty list when restoration is confirmed, or the
            list of mismatches.
        """
        base_number = (
            getattr(baseline, "record_number", "")
            or getattr(baseline, "incident_number", "")
            or ""
        )
        final_number = (
            getattr(final, "record_number", "")
            or getattr(final, "incident_number", "")
            or ""
        )
        base_state = (
            getattr(baseline, "current_state", "") or getattr(baseline, "record_state", "") or ""
        )
        final_state = (
            getattr(final, "current_state", "") or getattr(final, "record_state", "") or ""
        )

        if not base_number and not base_state:
            return None

        mismatches: list[str] = []
        if base_number and str(final_number).strip() != str(base_number).strip():
            mismatches.append(
                f"record number changed during cleanup: {base_number} -> {final_number}"
            )
        if base_state and str(final_state).strip().lower() != str(base_state).strip().lower():
            mismatches.append(f"state not restored: was {base_state}, now {final_state}")

        # Compare all visible fields
        base_fields = {f.name.lower(): f.value for f in getattr(baseline, "visible_fields", [])}
        final_fields = {f.name.lower(): f.value for f in getattr(final, "visible_fields", [])}

        for name, base_val in base_fields.items():
            final_val = final_fields.get(name, "")
            if str(base_val).strip() != str(final_val).strip():
                # Ignore empty to none translations and timestamp fields
                if not (str(base_val).strip() == "" and str(final_val).strip() == "") and "time" not in name and "date" not in name:
                    mismatches.append(f"field '{name}' not restored: was '{base_val}', now '{final_val}'")

        return mismatches

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
        session_store: SessionStore,
        learning_service: LearningService,
        intent_manager: IntentManager | None = None,
        world_model: WorldModel | None = None,
        skill_registry: CapabilityRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        reflection_engine: ReflectionEngine | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        knowledge_memory: KnowledgeMemory | None = None,
        decision_engine: DecisionEngine | None = None,
        recovery_store: RecoveryStore | None = None,
        grounder: GrounderBackend | None = None,
        behavioral_verifier: BehavioralVerifier | None = None,
        scenario_generator: ScenarioGenerator | None = None,
        test_store: TestIntelligenceStore | None = None,
        customer_knowledge_model: CustomerKnowledgeModel | None = None,
    ) -> None:
        self._settings = settings
        self._reporting_engine = reporting_engine
        self._learning = learning_service

        self._planner = planner
        self._browser_manager = browser_manager
        self._observation_engine = observation_engine
        self._validation_engine = validation_engine
        self._recovery_engine = recovery_engine
        self._knowledge_store = knowledge_store
        self._session_store = session_store

        self._grounder = grounder
        self._behavioral_verifier = behavioral_verifier

        # Cognitive components
        self._intent_manager = intent_manager or IntentManager()
        self._world_model = world_model or WorldModel()
        self._skill_registry = skill_registry or CapabilityRegistry()
        self._tool_registry = tool_registry or ToolRegistry()
        self._reflection_engine = reflection_engine or ReflectionEngine()
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._knowledge_memory = knowledge_memory or KnowledgeMemory()
        self._decision_engine = decision_engine or DecisionEngine(
            confidence_engine=self._confidence_engine,
            reflection_engine=self._reflection_engine,
            tool_registry=self._tool_registry,
        )

        from agent.cognition.orchestrator import CognitiveOrchestrator

        self._cognitive_orchestrator = CognitiveOrchestrator(
            skill_registry=self._skill_registry,
            knowledge_model=customer_knowledge_model,
            learning_service=learning_service,
            scenario_generator=scenario_generator,
            decision_engine=self._decision_engine,
            validation_engine=validation_engine,
            perception_engine=None,  # Will be set after launch
            execution_controller=None,  # Will be set after launch
            observation_engine=observation_engine,
            browser_manager=browser_manager,
            state_machine=None,
            settings=settings,
            llm_client=None,  # Planner LLM client
        )

        # Testing & Domain
        self._scenario_generator = scenario_generator
        self._test_store = test_store
        self._customer_knowledge_model = customer_knowledge_model

        # Audit issue I16 (P2) — proper fix: use public setters on Planner
        # and CognitiveOrchestrator instead of reaching into private attrs.
        self._planner.set_scenario_generator(self._scenario_generator)
        self._planner.set_test_store(self._test_store)

        self._cognitive_orchestrator.attach_llm(self._planner.get_llm_client())

        # State Machine & Memory
        self._state_machine = AgentStateMachine(initial_state=AgentState.IDLE)
        self._cognitive_orchestrator.attach_state_machine(self._state_machine)
        self._memory = SessionMemory(
            observation_window=settings.agent.observation_window,
        )
        from agent.core.locks import RecordLockManager
        self._lock_manager = RecordLockManager()
        self._locked_records: set[str] = set()
        self._journal = MutationJournal()
        self._cognitive_orchestrator.attach_journal(self._journal)
        self._stop_requested = False
        self._report: TestReport | None = None
        self._report_file: str | None = None
        self._event_publisher: Any | None = None
        self._control_receiver: Any | None = None

        # Built during run
        self._page_interactor: PageInteractor | None = None
        self._execution_controller: ExecutionController | None = None
        self._perception_engine: PerceptionDecisionEngine | None = None

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

    def set_event_publisher(self, publisher: Any) -> None:
        """Set the live run event publisher."""
        self._event_publisher = publisher
        if hasattr(self, "_cognitive_orchestrator") and self._cognitive_orchestrator:
            self._cognitive_orchestrator.set_event_publisher(publisher)

    def set_control_receiver(self, receiver: Any) -> None:
        """Set the interactive control receiver."""
        self._control_receiver = receiver
        if hasattr(self, "_cognitive_orchestrator") and self._cognitive_orchestrator:
            self._cognitive_orchestrator.set_control_receiver(receiver)

    def request_stop(self, reason: str = "User requested stop") -> None:
        """Signal the agent to stop after the current step."""
        logger.info("stop_requested", reason=reason)
        self._stop_requested = True
        if hasattr(self, "_cognitive_orchestrator") and self._cognitive_orchestrator:
            self._cognitive_orchestrator.request_stop()

    def set_test_case(self, tc_data: dict[str, Any]) -> None:
        """Inject a structured test case into the orchestrator memory (P0.2)."""
        from agent.domain.plan import ExecutionPlan, PlanStep
        
        goal = tc_data.get("title") or tc_data.get("description") or "Execute Test Case"
        plan = ExecutionPlan(goal=goal)
        
        for idx, step_data in enumerate(tc_data.get("ordered_steps", [])):
            if isinstance(step_data, dict):
                # Check for explicit action
                desc = step_data.get("description") or step_data.get("action") or ""
                
                # If we have raw TestStep dicts (action_type, target, value)
                if "action_type" in step_data:
                    at = step_data["action_type"]
                    tgt = step_data.get("target", "")
                    val = step_data.get("value", "")
                    if not desc:
                        desc = f"{at} {tgt}"
                        if val:
                            desc += f" with '{val}'"
                
                step = PlanStep(
                    step_index=idx + 1,
                    description=desc.strip() or f"Step {idx+1}",
                    expected_outcome=step_data.get("expected_outcome", ""),
                )
                
                # Store the explicit action for the bypass
                if "action_type" in step_data:
                    step.expected_values = step_data
                
                plan.steps.append(step)
                
        for idx, step_data in enumerate(tc_data.get("cleanup_steps", [])):
            if isinstance(step_data, dict):
                desc = step_data.get("description") or step_data.get("action") or ""
                if "action_type" in step_data:
                    at = step_data["action_type"]
                    tgt = step_data.get("target", "")
                    val = step_data.get("value", "")
                    if not desc:
                        desc = f"{at} {tgt}" + (f" with '{val}'" if val else "")
                
                step = PlanStep(
                    step_index=len(plan.steps) + idx + 1,
                    description=desc.strip() or f"Cleanup Step {idx+1}",
                    expected_outcome=step_data.get("expected_outcome", ""),
                )
                if "action_type" in step_data:
                    step.expected_values = step_data
                plan.cleanup_steps.append(step)

        self._memory.plan = plan
        
        # P0.6 FINAL VERIFICATION: Store final assertions in memory for later
        final_assertions = tc_data.get("final_assertions", [])
        if final_assertions:
            setattr(self._memory, 'final_assertions', final_assertions)
        self._memory.test_case_data = tc_data
        
        logger.info("test_case_loaded_as_plan", steps=len(plan.steps))

    async def _ensure_authenticated(self) -> None:
        """Log in to ServiceNow if the initial navigation lands on a login screen."""
        if not self._browser_manager:
            return
        try:
            page = self._browser_manager.get_page()
            user_input = page.locator("input#user_name, input[name='user_name']")
            if await user_input.count() > 0:
                logger.info("authenticating_servicenow_session")
                username, password = self._settings.servicenow.get_active_credentials()
                if username and password:
                    await user_input.first.fill(username)
                    pass_input = page.locator("input#user_password, input[name='user_password']")
                    if await pass_input.count() > 0:
                        await pass_input.first.fill(password)
                    login_btn = page.locator(
                        "button#sysverb_login, button:has-text('Log in'), input[type='submit']"
                    )
                    if await login_btn.count() > 0:
                        await login_btn.first.click()
                        await self._browser_manager.wait_for_load()
                        await page.wait_for_timeout(3000)
                        logger.info("servicenow_session_authenticated")
        except Exception as e:
            logger.warning("ensure_authenticated_skipped", error=str(e))

    async def _save_session(self) -> None:
        """Persist the current session state to the session store."""
        await self._session_store.save(self.session_id, self._memory.model_dump(mode="json"))

    async def wait_for_manual_browser_close(self, timeout_seconds: float | None = None) -> None:
        """Keep the configured headed browser alive for manual inspection with safe timeout."""
        if (
            self._browser_manager
            and self._settings.browser.keep_browser_open
            and not self._settings.browser.headless
        ):
            await self._browser_manager.wait_until_closed(timeout_seconds=timeout_seconds)
            await self._browser_manager.close()

    async def generate_test_scenarios(
        self,
        requirement: str,
        fields: list[dict[str, Any]],
        workflow_type: str | None = None,
        table_name: str | None = None,
    ) -> list[Any]:
        """Generate test scenarios, utilizing domain intelligence if available."""
        return await self._planner.generate_test_scenarios(
            requirement=requirement,
            fields=fields,
            workflow_type=workflow_type,
            knowledge_model=self._customer_knowledge_model,
            table_name=table_name,
        )

    async def run(self, goal: str, persona: str | None = None) -> TestReport:
        """Execute the full autonomous cognitive agent loop."""
        from agent.core.redaction import redact_string
        goal = redact_string(goal)
        
        logger.info("agent_run_started", goal=goal, session_id=self.session_id, persona=persona)

        if persona:
            # Persona isolation (P1.9): use a per-run copy of the ServiceNow
            # config so concurrent multi-persona sweeps never mutate the
            # process-wide cached settings and leak credentials between runs.
            self._settings = self._settings.model_copy(deep=True)
            self._settings.servicenow.active_persona = persona

        self._memory.goal = goal
        self._memory.persona = persona
        await self._save_session()

        if self._stop_requested:
            self._transition_safe(AgentState.COMPLETED, "Stop requested prior to run")
            report = await self._reporting_engine.generate_report(self._memory)
            self._report_file = await self._reporting_engine.save_report(report)
            return report

        try:
            # 1. INTENT ANALYSIS
            self._transition(
                AgentState.INTENT_ANALYSIS, "Parsing user prompt into structured intent"
            )
            structured_intent = await self._intent_manager.parse_intent(goal)
            self._memory.structured_intent = structured_intent

            # Resolve domain skill if registered
            skill = self._skill_registry.resolve_skill(structured_intent)
            if skill:
                logger.info("skill_resolved_for_intent", skill=skill.manifest.name)

            # 2. LAUNCH BROWSER
            await self._browser_manager.launch()
            self._observation_engine._browser_manager = self._browser_manager
            self._cognitive_orchestrator.attach_browser_manager(self._browser_manager)
            page = self._browser_manager.get_page()
            self._page_interactor = PageInteractor(page)
            self._execution_controller = ExecutionController(
                browser_manager=self._browser_manager,
                page_interactor=self._page_interactor,
                recovery_engine=self._recovery_engine,
                servicenow_config=self._settings.servicenow,
            )

            # If perception dependencies are available, set up PerceptionDecisionEngine
            if self._grounder and self._behavioral_verifier:
                self._perception_engine = PerceptionDecisionEngine(
                    browser=self._browser_manager,
                    interactor=self._page_interactor,
                    executor=self._execution_controller,
                    grounder=self._grounder,
                    verifier=self._behavioral_verifier,
                    learning_service=self._learning,
                    observer=self._observation_engine,
                )

            self._cognitive_orchestrator.attach_execution_controller(self._execution_controller)
            self._cognitive_orchestrator.attach_perception_engine(self._perception_engine)
            self._cognitive_orchestrator.attach_lock_manager(self._lock_manager)
            self._cognitive_orchestrator.session_id = self.session_id

            # Navigate to ServiceNow
            instance_url = self._settings.servicenow.instance_url
            self._memory.add_timeline_entry(action="Navigate to ServiceNow", result="started")
            await self._browser_manager.navigate(instance_url)
            await self._ensure_authenticated()

            # 3. PLANNING
            self._transition(AgentState.PLANNING, "Creating execution plan")
            story_id = self._memory.test_case_data.get('story_id') if self._memory.test_case_data else None

            # Story-scoped knowledge grounding (P0.8): load the imported
            # story's business rules, dependencies, preconditions, acceptance
            # criteria, and test data into the knowledge store BEFORE planning.
            # Scoped under story_id so one story can never bleed into another.
            if story_id and self._memory.test_case_data:
                story_ctx = self._memory.test_case_data.get("story_context") or {}
                if isinstance(story_ctx, dict) and story_ctx:
                    try:
                        await self._knowledge_store.index_story_context(story_id, story_ctx)
                        logger.info("story_context_grounded", story_id=story_id)
                    except Exception as ctx_err:
                        logger.warning("story_context_grounding_failed", error=str(ctx_err))

            knowledge = await self._knowledge_store.retrieve(goal, story_id=story_id)
            long_term_context = self._knowledge_memory.get_prompt_summary(goal)
            combined_context = f"{knowledge}\n{long_term_context}".strip()

            if skill and not self._memory.plan:
                plan = await skill.plan(structured_intent)
                self._memory.plan = plan
            elif not self._memory.plan:
                plan = await self._planner.create_plan(goal, combined_context)
                self._memory.plan = plan
            
            plan = self._memory.plan
            if plan:
                self._memory.add_timeline_entry(
                    action=f"Plan exists with {len(plan.steps)} steps",
                    result="success",
                )

            if self._memory.plan:
                # 4. EXECUTE COGNITIVE LOOP (Dynamic Phase 7 Orchestrator)
                await self._cognitive_orchestrator.run_cognitive_loop(self._memory, goal)

            # If we reach here without exceptions and we aren't failed, verify execution outcome
            if self._stop_requested:
                self._transition_safe(AgentState.COMPLETED, "Stop requested")
            elif self._memory.state not in (
                AgentState.FAILED,
                AgentState.CLEANUP_FAILED,
                AgentState.COMPLETED,
                AgentState.PRECONDITION_FAILED,
                AgentState.BLOCKED,
                AgentState.CANCELLED,
            ):
                if self._memory.total_actions_executed > 0 or len(self._memory.completed_steps) > 0:
                    self._transition_safe(AgentState.COMPLETED, "Agent execution finished")
                elif len(self._memory.failures) > 0:
                    self._transition_safe(AgentState.FAILED, "Agent execution had unresolved failures")
                else:
                    self._transition_safe(AgentState.FAILED, "No actions were executed for requested goal")

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
            # P0 Cleanup execution + independent restoration verification (QA-012)
            try:
                if self._memory.plan and getattr(self._memory.plan, "cleanup_steps", []):
                    logger.info("executing_cleanup_steps", step_count=len(self._memory.plan.cleanup_steps))
                    from agent.domain.plan import ExecutionPlan
                    cleanup_plan = ExecutionPlan(
                        goal="Cleanup",
                        steps=self._memory.plan.cleanup_steps
                    )

                    # Temporarily clear failures to allow cleanup to run
                    orig_precondition_failed = self._memory.precondition_failed
                    self._memory.precondition_failed = False

                    # Also temporarily clear stop_requested if we want cleanup to happen anyway,
                    # but usually stop means hard stop. Let's keep stop_requested as is.

                    # QA-012: snapshot the ORIGINAL record values from the first
                    # pre-action observation so restoration can be verified.
                    baseline_obs = None
                    if self._memory.completed_steps:
                        baseline_obs = self._memory.completed_steps[0].observation_before

                    await self._cognitive_orchestrator.execute_canonical_plan(self._memory, cleanup_plan, "Cleanup")

                    # Restore failures
                    self._memory.precondition_failed = orig_precondition_failed

                    self._memory.cleanup_status = "executed"

                    # QA-012: independently verify restoration by re-observing
                    # the record and comparing against the original snapshot.
                    try:
                        if baseline_obs is None:
                            self._memory.cleanup_status = "unverified"
                            self._memory.cleanup_details = (
                                "No baseline record snapshot available for restoration comparison."
                            )
                        else:
                            restored_mismatches: list[str] | None = None
                            if self._browser_manager:
                                page = self._browser_manager.get_page()
                                final_obs = await self._cognitive_orchestrator.get_observation_engine().observe(page)  # type: ignore[union-attr]
                                restored_mismatches = self._compare_restoration(baseline_obs, final_obs)
                            if restored_mismatches is None:
                                self._memory.cleanup_status = "unverified"
                                self._memory.cleanup_details = (
                                    "No original record values captured; restoration not verifiable."
                                )
                            elif restored_mismatches:
                                self._memory.cleanup_status = "cleanup_failed"
                                self._memory.cleanup_details = "; ".join(restored_mismatches)
                                self._memory.add_failure(
                                    error_type="CleanupVerificationFailed",
                                    error_message=(
                                        "Cleanup did not restore the original record state: "
                                        + "; ".join(restored_mismatches)
                                    ),
                                )
                                logger.error(
                                    "cleanup_restoration_failed",
                                    details=self._memory.cleanup_details,
                                )
                            else:
                                self._memory.cleanup_status = "verified"
                                self._memory.cleanup_details = "Original record state restored."
                    except Exception as cv_err:
                        self._memory.cleanup_status = "unverified"
                        self._memory.cleanup_details = f"Cleanup verification error: {cv_err}"
                        logger.warning("cleanup_verification_error", error=str(cv_err))

                # P1.7 Authoritative Mutation Journal cleanup (runs even if step 0 failed)
                if hasattr(self, "_journal") and self._journal and self._journal.entries:
                    try:
                        from agent.skills.incident.api_oracle import IncidentApiOracle
                        sn_cfg = getattr(self._settings, "servicenow", None) if self._settings else None
                        if sn_cfg and getattr(sn_cfg, "instance_url", None) and getattr(sn_cfg, "username", None):
                            oracle = IncidentApiOracle(sn_cfg)
                            j_success, j_errors, j_orphaned = await self._journal.execute_cleanup(
                                client=oracle.get_client(),
                                base_url=str(sn_cfg.instance_url),
                            )
                            await oracle.aclose()
                            if not j_success:
                                self._memory.cleanup_status = "cleanup_failed"
                                self._memory.cleanup_details = "; ".join(j_errors)
                                self._memory.add_failure(
                                    error_type="MutationJournalCleanupFailed",
                                    error_message=f"Journal cleanup failed for {len(j_orphaned)} records: " + "; ".join(j_errors),
                                )
                                self._transition_safe(AgentState.CLEANUP_FAILED, "Mutation journal cleanup failed")
                            elif self._memory.cleanup_status != "cleanup_failed":
                                self._memory.cleanup_status = "verified"
                    except Exception as j_err:
                        logger.error("journal_cleanup_exception", error=str(j_err))
                        self._memory.cleanup_status = "cleanup_failed"
                        self._memory.add_failure(
                            error_type="MutationJournalCleanupException",
                            error_message=f"Exception during journal cleanup: {j_err}",
                        )
                        self._transition_safe(AgentState.CLEANUP_FAILED, "Mutation journal cleanup exception")
            except Exception as e:
                logger.error("cleanup_execution_failed", error=str(e))
                self._memory.cleanup_status = "cleanup_failed"
                self._memory.cleanup_details = f"Cleanup execution failed: {e}"
                self._memory.add_failure(
                    error_type="CleanupExecutionFailed",
                    error_message=f"Cleanup execution failed: {e}",
                )

            # Generate report
            try:
                self._report = await self._generate_report()
                if self._report:
                    if self._report.status == "cleanup_failed":
                        self._transition_safe(AgentState.CLEANUP_FAILED, "Report status is cleanup_failed")
                    elif self._report.status == "precondition_failed":
                        self._transition_safe(AgentState.PRECONDITION_FAILED, "Report status is precondition_failed")
                    elif self._report.status == "blocked":
                        self._transition_safe(AgentState.BLOCKED, "Report status is blocked")
                    elif self._report.status == "failed":
                        self._transition_safe(AgentState.FAILED, "Report status is failed")
                    elif self._report.status == "passed" and len(self._memory.failures) == 0:
                        self._transition_safe(AgentState.COMPLETED, "Report status is passed")
            except Exception as e:
                logger.error("report_generation_failed", error=str(e))
                
            if hasattr(self, "_lock_manager") and hasattr(self._cognitive_orchestrator, "_locked_records"):
                for rec in self._cognitive_orchestrator.get_locked_records():
                    try:
                        await self._lock_manager.release_lease(rec, self.session_id)
                    except Exception as le:
                        logger.warning("failed_to_release_lease", record=rec, error=str(le))

            await self._save_session()
            if self._browser_manager:
                if (
                    self._settings.browser.keep_browser_open
                    and not self._settings.browser.headless
                ):
                    logger.info(
                        "keeping_browser_open_after_run",
                        session_id=self.session_id,
                        reason="BROWSER_KEEP_BROWSER_OPEN is true and running in headed mode",
                    )
                else:
                    logger.info(
                        "closing_browser_after_run",
                        session_id=self.session_id,
                        headless=self._settings.browser.headless,
                        keep_browser_open=self._settings.browser.keep_browser_open,
                    )
                    await self._browser_manager.close()

        logger.info(
            "agent_run_completed",
            session_id=self.session_id,
            state=self._memory.state.value,
            actions=self._memory.total_actions_executed,
        )

        return self._report  # type: ignore[return-value]

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
        if self._browser_manager:
            try:
                raw_logs = self._browser_manager.get_console_logs()
                if inspect.isawaitable(raw_logs):
                    raw_logs = await raw_logs
                self._memory.browser_logs = raw_logs if isinstance(raw_logs, list) else []

                raw_errors = self._browser_manager.get_new_console_errors()
                if inspect.isawaitable(raw_errors):
                    raw_errors = await raw_errors
                self._memory.console_errors = raw_errors if isinstance(raw_errors, list) else []

                get_net = getattr(self._browser_manager, "get_network_errors", None)
                if callable(get_net):
                    raw_net = get_net()
                    if inspect.isawaitable(raw_net):
                        raw_net = await raw_net
                    self._memory.network_errors = raw_net if isinstance(raw_net, list) else []
            except Exception as e:
                logger.warning("collect_browser_telemetry_failed", error=str(e))

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
            await self._reporting_engine.save_report(report, format='json')
            if hasattr(self._reporting_engine, 'save_xlsx_report'):
                await self._reporting_engine.save_xlsx_report(report, self._memory)
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
        session_store=get_session_store(s),
        intent_manager=get_intent_manager(s),
        world_model=get_world_model(),
        skill_registry=get_skill_registry(s),
        tool_registry=get_tool_registry(),
        reflection_engine=get_reflection_engine(s),
        confidence_engine=get_confidence_engine(),
        knowledge_memory=get_knowledge_memory(),
        decision_engine=get_decision_engine(s),
        learning_service=get_learning_service(),
        grounder=get_grounder_backend(s),
        behavioral_verifier=get_behavioral_verifier(s),
        scenario_generator=get_scenario_generator(),
        test_store=get_test_intelligence_store(s),
        customer_knowledge_model=get_customer_knowledge_model(),
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

    # Startup health probe for embedding client (bounded timeout, non-blocking)
    try:
        from agent.api.v1.dependencies import get_embedding_client

        embedding_client = get_embedding_client(settings)
        if hasattr(embedding_client, "startup_health_check"):
            probe_ok = await asyncio.wait_for(embedding_client.startup_health_check(), timeout=5.0)
            logger.info(
                "embedding_startup_probe_result",
                healthy=probe_ok,
                model=settings.llm.embedding_model,
            )
    except Exception as e:
        logger.warning("embedding_startup_probe_failed", error=str(e))

    yield
    logger.info("application_stopped")


app = FastAPI(
    title="ServiceNow QA Agent",
    description="Autonomous AI-powered QA Agent for ServiceNow Incident Management",
    version=__version__,
    lifespan=lifespan,
)

cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8005",
    "http://127.0.0.1:8005",
]
custom_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
if custom_origins:
    cors_origins.extend([o.strip() for o in custom_origins.split(",") if o.strip()])

from agent.api.v1.router import router, TicketRedactionMiddleware

app.add_middleware(TicketRedactionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_router)


@app.get("/", tags=["Info"])
async def root_index() -> dict[str, Any]:
    """Root endpoint providing service metadata and navigation links."""
    return {
        "name": "ServiceNow UAT Agent API",
        "version": __version__,
        "docs_url": "/docs",
        "frontend_url": "http://127.0.0.1:5173",
        "health_url": "/api/v1/health",
        "ready_url": "/api/v1/ready",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def root_health_check() -> HealthResponse:
    """Root health check alias for /api/v1/health."""
    return await health_check()


@app.get("/ready", tags=["Health"])
async def root_readiness_check() -> Any:
    """Root readiness check alias for /api/v1/ready."""
    return await readiness_check()


# Export AgentRunner alias for evaluation and benchmark suites
AgentRunner = AgentOrchestrator







