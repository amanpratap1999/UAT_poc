"""Unit tests for Intent Manager (Deliverable 1)."""

from __future__ import annotations

import pytest

from agent.domain.intent import StructuredIntent
from agent.intent.manager import IntentManager
from tests.conftest import MockLLMClient


@pytest.mark.asyncio
async def test_intent_manager_parse_rule_fallback() -> None:
    """Test heuristic parsing when no LLM is provided."""
    manager = IntentManager(llm_client=None)
    intent = await manager.parse_intent("Check whether incidents can be created and resolved.")

    assert isinstance(intent, StructuredIntent)
    assert intent.target_module == "incident"
    assert intent.confidence >= 0.90


@pytest.mark.asyncio
async def test_intent_manager_parse_llm() -> None:
    """Test LLM-based intent parsing."""
    client = MockLLMClient(
        responses=[
            {
                "intent_type": "IncidentValidation",
                "goal": "Validate incident resolution workflow",
                "target_module": "incident",
                "priority": "High",
                "confidence": 0.97,
                "is_ambiguous": False,
            }
        ]
    )
    manager = IntentManager(llm_client=client)
    intent = await manager.parse_intent("Verify resolve incident functionality")

    assert intent.intent_type == "IncidentValidation"
    assert intent.goal == "Validate incident resolution workflow"
    assert intent.priority == "High"
    assert intent.confidence == 0.97


@pytest.mark.asyncio
async def test_intent_manager_parse_general_ui() -> None:
    """Test heuristic parsing for general UI / login goals."""
    manager = IntentManager(llm_client=None)
    intent = await manager.parse_intent("Click the 'Show Password' icon on the ServiceNow login page")

    assert intent.target_module in ("auth", "general")
    assert intent.intent_type == "GeneralValidation"
