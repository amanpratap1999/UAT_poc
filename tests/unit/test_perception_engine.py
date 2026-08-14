from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.types import ActionType
from agent.domain.actions import ActionResult, AgentAction
from agent.perception.engine import PerceptionDecisionEngine
from agent.perception.models import GroundingFailure, PerceptionCandidate
from agent.perception.verifier import VerificationResult


@pytest.mark.asyncio
async def test_perception_engine_single_dom_match():
    # Setup mocks
    browser = AsyncMock()
    interactor = AsyncMock()
    executor = AsyncMock()
    grounder = AsyncMock()
    verifier = AsyncMock()
    learning = AsyncMock()
    observer = AsyncMock()

    # Observation setup
    obs = MagicMock()
    obs.url = "http://example.com"
    obs.model_dump_json.return_value = "{}"
    observer.observe.return_value = obs

    # Learning service returns None
    learning.get_valid_recovery.return_value = None

    # Interactor finds 1 candidate
    cand = PerceptionCandidate(
        source="dom",
        target_description="btn",
        locator_str="btn >> nth=0",
        is_visible=True,
        is_enabled=True,
        confidence=1.0,
    )
    interactor.resolve_candidates.return_value = [cand]

    # Executor succeeds
    exec_result = ActionResult(
        success=True, action=AgentAction(action_type=ActionType.CLICK.value, target="btn >> nth=0")
    )
    executor.execute.return_value = exec_result

    engine = PerceptionDecisionEngine(
        browser, interactor, executor, grounder, verifier, learning, observer
    )

    action = AgentAction(action_type=ActionType.CLICK.value, target="btn")
    result = await engine.execute_with_perception(action)

    # Assert execution was successful and used precise locator
    assert result.success is True
    # Verify vision was not called
    grounder.ground_element.assert_not_called()
    # Verify behavioral verifier was not called (since we didn't use vision or recovered)
    verifier.verify_action.assert_not_called()


@pytest.mark.asyncio
async def test_perception_engine_zero_matches_visual_fallback():
    # Setup mocks
    browser = AsyncMock()
    browser.take_screenshot.return_value = "screenshot.png"
    page_mock = AsyncMock()
    page_mock.screenshot = AsyncMock(return_value=b"bytes")
    browser.get_page = MagicMock(return_value=page_mock)

    interactor = AsyncMock()
    executor = AsyncMock()
    grounder = AsyncMock()
    verifier = AsyncMock()
    learning = AsyncMock()
    observer = AsyncMock()

    # Observation setup
    obs = MagicMock()
    obs.url = "http://example.com"
    obs.model_dump_json.return_value = "{}"
    observer.observe.return_value = obs

    learning.get_valid_recovery.return_value = None

    # Interactor finds 0 candidates
    interactor.resolve_candidates.return_value = []

    # Grounder finds candidate
    from agent.perception.models import BoundingBox

    cand = PerceptionCandidate(
        source="vision",
        target_description="btn",
        confidence=0.9,
        bounding_box=BoundingBox(x=10, y=10, width=10, height=10),
    )
    grounder.ground_element.return_value = cand

    # Executor succeeds
    exec_result = ActionResult(
        success=True, action=AgentAction(action_type=ActionType.CLICK.value, target="btn")
    )
    executor.execute.return_value = exec_result

    # Verifier succeeds
    verifier.verify_action.return_value = VerificationResult(
        is_verified=True, confidence=0.9, reasoning="ok"
    )

    engine = PerceptionDecisionEngine(
        browser, interactor, executor, grounder, verifier, learning, observer
    )

    action = AgentAction(action_type=ActionType.CLICK.value, target="btn")
    result = await engine.execute_with_perception(action)

    assert result.success is True
    grounder.ground_element.assert_called_once()
    verifier.verify_action.assert_called_once()
    learning.record_recovery_outcome.assert_called_once()

@pytest.mark.asyncio
async def test_perception_engine_grounding_failure():
    # Setup mocks
    browser = AsyncMock()
    browser.take_screenshot.return_value = "screenshot.png"
    page_mock = AsyncMock()
    page_mock.screenshot = AsyncMock(return_value=b"bytes")
    browser.get_page = MagicMock(return_value=page_mock)

    interactor = AsyncMock()
    executor = AsyncMock()
    grounder = AsyncMock()
    verifier = AsyncMock()
    learning = AsyncMock()
    observer = AsyncMock()

    obs = MagicMock()
    obs.url = "http://example.com"
    obs.model_dump_json.return_value = "{}"
    observer.observe.return_value = obs

    learning.get_valid_recovery.return_value = None

    # Interactor finds 0 candidates
    interactor.resolve_candidates.return_value = []

    # Grounder raises GroundingFailure
    grounder.ground_element.side_effect = GroundingFailure("API Timeout")

    engine = PerceptionDecisionEngine(
        browser, interactor, executor, grounder, verifier, learning, observer
    )

    action = AgentAction(action_type=ActionType.CLICK.value, target="btn")
    result = await engine.execute_with_perception(action)

    assert result.success is False
    assert result.error_type == "GroundingFailure"
    assert "Visual grounding failed critically" in result.error
