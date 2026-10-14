"""Perception Router — confidence-driven DOM → Moondream → Gemini routing.

Implements the core perception decision logic:
1. DOM reliable? → use directly (no vision call)
2. Moondream PRIMARY → check confidence
   - >= HIGH → execute
   - MEDIUM-HIGH → Gemini verification
   - < MEDIUM → Gemini fallback
3. Gemini FALLBACK → last resort

Logs perception_route at every decision for full traceability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.core.logging import get_logger
from agent.perception.backends import GrounderBackend
from agent.perception.models import GroundingFailure, PerceptionCandidate

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)


class PerceptionRouter(GrounderBackend):
    """Routes perception through DOM → Moondream → Gemini with confidence.

    This replaces the simple primary/fallback router from backends.py with
    a confidence-aware routing layer that minimizes vision calls and
    maximizes reliability.
    """

    # Confidence thresholds (configurable via constructor)
    CONFIDENCE_HIGH = 0.85
    CONFIDENCE_MEDIUM = 0.60

    def __init__(
        self,
        primary: GrounderBackend,
        fallback: GrounderBackend | None = None,
        confidence_high: float = 0.85,
        confidence_medium: float = 0.60,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.CONFIDENCE_HIGH = confidence_high
        self.CONFIDENCE_MEDIUM = confidence_medium

    async def ground_element(
        self,
        screenshot_bytes: bytes,
        target_description: str,
        threshold: float = 0.8,
        frame_context: str | None = None,
        page: Page | None = None,
    ) -> PerceptionCandidate | None:
        """Ground an element using the full perception routing flow."""
        res = await self.route(
            target=target_description,
            screenshot_bytes=screenshot_bytes,
            dom_candidates=[],
            page=page,
            threshold=threshold,
            frame_context=frame_context,
        )
        return res.candidate

    async def _verify_candidate_executable(
        self, candidate: PerceptionCandidate, page: Page | None
    ) -> bool:
        """Verify that a DOM candidate can genuinely be located on the live page."""
        if not candidate.is_visible or not candidate.is_enabled:
            return False

        if not candidate.bounding_box or candidate.bounding_box.width <= 0 or candidate.bounding_box.height <= 0:
            return False

        if not page or not candidate.locator_str:
            return True

        try:
            loc_str = candidate.locator_str
            if loc_str.startswith("role:"):
                parts = loc_str.split(":", 2)
                role = parts[1] if len(parts) > 1 else "button"
                name = parts[2] if len(parts) > 2 else ""
                loc = page.get_by_role(role, name=name) if name else page.get_by_role(role)  # type: ignore[arg-type]
            elif loc_str.startswith("label:"):
                loc = page.get_by_label(loc_str[6:].strip())
            elif loc_str.startswith("text:"):
                loc = page.get_by_text(loc_str[5:].strip(), exact=False)
            elif loc_str.startswith("placeholder:"):
                loc = page.get_by_placeholder(loc_str[12:].strip())
            elif loc_str.startswith("title:"):
                loc = page.get_by_title(loc_str[6:].strip(), exact=False)
            else:
                loc = page.locator(loc_str)

            count = await loc.count()
            if count > 0:
                return await loc.first.is_visible()
        except Exception:
            return False

        return False

    async def route(
        self,
        target: str,
        screenshot_bytes: bytes,
        dom_candidates: list[PerceptionCandidate],
        page: Page | None = None,
        threshold: float = 0.8,
        frame_context: str | None = None,
    ) -> PerceptionRouteResult:
        """Route perception through the decision matrix.

        Args:
            target: Natural language description of the target element.
            screenshot_bytes: PNG screenshot bytes.
            dom_candidates: Pre-resolved DOM candidates from PageInteractor.
            page: Playwright Page (required for Gemini Set-of-Mark).
            threshold: Confidence threshold for grounding.
            frame_context: Optional frame identifier.

        Returns:
            PerceptionRouteResult with the selected candidate and routing info.
        """
        # Level 1: DOM — single reliable, verified match
        valid_dom = [
            c for c in dom_candidates
            if c.is_visible and c.is_enabled and c.bounding_box and c.bounding_box.width > 0 and c.bounding_box.height > 0
        ]

        if len(valid_dom) == 1:
            candidate = valid_dom[0]
            is_exec = await self._verify_candidate_executable(candidate, page)
            if is_exec:
                logger.info(
                    "perception_route",
                    route="DOM",
                    target=target,
                    confidence=candidate.confidence,
                )
                return PerceptionRouteResult(
                    candidate=candidate,
                    route="DOM",
                    confidence=candidate.confidence or 1.0,
                    verified=True,
                )
            logger.info("dom_candidate_unverified_escalating", target=target, locator=candidate.locator_str)

        # Level 1b: DOM — disambiguated single match
        if len(valid_dom) > 1:
            best = self._disambiguate_dom(valid_dom, target)
            if best:
                is_exec = await self._verify_candidate_executable(best, page)
                if is_exec:
                    logger.info(
                        "perception_route",
                        route="DOM_DISAMBIGUATED",
                        target=target,
                        confidence=best.confidence,
                    )
                    return PerceptionRouteResult(
                        candidate=best,
                        route="DOM_DISAMBIGUATED",
                        confidence=best.confidence or 0.9,
                        verified=True,
                    )
                logger.info("dom_disambiguated_unverified_escalating", target=target, locator=best.locator_str)

        # Level 2: Moondream PRIMARY
        logger.info(
            "perception_started",
            provider="moondream",
            target=target,
            reason="dom_insufficient" if dom_candidates else "dom_empty",
        )

        moondream_candidate = None
        try:
            moondream_candidate = await self.primary.ground_element(
                screenshot_bytes=screenshot_bytes,
                target_description=target,
                threshold=threshold,
                frame_context=frame_context,
                page=page,
            )
        except GroundingFailure as e:
            logger.warning(
                "moondream_grounding_failed",
                target=target,
                error=str(e),
            )
            if not self.fallback:
                raise
        except Exception as e:
            logger.warning(
                "moondream_unexpected_error",
                target=target,
                error=str(e),
            )
            if not self.fallback:
                raise GroundingFailure(f"Visual grounding failed critically: {e}") from e

        if moondream_candidate:
            confidence = moondream_candidate.confidence or 0.0
            logger.info(
                "perception_completed",
                provider="moondream",
                target=target,
                confidence=confidence,
                success=True,
            )

            # High confidence → execute directly
            if confidence >= self.CONFIDENCE_HIGH:
                logger.info(
                    "perception_route",
                    route="MOONDREAM",
                    target=target,
                    confidence=confidence,
                    decision="high_confidence_execute",
                )
                return PerceptionRouteResult(
                    candidate=moondream_candidate,
                    route="MOONDREAM",
                    confidence=confidence,
                    verified=True,
                )

            # Medium confidence → Gemini verification
            if confidence >= self.CONFIDENCE_MEDIUM and self.fallback:
                logger.info(
                    "gemini_verification_triggered",
                    target=target,
                    moondream_confidence=confidence,
                    reason="moondream_confidence_below_high_threshold",
                )
                gemini_candidate = await self._try_gemini(
                    target, screenshot_bytes, threshold, frame_context, page
                )

                if gemini_candidate:
                    # If Gemini agrees (similar location), boost confidence
                    if self._candidates_agree(moondream_candidate, gemini_candidate):
                        logger.info(
                            "perception_route",
                            route="MOONDREAM_GEMINI_VERIFIED",
                            target=target,
                            confidence=max(confidence, 0.90),
                        )
                        moondream_candidate.confidence = max(confidence, 0.90)
                        return PerceptionRouteResult(
                            candidate=moondream_candidate,
                            route="MOONDREAM_GEMINI_VERIFIED",
                            confidence=max(confidence, 0.90),
                            verified=True,
                        )
                    else:
                        # Gemini disagrees — use Gemini result
                        logger.warning(
                            "perception_route",
                            route="GEMINI_OVERRIDE",
                            target=target,
                            moondream_confidence=confidence,
                            gemini_confidence=gemini_candidate.confidence,
                        )
                        return PerceptionRouteResult(
                            candidate=gemini_candidate,
                            route="GEMINI_OVERRIDE",
                            confidence=gemini_candidate.confidence or 0.85,
                            verified=True,
                        )

                # Gemini unavailable — use Moondream anyway at medium conf
                return PerceptionRouteResult(
                    candidate=moondream_candidate,
                    route="MOONDREAM",
                    confidence=confidence,
                    verified=False,
                )

            # Low confidence → Gemini fallback
            if self.fallback:
                logger.info(
                    "gemini_fallback_triggered",
                    target=target,
                    moondream_confidence=confidence,
                    reason="moondream_confidence_below_medium_threshold",
                )
                gemini_candidate = await self._try_gemini(
                    target, screenshot_bytes, threshold, frame_context, page
                )
                if gemini_candidate:
                    logger.info(
                        "perception_route",
                        route="GEMINI_FALLBACK",
                        target=target,
                        confidence=gemini_candidate.confidence,
                    )
                    return PerceptionRouteResult(
                        candidate=gemini_candidate,
                        route="GEMINI_FALLBACK",
                        confidence=gemini_candidate.confidence or 0.85,
                        verified=True,
                    )

            # Use Moondream low-conf as last resort
            return PerceptionRouteResult(
                candidate=moondream_candidate,
                route="MOONDREAM_LOW_CONFIDENCE",
                confidence=confidence,
                verified=False,
            )

        # Level 3: Gemini FALLBACK (Moondream returned nothing)
        if self.fallback:
            logger.info(
                "gemini_fallback_triggered",
                target=target,
                reason="moondream_returned_no_candidate",
            )
            gemini_candidate = await self._try_gemini(
                target, screenshot_bytes, threshold, frame_context, page
            )
            if gemini_candidate:
                logger.info(
                    "perception_route",
                    route="GEMINI_FALLBACK",
                    target=target,
                    confidence=gemini_candidate.confidence,
                )
                return PerceptionRouteResult(
                    candidate=gemini_candidate,
                    route="GEMINI_FALLBACK",
                    confidence=gemini_candidate.confidence or 0.85,
                    verified=True,
                )

        # All perception tiers failed
        logger.error("perception_all_tiers_failed", target=target)
        return PerceptionRouteResult(
            candidate=None,
            route="FAILED",
            confidence=0.0,
            verified=False,
        )

    async def _try_gemini(
        self,
        target: str,
        screenshot_bytes: bytes,
        threshold: float,
        frame_context: str | None,
        page: Page | None,
    ) -> PerceptionCandidate | None:
        """Attempt Gemini grounding with error handling."""
        if not self.fallback:
            return None
        try:
            result = await self.fallback.ground_element(
                screenshot_bytes=screenshot_bytes,
                target_description=target,
                threshold=threshold,
                frame_context=frame_context,
                page=page,
            )
            if result:
                logger.info(
                    "gemini_fallback_completed",
                    target=target,
                    confidence=result.confidence,
                    success=True,
                )
            return result
        except GroundingFailure as e:
            logger.warning("gemini_grounding_failed", target=target, error=str(e))
            return None
        except Exception as e:
            logger.warning("gemini_unexpected_error", target=target, error=str(e))
            return None

    def _disambiguate_dom(
        self,
        candidates: list[PerceptionCandidate],
        target: str,
    ) -> PerceptionCandidate | None:
        """Apply deterministic rules to disambiguate multiple DOM candidates."""
        target_lower = target.lower().strip().lstrip("#")

        # 1. Exact ID match (e.g. #sysverb_update when target is sysverb_update)
        exact_id = [
            c for c in candidates
            if c.locator_str and (
                c.locator_str.lstrip("#").lower() == target_lower
                or c.locator_str.lower() == target.lower()
            )
        ]
        if len(exact_id) == 1:
            return exact_id[0]
        elif len(exact_id) > 1:
            return min(exact_id, key=lambda c: c.bounding_box.y if c.bounding_box else 99999)

        # 2. Prefer exact label match (e.g. "Update" vs "Update with Lens")
        exact_label = [c for c in candidates if (c.label or "").lower().strip() == target_lower]
        if len(exact_label) == 1:
            return exact_label[0]
        elif len(exact_label) > 1:
            return min(exact_label, key=lambda c: c.bounding_box.y if c.bounding_box else 99999)

        # 3. Prefer main frame
        main_frame = [
            c
            for c in candidates
            if c.frame_context == "main" or "gsft_main" in (c.frame_context or "")
        ]
        if len(main_frame) == 1:
            return main_frame[0]

        # 4. If all candidates are identical except position, pick topmost visible
        if candidates and all(c.label == candidates[0].label for c in candidates):
            return min(candidates, key=lambda c: c.bounding_box.y if c.bounding_box else 99999)

        return None

    def _candidates_agree(
        self,
        a: PerceptionCandidate,
        b: PerceptionCandidate,
        tolerance: int = 50,
    ) -> bool:
        """Check if two candidates refer to approximately the same element."""
        if a.bounding_box and b.bounding_box:
            return (
                abs(a.bounding_box.center_x - b.bounding_box.center_x) < tolerance
                and abs(a.bounding_box.center_y - b.bounding_box.center_y) < tolerance
            )
        # If one has a locator and the other a bounding box, can't compare meaningfully
        return False


class PerceptionRouteResult:
    """Result of perception routing."""

    def __init__(
        self,
        candidate: PerceptionCandidate | None,
        route: str,
        confidence: float,
        verified: bool,
    ) -> None:
        self.candidate = candidate
        self.route = route
        self.confidence = confidence
        self.verified = verified

    @property
    def success(self) -> bool:
        return self.candidate is not None
