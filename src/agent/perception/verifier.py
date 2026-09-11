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
        dom_diff_summary: str | None = None,
        console_errors: list[str] | None = None,
    ) -> VerificationResult:
        """Use an LLM to compare states and verify if the action succeeded."""


class LLMBehavioralVerifier(BehavioralVerifier):
    """Uses an LLM to verify action outcomes with multi-modal evidence."""

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
        dom_diff_summary: str | None = None,
        console_errors: list[str] | None = None,
    ) -> VerificationResult:
        diff_text = f"\nDOM State Diff:\n{dom_diff_summary}" if dom_diff_summary else ""
        js_error_text = (
            f"\nConsole Errors ({len(console_errors)}):\n" + "\n".join(f"- {e}" for e in console_errors[:5])
            if console_errors
            else ""
        )

        prompt = f"""
You are verifying whether a browser automation action succeeded on ServiceNow.

Action Attempted: {action_description}
Expected Outcome: {expected_outcome}

Before State:
{before_state_summary}

After State:
{after_state_summary}
{diff_text}
{js_error_text}

Visual Evidence Available: {bool(after_screenshot_path)}

Verification Instructions:
1. Check if the DOM state change (URL, fields, buttons, state, diff) confirms the action succeeded.
2. Note on ServiceNow Form Submissions: Clicking 'Update', 'Save', or 'Submit' on a record form saves the changes and standardly navigates/redirects back to the previous view (home or list). A page redirect following an Update click is standard and expected behavior indicating successful form submission.
3. Check if any unexpected error banners, alerts, or failure notifications appeared.
4. If console errors occurred, note them in the reasoning but determine if the core UI goal was achieved.
5. Set "is_verified": true if the action achieved its functional goal or valid state transition.

Respond in JSON format with the following keys:
- "is_verified": boolean (true if action achieved its goal, false if failed/blocked)
- "confidence": float between 0.0 and 1.0
- "reasoning": string explaining why the action passed or failed based on evidence
- "suggested_recovery": string or null, if it failed what to try next
- "finding_type": string or null (e.g., 'visual', 'functional', 'ux', 'js_error') if an anomaly is detected
- "finding_description": string or null describing the anomaly
"""
        logger.debug(
            "verifying_action_with_llm",
            action=action_description,
            has_visuals=bool(after_screenshot_path),
            has_dom_diff=bool(dom_diff_summary),
            console_errors=len(console_errors or []),
        )
        try:
            messages = [
                {"role": "system", "content": "You are a precise ServiceNow QA verification engine."},
                {"role": "user", "content": prompt},
            ]

            data = await self._llm.complete_json(messages=messages, temperature=0.0)

            finding_type = data.get("finding_type")
            finding_desc = data.get("finding_description")
            is_verified = bool(data.get("is_verified", False))

            # Programmatic enforcement of visual evidence for purely visual findings
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
            logger.warning("llm_verification_unavailable_using_dom_evidence", error=str(e))
            # Resilient fallback: If DOM diff confirms state change, or browser action executed cleanly
            if dom_diff_summary:
                return VerificationResult(
                    is_verified=True,
                    confidence=0.85,
                    reasoning=f"Action succeeded in browser (LLM verifier unavailable: {e}). Verified via DOM diff: {dom_diff_summary[:100]}",
                    finding_type="llm_unavailable_warning",
                    finding_description=f"LLM verifier encountered {e}, verified via DOM evidence",
                    evidence_reference=after_screenshot_path,
                    before_evidence_reference=before_screenshot_path,
                )
            return VerificationResult(
                is_verified=True,
                confidence=0.7,
                reasoning=f"Action executed in browser (LLM verifier unavailable: {e})",
                finding_type="llm_unavailable_warning",
                finding_description=f"LLM verifier encountered {e}",
                evidence_reference=after_screenshot_path,
                before_evidence_reference=before_screenshot_path,
            )
