"""Cognitive Orchestrator.

Manages the dynamic multi-skill reasoning loop.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.capabilities.registry import CapabilityRegistry
from agent.cognition.investigation import InvestigationEngine
from agent.cognition.models import TestHypothesis
from agent.core.logging import get_logger
from agent.core.types import ActionType, AgentState, RunEventType, StepStatus
from agent.domain.plan import ExecutionPlan
from agent.domain.actions import AgentAction
from agent.domain.validation import ValidationResult
from agent.domain.knowledge_model import CustomerKnowledgeModel
from agent.memory.session import SessionMemory
from agent.world.model import WorldModel

logger = get_logger(__name__)


class CognitiveOrchestrator:
    """Orchestrates test hypotheses across multiple capabilities dynamically."""

    def __init__(
        self,
        skill_registry: CapabilityRegistry,
        knowledge_model: CustomerKnowledgeModel | None = None,
        learning_service: Any | None = None,
        scenario_generator: Any | None = None,
        decision_engine: Any | None = None,
        validation_engine: Any | None = None,
        perception_engine: Any | None = None,
        execution_controller: Any | None = None,
        observation_engine: Any | None = None,
        browser_manager: Any | None = None,
        state_machine: Any | None = None,
        settings: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._knowledge_model = knowledge_model
        self._learning_service = learning_service
        self._scenario_generator = scenario_generator
        self._decision_engine = decision_engine
        self._validation_engine = validation_engine
        self._perception_engine = perception_engine
        self._execution_controller = execution_controller
        self._observation_engine = observation_engine
        self._browser_manager = browser_manager
        self._state_machine = state_machine
        self._settings = settings
        self._llm = llm_client

        self._investigation_engine = InvestigationEngine(
            knowledge_model=knowledge_model, learning_service=learning_service
        )
        self._world_model = WorldModel()
        self._stop_requested = False
        self._event_publisher: Any | None = None
        self._control_receiver: Any | None = None

    def set_event_publisher(self, publisher: Any) -> None:
        """Set the live run event publisher."""
        self._event_publisher = publisher

    def set_control_receiver(self, receiver: Any) -> None:
        """Set the interactive control receiver."""
        self._control_receiver = receiver

    async def _publish_event(
        self, event_type: RunEventType | str, payload: dict[str, Any] | None = None
    ) -> None:
        """Publish a live event if publisher is attached."""
        if self._event_publisher:
            try:
                await self._event_publisher.publish(event_type, payload)
            except Exception as e:
                logger.debug("publish_event_failed", error=str(e))

    async def _check_controls(self) -> str:
        """Check interactive controls (pause/resume/cancel)."""
        if not self._control_receiver:
            return "running"
        try:
            status = await self._control_receiver.get_status()
            if status == "paused":
                logger.info("run_paused_by_user")
                await self._publish_event(RunEventType.RUN_PAUSED)
                self._transition(AgentState.PAUSED, "Execution paused by user")
                status = await self._control_receiver.await_resume_or_cancel()
                if status == "running":
                    logger.info("run_resumed_by_user")
                    await self._publish_event(RunEventType.RUN_RESUMED)
                    self._transition(AgentState.EXECUTING, "Execution resumed by user")
            return str(status)
        except Exception as e:
            logger.debug("check_controls_failed", error=str(e))
            return "running"

    def request_stop(self) -> None:
        self._stop_requested = True

    def _transition(self, state: AgentState, reason: str) -> None:
        if self._state_machine:
            try:
                self._state_machine.transition_to(state, reason=reason)
            except Exception as e:
                logger.warning("state_transition_failed", error=str(e))

    def _annotate_initial_precondition(
        self, action: Any, objective: str, memory: SessionMemory
    ) -> None:
        """Attach an authoritative initial-state contract to the first validation.

        The previous loop asked the LLM to infer this contract repeatedly.  A
        lifecycle goal already contains the expected starting state, so parse
        it once and carry it as structured metadata.  This prevents numeric
        ServiceNow values from being hallucinated in the reasoning text.
        """
        try:
            action_type = ActionType(action.action_type)
        except (TypeError, ValueError):
            return
        if action_type not in (
            ActionType.VALIDATE,
            ActionType.VALIDATE_STATE,
            ActionType.VALIDATE_FIELD,
        ):
            return
        if any(
            bool(getattr(step.action, "metadata", {}).get("is_precondition_check"))
            for step in memory.completed_steps
        ):
            return

        text = f"{objective} {action.reasoning}".lower()
        if "persisted" in text or "after update" in text or "final state" in text:
            return

        state_match = re.search(
            r"(?:initial|current)\s+state\s*(?:is|=|to|as|:)\s*"
            r"(new|in\s+progress|on\s+hold|resolved|closed|canceled)\b",
            text,
            re.IGNORECASE,
        )
        if not state_match:
            return

        state = " ".join(state_match.group(1).split()).title()
        state_values = {
            "New": "1",
            "In Progress": "2",
            "On Hold": "3",
            "Resolved": "6",
            "Closed": "7",
            "Canceled": "8",
        }
        record_match = re.search(r"\b(INC\d{5,10})\b", objective, re.IGNORECASE)
        record = record_match.group(1).upper() if record_match else None

        action.metadata.update(
            {
                "is_precondition_check": True,
                "expected_record": record,
                "expected_state": state,
            }
        )
        action.reasoning = (
            f"Precondition check: verify {record or 'the incident'} is in "
            f"initial state {state} (ServiceNow value {state_values[state]}) "
            "before any record mutation. Stop if it does not match."
        )

    @staticmethod
    def _merge_domain_validation(
        validation: ValidationResult, domain_validation: ValidationResult
    ) -> ValidationResult:
        """Merge skill/business validation into the authoritative result."""
        for check in domain_validation.checks:
            validation.add_check(check)
        if domain_validation.is_precondition_check:
            validation.is_precondition_check = True
            validation.precondition_failed = domain_validation.precondition_failed
            validation.precondition_details = dict(
                domain_validation.precondition_details or {}
            )
        validation.overall_passed = (
            validation.overall_passed and domain_validation.overall_passed
        )
        return validation

    def _parse_hypotheses_from_response(
        self, response: Any, objective: str
    ) -> list[TestHypothesis]:
        """Extract and validate TestHypothesis instances from any LLM response structure."""
        raw_items: list[dict[str, Any]] = []
        if isinstance(response, list):
            raw_items = [item for item in response if isinstance(item, dict)]
        elif isinstance(response, dict):
            for key in (
                "hypotheses",
                "test_hypotheses",
                "hypotheses_list",
                "scenarios",
                "items",
                "plan",
            ):
                if key in response and isinstance(response[key], list):
                    raw_items = [item for item in response[key] if isinstance(item, dict)]
                    break
            if not raw_items and "statement" in response:
                raw_items = [response]

        hypotheses: list[TestHypothesis] = []
        for idx, item in enumerate(raw_items, 1):
            try:
                h_id = str(item.get("id") or f"hyp-{idx}")
                cap = str(item.get("capability") or item.get("module") or "general")
                stmt = str(
                    item.get("statement")
                    or item.get("description")
                    or item.get("goal")
                    or objective
                )
                rationale = str(
                    item.get("rationale") or item.get("reasoning") or f"Testing: {stmt}"
                )
                strategy = str(item.get("strategy") or "Positive Testing")
                expected = str(
                    item.get("expected_outcome")
                    or item.get("expected")
                    or "Action completes successfully"
                )
                falsification = str(
                    item.get("falsification_condition")
                    or item.get("falsification")
                    or "Error occurs or element not found"
                )

                raw_risk = item.get("risk", 5)
                try:
                    risk = int(raw_risk)
                except (ValueError, TypeError):
                    risk = 5

                facts = item.get("supporting_facts", [])
                if isinstance(facts, str):
                    facts = [facts]
                elif not isinstance(facts, list):
                    facts = []

                prov = item.get("provenance", {})
                if not isinstance(prov, dict):
                    prov = {}

                hypotheses.append(
                    TestHypothesis(
                        id=h_id,
                        capability=cap,
                        statement=stmt,
                        rationale=rationale,
                        supporting_facts=facts,
                        strategy=strategy,
                        expected_outcome=expected,
                        falsification_condition=falsification,
                        risk=risk,
                        provenance=prov,
                    )
                )
            except Exception as e:
                logger.warning("failed_parsing_hypothesis_item", item=item, error=str(e))

        return hypotheses

    async def _formulate_hypotheses(self, objective: str) -> list[TestHypothesis]:
        """Use the LLM to formulate test hypotheses based on the user's objective.

        It determines which capabilities are relevant based on the objective.
        """
        if not self._llm:
            return [
                TestHypothesis(
                    id="hyp-fallback-1",
                    capability="general",
                    statement=f"Verify objective: {objective}",
                    rationale="Fallback hypothesis.",
                    strategy="Positive Testing",
                    expected_outcome="Success",
                    falsification_condition="Error occurs",
                )
            ]

        # Provide the list of available capabilities, always including general UI interactions
        capabilities_list = [
            {
                "name": "GeneralUI",
                "module_name": "general",
                "description": "General UI interactions (clicking buttons, toggling controls, filling inputs, login verification)",
            }
        ]
        for _name, skill_tuple in self._skill_registry._skills.items():
            _skill, definition = skill_tuple
            capabilities_list.append(
                {
                    "name": definition.name,
                    "module_name": definition.module_name,
                    "description": definition.description,
                }
            )

        prompt = f"""
        You are the Multi-Skill Cognitive Orchestrator for a ServiceNow QA Agent.
        The user's objective is: '{objective}'

        Available Capabilities:
        {json.dumps(capabilities_list, indent=2)}

        CRITICAL SCOPING RULES:
        1. Focus STRICTLY and ONLY on fulfilling the exact user objective: '{objective}'.
        2. Do NOT generate unnecessary setup steps (such as filling username or password) unless the user's objective explicitly requests it.
        3. For an Incident Lifecycle state transition test (e.g. transitioning from On Hold to In Progress and saving):
           - Formulate sequential test hypotheses:
             a) Navigate to the target incident record and verify initial state.
             b) Change the State dropdown to the target state (e.g. 'In Progress' / value 2).
             c) Click Update (save) to persist the change.
             d) Re-open / verify the incident record confirms the persisted state and unchanged record number.
        4. Do NOT generate extraneous exploratory or reverse actions.

        Formulate a set of TestHypotheses to fulfill this objective.
        Return a JSON object with a 'hypotheses' array containing objects matching
        the TestHypothesis schema. Each object MUST have exactly these fields:
        - "id": string (unique identifier, e.g. "hyp-1")
        - "capability": string (e.g. "general" or the specific capability module)
        - "statement": string (what we believe may happen)
        - "rationale": string (why we believe it)
        - "supporting_facts": array of strings (authoritative facts)
        - "strategy": string (which strategy will test it)
        - "expected_outcome": string (what evidence would confirm it)
        - "falsification_condition": string (what evidence would reject it)
        - "risk": integer (deterministic risk score 1-10)
        - "provenance": empty object
        """

        try:
            response = await self._llm.complete_json(
                messages=[
                    {"role": "system", "content": "You are a senior QA Architect. Focus strictly on the exact user objective without adding unrelated actions. Respond ONLY with valid JSON."},
                    {"role": "user", "content": prompt},
                ]
            )
            return self._parse_hypotheses_from_response(response, objective)
        except Exception as e:
            logger.warning("primary_hypothesis_formulation_failed", error=str(e))
            if "inc" in objective.lower() or "incident" in objective.lower():
                logger.info("using_structured_domain_hypotheses_fallback", objective=objective)
                return [
                    TestHypothesis(
                        id="hyp-1",
                        capability="incident",
                        statement="Navigate to target incident record and verify initial state",
                        rationale="Open target incident record for state inspection",
                        strategy="Positive Testing",
                        expected_outcome="Incident record is loaded and visible",
                        falsification_condition="Page fails to load or record mismatch",
                        risk=3,
                    ),
                    TestHypothesis(
                        id="hyp-2",
                        capability="incident",
                        statement="Transition State dropdown to In Progress (value 2)",
                        rationale="Change incident lifecycle state from On Hold to In Progress",
                        strategy="State Transition Testing",
                        expected_outcome="State dropdown updates to In Progress",
                        falsification_condition="State dropdown rejects selection",
                        risk=5,
                    ),
                    TestHypothesis(
                        id="hyp-3",
                        capability="incident",
                        statement="Click Update to persist incident changes",
                        rationale="Save the updated incident state to the database",
                        strategy="Data Persistence Testing",
                        expected_outcome="Form submits successfully and record is saved",
                        falsification_condition="Form submission fails or validation error banner appears",
                        risk=6,
                    ),
                    TestHypothesis(
                        id="hyp-4",
                        capability="incident",
                        statement="Re-navigate and verify incident record persisted in In Progress state",
                        rationale="Confirm persisted state and record number integrity",
                        strategy="Audit Verification Testing",
                        expected_outcome="Incident is confirmed in In Progress state with unchanged number",
                        falsification_condition="Incident state is not In Progress or record number changed",
                        risk=4,
                    ),
                ]
            return []



    async def run_cognitive_loop(self, memory: SessionMemory, objective: str) -> None:
        """The dynamic reasoning loop replacing the fixed single-skill loop."""
        max_steps = self._settings.agent.max_steps if self._settings else 20

        # Canonical ExecutionPlan execution path
        from agent.domain.plan import ExecutionPlan

        canonical_plan = getattr(memory, "plan", None)
        if isinstance(canonical_plan, ExecutionPlan) and canonical_plan.steps:
            logger.info(
                "executing_canonical_plan",
                step_count=len(canonical_plan.steps),
                goal=canonical_plan.goal,
            )
            await self._execute_canonical_plan(memory, canonical_plan, objective)
            return

        self._transition(AgentState.PLANNING, "Formulating multi-skill hypotheses")
        hypotheses = await self._formulate_hypotheses(objective)

        if not hypotheses:
            logger.error("no_hypotheses_generated", objective=objective)
            self._transition(
                AgentState.FAILED,
                f"PlanningFailure: No executable hypothesis generated for objective '{objective}'",
            )
            memory.add_failure(
                error_type="PlanningFailure",
                error_message=f"No executable hypothesis generated for objective: '{objective}'",
            )
            memory.add_timeline_entry(
                action=f"Planning for objective: '{objective}'",
                result="failed: No executable hypothesis generated",
            )
            raise RuntimeError(
                f"PlanningFailure: No executable hypothesis generated for objective: '{objective}'"
            )

        logger.info("hypotheses_formulated", count=len(hypotheses))

        # Loop through hypotheses
        for hypothesis in hypotheses:
            if (
                self._stop_requested
                or memory.precondition_failed
                or memory.total_actions_executed >= max_steps
            ):
                break

            logger.info(
                "executing_hypothesis", hyp_id=hypothesis.id, capability=hypothesis.capability
            )

            # Capability Selection (Dynamic)
            try:
                skill = self._skill_registry.get_skill_for_module(hypothesis.capability)
            except Exception as e:
                logger.error("error_resolving_skill", error=str(e))
                skill = None

            if skill:
                logger.info("using_domain_skill", capability=hypothesis.capability, skill=skill.manifest.name)
            else:
                logger.info("using_generic_cognitive_engine", capability=hypothesis.capability)

            # A. OBSERVATION
            self._transition(AgentState.OBSERVING, "Observing browser state")
            page = self._browser_manager.get_page()  # type: ignore[union-attr]
            raw_obs = await self._observation_engine.observe(page)  # type: ignore[union-attr]
            memory.add_observation(raw_obs)

            world_state = self._world_model.build_semantic_state(raw_obs)

            # Since we don't have a rigid sequence here, we rely on the decision engine
            # to fulfill the hypothesis using the selected capability.
            # We mock a few cognitive steps for the loop demonstration.

            # Execute scenario via decision engine
            self._transition(AgentState.DECISION, f"Evaluating hypothesis: {hypothesis.id}")
            decision = await self._decision_engine.decide_next_action(  # type: ignore[union-attr]
                intent=memory.structured_intent,
                world_state=world_state,
                memory=memory,
                latest_reflection=None,
            )

            action = decision.action
            self._annotate_initial_precondition(action, objective, memory)

            self._transition(AgentState.EXECUTING, "Executing action for hypothesis")
            if self._perception_engine:
                result = await self._perception_engine.execute_with_perception(action)
            else:
                result = await self._execution_controller.execute(action)  # type: ignore[union-attr]

            # B. OBSERVATION AFTER EXECUTION
            self._transition(AgentState.OBSERVING, "Post-action observation")
            raw_obs_after = await self._observation_engine.observe(page)  # type: ignore[union-attr]
            world_state_after = self._world_model.build_semantic_state(raw_obs_after)

            # C. EXPECTED VS ACTUAL & INVESTIGATION
            self._transition(AgentState.VALIDATING, "Comparing expected vs actual")

            # Check expectation
            validation = await self._validation_engine.validate_action(  # type: ignore[union-attr]
                action=action,
                result=result,
                before=raw_obs,
                after=raw_obs_after,
            )

            if skill and hasattr(skill, "validate"):
                try:
                    domain_validation = await skill.validate(
                        action, world_state, world_state_after
                    )
                    if isinstance(domain_validation, ValidationResult):
                        validation = self._merge_domain_validation(
                            validation, domain_validation
                        )
                except Exception as e:
                    logger.warning("skill_validation_failed", error=str(e))

            # Record completed step in memory for metrics, reports, and action counter
            memory.add_completed_step(
                action=action,
                result=result,
                observation_before=raw_obs,
                observation_after=raw_obs_after,
                validation=validation,
            )
            memory.add_timeline_entry(
                action=f"{action.action_type}: {action.target}",
                result="success" if result.success else "failed",
                duration_ms=result.duration_ms,
                screenshot_path=result.screenshot_path,
            )

            if getattr(validation, "precondition_failed", False) is True:
                memory.precondition_failed = True
                failed = getattr(validation, "failed_checks", []) or []
                if isinstance(failed, (list, tuple)):
                    memory.precondition_failure_reason = "; ".join(
                        check.error_message or check.actual
                        for check in failed
                        if hasattr(check, "error_message") or hasattr(check, "actual")
                    ) or "Initial test precondition was not satisfied"
                else:
                    memory.precondition_failure_reason = str(failed) or "Initial test precondition was not satisfied"
                memory.add_timeline_entry(
                    action="Precondition failed; stopping before mutation",
                    result=memory.precondition_failure_reason,
                )
                self._transition(
                    AgentState.PRECONDITION_FAILED,
                    memory.precondition_failure_reason,
                )
                return

            if not validation.overall_passed:
                # Mismatch detected -> Trigger Investigation Loop
                logger.info("expectation_mismatch_detected", expected=hypothesis.expected_outcome)

                # Defect-scope gate: if the agent itself failed to perform,
                # observe, or verify (agent-scope failure), no conclusion about
                # the application can be drawn — record it as an agent issue
                # and never let it become an application defect.
                from agent.domain.defect_scope import classify_step_failure

                mismatch_scope = classify_step_failure(result, validation)

                if mismatch_scope == "precondition":
                    memory.precondition_failed = True
                    memory.precondition_failure_reason = (
                        validation.precondition_details.get("reason")
                        or "Initial test precondition was not satisfied"
                    )
                    self._transition(
                        AgentState.PRECONDITION_FAILED,
                        memory.precondition_failure_reason,
                    )
                    return

                if mismatch_scope == "agent":
                    logger.warning(
                        "mismatch_agent_scope_skipping_investigation",
                        hyp_id=hypothesis.id,
                        scope=mismatch_scope,
                        action_error=result.error,
                    )
                    memory.add_timeline_entry(
                        action=f"Agent issue (not an application defect): {hypothesis.id}",
                        result="agent-side failure",
                    )
                    # Agent-side diagnostic is already captured in the failed
                    # step/validation — no defect verdict is recorded.

                else:
                    investigation = await self._investigation_engine.investigate_mismatch(
                        action=action,
                        expected=hypothesis.expected_outcome,
                        actual=validation.to_summary(),
                        table_name=hypothesis.capability,
                        result=result,
                        validation=validation,
                    )

                    # Record the authoritative verdict for the reporting engine
                    kr = getattr(investigation, "knowledge_reference", None)
                    memory.add_defect_verdict(
                        step_index=memory.current_step_index - 1,
                        hypothesis_id=hypothesis.id,
                        is_defect=investigation.is_defect,
                        classification=investigation.classification,
                        reasoning=investigation.reasoning,
                        # Coerce non-string values (e.g. Mocks in tests) to None
                        knowledge_reference=kr if isinstance(kr, str) else None,
                    )



                    if investigation.is_defect:
                        memory.add_failure(
                            error_type="InvestigationVerifiedDefect",
                            error_message=f"Hypothesis {hypothesis.id}: {investigation.reasoning}",
                        )
                    else:
                        logger.info(
                            "false_positive_prevented", classification=investigation.classification
                        )
                        # Not a defect, learning or knowledge model explained it
                        memory.add_timeline_entry(
                            action=f"Investigated Mismatch: {hypothesis.id}",
                            result=investigation.classification,
                        )

            # D. RECORD EXPERIENCE
            if self._learning_service:
                try:
                    await self._learning_service.record_strategy_execution(
                        module=hypothesis.capability,
                        strategy=hypothesis.strategy,
                        is_finding=not validation.overall_passed,
                    )
                except Exception as e:
                    logger.warning("learning_service_record_failed", error=str(e), exc_info=True)

    async def _execute_canonical_plan(
        self, memory: SessionMemory, plan: ExecutionPlan, objective: str
    ) -> None:
        """Execute the single canonical ExecutionPlan sequentially."""
        max_steps = self._settings.agent.max_steps if self._settings else 20

        # Emit plan created event
        await self._publish_event(
            RunEventType.PLAN_CREATED,
            {
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "steps": [
                    {
                        "step_index": s.step_index,
                        "description": s.description,
                        "expected_outcome": s.expected_outcome,
                        "risk_level": s.risk_level,
                    }
                    for s in plan.steps
                ],
            },
        )

        for step in plan.steps:
            if (
                self._stop_requested
                or memory.precondition_failed
                or memory.total_actions_executed >= max_steps
            ):
                break

            # 1. Interactive control check (Pause / Resume / Cancel) before action
            control_status = await self._check_controls()
            if control_status == "cancelled" or self._stop_requested:
                step.mark_skipped("Execution cancelled by user")
                plan.skip_remaining_steps(step.step_index + 1, "Execution cancelled by user")
                self._transition(AgentState.CANCELLED, "Run cancelled by user")
                await self._publish_event(RunEventType.RUN_CANCELLED)
                return

            step.mark_in_progress()
            logger.info("executing_plan_step", step_index=step.step_index, description=step.description)
            await self._publish_event(
                RunEventType.STEP_STARTED,
                {
                    "step_index": step.step_index,
                    "description": step.description,
                    "status": "in_progress",
                    "expected_outcome": step.expected_outcome,
                    "observed_values": step.observed_values or {},
                    "actual_result": None,
                    "screenshot": None,
                },
            )

            # Determine target capability/skill
            skill = None
            if memory.structured_intent:
                skill = self._skill_registry.resolve_skill(memory.structured_intent)
            if not skill:
                try:
                    skill = self._skill_registry.get_skill_for_module("incident")
                except Exception:
                    skill = None

            # 2. Observation Before
            self._transition(AgentState.OBSERVING, f"Observing before: {step.description}")
            page = self._browser_manager.get_page()  # type: ignore[union-attr]
            raw_obs = await self._observation_engine.observe(page)  # type: ignore[union-attr]
            memory.add_observation(raw_obs)
            world_state = self._world_model.build_semantic_state(raw_obs)

            # 3. Decision
            self._transition(AgentState.DECISION, f"Deciding action for: {step.description}")
            
            # P0.2 SCRIPTED TEST EXECUTION MODE bypass
            action = None
            if step.expected_values and "action_type" in step.expected_values:
                # Build AgentAction from the explicitly mapped step. An
                # unrecognized action_type string must degrade gracefully to
                # the decision engine rather than crashing the run with a
                # ValueError.
                raw_action_type = str(step.expected_values["action_type"]).lower().strip()
                try:
                    typed_action = ActionType(raw_action_type)
                except ValueError:
                    typed_action = None
                    logger.warning(
                        "scripted_step_unknown_action_type",
                        action_type=raw_action_type,
                        step=step.step_index,
                    )

                if typed_action is not None:
                    action = AgentAction(
                        action_type=typed_action,
                        target=step.expected_values.get("target", ""),
                        value=step.expected_values.get("value", ""),
                        reasoning=f"Explicitly scripted step: {step.description}",
                        metadata={"is_scripted": True}
                    )
                    logger.info("decision_engine_bypassed", reason="Scripted test execution mode active")

            if action is None:
                decision = await self._decision_engine.decide_next_action(  # type: ignore[union-attr]
                    intent=memory.structured_intent,
                    world_state=world_state,
                    memory=memory,
                    latest_reflection=None,
                )
                action = decision.action
            
            self._annotate_initial_precondition(action, objective, memory)

            # P0.4 Incident Lifecycle Gate
            # If this is a state-change action, validate against lifecycle rules
            if skill and hasattr(skill, "_lifecycle_engine"):
                try:
                    action_type_str = str(action.action_type).lower()
                    target_str = str(action.target).lower()
                    value_str = str(action.value).lower() if action.value else ""
                    
                    is_state_change = (
                        action_type_str in ("select", "fill")
                        and ("state" in target_str or "incident_state" in target_str)
                        and value_str
                    )
                    
                    if is_state_change:
                        from agent.skills.incident.domain.models import IncidentState
                        
                        # Map common display values to IncidentState
                        state_map = {
                            "new": IncidentState.NEW,
                            "in progress": IncidentState.IN_PROGRESS,
                            "on hold": IncidentState.ON_HOLD,
                            "resolved": IncidentState.RESOLVED,
                            "closed": IncidentState.CLOSED,
                            "canceled": IncidentState.CANCELED,
                            "1": IncidentState.NEW,
                            "2": IncidentState.IN_PROGRESS,
                            "3": IncidentState.ON_HOLD,
                            "6": IncidentState.RESOLVED,
                            "7": IncidentState.CLOSED,
                            "8": IncidentState.CANCELED,
                        }
                        
                        target_state = state_map.get(value_str.strip())
                        if target_state:
                            # Get current state from world state
                            current_state_raw = world_state.get_field_value("state") or world_state.get_field_value("incident_state") or ""
                            current_state = state_map.get(current_state_raw.strip().lower())
                            
                            if current_state and current_state != target_state:
                                is_valid = True
                                if self._knowledge_memory and self._knowledge_memory.customer_model:
                                    is_valid = self._knowledge_memory.customer_model.is_valid_state_transition(
                                        "incident", 
                                        current_state.value if hasattr(current_state, "value") else str(current_state), 
                                        target_state.value if hasattr(target_state, "value") else str(target_state)
                                    )
                                else:
                                    # Fallback
                                    from agent.skills.incident.knowledge.rules import IncidentLifecycle
                                    is_valid = IncidentLifecycle.is_valid_transition(current_state, target_state)
                                
                                if not is_valid:
                                    logger.warning(
                                        "lifecycle_gate_blocked",
                                        from_state=current_state.name,
                                        to_state=target_state.name,
                                    )
                                    step.mark_failed(
                                        f"Lifecycle violation: {current_state.name} -> {target_state.name} is not a valid transition"
                                    )
                                    continue
                except Exception as lc_err:
                    logger.debug("lifecycle_gate_check_error", error=str(lc_err))

            # 4. Human Approval Gate for High Risk Actions
            threshold = (
                getattr(self._settings.agent, "require_approval_risk_threshold", 8)
                if self._settings
                else 8
            )
            step_risk = 8 if step.risk_level in ("High", "Critical") else 5
            if step_risk >= threshold and self._control_receiver:
                self._transition(
                    AgentState.AWAITING_USER_INPUT,
                    "Waiting for user approval on high-risk action",
                )
                approved = await self._control_receiver.request_approval(
                    step.description, step_risk, publisher=self._event_publisher
                )
                if not approved:
                    step.mark_blocked("Action rejected by user during human approval gate")
                    plan.skip_remaining_steps(
                        step.step_index + 1, "Blocked due to human approval rejection"
                    )
                    self._transition(AgentState.BLOCKED, "Approval rejected by user")
                    return
                self._transition(AgentState.EXECUTING, "Action approved by user")

            # Check control again immediately before action execution
            control_status = await self._check_controls()
            if control_status == "cancelled" or self._stop_requested:
                step.mark_skipped("Execution cancelled by user")
                plan.skip_remaining_steps(step.step_index + 1, "Execution cancelled by user")
                self._transition(AgentState.CANCELLED, "Run cancelled by user")
                await self._publish_event(RunEventType.RUN_CANCELLED)
                return

            # 5. Execution
            self._transition(
                AgentState.EXECUTING, f"Executing: {action.action_type} on {action.target}"
            )
            if self._perception_engine:
                result = await self._perception_engine.execute_with_perception(action)
            else:
                result = await self._execution_controller.execute(action)  # type: ignore[union-attr]

            # P0 QA-005 Fix: Reload page to verify mutations after save/update
            action_type_val = getattr(action.action_type, "value", action.action_type)
            if str(action_type_val) == "click" and action.target and ("sysverb_update" in str(action.target).lower() or "sysverb_insert" in str(action.target).lower()):
                try:
                    if self._browser_manager:
                        page = self._browser_manager.get_page()
                        await page.reload(wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.debug("failed_to_reload_after_update", error=str(e))

            # Capture screenshot if not already captured
            if not result.screenshot_path and self._browser_manager:
                try:
                    result.screenshot_path = await self._browser_manager.take_screenshot(
                        f"step_{step.step_index}_{action.action_type}"
                    )
                except Exception:
                    pass

            # Check control after action execution
            control_status = await self._check_controls()
            if control_status == "cancelled" or self._stop_requested:
                step.mark_skipped("Execution cancelled by user")
                plan.skip_remaining_steps(step.step_index + 1, "Execution cancelled by user")
                self._transition(AgentState.CANCELLED, "Run cancelled by user")
                await self._publish_event(RunEventType.RUN_CANCELLED)
                return

            # 6. Observation After
            self._transition(AgentState.OBSERVING, f"Observing after: {step.description}")
            raw_obs_after = await self._observation_engine.observe(page)  # type: ignore[union-attr]
            world_state_after = self._world_model.build_semantic_state(raw_obs_after)

            # 7. Validation
            self._transition(AgentState.VALIDATING, f"Validating: {step.description}")
            validation = await self._validation_engine.validate_action(  # type: ignore[union-attr]
                action=action,
                result=result,
                before=raw_obs,
                after=raw_obs_after,
            )

            if skill and hasattr(skill, "validate"):
                try:
                    domain_val = await skill.validate(action, world_state, world_state_after)
                    if isinstance(domain_val, ValidationResult):
                        validation = self._merge_domain_validation(validation, domain_val)
                except Exception as val_err:
                    logger.warning("skill_validation_failed", error=str(val_err))

            # Record step observed values
            step.observed_values = dict(validation.precondition_details or {})
            if hasattr(action, "metadata") and action.metadata:
                step.expected_values = dict(action.metadata)

            memory.add_completed_step(
                action=action,
                result=result,
                observation_before=raw_obs,
                observation_after=raw_obs_after,
                validation=validation,
            )
            memory.add_timeline_entry(
                action=f"{action.action_type}: {action.target}",
                result="success" if result.success else "failed",
                duration_ms=result.duration_ms,
                screenshot_path=result.screenshot_path,
            )

            # P0.3 Save successful action to StepCache
            if validation.overall_passed and not (hasattr(action, "metadata") and action.metadata and action.metadata.get("is_scripted")):
                if memory.plan and memory.plan.current_step and self._decision_engine and hasattr(self._decision_engine, "_step_cache"):
                    try:
                        intent_type_str = "unknown"
                        if memory.structured_intent:
                            intent_type_str = str(memory.structured_intent.intent_type.value) if hasattr(memory.structured_intent.intent_type, "value") else str(memory.structured_intent.intent_type)
                        self._decision_engine._step_cache.save_action(
                            goal=objective,
                            intent_type=intent_type_str,
                            step_desc=memory.plan.current_step.description,
                            expected=memory.plan.current_step.expected_outcome,
                            action=action
                        )
                    except Exception as cache_err:
                        logger.warning("cache_save_failed", error=str(cache_err))

            if hasattr(self, "_on_step_complete") and callable(self._on_step_complete):
                try:
                    self._on_step_complete(step, memory)
                except Exception as step_cb_err:
                    logger.debug("on_step_complete_callback_error", error=str(step_cb_err))

            # 8. Precondition Check Failure Handling
            if getattr(validation, "precondition_failed", False) is True:
                memory.precondition_failed = True
                failed = getattr(validation, "failed_checks", []) or []
                if isinstance(failed, (list, tuple)):
                    reason = "; ".join(
                        check.error_message or check.actual
                        for check in failed
                        if hasattr(check, "error_message") or hasattr(check, "actual")
                    ) or "Initial test precondition was not satisfied"
                else:
                    reason = str(failed) or "Initial test precondition was not satisfied"
                memory.precondition_failure_reason = reason
                step.mark_failed(reason)
                # Mark ALL remaining plan steps as SKIPPED with the exact reason
                plan.skip_remaining_steps(
                    step.step_index + 1,
                    f"Skipped due to initial state precondition failure on step {step.step_index}: {reason}",
                )
                memory.add_timeline_entry(
                    action="Precondition failed; stopping before mutation",
                    result=reason,
                )
                self._transition(AgentState.PRECONDITION_FAILED, reason)
                await self._publish_event(
                    RunEventType.PRECONDITION_CHECK_FAILED,
                    {"reason": reason, "step_index": step.step_index},
                )
                await self._publish_event(
                    RunEventType.STEP_FINISHED,
                    {
                        "step_index": step.step_index,
                        "description": step.description,
                        "status": "failed",
                        "expected_outcome": step.expected_outcome,
                        "observed_values": step.observed_values,
                        "actual_result": reason,
                        "screenshot": result.screenshot_path,
                    },
                )
                return

            if validation.overall_passed:
                step.mark_success()
                await self._publish_event(
                    RunEventType.STEP_FINISHED,
                    {
                        "step_index": step.step_index,
                        "description": step.description,
                        "status": "passed",
                        "expected_outcome": step.expected_outcome,
                        "observed_values": step.observed_values,
                        "actual_result": "success",
                        "screenshot": result.screenshot_path,
                    },
                )
            else:
                from agent.domain.defect_scope import classify_step_failure

                mismatch_scope = classify_step_failure(result, validation)
                if mismatch_scope == "precondition":
                    memory.precondition_failed = True
                    reason = (
                        validation.precondition_details.get("reason")
                        or "Initial test precondition was not satisfied"
                    )
                    memory.precondition_failure_reason = reason
                    step.mark_failed(reason)
                    plan.skip_remaining_steps(
                        step.step_index + 1,
                        f"Skipped due to precondition failure on step {step.step_index}: {reason}",
                    )
                    self._transition(AgentState.PRECONDITION_FAILED, reason)
                    await self._publish_event(
                        RunEventType.PRECONDITION_CHECK_FAILED,
                        {"reason": reason, "step_index": step.step_index},
                    )
                    await self._publish_event(
                        RunEventType.STEP_FINISHED,
                        {
                            "step_index": step.step_index,
                            "description": step.description,
                            "status": "failed",
                            "expected_outcome": step.expected_outcome,
                            "observed_values": step.observed_values,
                            "actual_result": reason,
                            "screenshot": result.screenshot_path,
                        },
                    )
                    return

                if mismatch_scope == "agent":
                    step.mark_failed(f"Agent issue: {result.error or 'interaction failure'}")
                    memory.add_timeline_entry(
                        action=f"Agent issue (not an application defect): {step.description}",
                        result="agent-side failure",
                    )
                    await self._publish_event(
                        RunEventType.STEP_FINISHED,
                        {
                            "step_index": step.step_index,
                            "description": step.description,
                            "status": "failed",
                            "expected_outcome": step.expected_outcome,
                            "observed_values": step.observed_values,
                            "actual_result": f"Agent issue: {result.error}",
                            "screenshot": result.screenshot_path,
                        },
                    )
                else:
                    investigation = await self._investigation_engine.investigate_mismatch(
                        action=action,
                        expected=step.expected_outcome,
                        actual=validation.to_summary(),
                        table_name="incident",
                        result=result,
                        validation=validation,
                    )
                    kr = getattr(investigation, "knowledge_reference", None)
                    memory.add_defect_verdict(
                        step_index=memory.current_step_index - 1,
                        hypothesis_id=f"step-{step.step_index}",
                        is_defect=investigation.is_defect,
                        classification=investigation.classification,
                        reasoning=investigation.reasoning,
                        knowledge_reference=kr if isinstance(kr, str) else None,
                    )
                    if investigation.is_defect:
                        step.mark_failed(investigation.reasoning)
                        memory.add_failure(
                            error_type="InvestigationVerifiedDefect",
                            error_message=f"Step {step.step_index}: {investigation.reasoning}",
                        )
                    else:
                        step.mark_success()

                    await self._publish_event(
                        RunEventType.STEP_FINISHED,
                        {
                            "step_index": step.step_index,
                            "description": step.description,
                            "status": "failed" if investigation.is_defect else "passed",
                            "expected_outcome": step.expected_outcome,
                            "observed_values": step.observed_values,
                            "actual_result": investigation.reasoning,
                            "screenshot": result.screenshot_path,
                        },
                    )

        # P0.6 FINAL VERIFICATION — Independent assertion pass on fresh browser state
        final_assertions = getattr(memory, "final_assertions", None) or []
        final_verification_passed = True
        final_verification_ran = False
        
        if final_assertions and not memory.precondition_failed:
            logger.info("final_verification_start", assertion_count=len(final_assertions))
            self._transition(AgentState.VALIDATING, "Running final verification assertions")
            
            try:
                # Get fresh page observation — do NOT use cached state
                page = self._browser_manager.get_page()  # type: ignore[union-attr]
                fresh_obs = await self._observation_engine.observe(page)  # type: ignore[union-attr]
                fresh_world = self._world_model.build_semantic_state(fresh_obs)
                
                for assertion in final_assertions:
                    final_verification_ran = True
                    
                    # Handle both dict and ExpectedAssertion objects
                    if isinstance(assertion, dict):
                        field = assertion.get("field", "")
                        expected = assertion.get("expected_value", "")
                        operator = assertion.get("operator", "equals")
                        desc = assertion.get("description", f"Assert {field} {operator} {expected}")
                    elif isinstance(assertion, str):
                        # Plain string assertion — pass to LLM validation
                        field = ""
                        expected = assertion
                        operator = "contains"
                        desc = assertion
                    else:
                        field = getattr(assertion, "field", "")
                        expected = getattr(assertion, "expected_value", "")
                        operator = getattr(assertion, "operator", "equals")
                        desc = getattr(assertion, "description", f"Assert {field} {operator} {expected}")
                    
                    # Check assertion against fresh world state
                    actual_value = ""
                    if field:
                        actual_value = str(fresh_world.get_field_value(field) or "")
                    
                    assertion_passed = False
                    if operator == "equals":
                        assertion_passed = actual_value.strip().lower() == str(expected).strip().lower()
                    elif operator == "contains":
                        assertion_passed = str(expected).strip().lower() in actual_value.strip().lower()
                    elif operator == "not_empty":
                        assertion_passed = bool(actual_value.strip())
                    else:
                        # Default: case-insensitive equality
                        assertion_passed = actual_value.strip().lower() == str(expected).strip().lower()
                    
                    if not assertion_passed:
                        final_verification_passed = False
                        logger.warning(
                            "final_assertion_failed",
                            field=field,
                            expected=str(expected),
                            actual=actual_value,
                            operator=operator,
                        )
                        memory.add_failure(
                            error_type="FinalAssertionFailed",
                            error_message=f"{desc}: expected={expected}, actual={actual_value}",
                        )
                    else:
                        logger.info("final_assertion_passed", field=field, desc=desc)
                        
            except Exception as fv_err:
                logger.error("final_verification_error", error=str(fv_err))
                final_verification_passed = False
                memory.add_failure(
                    error_type="FinalVerificationError",
                    error_message=f"Final verification failed with error: {fv_err}",
                )

        # P0.7 FALSE-PASS PREVENTION
        # A run with zero validated assertions must not be marked PASSED
        steps_actually_validated = sum(
            1 for s in plan.steps if s.status == StepStatus.SUCCESS
        )

        # Mark complete if all executed without hard failure
        if all(
            s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)
            for s in plan.steps
        ):
            if final_verification_ran and not final_verification_passed:
                # Final assertions failed — do NOT mark as passed
                logger.warning("false_pass_prevented", reason="Final assertions failed")
                await self._publish_event(
                    RunEventType.RUN_FINISHED,
                    {"goal": plan.goal, "status": "failed", "reason": "Final verification assertions failed"},
                )
            elif steps_actually_validated == 0 and not plan.steps:
                # No steps executed at all — cannot be a pass
                logger.warning("false_pass_prevented", reason="Zero steps validated")
                await self._publish_event(
                    RunEventType.RUN_FINISHED,
                    {"goal": plan.goal, "status": "failed", "reason": "No steps were validated"},
                )
            else:
                plan.is_complete = True
                await self._publish_event(RunEventType.RUN_FINISHED, {"goal": plan.goal})
