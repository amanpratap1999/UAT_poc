"""Tests for Scenario Generator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.domain.knowledge_model import CustomerKnowledgeModel, FieldMetadata, TableMetadata
from agent.planner.llm_client import OpenAILLMClient
from agent.testing.generator import ScenarioGenerator
from agent.testing.strategy_selector import StrategySelector


@pytest.mark.asyncio
async def test_generate_scenarios():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    # The LLM returns a JSON dictionary according to complete_json
    mock_llm.complete_json.return_value = {
        "scenarios": [
            {
                "id": "test-1",
                "title": "Nominal Path",
                "description": "Submit a valid form",
                "steps": ["Fill form", "Click Submit"],
                "expected_outcome": "Form submitted",
                "is_exploratory": False,
                "risk_score": 2,
                "strategies_applied": ["[Boundary Value Analysis for 'amount' (numeric field)]"],
            },
            {
                "id": "test-2",
                "title": "Exploratory Path",
                "description": "Submit form twice rapidly",
                "steps": ["Fill form", "Click Submit", "Click Submit again"],
                "expected_outcome": "Second click is ignored or shows duplicate error",
                "is_exploratory": True,
                "risk_score": 6,
                "strategies_applied": [],
            },
        ],
        "reasoning": "Standard testing followed by a concurrency check.",
    }

    mock_selector = MagicMock(spec=StrategySelector)
    mock_selector.select_strategies.return_value = [
        "[Boundary Value Analysis for 'amount' (numeric field)]"
    ]

    generator = ScenarioGenerator(llm_client=mock_llm, strategy_selector=mock_selector)

    fields = [{"name": "amount", "type": "numeric"}]
    scenarios = await generator.generate_scenarios("Submit expense", fields)

    assert len(scenarios) == 2
    assert scenarios[0].id == "test-1"
    assert scenarios[1].is_exploratory is True
    # The deterministic risk score is recalculated. Exploratory (+2), baseline (+2) = 4
    assert scenarios[1].risk_score == 4


@pytest.mark.asyncio
async def test_generate_scenarios_with_domain_knowledge():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {
        "scenarios": [
            {
                "id": "test-1",
                "title": "Nominal Path",
                "description": "Submit a valid form",
                "steps": ["Fill form", "Click Submit"],
                "expected_outcome": "Form submitted",
                "is_exploratory": False,
                "strategies_applied": [
                    "Negative Testing for 'short_description' (mandatory field)"
                ],
            }
        ],
        "reasoning": "Standard testing.",
    }

    mock_selector = MagicMock(spec=StrategySelector)
    mock_selector.select_strategies.return_value = [
        "Negative Testing for 'short_description' (mandatory field)"
    ]

    generator = ScenarioGenerator(llm_client=mock_llm, strategy_selector=mock_selector)

    model = CustomerKnowledgeModel()
    table = TableMetadata(name="incident")
    table.fields["short_description"] = FieldMetadata(
        name="short_description", label="Short desc", type="string", mandatory=True
    )
    model.add_table_metadata(table)

    fields = [{"name": "short_description", "type": "string"}]
    scenarios = await generator.generate_scenarios(
        "Create incident", fields, knowledge_model=model, table_name="incident"
    )

    assert len(scenarios) == 1
    # Score calculation: baseline (2) + mandatory field (1) + negative testing (1) = 4
    assert scenarios[0].risk_score == 4


@pytest.mark.asyncio
async def test_generate_scenarios_malformed_llm():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {"broken": "format"}

    mock_selector = MagicMock(spec=StrategySelector)
    mock_selector.select_strategies.return_value = []
    generator = ScenarioGenerator(llm_client=mock_llm, strategy_selector=mock_selector)

    scenarios = await generator.generate_scenarios("Req", [])

    assert len(scenarios) == 1
    assert scenarios[0].id == "fallback-1"
    assert scenarios[0].risk_score == 5


@pytest.mark.asyncio
async def test_generate_scenarios_safety_rejection():
    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {
        "scenarios": [
            {
                "id": "test-bad",
                "title": "Bad Path",
                "description": "Delete all data",
                "steps": ["Delete the current record"],
                "expected_outcome": "Data is gone",
                "is_exploratory": True,
                "strategies_applied": [],
            }
        ],
        "reasoning": "Attempting dangerous exploratory.",
    }

    mock_selector = MagicMock(spec=StrategySelector)
    mock_selector.select_strategies.return_value = []
    generator = ScenarioGenerator(llm_client=mock_llm, strategy_selector=mock_selector)

    scenarios = await generator.generate_scenarios("Req", [])

    # Should skip the scenario because it is exploratory and contains 'Delete'
    assert len(scenarios) == 0
