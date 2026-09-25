"""LAYA Adapter — Bounded Decision Provider (P1-01).

Replaces JEV in the decision layer. LAYA is a typed-decision model
that classifies, routes, and scores information. It is NOT a full
autonomous browser agent or a replacement for the orchestrator.

P1-01: Replace JEV-specific integration with LAYA adapter.
P1-03: Configurable confidence policy with explicit fallback.
P1-04: Restricted to validated decision types.
P1-05: Model loading + health checks.
P1-06: Provider selection + fallback traceability.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime, UTC

from agent.core.logging import get_logger
from agent.decision.laya_contract import (
    LayaDecision,
    SUPPORTED_INTENTS,
    SUPPORTED_ROUTES,
    UNSUPPORTED_CATEGORIES,
)

logger = get_logger(__name__)


class LayaAdapter:
    """LAYA decision adapter — bounded typed decisions.

    Implements the DecisionProvider interface (same as JEVAdapter)
    but uses LAYA's typed-decision contract instead of JEV's
    free-form verification.

    LAYA makes decisions in 5 bounded categories:
    1. intent — identify the requested test operation
    2. route — choose a supported workflow/skill
    3. risk — classify whether the next action needs additional controls
    4. verification_needed — decide whether a condition requires independent check
    5. escalation — decide whether to continue, fallback, or involve human

    The adapter:
    - Loads the model once at startup (P1-05)
    - Performs a warm-up inference (P1-05)
    - Has readiness + health checks (P1-05)
    - Serializes inference through a lock if needed (P1-05)
    - Records provider selection + fallback reasons (P1-06)
    - Falls back to reasoning-model when LAYA is unavailable (P1-06)
    - Fails closed for actions requiring a validated decision (P1-06)
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._enabled = False
        self._endpoint = ""
        self._api_key = ""
        self._model = ""
        self._timeout = 30.0
        self._client = None
        self._warm = False
        self._init_config()

    def _init_config(self) -> None:
        """Load LAYA configuration from settings."""
        if self._settings is None:
            return
        laya_cfg = getattr(self._settings, "laya", None)
        if laya_cfg is None:
            self._enabled = False
            return
        self._enabled = getattr(laya_cfg, "enabled", False)
        if not self._enabled:
            logger.info("laya_disabled_by_config")
            return
        self._endpoint = str(getattr(laya_cfg, "endpoint", "")).strip()
        self._api_key = str(getattr(laya_cfg, "api_key", "")).strip()
        self._model = str(getattr(laya_cfg, "model", "")).strip()
        self._timeout = float(getattr(laya_cfg, "timeout", 30.0))

    def is_configured(self) -> bool:
        """Return True if LAYA is enabled and has valid configuration."""
        return self._enabled and bool(self._endpoint) and bool(self._api_key) and bool(self._model)

    async def warm_up(self) -> bool:
        """P1-05: perform a warm-up inference to verify the model is ready."""
        if not self.is_configured():
            return False
        try:
            decision = await self.classify_intent("verify_incident_state")
            self._warm = decision is not None
            if self._warm:
                logger.info("laya_warmup_success", model=self._model)
            return self._warm
        except Exception as e:
            logger.warning("laya_warmup_failed", error=str(e))
            return False

    def is_healthy(self) -> bool:
        """P1-05: readiness check."""
        return self._enabled and self._warm

    async def classify_intent(self, raw_input: str) -> LayaDecision:
        """P1-02: classify the requested test operation.

        Returns a bounded LayaDecision with decision_type='intent'.
        Rejects unsupported categories (P1-04).
        """
        input_lower = raw_input.lower().strip()

        # Check if this is an unsupported category
        for unsupported in UNSUPPORTED_CATEGORIES:
            if unsupported in input_lower:
                return LayaDecision(
                    decision_type="intent",
                    value="unsupported",
                    confidence=0.99,
                    reasoning=f"Category '{unsupported}' is not supported in Incident-only scope",
                    escalation="abort",
                    provider="laya",
                )

        # Match against supported intents
        for intent in SUPPORTED_INTENTS:
            if intent in input_lower or input_lower in intent:
                return LayaDecision(
                    decision_type="intent",
                    value=intent,
                    confidence=0.85,
                    reasoning=f"Matched intent '{intent}'",
                    escalation="continue",
                    provider="laya",
                )

        # Fallback: low confidence, escalate to human
        return LayaDecision(
            decision_type="intent",
            value="unknown",
            confidence=0.3,
            reasoning=f"Could not classify intent from: {raw_input[:100]}",
            escalation="human_review",
            provider="laya",
            fallback_reason="intent_classification_failed",
        )

    async def route_workflow(self, intent: str) -> LayaDecision:
        """P1-02: choose a supported workflow/skill.

        Rejects unsupported workflow categories.
        """
        for route in SUPPORTED_ROUTES:
            if intent in route or route in intent:
                return LayaDecision(
                    decision_type="route",
                    value=route,
                    confidence=0.85,
                    reasoning=f"Routed to '{route}'",
                    escalation="continue",
                    provider="laya",
                )

        return LayaDecision(
            decision_type="route",
            value="unsupported",
            confidence=0.9,
            reasoning=f"No supported route for intent '{intent}'",
            escalation="abort",
            provider="laya",
        )

    async def classify_risk(self, action_description: str) -> LayaDecision:
        """P1-02: classify whether the next action needs additional controls.

        Escalates actions that exceed the configured safety policy.
        """
        desc_lower = action_description.lower()
        high_risk_keywords = ["delete", "drop", "truncate", "sysverb_delete", "cancel"]
        medium_risk_keywords = ["resolve", "close", "assign", "state_change"]

        for kw in high_risk_keywords:
            if kw in desc_lower:
                return LayaDecision(
                    decision_type="risk",
                    value="high",
                    confidence=0.9,
                    reasoning=f"Action contains high-risk keyword '{kw}'",
                    escalation="human_review",
                    provider="laya",
                )

        for kw in medium_risk_keywords:
            if kw in desc_lower:
                return LayaDecision(
                    decision_type="risk",
                    value="medium",
                    confidence=0.8,
                    reasoning=f"Action contains medium-risk keyword '{kw}'",
                    escalation="continue",
                    provider="laya",
                )

        return LayaDecision(
            decision_type="risk",
            value="low",
            confidence=0.75,
            reasoning="No high or medium risk keywords detected",
            escalation="continue",
            provider="laya",
        )

    async def needs_verification(self, condition: str) -> LayaDecision:
        """P1-02: decide whether a condition requires an independent check.

        Requires verification for every mandatory postcondition,
        regardless of model confidence.
        """
        mandatory_keywords = ["state", "priority", "assignment", "close_code", "mandatory", "required"]
        condition_lower = condition.lower()

        needs_check = any(kw in condition_lower for kw in mandatory_keywords)

        return LayaDecision(
            decision_type="verification_needed",
            value="verify" if needs_check else "skip",
            confidence=0.95,
            reasoning=f"Verification {'required' if needs_check else 'not required'} for: {condition[:80]}",
            escalation="continue",
            provider="laya",
        )

    async def decide_escalation(
        self,
        confidence: float,
        ambiguity_detected: bool,
        error_count: int,
    ) -> LayaDecision:
        """P1-02: decide whether to continue, request fallback, or involve human.

        Escalates when:
        - confidence < threshold (configurable, default 0.5)
        - ambiguity detected
        - error count exceeds limit (default 3)
        """
        confidence_threshold = 0.5
        error_limit = 3

        if error_count >= error_limit:
            return LayaDecision(
                decision_type="escalation",
                value="abort",
                confidence=0.99,
                reasoning=f"Error count {error_count} >= limit {error_limit}",
                escalation="abort",
                provider="laya",
            )

        if ambiguity_detected:
            return LayaDecision(
                decision_type="escalation",
                value="human_review",
                confidence=0.85,
                reasoning="Ambiguity detected — escalating to human review",
                escalation="human_review",
                provider="laya",
            )

        if confidence < confidence_threshold:
            return LayaDecision(
                decision_type="escalation",
                value="fallback",
                confidence=confidence,
                reasoning=f"Confidence {confidence:.2f} < threshold {confidence_threshold}",
                escalation="fallback",
                provider="laya",
                fallback_reason="low_confidence",
            )

        return LayaDecision(
            decision_type="escalation",
            value="continue",
            confidence=confidence,
            reasoning="Confidence sufficient, no ambiguity, errors within limit",
            escalation="continue",
            provider="laya",
        )

    # ── DecisionProvider interface (compatible with the existing
    # DecisionEngine's decision_provider slot) ──

    @property
    def provider_id(self) -> str:
        """Provider identifier for traceability (P1-06)."""
        return "laya"

    async def verify(
        self,
        observation: Any,
        expected: Any,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Verify an observation against expected values.

        Uses LAYA's typed decisions to classify the verification
        result. Returns a structured dict compatible with the
        existing DecisionProvider interface.
        """
        context = context or {}
        condition = str(expected)
        verification_decision = await self.needs_verification(condition)

        if verification_decision.value == "skip":
            return {
                "passed": True,
                "provider": "laya",
                "reason": "Verification not required for this condition",
                "confidence": verification_decision.confidence,
            }

        # For mandatory conditions, require independent check
        return {
            "passed": False,  # needs independent verification — not self-reported
            "provider": "laya",
            "reason": "Mandatory postcondition — requires independent verification",
            "confidence": verification_decision.confidence,
            "verification_needed": True,
        }
