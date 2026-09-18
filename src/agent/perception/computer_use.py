"""Gemini Computer Use Adapter — emergency browser action planning fallback.

When Moondream cannot ground an element, Gemini Computer Use acts as an
emergency action proposer. It takes the current screenshot and goal,
and proposes structured browser actions (click at coordinates, type text,
scroll, key press).

Playwright remains the deterministic executor. The model NEVER touches the
browser directly; all proposed actions flow through ActionPolicy and
ExecutionController.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.core.types import ActionType

if TYPE_CHECKING:
    from agent.execution.policy import ActionPolicy

logger = get_logger(__name__)


class ProposedBrowserAction(BaseModel):
    """An action proposed by Gemini Computer Use."""

    action_type: str = Field(description="click, fill, scroll, key_press, wait")
    target: str = ""
    value: str | None = None
    x: int | None = None
    y: int | None = None
    confidence: float = 0.8
    reasoning: str = ""
    is_safe: bool = True

    def to_agent_action(self) -> AgentAction:
        """Convert proposed action into an executable AgentAction."""
        metadata: dict[str, Any] = {
            "source": "gemini_computer_use",
            "reasoning": self.reasoning,
        }
        if self.x is not None and self.y is not None:
            metadata["is_coordinate"] = True
            metadata["x"] = self.x
            metadata["y"] = self.y

        return AgentAction(
            action_type=ActionType(self.action_type),
            target=self.target or f"coordinate({self.x},{self.y})",
            value=self.value or "",
            metadata=metadata,
        )


class GeminiComputerUseAdapter:
    """Proposes browser actions using Gemini Vision / Computer Use."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model = None
        if self.api_key:
            self._init_model()

    def _init_model(self) -> None:
        """Initialize the Gemini generative model."""
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]

            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel("gemini-2.0-flash")
            logger.info("gemini_computer_use_initialized")
        except Exception as e:
            logger.warning("gemini_computer_use_init_failed", error=str(e))
            self._model = None

    async def propose_fallback_action(
        self,
        screenshot_bytes: bytes,
        goal: str,
        failed_target: str,
        current_url: str = "",
        policy: ActionPolicy | None = None,
    ) -> ProposedBrowserAction | None:
        """Propose an action when Moondream and DOM grounding fail.

        Args:
            screenshot_bytes: PNG screenshot bytes.
            goal: The overarching test goal.
            failed_target: The target that could not be grounded.
            current_url: Current browser page URL.
            policy: Optional ActionPolicy to validate proposed action safety.

        Returns:
            ProposedBrowserAction or None if Gemini cannot propose a valid action.
        """
        if not self._model or not screenshot_bytes:
            logger.warning("gemini_computer_use_unavailable")
            return None

        logger.info(
            "gemini_computer_use_started",
            goal=goal,
            failed_target=failed_target,
        )

        from PIL import Image
        import io

        img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
        width, height = img.size

        prompt = f"""
You are an intelligent browser automation fallback assistant.
The agent is trying to accomplish: "{goal}"
It attempted to locate target: "{failed_target}" but standard DOM and primary vision grounding failed.

Examine the screenshot ({width}x{height} pixels).
Determine the next best browser action to interact with "{failed_target}" or achieve the goal.

Respond ONLY with a JSON object in this exact format:
{{
    "action_type": "click" | "fill" | "scroll" | "key_press",
    "x": integer pixel x coordinate (or null),
    "y": integer pixel y coordinate (or null),
    "value": string value if filling an input or pressing a key (or null),
    "confidence": float between 0.0 and 1.0,
    "reasoning": "brief explanation of why this coordinate/element corresponds to the target"
}}
"""

        try:
            response = await self._model.generate_content_async([prompt, img])
            text = response.text.strip()

            # Parse JSON from response
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if not json_match:
                logger.warning("gemini_computer_use_no_json", response=text[:200])
                return None

            data = json.loads(json_match.group())

            action_type = data.get("action_type", "click")
            x = data.get("x")
            y = data.get("y")
            val = data.get("value")
            conf = float(data.get("confidence", 0.75))
            reasoning = data.get("reasoning", "")

            # Sanity check coordinates
            if x is not None and (x < 0 or x > width):
                x = None
            if y is not None and (y < 0 or y > height):
                y = None

            proposed = ProposedBrowserAction(
                action_type=action_type,
                target=failed_target,
                value=val,
                x=x,
                y=y,
                confidence=conf,
                reasoning=reasoning,
            )

            # Check safety against policy if provided
            if policy:
                agent_action = proposed.to_agent_action()
                policy_res = policy.validate(agent_action, current_url=current_url)
                if not policy_res.is_allowed:
                    logger.warning(
                        "gemini_proposed_action_blocked_by_policy",
                        reason=policy_res.reason,
                    )
                    proposed.is_safe = False
                    return None

            logger.info(
                "gemini_action_received",
                action_type=action_type,
                x=x,
                y=y,
                confidence=conf,
            )
            return proposed

        except Exception as e:
            logger.error("gemini_computer_use_failed", error=str(e))
            return None
