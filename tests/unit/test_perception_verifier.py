from unittest.mock import AsyncMock

import pytest

from agent.perception.verifier import LLMBehavioralVerifier
from agent.planner.llm_client import OpenAILLMClient


@pytest.mark.asyncio
async def test_llm_behavioral_verifier_success():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    # The LLM returns a JSON dictionary now
    mock_llm.complete_json.return_value = {
        "is_verified": True,
        "confidence": 0.95,
        "reasoning": "Looks good",
    }

    verifier = LLMBehavioralVerifier(llm_client=mock_llm)
    result = await verifier.verify_action(
        action_description="Click Submit",
        expected_outcome="Success message appears",
        before_state_summary="{}",
        after_state_summary="{}",
    )

    assert result.is_verified is True
    assert result.confidence == 0.95
    assert result.reasoning == "Looks good"


@pytest.mark.asyncio
async def test_llm_behavioral_verifier_failure():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {
        "is_verified": False,
        "confidence": 0.8,
        "reasoning": "Still on same page",
    }

    verifier = LLMBehavioralVerifier(llm_client=mock_llm)
    result = await verifier.verify_action(
        action_description="Click Submit",
        expected_outcome="Success message appears",
        before_state_summary="{}",
        after_state_summary="{}",
    )

    assert result.is_verified is False
    assert result.confidence == 0.8
    assert result.reasoning == "Still on same page"


@pytest.mark.asyncio
async def test_visual_finding_unavailable_without_evidence():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    # The LLM attempts to return a visual finding, but we didn't provide visual evidence.
    mock_llm.complete_json.return_value = {
        "is_verified": False,
        "confidence": 0.5,
        "reasoning": "Looks misaligned",
        "finding_type": "visual",
        "finding_description": "Button is shifted",
    }

    verifier = LLMBehavioralVerifier(llm_client=mock_llm)
    # Missing screenshot inputs
    result = await verifier.verify_action(
        action_description="Click",
        expected_outcome="Click success",
        before_state_summary="State A",
        after_state_summary="State B",
    )

    assert result.is_verified is False
    assert result.finding_type == "functional"
    assert "[REJECTED VISUAL: No evidence]" in str(result.finding_description)


@pytest.mark.asyncio
async def test_visual_finding_with_actual_evidence():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {
        "is_verified": False,
        "confidence": 0.8,
        "reasoning": "Button overlap",
        "finding_type": "visual",
        "finding_description": "Button is shifted",
    }

    verifier = LLMBehavioralVerifier(llm_client=mock_llm)
    result = await verifier.verify_action(
        action_description="Click",
        expected_outcome="Click success",
        before_state_summary="State A",
        after_state_summary="State B",
        after_screenshot_path="/tmp/after.png",
    )

    assert result.is_verified is False
    assert result.finding_type == "visual"
    assert result.evidence_reference == "/tmp/after.png"
