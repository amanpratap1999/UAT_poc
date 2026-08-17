"""Perception Decision Engine — coordinates perception logic.

Implements the core decision matrix for how to interact with the DOM,
falling back to vision, and verifying outcomes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.learning.service import LearningService
from agent.perception.models import GroundingFailure, PerceptionCandidate

if TYPE_CHECKING:
    from agent.browser.manager import BrowserManager
    from agent.browser.page_interactor import PageInteractor
    from agent.execution.controller import ExecutionController
    from agent.observation.engine import ObservationEngine
    from agent.perception.backends import GrounderBackend
    from agent.perception.verifier import BehavioralVerifier

logger = get_logger(__name__)


class PerceptionDecisionEngine:
    """Coordinates structural and visual perception for action execution."""

    def __init__(
        self,
        browser: BrowserManager,
        interactor: PageInteractor,
        executor: ExecutionController,
        grounder: GrounderBackend,
        verifier: BehavioralVerifier,
        learning_service: LearningService,
        observer: ObservationEngine,
    ) -> None:
        self._browser = browser
        self._interactor = interactor
        self._executor = executor
        self._grounder = grounder
        self._verifier = verifier
        self._learning = learning_service
        self._observer = observer

    async def execute_with_perception(self, action: AgentAction) -> ActionResult:
        """Execute an action using perception logic and behavioral verification."""
        # Non-interactive actions don't need deep perception
        if ActionType(action.action_type) not in (
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.SELECT,
        ):
            return await self._executor.execute(action)

        target = action.metadata.get("field_label", action.target)
        if not target:
            return await self._executor.execute(action)

        # Before state for verification
        await self._browser.take_screenshot("before_perception")
        try:
            page = self._browser.get_page()
            before_obs = await self._observer.observe(page)
        except Exception:
            before_obs = None

        before_state_summary = (
            before_obs.model_dump_json(exclude={"buttons", "tabs"}) if before_obs else "Unknown"
        )

        # 1. Check Learning Service for existing valid recoveries
        fingerprint = before_obs.url.split("?")[0] if before_obs else "unknown"
        recovery = await self._learning.get_valid_recovery(target, fingerprint)

        recovered_candidate: PerceptionCandidate | None = None
        if recovery:
            # We have a valid learned recovery.
            logger.info("using_learned_recovery", target=target, recovery_id=recovery.id)
            # Reconstruct a basic candidate
            recovered_candidate = PerceptionCandidate(
                source="learned",
                confidence=recovery.confidence,
                target_description=target,
                locator_str=recovery.successful_locator,
                is_visible=True,
                is_enabled=True,
            )

        final_action = action.model_copy(deep=True)
        used_vision = False
        selected_candidate = None

        if recovered_candidate:
            selected_candidate = recovered_candidate
            self._apply_candidate_to_action(final_action, selected_candidate)
            # If it has a locator string, we should ideally revalidate if it still exists
            if selected_candidate.locator_str:
                try:
                    cands = await self._interactor.resolve_candidates(
                        selected_candidate.locator_str
                    )
                    if not any(c.is_visible for c in cands):
                        logger.warning("learned_recovery_stale", target=target)
                        selected_candidate = None  # Force re-perception
                        if recovery:
                            await self._learning.record_recovery_outcome(
                                target=target,
                                fingerprint=fingerprint,
                                original_locator=None,
                                successful_locator=recovery.successful_locator,
                                is_success=False,
                            )
                except Exception:
                    selected_candidate = None

        # 2. Level 1: Structural Perception
        if not selected_candidate:
            try:
                dom_candidates = await self._interactor.resolve_candidates(target)
            except Exception as e:
                logger.warning("dom_resolution_failed", error=str(e))
                dom_candidates = []

            if len(dom_candidates) == 1:
                # Single Match
                selected_candidate = dom_candidates[0]
                self._apply_candidate_to_action(final_action, selected_candidate)
                logger.info("single_dom_candidate_found", target=target)
            elif len(dom_candidates) > 1:
                # Multiple Matches: Disambiguate deterministically
                selected_candidate = self._disambiguate_candidates(dom_candidates, target)
                if selected_candidate:
                    self._apply_candidate_to_action(final_action, selected_candidate)
                    logger.info("disambiguated_dom_candidate", target=target)

            # 3. Level 2: Semantic Perception (Visual Grounding Fallback)
            if not selected_candidate:
                # Zero DOM matches or ambiguous -> Vision fallback
                logger.info("invoking_visual_grounding", target=target)
                used_vision = True

                # We need raw bytes for the vision model
                screenshot_bytes = b""
                try:
                    screenshot_bytes = await page.screenshot(type="png")
                except Exception as e:
                    logger.error("vision_screenshot_failed", error=str(e))

                if screenshot_bytes:
                    try:
                        v_cand = await self._grounder.ground_element(
                            screenshot_bytes=screenshot_bytes,
                            target_description=target,
                            page=page,
                        )
                        if v_cand:
                            selected_candidate = v_cand
                            self._apply_candidate_to_action(final_action, selected_candidate)
                            logger.info(
                                "visual_candidate_found",
                                target=target,
                                conf=v_cand.confidence,
                            )
                    except GroundingFailure as e:
                        logger.error("puter_grounding_failure", error=str(e))
                        return ActionResult(
                            success=False,
                            action=action,
                            error=f"Visual grounding failed critically: {e}",
                            error_type="GroundingFailure",
                        )

        if not selected_candidate:
            # We failed to find anything structurally or visually
            logger.error("perception_failed_all_tiers", target=target)
            return ActionResult(
                success=False,
                action=action,
                error=f"Perception failed to locate target '{target}'",
                error_type="PerceptionFailure",
            )

        # 4. Execute the action
        exec_result = await self._executor.execute(final_action)
        if not exec_result.success:
            return exec_result

        # 5. Level 3: Behavioral Verification
        # Only verify if we used vision or if it's a recovered mapping being reused
        if used_vision or recovered_candidate:
            await self._browser.take_screenshot("after_perception")
            try:
                after_obs = await self._observer.observe(page)
            except Exception:
                after_obs = None
            after_state_summary = (
                after_obs.model_dump_json(exclude={"buttons", "tabs"}) if after_obs else "Unknown"
            )

            verification = await self._verifier.verify_action(
                action_description=f"{action.action_type} on '{target}'",
                expected_outcome="Interaction successful, page navigated or state changed",
                before_state_summary=before_state_summary,
                after_state_summary=after_state_summary,
            )

            if verification.is_verified:
                logger.info("behavioral_verification_passed", target=target)
                # Persist learning
                await self._learning.record_recovery_outcome(
                    target=target,
                    fingerprint=fingerprint,
                    original_locator=None,
                    successful_locator=selected_candidate.locator_str
                    if selected_candidate
                    else None,
                    is_success=True,
                )
            else:
                logger.warning(
                    "behavioral_verification_failed",
                    target=target,
                    reasoning=verification.reasoning,
                )
                # Penalize learning
                await self._learning.record_recovery_outcome(
                    target=target,
                    fingerprint=fingerprint,
                    original_locator=None,
                    successful_locator=selected_candidate.locator_str
                    if selected_candidate
                    else None,
                    is_success=False,
                )

                exec_result.success = False
                exec_result.error = "Behavioral verification failed after execution"
                exec_result.error_type = "VerificationFailure"

        return exec_result

    def _disambiguate_candidates(
        self, candidates: list[PerceptionCandidate], target: str
    ) -> PerceptionCandidate | None:
        """Apply deterministic rules to filter multiple DOM candidates."""
        # 1. Filter invisible
        visible = [c for c in candidates if c.is_visible]
        if len(visible) == 1:
            return visible[0]

        # 2. Filter disabled
        enabled = [c for c in visible if c.is_enabled]
        if len(enabled) == 1:
            return enabled[0]

        # 3. Prefer main frame over generic iframes
        main_frame = [
            c
            for c in enabled
            if c.frame_context == "main" or "gsft_main" in (c.frame_context or "")
        ]
        if len(main_frame) == 1:
            return main_frame[0]

        # Still ambiguous -> return None to trigger vision fallback
        return None

    def _apply_candidate_to_action(
        self, action: AgentAction, candidate: PerceptionCandidate
    ) -> None:
        """Modify the action to target the precise candidate."""
        if candidate.locator_str:
            action.target = candidate.locator_str
        elif candidate.bounding_box:
            action.metadata["is_coordinate"] = True
            action.metadata["x"] = candidate.bounding_box.center_x
            action.metadata["y"] = candidate.bounding_box.center_y
