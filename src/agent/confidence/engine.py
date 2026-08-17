"""Confidence Engine for Deliverable 6.

Evaluates every proposed action with a confidence score (0.0 to 1.0).
Actions below the configurable threshold trigger re-observation,
knowledge lookup, or reflection before execution.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction
from agent.domain.world import SemanticWorldState

logger = get_logger(__name__)


class ConfidenceAssessment(BaseModel):
    """Assessment of confidence for a proposed action."""

    action_type: str
    target: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(default=0.70)
    is_above_threshold: bool = True
    reasons: list[str] = Field(default_factory=list)
    suggested_pre_action: str | None = None  # e.g. "observe", "search_docs", "reflect"


class ConfidenceEngine:
    """Evaluates proposed actions against the semantic world state to compute confidence."""

    def __init__(self, default_threshold: float = 0.70) -> None:
        self._default_threshold = default_threshold

    def evaluate_confidence(
        self,
        action: AgentAction,
        world_state: SemanticWorldState,
        threshold: float | None = None,
    ) -> ConfidenceAssessment:
        """Calculate confidence score for taking an action in the current world state.

        Args:
            action: The proposed AgentAction.
            world_state: Current SemanticWorldState.
            threshold: Override default confidence threshold.

        Returns:
            A ConfidenceAssessment object.
        """
        thresh = threshold if threshold is not None else self._default_threshold
        score = 0.95
        reasons: list[str] = []
        pre_action: str | None = None

        target_lower = action.target.lower()
        target_name = action.target.split(":", 1)[-1].strip().lower()

        # Check if action targets a blocked action in world state
        for blocked in world_state.blocked_actions:
            if blocked.action_name.lower() in (target_name, target_lower):
                score -= 0.50
                reasons.append(f"Target action is marked blocked: {blocked.block_reason}")
                pre_action = "reflect"

        # Check missing mandatory fields for submit/resolve actions
        if (
            action.action_type in ("click", "fill")
            and target_name
            in (
                "resolve",
                "submit",
                "update",
            )
            and world_state.missing_mandatory_fields
        ):
            score -= 0.35
            reasons.append(
                f"Missing mandatory fields: {', '.join(world_state.missing_mandatory_fields)}"
            )
            pre_action = "observe"

        # Low confidence if target is not found in available actions or fields
        if action.action_type == "click":
            avail_names = [a.action_name.lower() for a in world_state.available_actions]
            if target_name not in avail_names and not any(target_name in a for a in avail_names):
                score -= 0.20
                reasons.append(
                    f"Target '{action.target}' not explicitly detected in available UI actions"
                )
                pre_action = "observe"

        score = max(0.0, min(1.0, score))
        is_above = score >= thresh

        logger.info(
            "evaluated_confidence",
            action=action.action_type,
            target=action.target,
            score=f"{score:.2f}",
            threshold=thresh,
            is_above=is_above,
        )

        return ConfidenceAssessment(
            action_type=str(action.action_type),
            target=action.target,
            score=score,
            threshold=thresh,
            is_above_threshold=is_above,
            reasons=reasons or ["Action aligns well with world state"],
            suggested_pre_action=pre_action if not is_above else None,
        )
