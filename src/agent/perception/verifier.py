"""Behavioral Verifier — Level 3 perception validation.

Validates that an action achieved its expected outcome by comparing
before and after states (visual or DOM-based).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from agent.core.logging import get_logger
from agent.planner.llm_client import OpenAILLMClient

logger = get_logger(__name__)


class VerificationResult(BaseModel):
    """Result of a behavioral verification check."""

    is_verified: bool
    confidence: float
    reasoning: str
    suggested_recovery: str | None = None
    finding_type: str | None = None  # e.g., 'functional', 'visual', 'ux'
    finding_description: str | None = None
    evidence_reference: str | None = None
    before_evidence_reference: str | None = None


class BehavioralVerifier(ABC):
    """Interface for behavioral verification."""

    @abstractmethod
    async def verify_action(
        self,
        action_description: str,
        expected_outcome: str,
        before_state_summary: str,
        after_state_summary: str,
        before_screenshot_path: str | None = None,
        after_screenshot_path: str | None = None,
        bounding_boxes: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Use an LLM to compare states and verify if the action succeeded."""


class LLMBehavioralVerifier(BehavioralVerifier):
    """Uses an LLM to verify action outcomes."""

    def __init__(self, llm_client: OpenAILLMClient) -> None:
        self._llm = llm_client

    async def verify_action(
        self,
        action_description: str,
        expected_outcome: str,
        before_state_summary: str,
        after_state_summary: str,
        before_screenshot_path: str | None = None,
        after_screenshot_path: str | None = None,
        bounding_boxes: dict[str, Any] | None = None,
    ) -> VerificationResult:
        prompt = f"""
You are verifying whether a browser automation action succeeded.

Action Attempted: {action_description}
Expected Outcome: {expected_outcome}

Before State:
{before_state_summary}

After State:
{after_state_summary}

Did the action succeed in achieving the expected outcome?
Additionally, review the state for any visual anomalies
(misalignment, broken layout, error banners)
even if the functional outcome succeeded.

CRITICAL RULE FOR VISUAL FINDINGS:
You MUST NOT generate a 'visual' finding unless actual visual evidence
(screenshots or bounding boxes) was provided.
If no visual evidence is provided, you MUST set is_verified=False.

Visual Evidence Provided: {bool(after_screenshot_path)}

Respond in JSON format with the following keys:
- "is_verified": boolean
- "confidence": float between 0.0 and 1.0
- "reasoning": string explaining why
- "suggested_recovery": string or null, if it failed what to try next
- "finding_type": string or null (e.g., 'visual', 'functional', 'ux') if an anomaly is detected
- "finding_description": string or null describing the anomaly
"""
        logger.debug(
            "verifying_action_with_llm",
            action=action_description,
            has_visuals=bool(after_screenshot_path),
        )
        try:
            messages = [
                {"role": "system", "content": "You are a precise QA verification engine."},
                {"role": "user", "content": prompt},
            ]

            data = await self._llm.complete_json(messages=messages, temperature=0.0)

            finding_type = data.get("finding_type")
            finding_desc = data.get("finding_description")
            is_verified = bool(data.get("is_verified", False))

            # Programmatic enforcement of visual evidence
            if finding_type == "visual" and not after_screenshot_path:
                logger.warning(
                    "visual_finding_rejected_no_evidence", finding_description=finding_desc
                )
                finding_type = "functional"
                finding_desc = f"[REJECTED VISUAL: No evidence] {finding_desc}"
                is_verified = False

            return VerificationResult(
                is_verified=is_verified,
                confidence=float(data.get("confidence", 0.0)),
                reasoning=str(data.get("reasoning", "")),
                suggested_recovery=data.get("suggested_recovery"),
                finding_type=finding_type,
                finding_description=finding_desc,
                evidence_reference=after_screenshot_path,
                before_evidence_reference=before_screenshot_path,
            )
        except Exception as e:
            logger.error("verification_failed_with_exception", error=str(e))
            return VerificationResult(
                is_verified=False,
                confidence=0.0,
                reasoning=f"Verification process failed: {e}",
            )
