"""Perception Decision Engine — coordinates perception logic.

Implements the core decision matrix for how to interact with the DOM,
falling back to vision, and verifying outcomes.

Uses the confidence-driven PerceptionRouter:
1. DOM reliable → use directly (no vision call)
2. Moondream PRIMARY → check confidence
3. Gemini FALLBACK → last resort
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.core.logging import get_logger
from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.learning.service import LearningService
from agent.observation.page_state import PageStateFingerprint
from agent.perception.models import GroundingFailure, PerceptionCandidate
from agent.perception.router import PerceptionRouter

if TYPE_CHECKING:
    from agent.browser.manager import BrowserManager
    from agent.browser.page_interactor import PageInteractor
    from agent.execution.controller import ExecutionController
    from agent.observation.engine import ObservationEngine
    from agent.perception.backends import GrounderBackend
    from agent.perception.verifier import BehavioralVerifier

logger = get_logger(__name__)


class PerceptionDecisionEngine:
    """Coordinates structural and visual perception for action execution.

    Uses the PerceptionRouter for confidence-driven DOM → Moondream → Gemini
    routing. Tracks perception_route for full log traceability.
    """

    def __init__(
        self,
        browser: BrowserManager,
        interactor: PageInteractor,
        executor: ExecutionController,
        grounder: GrounderBackend,
        verifier: BehavioralVerifier,
        learning_service: LearningService,
        observer: ObservationEngine,
        perception_router: PerceptionRouter | None = None,
    ) -> None:
        self._browser = browser
        self._interactor = interactor
        self._executor = executor
        self._grounder = grounder
        self._verifier = verifier
        self._learning = learning_service
        self._observer = observer
        self._router = perception_router

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
        before_screenshot_path = None
        try:
            before_screenshot_path = await self._browser.take_screenshot("before_perception")
        except Exception as e:
            logger.warning("before_screenshot_failed", error=str(e))

        try:
            page = self._browser.get_page()
            before_obs = await self._observer.observe(page)
        except Exception:
            before_obs = None

        before_state_summary = (
            before_obs.model_dump_json(exclude={"buttons", "tabs"}) if before_obs else "Unknown"
        )
        before_fingerprint = (
            PageStateFingerprint.from_observation(before_obs) if before_obs else None
        )

        fingerprint = before_obs.url.split("?")[0] if before_obs else "unknown"
        final_action = action.model_copy(deep=True)
        used_vision = False
        selected_candidate = None
        recovered_candidate: PerceptionCandidate | None = None
        perception_route = "NONE"

        # 1. Primary Perception Pipeline: DOM -> Moondream (Primary) -> Gemini (Fallback)
        router = self._router or (
            self._grounder if isinstance(self._grounder, PerceptionRouter) else None
        )

        # Resolve DOM candidates first
        try:
            dom_candidates = await self._interactor.resolve_candidates(target)
        except Exception as e:
            logger.warning("dom_resolution_failed", error=str(e))
            dom_candidates = []

        # Get screenshot bytes for vision models (P1.2 Deduplication)
        screenshot_bytes = b""
        if before_screenshot_path:
            try:
                with open(before_screenshot_path, "rb") as f:
                    screenshot_bytes = f.read()
            except Exception as e:
                logger.warning("failed_to_read_cached_screenshot", error=str(e))
        
        if not screenshot_bytes:
            try:
                screenshot_bytes = await page.screenshot(type="png")
            except Exception as e:
                logger.error("vision_screenshot_failed", error=str(e))

        # Check learned recovery before visual fallback
        if not dom_candidates and not selected_candidate and self._learning:
            recovery = await self._learning.get_valid_recovery(target, fingerprint)
            if recovery and recovery.successful_locator:
                try:
                    cands = await self._interactor.resolve_candidates(recovery.successful_locator)
                    if any(c.is_visible for c in cands):
                        selected_candidate = PerceptionCandidate(
                            source="learned",
                            confidence=recovery.confidence,
                            target_description=target,
                            locator_str=recovery.successful_locator,
                            is_visible=True,
                            is_enabled=True,
                        )
                        perception_route = "LEARNED"
                        self._apply_candidate_to_action(final_action, selected_candidate)
                        logger.info("using_learned_recovery", target=target, recovery_id=recovery.id)
                except Exception:
                    pass

        if not selected_candidate and router:
            try:
                route_result = await router.route(
                    target=target,
                    screenshot_bytes=screenshot_bytes,
                    dom_candidates=dom_candidates,
                    page=page,
                )
            except GroundingFailure as e:
                logger.error("grounding_failure", error=str(e))
                return ActionResult(
                    success=False,
                    action=action,
                    error=f"Visual grounding failed critically: {e}",
                    error_type="GroundingFailure",
                )

            perception_route = route_result.route
            if route_result.success and route_result.candidate is not None:
                selected_candidate = route_result.candidate
                self._apply_candidate_to_action(final_action, selected_candidate)
                used_vision = perception_route not in ("DOM", "DOM_DISAMBIGUATED")
                logger.info(
                    "perception_routing_complete",
                    target=target,
                    route=perception_route,
                    confidence=route_result.confidence,
                    verified=route_result.verified,
                )
        else:
            # Fallback legacy routing if router not initialized
            if len(dom_candidates) == 1:
                selected_candidate = dom_candidates[0]
                perception_route = "DOM"
                self._apply_candidate_to_action(final_action, selected_candidate)
                logger.info("single_dom_candidate_found", target=target)
            elif len(dom_candidates) > 1:
                selected_candidate = self._disambiguate_candidates(dom_candidates, target)
                if selected_candidate:
                    perception_route = "DOM_DISAMBIGUATED"
                    self._apply_candidate_to_action(final_action, selected_candidate)
                    logger.info("disambiguated_dom_candidate", target=target)

            if not selected_candidate and screenshot_bytes:
                logger.info("invoking_visual_grounding", target=target)
                used_vision = True
                try:
                    v_cand = await self._grounder.ground_element(
                        screenshot_bytes=screenshot_bytes,
                        target_description=target,
                        page=page,
                    )
                    if v_cand:
                        selected_candidate = v_cand
                        perception_route = "MOONDREAM"
                        self._apply_candidate_to_action(final_action, selected_candidate)
                        logger.info(
                            "visual_candidate_found",
                            target=target,
                            conf=v_cand.confidence,
                        )
                except GroundingFailure as e:
                    logger.error("grounding_failure", error=str(e))
                    return ActionResult(
                        success=False,
                        action=action,
                        error=f"Visual grounding failed critically: {e}",
                        error_type="GroundingFailure",
                    )

        # 2. Recovery Fallback: Check Learning Service only if DOM + Vision failed
        if not selected_candidate and self._learning:
            fingerprint = before_obs.url.split("?")[0] if before_obs else "unknown"
            recovery = await self._learning.get_valid_recovery(target, fingerprint)
            if recovery:
                logger.info("using_learned_recovery_fallback", target=target, recovery_id=recovery.id)
                recovered_candidate = PerceptionCandidate(
                    source="learned",
                    confidence=recovery.confidence,
                    target_description=target,
                    locator_str=recovery.successful_locator,
                    is_visible=True,
                    is_enabled=True,
                )
                if recovered_candidate.locator_str:
                    try:
                        cands = await self._interactor.resolve_candidates(
                            recovered_candidate.locator_str
                        )
                        if any(c.is_visible for c in cands):
                            selected_candidate = recovered_candidate
                            perception_route = "LEARNED"
                            self._apply_candidate_to_action(final_action, selected_candidate)
                    except Exception:
                        pass

        if not selected_candidate:
            logger.error("perception_failed_all_tiers", target=target)
            return ActionResult(
                success=False,
                action=action,
                error=f"Perception failed to locate target '{target}'",
                error_type="PerceptionFailure",
            )

        # A coordinate identifies a point to click, not an option inside a
        # native/select control.  Never pretend that a visual click selected a
        # value; require a deterministic locator for SELECT actions.
        if (
            ActionType(action.action_type) == ActionType.SELECT
            and not selected_candidate.locator_str
        ):
            logger.error("select_requires_dom_locator", target=target)
            return ActionResult(
                success=False,
                action=action,
                error=f"Select target '{target}' was only visually grounded; a DOM locator is required",
                error_type="PerceptionFailure",
            )

        # 4. Execute the action
        exec_result = await self._executor.execute(final_action)

        # Selecting the value already present is a valid human no-op.  The
        # final value assertion will verify the business state; behavioral
        # verification must not require a visual change for this case.
        if final_action.metadata.get("no_op"):
            exec_result.details["no_op"] = True
            exec_result.details["perception_verification_skipped"] = True
            return exec_result

        # Dynamic Escalation: If DOM execution failed, immediately escalate to Moondream Visual Grounding
        if not exec_result.success and perception_route in ("DOM", "DOM_DISAMBIGUATED", "NONE"):
            logger.warning(
                "dom_execution_failed_escalating_to_vision",
                target=target,
                error=exec_result.error,
                attempted_locator=final_action.target,
            )
            # Re-capture screenshot and invoke Moondream visual grounding
            screenshot_bytes = b""
            try:
                screenshot_bytes = await page.screenshot(type="png")
            except Exception:
                pass

            if screenshot_bytes:
                try:
                    if router:
                        # Call router with empty dom_candidates to trigger the vision tier
                        route_result = await router.route(
                            target=target,
                            screenshot_bytes=screenshot_bytes,
                            dom_candidates=[],
                            page=page,
                        )
                        if route_result.success and route_result.candidate:
                            selected_candidate = route_result.candidate
                            perception_route = route_result.route
                            used_vision = True
                            final_action = action.model_copy(deep=True)
                            self._apply_candidate_to_action(final_action, selected_candidate)
                            exec_result = await self._executor.execute(final_action)
                    elif self._grounder:
                        v_cand = await self._grounder.ground_element(
                            screenshot_bytes=screenshot_bytes,
                            target_description=target,
                            page=page,
                        )
                        if v_cand:
                            selected_candidate = v_cand
                            perception_route = "MOONDREAM"
                            used_vision = True
                            final_action = action.model_copy(deep=True)
                            self._apply_candidate_to_action(final_action, selected_candidate)
                            exec_result = await self._executor.execute(final_action)
                except Exception as e:
                    logger.error("vision_escalation_failed", target=target, error=str(e))

        if not exec_result.success:
            return exec_result

        # 5. Level 3: Behavioral Verification
        if self._verifier and perception_route != "NONE":
            after_screenshot_path = None
            try:
                after_screenshot_path = await self._browser.take_screenshot("after_perception")
            except Exception as e:
                logger.warning("after_screenshot_failed", error=str(e))

            try:
                after_obs = await self._observer.observe(page)
            except Exception:
                after_obs = None
            after_state_summary = (
                after_obs.model_dump_json(exclude={"buttons", "tabs"})
                if after_obs
                else "Unknown"
            )

            # Compute DOM diff for richer verification context
            dom_diff_summary = ""
            after_fingerprint = (
                PageStateFingerprint.from_observation(after_obs) if after_obs else None
            )
            if before_fingerprint and after_fingerprint:
                diff = before_fingerprint.diff(after_fingerprint)
                dom_diff_summary = diff.to_summary()

            # Console errors that occurred during the action
            console_errors_during: list[str] = []
            if after_obs:
                console_errors_during = after_obs.console_errors

            verification = await self._verifier.verify_action(
                action_description=f"{action.action_type} on '{target}'",
                expected_outcome="Interaction successful, page navigated or state changed",
                before_state_summary=before_state_summary,
                after_state_summary=after_state_summary,
                before_screenshot_path=before_screenshot_path,
                after_screenshot_path=after_screenshot_path,
                dom_diff_summary=dom_diff_summary,
                console_errors=console_errors_during,
            )

            if verification.is_verified:
                logger.info(
                    "behavioral_verification_passed",
                    target=target,
                    perception_route=perception_route,
                    dom_diff=dom_diff_summary[:100] if dom_diff_summary else "none",
                )
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
                    perception_route=perception_route,
                    reasoning=verification.reasoning,
                    console_errors=len(console_errors_during),
                )
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

        if selected_candidate:
            exec_result.details["perception"] = {
                "route": perception_route,
                "confidence": selected_candidate.confidence,
                "target": target,
                "bounding_box": selected_candidate.bounding_box.model_dump() if selected_candidate.bounding_box else None,
                "locator": selected_candidate.locator_str,
                "before_screenshot": before_screenshot_path,
                "after_screenshot": after_screenshot_path if "after_screenshot_path" in locals() else None,
            }

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
            action.metadata["resolved_locator"] = candidate.locator_str
        elif candidate.bounding_box:
            action.metadata["is_coordinate"] = True
            action.metadata["x"] = candidate.bounding_box.center_x
            action.metadata["y"] = candidate.bounding_box.center_y
