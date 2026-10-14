"""End-to-End test for the Operational Learning loop (Phase 4).

Proves that:
1. Run 1 records a verified visual recovery when DOM fails.
2. Run 2 fetches the persisted recovery.
3. Run 2 successfully reuses and revalidates the recovery without invoking visual grounder again.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.learning.service import LearningService
from agent.learning.store import LearningStore
from agent.learning.types import LearnedRecovery
from agent.perception.engine import PerceptionDecisionEngine
from agent.perception.models import PerceptionCandidate
from agent.perception.verifier import VerificationResult


class FakeLearningStore(LearningStore):
    """In-memory fake store for learning records to bypass Postgres during testing."""

    def __init__(self) -> None:
        self.recoveries: dict[str, LearnedRecovery] = {}

    async def get_recovery(
        self, page_fingerprint: str, target_description: str
    ) -> LearnedRecovery | None:
        for r in self.recoveries.values():
            if (
                r.page_fingerprint == page_fingerprint
                and r.target_description == target_description
            ):
                return r
        return None

    async def save_recovery(self, recovery: LearnedRecovery) -> None:
        self.recoveries[recovery.id] = recovery

    async def delete_recovery(self, recovery_id: str) -> None:
        self.recoveries.pop(recovery_id, None)


@pytest.mark.asyncio
async def test_learning_loop_end_to_end() -> None:
    # 1. Setup Shared Infrastructure
    fake_store = FakeLearningStore()
    learning_service = LearningService(store=fake_store)

    # Setup Mocks
    browser = AsyncMock()
    browser.take_screenshot.return_value = "screenshot.png"
    page_mock = AsyncMock()
    page_mock.screenshot = AsyncMock(return_value=b"bytes")
    browser.get_page = MagicMock(return_value=page_mock)

    observer = AsyncMock()
    obs = MagicMock()
    obs.url = "http://test.service-now.com"
    obs.model_dump_json.return_value = "{}"
    observer.observe.return_value = obs

    executor = AsyncMock()
    exec_result = ActionResult(
        success=True, action=AgentAction(action_type=ActionType.CLICK, target="btn")
    )
    executor.execute.return_value = exec_result

    # ---------------------------------------------------------
    # RUN 1: Visual Fallback + Persistence
    # ---------------------------------------------------------
    interactor_run1 = AsyncMock()
    interactor_run1.resolve_candidates.return_value = []  # DOM fails

    grounder_run1 = AsyncMock()
    from agent.perception.models import BoundingBox

    cand = PerceptionCandidate(
        source="vision",
        target_description="btn",
        confidence=0.9,
        bounding_box=BoundingBox(x=10, y=10, width=10, height=10),
    )
    cand.locator_str = "vision_recovered_btn"
    grounder_run1.ground_element.return_value = cand

    verifier_run1 = AsyncMock()
    verifier_run1.verify_action.return_value = VerificationResult(
        is_verified=True, confidence=0.9, reasoning="Visual click worked"
    )

    engine_run1 = PerceptionDecisionEngine(
        browser, interactor_run1, executor, grounder_run1, verifier_run1, learning_service, observer
    )

    action1 = AgentAction(action_type=ActionType.CLICK, target="btn")
    result1 = await engine_run1.execute_with_perception(action1)

    assert result1.success is True, "Run 1 execution should succeed"
    grounder_run1.ground_element.assert_called_once()
    verifier_run1.verify_action.assert_called_once()

    # Verify learning persisted
    saved_recovery = await fake_store.get_recovery("http://test.service-now.com", "btn")
    assert saved_recovery is not None, "Recovery must be persisted to the store"
    assert saved_recovery.successful_locator == "vision_recovered_btn", (
        "Must save the successful locator"
    )
    original_confidence = saved_recovery.confidence

    # ---------------------------------------------------------
    # RUN 2: Experience Retrieval + Reuse
    interactor_run2 = AsyncMock()

    async def mock_resolve_run2(locator: str) -> list[PerceptionCandidate]:
        if locator == "vision_recovered_btn":
            return [
                PerceptionCandidate(
                    source="dom",
                    target_description="btn",
                    locator_str=locator,
                    is_visible=True,
                    is_enabled=True,
                    confidence=1.0,
                )
            ]
        return []

    interactor_run2.resolve_candidates.side_effect = mock_resolve_run2

    grounder_run2 = AsyncMock()
    verifier_run2 = AsyncMock()
    verifier_run2.verify_action.return_value = VerificationResult(
        is_verified=True, confidence=0.95, reasoning="Recovered click worked"
    )

    engine_run2 = PerceptionDecisionEngine(
        browser, interactor_run2, executor, grounder_run2, verifier_run2, learning_service, observer
    )

    action2 = AgentAction(action_type=ActionType.CLICK, target="btn")
    result2 = await engine_run2.execute_with_perception(action2)

    assert result2.success is True, "Run 2 execution should succeed"

    # Prove that Grounder (visual fallback) was skipped because of learning!
    grounder_run2.ground_element.assert_not_called()

    # Prove that the verifier was still called to validate the recovered action
    # (Safety/Revalidation)
    verifier_run2.verify_action.assert_called_once()

    # Prove that confidence increased
    updated_recovery = await fake_store.get_recovery("http://test.service-now.com", "btn")
    assert updated_recovery is not None
    assert updated_recovery.verification_count == 2, "Verification count should increment"
    assert updated_recovery.confidence > original_confidence, (
        "Confidence should increase on repeated success"
    )
