"""JEV Adapter — Implements DecisionProvider using JEV model/runtime."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from agent.core.config import get_settings
from agent.core.logging import get_logger
from agent.decision.provider import (
    Assertion,
    AssertionOperator,
    AssertionResult,
    DecisionProvider,
    VerificationDecision,
    VerificationRequest,
    VerificationResponse,
)
from openai import AsyncOpenAI

logger = get_logger(__name__)


class JEVAdapter(DecisionProvider):
    """JEV (Judgment Evaluation Verification) adapter.

    Calls an OpenAI-compatible endpoint with structured prompts for
    verification/decision making. Returns machine-readable PASS/FAIL
    with per-assertion results.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings or get_settings()
        self._enabled = False
        self._model = ""
        self._endpoint = ""
        self._api_key = ""
        self._timeout = 30.0
        self._client: AsyncOpenAI | None = None
        self._init_config()

    def is_configured(self) -> bool:
        """Return True if JEV is enabled and has valid configuration.

        INC-UAT-07: used by the dependency factory to decide whether
        to attach JEV as the default DecisionProvider.
        """
        return self._enabled and bool(self._model) and bool(self._endpoint) and bool(self._api_key)

    def _init_config(self) -> None:
        """Load JEV configuration from settings."""
        jev_cfg = getattr(self._settings, "jev", None)
        if jev_cfg is None:
            self._enabled = False
            return

        self._enabled = getattr(jev_cfg, "enabled", False)

        if not self._enabled:
            logger.info("jev_disabled_by_config")
            return

        # Load required configuration
        self._model = str(getattr(jev_cfg, "model", "")).strip()
        self._endpoint = str(getattr(jev_cfg, "endpoint", "")).strip()
        self._api_key = str(getattr(jev_cfg, "api_key", "")).strip()
        self._timeout = float(getattr(jev_cfg, "timeout", 30.0))

        # Validate required config
        if not self._model:
            logger.error("jev_config_missing", missing="JEV_MODEL")
            self._enabled = False
            return

        if not self._endpoint:
            logger.error("jev_config_missing", missing="JEV_ENDPOINT")
            self._enabled = False
            return

        if not self._api_key:
            logger.error("jev_config_missing", missing="JEV_API_KEY")
            self._enabled = False
            return

        # Initialize OpenAI-compatible client
        try:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._endpoint,
                timeout=self._timeout,
                max_retries=0,
            )
            logger.info("jev_adapter_initialized", model=self._model, endpoint=self._endpoint)
        except Exception as e:
            logger.error("jev_client_init_failed", error=str(e))
            self._enabled = False

    @property
    def name(self) -> str:
        return "jev"

    @property
    def is_available(self) -> bool:
        return self._enabled and self._client is not None

    def _build_verification_prompt(self, request: VerificationRequest) -> str:
        """Build the verification prompt for JEV."""
        assertions_text = ""
        if request.assertions:
            assertions_text = "\n\n## Assertions to Evaluate\n"
            for i, a in enumerate(request.assertions, 1):
                field = a.field_path or a.name
                assertions_text += f"{i}. {field} {a.operator.value} {a.expected!r}"
                if a.description:
                    assertions_text += f"  # {a.description}"
                assertions_text += "\n"

        expected_text = ""
        if request.expected:
            expected_text = "\n\n## Expected State\n"
            for k, v in request.expected.items():
                expected_text += f"- {k}: {v!r}\n"

        observed_text = ""
        if request.observed:
            observed_text = "\n\n## Observed State\n"
            for k, v in request.observed.items():
                observed_text += f"- {k}: {v!r}\n"

        return f"""You are JEV — a structured verification engine for ServiceNow UAT.
Evaluate whether the observed state satisfies the expected conditions.

## Task
{request.task}{assertions_text}{expected_text}{observed_text}

## Instructions
1. Evaluate EACH assertion independently against the observed state.
2. For field access, use the observed state dictionary.
3. If an assertion references a field not in observed state, treat as FAIL.
4. Return a JSON object with exactly this structure:
{{
    "decision": "PASS" | "FAIL" | "VERIFICATION_ERROR",
    "confidence": 0.95,
    "reason": "Brief explanation of overall decision",
    "assertions": [
        {{
            "name": "assertion_name",
            "expected": "expected_value",
            "observed": "observed_value",
            "result": "PASS" | "FAIL",
            "reason": "Why this assertion passed/failed",
            "confidence": 0.98
        }}
    ]
}}

## Operator Semantics
- equals: observed == expected (string comparison)
- not_equals: observed != expected
- contains: expected in observed (substring for strings)
- not_contains: expected not in observed
- is_empty: observed is null, empty string, or empty collection
- not_empty: observed is not null/empty
- state_matches: ServiceNow state value matches (e.g., "2" == "In Progress")
- regex_match: regex pattern matches observed string
- greater_than: numeric comparison
- less_than: numeric comparison

## Critical Rules
- If ANY assertion fails, overall decision = FAIL
- Only PASS if ALL assertions pass
- VERIFICATION_ERROR only for system errors (not assertion failures)
- Confidence reflects certainty in the evaluation
- Be precise: use exact string/numeric comparison
"""

    def _parse_jev_response(self, response_text: str) -> VerificationResponse:
        """Parse JEV response into VerificationResponse."""
        try:
            # Extract JSON from response (handle potential markdown fences)
            content = response_text.strip()
            if content.startswith("```"):
                # Extract from markdown code fence
                import re
                fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
                if fence_match:
                    content = fence_match.group(1).strip()

            data = json.loads(content)

            # Validate required fields
            decision_str = data.get("decision", "VERIFICATION_ERROR").upper()
            try:
                decision = VerificationDecision(decision_str)
            except ValueError:
                decision = VerificationDecision.VERIFICATION_ERROR

            confidence = float(data.get("confidence", 0.0))
            reason = str(data.get("reason", "No reason provided"))

            assertions = []
            for a_data in data.get("assertions", []):
                try:
                    assertion_result = AssertionResult(
                        assertion=Assertion(
                            name=a_data.get("name", ""),
                            operator=AssertionOperator.EQUALS,  # We don't reconstruct the original operator
                            expected=a_data.get("expected"),
                        ),
                        observed=a_data.get("observed"),
                        result=VerificationDecision(a_data.get("result", "FAIL").upper()),
                        reason=str(a_data.get("reason", "")),
                        confidence=float(a_data.get("confidence", 1.0)),
                    )
                    assertions.append(assertion_result)
                except Exception as e:
                    logger.warning("jev_assertion_parse_failed", error=str(e), assertion_data=a_data)

            return VerificationResponse(
                decision=decision,
                confidence=confidence,
                reason=reason,
                assertions=assertions,
                raw_response=data,
            )

        except json.JSONDecodeError as e:
            logger.error("jev_response_json_decode_failed", error=str(e), response=response_text[:500])
            return VerificationResponse(
                decision=VerificationDecision.VERIFICATION_ERROR,
                confidence=0.0,
                reason=f"Malformed JEV response: {e}",
                error="JSON_DECODE_ERROR",
            )
        except Exception as e:
            logger.error("jev_response_parse_failed", error=str(e))
            return VerificationResponse(
                decision=VerificationDecision.VERIFICATION_ERROR,
                confidence=0.0,
                reason=f"Failed to parse JEV response: {e}",
                error="PARSE_ERROR",
            )

    async def verify(self, request: VerificationRequest) -> VerificationResponse:
        """Execute JEV verification."""
        if not self.is_available or self._client is None:
            logger.warning("jev_verify_unavailable")
            return VerificationResponse(
                decision=VerificationDecision.VERIFICATION_ERROR,
                confidence=0.0,
                reason="JEV is not configured or unavailable",
                error="JEV_UNAVAILABLE",
            )

        logger.info("jev_verification_started", task=request.task)

        prompt = self._build_verification_prompt(request)

        try:
            logger.debug("jev_request_prepared", prompt_length=len(prompt))

            # Call JEV endpoint
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "You are JEV — a structured verification engine. Return only valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    max_tokens=2048,
                ),
                timeout=self._timeout,
            )

            raw_content = response.choices[0].message.content or ""
            logger.debug("jev_response_received", response_length=len(raw_content))

            result = self._parse_jev_response(raw_content)

            logger.info(
                "jev_verification_completed",
                decision=result.decision.value,
                confidence=result.confidence,
                assertions_count=len(result.assertions),
            )

            return result

        except asyncio.TimeoutError:
            logger.error("jev_verification_timeout", timeout=self._timeout)
            return VerificationResponse(
                decision=VerificationDecision.VERIFICATION_ERROR,
                confidence=0.0,
                reason=f"JEV request timed out after {self._timeout}s",
                error="TIMEOUT",
            )
        except Exception as e:
            logger.error("jev_verification_failed", error=str(e))
            return VerificationResponse(
                decision=VerificationDecision.VERIFICATION_ERROR,
                confidence=0.0,
                reason=f"JEV verification failed: {e}",
                error="REQUEST_FAILED",
            )

    async def decide(self, request: VerificationRequest) -> VerificationResponse:
        """Alias for verify — future action-selection can extend this."""
        return await self.verify(request)


# Global instance (lazy initialization)
_jev_adapter: JEVAdapter | None = None


def get_jev_adapter() -> JEVAdapter:
    """Get or create the JEV adapter singleton."""
    global _jev_adapter
    if _jev_adapter is None:
        _jev_adapter = JEVAdapter()
    return _jev_adapter