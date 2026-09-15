"""Decision Engine for Deliverable 9.

Separates macro-planning (Planner) from immediate action selection.
Inputs:
- StructuredIntent
- SemanticWorldState
- SessionMemory
- ConfidenceAssessment
- ReflectionResult
- ToolRegistry

Output:
- AgentAction with target, reasoning, confidence, expected outcome
"""

from __future__ import annotations

from pydantic import BaseModel

from agent.confidence.engine import ConfidenceAssessment, ConfidenceEngine
from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import AgentAction
from agent.domain.intent import StructuredIntent
from agent.domain.reflection import ReflectionResult
from agent.domain.world import SemanticWorldState
from agent.memory.session import SessionMemory
from agent.planner.llm_client import BaseLLMClient
from agent.reflection.engine import ReflectionEngine
from agent.tools.registry import ToolRegistry

logger = get_logger(__name__)

DECISION_PROMPT = """You are the Decision Engine of an autonomous ServiceNow QA agent.
Select the single best immediate action to execute to advance the plan.

## Structured Intent
Goal: {goal}
Intent Type: {intent_type}

## Execution Plan
{plan_summary}

## World State
{world_state_summary}

## Session Context
{session_context}

## Available Tools
{tool_summary}

## Recent Reflection (if any)
{reflection_summary}

## Instructions
1. Review the Execution Plan, current page World State, and recent actions.
2. Select the NEXT logical step in the plan that has not yet been completed.
3. If on the Incident form and State was just changed to 'In Progress' (2), click 'Update' (button#sysverb_update) to save the record.
4. If the form was saved and redirected to home/list, navigate back to the incident record to re-observe and verify.
5. Do NOT toggle back to On Hold once In Progress has been chosen.

Respond with a JSON object:
{{
    "action_type": "click|fill|select|navigate|wait|key_press|scroll|validate|screenshot",
    "target": "target element or selector",
    "value": "value if applicable",
    "reasoning": "rationale for choosing this immediate action",
    "expected_outcome": "what we expect to happen",
    "confidence": 0.95
}}
"""


class CognitiveDecision(BaseModel):
    """Output of the DecisionEngine."""

    action: AgentAction
    reasoning: str
    expected_outcome: str
    confidence_assessment: ConfidenceAssessment


class DecisionEngine:
    """Selects immediate micro-actions based on current world state, confidence, and reflection."""

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        reflection_engine: ReflectionEngine | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._llm = llm_client
        self._confidence_engine = confidence_engine or ConfidenceEngine()
        self._reflection_engine = reflection_engine or ReflectionEngine(llm_client)
        self._tool_registry = tool_registry
        
        from agent.cognition.step_cache import StepCache
        self._step_cache = StepCache()

    async def decide_next_action(
        self,
        intent: StructuredIntent,
        world_state: SemanticWorldState,
        memory: SessionMemory,
        latest_reflection: ReflectionResult | None = None,
    ) -> CognitiveDecision:
        """Select immediate action to take.

        Args:
            intent: Structured user intent.
            world_state: Semantic world state.
            memory: Current session memory.
            latest_reflection: Recent reflection result if available.

        Returns:
            A CognitiveDecision model.
        """
        logger.info("making_immediate_decision", step=memory.current_step_index)

        tool_summary = (
            self._tool_registry.get_prompt_summary()
            if self._tool_registry
            else "Browser & Validation tools"
        )
        reflection_summary = latest_reflection.model_dump_json() if latest_reflection else "None"

        chosen_action: AgentAction | None = None
        rationale = ""
        expected = ""

        # Check step cache first
        plan_desc = ""
        plan_expected = ""
        if memory.plan and memory.plan.current_step:
            plan_desc = memory.plan.current_step.description
            plan_expected = memory.plan.current_step.expected_outcome

        if plan_desc:
            intent_type_str = str(intent.intent_type.value) if hasattr(intent.intent_type, "value") else str(intent.intent_type)
            cached = self._step_cache.get_action(intent.goal, intent_type_str, plan_desc, plan_expected)
            if cached:
                chosen_action = cached
                rationale = "Retrieved from StepCache"
                expected = plan_expected

        if not chosen_action and self._llm:
            try:
                response = await self._llm.complete_json(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a Cognitive Decision Engine selecting immediate agent actions.",  # noqa: E501
                        },
                        {
                            "role": "user",
                            "content": DECISION_PROMPT.format(
                                goal=intent.goal,
                                intent_type=intent.intent_type,
                                plan_summary=memory.plan.to_summary() if memory.plan else "None",
                                world_state_summary=world_state.to_compact_cognitive_summary(),
                                session_context=memory.get_context_for_llm(),
                                tool_summary=tool_summary,
                                reflection_summary=reflection_summary,
                            ),
                        },
                    ]
                )
                action_type = response.get("action_type", "wait")
                target = response.get("target", "")
                value = response.get("value", "")
                rationale = response.get("reasoning", "Selected by decision engine")
                expected = response.get("expected_outcome", "Action executes successfully")

                chosen_action = AgentAction(
                    action_type=ActionType(action_type),
                    target=target,
                    value=value,
                    reasoning=rationale,
                )
            except Exception as e:
                logger.warning("llm_decision_failed_fallback_to_heuristic", error=str(e))
                chosen_action = self._heuristic_decision(world_state, memory)
                rationale = chosen_action.reasoning
                expected = "Action executes"
        else:
            chosen_action = self._heuristic_decision(world_state, memory)
            rationale = chosen_action.reasoning
            expected = "Action executes"

        # Evaluate action confidence
        confidence_assessment = self._confidence_engine.evaluate_confidence(
            action=chosen_action,
            world_state=world_state,
        )

        return CognitiveDecision(
            action=chosen_action,
            reasoning=rationale,
            expected_outcome=expected,
            confidence_assessment=confidence_assessment,
        )

    def _heuristic_decision(
        self, world_state: SemanticWorldState, memory: SessionMemory
    ) -> AgentAction:
        """Heuristic fallback action decision."""
        if world_state.available_actions:
            first_action = world_state.available_actions[0]
            return AgentAction(
                action_type=ActionType.CLICK,
                target=first_action.target,
                reasoning=f"Heuristic choice: click available action {first_action.action_name}",
            )
        return AgentAction(
            action_type=ActionType.WAIT,
            target="",
            value="1000",
            reasoning="Heuristic fallback: wait for page state",
        )
