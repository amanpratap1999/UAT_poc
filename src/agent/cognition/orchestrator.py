"""Cognitive Orchestrator.

Manages the dynamic multi-skill reasoning loop.
"""

from __future__ import annotations

import json
from typing import Any

from agent.capabilities.registry import CapabilityRegistry
from agent.cognition.investigation import InvestigationEngine
from agent.cognition.models import TestHypothesis
from agent.core.logging import get_logger
from agent.core.types import AgentState
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

    def request_stop(self) -> None:
        self._stop_requested = True

    def _transition(self, state: AgentState, reason: str) -> None:
        if self._state_machine:
            try:
                self._state_machine.transition_to(state, reason=reason)
            except Exception as e:
                logger.warning("state_transition_failed", error=str(e))

    async def _formulate_hypotheses(self, objective: str) -> list[TestHypothesis]:
        """Use the LLM to formulate test hypotheses based on the user's objective.

        It determines which capabilities are relevant based on the objective.
        """
        if not self._llm:
            # Fallback if no LLM
            return [
                TestHypothesis(
                    id="hyp-fallback-1",
                    capability="incident",
                    statement="Verify baseline incident flow.",
                    rationale="Fallback hypothesis.",
                    strategy="Positive Testing",
                    expected_outcome="Success",
                    falsification_condition="Error occurs",
                )
            ]

        # Provide the list of available capabilities
        capabilities_list = []
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

        Formulate a set of TestHypotheses to fulfill this objective.
        You may span multiple capabilities if the objective requires it
        (e.g., verifying a Change creates an Incident).

        Return a JSON object with a 'hypotheses' array containing objects matching
        the TestHypothesis schema. Each object MUST have exactly these fields:
        - "id": string (unique identifier)
        - "capability": string (the primary target capability name)
        - "statement": string (what we believe may happen)
        - "rationale": string (why we believe it)
        - "supporting_facts": array of strings (authoritative facts)
        - "strategy": string (which strategy will test it)
        - "expected_outcome": string (what evidence would confirm it)
        - "falsification_condition": string (what evidence would reject it)
        - "risk": integer (deterministic risk score)
        - "provenance": empty object
        """

        try:
            response = await self._llm.complete_json(
                messages=[
                    {"role": "system", "content": "You are a senior QA Architect."},
                    {"role": "user", "content": prompt},
                ]
            )

            if "hypotheses" in response:
                return [TestHypothesis(**h) for h in response["hypotheses"]]
            return []
        except Exception as e:
            logger.error("hypothesis_formulation_failed", error=str(e))
            return [
                TestHypothesis(
                    id="hyp-fallback-1",
                    capability="incident",
                    statement="Verify baseline incident flow.",
                    rationale="Fallback hypothesis.",
                    strategy="Positive Testing",
                    expected_outcome="Success",
                    falsification_condition="Error occurs",
                )
            ]

    async def run_cognitive_loop(self, memory: SessionMemory, objective: str) -> None:
        """The dynamic reasoning loop replacing the fixed single-skill loop."""
        max_steps = self._settings.agent.max_steps if self._settings else 20

        self._transition(AgentState.PLANNING, "Formulating multi-skill hypotheses")
        hypotheses = await self._formulate_hypotheses(objective)

        if not hypotheses:
            logger.error("no_hypotheses_generated")
            return

        logger.info("hypotheses_formulated", count=len(hypotheses))

        # Loop through hypotheses
        for hypothesis in hypotheses:
            if self._stop_requested or memory.total_actions_executed >= max_steps:
                break

            logger.info(
                "executing_hypothesis", hyp_id=hypothesis.id, capability=hypothesis.capability
            )

            # Capability Selection (Dynamic)
            try:
                skill = self._skill_registry.get_skill_for_module(hypothesis.capability)
                (self._skill_registry.get_definition(hypothesis.capability) if skill else None)
            except Exception as e:
                logger.error("error_resolving_skill", error=str(e))
                skill = None

            if not skill:
                logger.warning("capability_not_found", capability=hypothesis.capability)
                continue

            # Delegate to skill-specific planning / execution bounds if needed,
            # or dynamically form a plan for this hypothesis.

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
                    await skill.validate(action, world_state, world_state_after)
                except Exception as e:
                    logger.warning("skill_validation_failed", error=str(e))

            if not validation.overall_passed:
                # Mismatch detected -> Trigger Investigation Loop
                logger.info("expectation_mismatch_detected", expected=hypothesis.expected_outcome)

                investigation = await self._investigation_engine.investigate_mismatch(
                    action=action,
                    expected=hypothesis.expected_outcome,
                    actual=validation.to_summary(),
                    table_name=hypothesis.capability,
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
