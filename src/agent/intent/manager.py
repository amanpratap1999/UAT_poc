"""Intent Manager — parses natural language user goals into structured intents.

Deliverable 1:
- Goal normalization
- Intent type extraction
- Ambiguity detection
- Entity extraction
"""

from __future__ import annotations

from typing import Any

from agent.core.logging import get_logger
from agent.core.untrusted import UNTRUSTED_DATA_POLICY, wrap_untrusted, scan_for_injection
from agent.domain.intent import StructuredIntent
from agent.planner.llm_client import BaseLLMClient

logger = get_logger(__name__)

INTENT_PARSER_PROMPT = """Analyze the following user testing goal for a ServiceNow application
and convert it into a structured intent.

User Goal: {raw_prompt}

Respond with a JSON object:
{{
    "intent_type": "IncidentValidation|IncidentCreation|IncidentLifecycle|GeneralValidation|UIInteraction|AuthValidation",
    "goal": "Normalized concise goal statement",
    "target_module": "general|auth|ui|incident|problem|change",
    "priority": "High|Normal|Low",
    "confidence": 0.95,
    "is_ambiguous": false,
    "clarification_needed": null,
    "extracted_entities": {{}}
}}
"""


class IntentManager:
    """Understands, normalizes, and structures natural language testing goals."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self._llm = llm_client

    async def parse_intent(self, raw_prompt: str) -> StructuredIntent:
        """Parse natural language prompt into a StructuredIntent.

        Args:
            raw_prompt: User prompt string (e.g. "Check whether incidents can be resolved.")

        Returns:
            A StructuredIntent instance.
        """
        logger.info("parsing_user_intent", prompt=raw_prompt[:80])

        prompt_safe = wrap_untrusted("raw_prompt", raw_prompt)
        if scan_for_injection(raw_prompt):
            logger.warning("prompt_injection_detected_in_intent_manager")

        if self._llm:
            try:
                response = await self._llm.complete_json(
                    messages=[
                        {
                            "role": "system",
                            "content": f"You are a Goal Parsing Engine for ServiceNow QA Agent.\n\n{UNTRUSTED_DATA_POLICY}",
                        },
                        {
                            # Audit issue I20 (P1): previously used
                            # INTENT_PARSER_PROMPT.format(raw_prompt=prompt_safe)
                            # but the wrapped prompt_safe may contain literal
                            # { or } characters (the wrap_untrusted helper
                            # neutralizes </untrusted_data> but does NOT
                            # escape Python str.format placeholders). A
                            # literal '{' in user input would raise
                            # KeyError/ValueError and silently fall back to
                            # the heuristic rule path, defeating the LLM-based
                            # intent parsing for any goal containing braces.
                            # Fix: use str.replace() which does NOT interpret
                            # format-spec syntax.
                            "role": "user",
                            "content": INTENT_PARSER_PROMPT.replace("{raw_prompt}", prompt_safe),
                        },
                    ]
                )
                target_mod = response.get("target_module", "").lower()
                # Sanity check: don't classify as incident if prompt has zero incident keywords
                prompt_lower = raw_prompt.lower()
                if target_mod == "incident" and not any(k in prompt_lower for k in ["inc", "incident"]):
                    target_mod = "auth" if any(k in prompt_lower for k in ["login", "password", "auth", "sign in"]) else "general"

                if not target_mod:
                    target_mod = "incident" if any(k in prompt_lower for k in ["inc", "incident"]) else "general"

                return StructuredIntent(
                    intent_type=response.get("intent_type", "GeneralValidation"),
                    goal=response.get("goal", raw_prompt),
                    raw_prompt=raw_prompt,
                    priority=response.get("priority", "Normal"),
                    confidence=float(response.get("confidence", 0.95)),
                    target_module=target_mod,
                    extracted_entities=response.get("extracted_entities", {}),
                    is_ambiguous=bool(response.get("is_ambiguous", False)),
                    clarification_needed=response.get("clarification_needed"),
                )
            except Exception as e:
                logger.warning("llm_intent_parsing_failed_fallback_to_rules", error=str(e))

        # Heuristic rule fallback with extended Incident intent patterns
        prompt_lower = raw_prompt.lower()
        extracted_entities: dict[str, Any] = {}

        import re

        inc_match = re.search(r"inc\d+", prompt_lower)
        if inc_match:
            extracted_entities["incident_number"] = inc_match.group(0).upper()

        is_incident = bool(inc_match) or "incident" in prompt_lower

        if is_incident:
            target_module = "incident"
            intent_type = "IncidentValidation"
            if "open" in prompt_lower or "view" in prompt_lower:
                intent_type = "IncidentOpen"
            elif "resolve" in prompt_lower or "resolution" in prompt_lower:
                intent_type = "IncidentResolutionCheck"
            elif "assignment" in prompt_lower or "assign" in prompt_lower:
                intent_type = "IncidentAssignmentValidation"
            elif "mandatory" in prompt_lower or "required" in prompt_lower:
                intent_type = "IncidentMandatoryFieldsCheck"
            elif "lifecycle" in prompt_lower or "transition" in prompt_lower:
                intent_type = "IncidentLifecycle"
            elif "create" in prompt_lower:
                intent_type = "IncidentCreation"
        else:
            target_module = "auth" if any(k in prompt_lower for k in ["login", "password", "auth", "sign in"]) else "general"
            intent_type = "GeneralValidation"

        return StructuredIntent(
            intent_type=intent_type,
            goal=raw_prompt.strip(),
            raw_prompt=raw_prompt,
            priority="Normal",
            confidence=0.95,
            target_module=target_module,
            extracted_entities=extracted_entities,
        )
