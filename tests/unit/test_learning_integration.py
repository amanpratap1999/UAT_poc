"""Integration tests for the LearningService with ScenarioGenerator and StrategySelector."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.learning.service import LearningService
from agent.learning.store import LearningStore
from agent.learning.types import LearnedExplorationOutcome, LearnedStrategyEffectiveness
from agent.planner.llm_client import OpenAILLMClient
from agent.testing.generator import ScenarioGenerator
from agent.testing.strategy_selector import StrategySelector


@pytest.fixture
def mock_store() -> LearningStore:
    store = MagicMock(spec=LearningStore)
    return store


@pytest.fixture
def learning_service(mock_store: LearningStore) -> LearningService:
    return LearningService(store=mock_store)


@pytest.mark.asyncio
async def test_strategy_selector_prioritization(learning_service, mock_store):
    # Mock some learned effectiveness
    async def mock_get_eff(module, strategy, field_type, workflow_type):
        if strategy == "Boundary Value Analysis":
            return LearnedStrategyEffectiveness(
                module=module,
                strategy=strategy,
                field_type=field_type,
                workflow_type=workflow_type,
                executions=10,
                findings=8,
                confidence=0.9,
            )
        return None

    mock_store.get_strategy_effectiveness.side_effect = mock_get_eff

    selector = StrategySelector(learning_service=learning_service)
    # Re-mock the loaded strategies for deterministic test
    selector._field_strategies = {
        "numeric": ["Equivalence Partitioning", "Boundary Value Analysis"]
    }

    fields = [{"type": "numeric", "name": "Priority"}]

    strategies = await selector.select_strategies(fields=fields)

    # Boundary Value Analysis should be first because it has high yield and confidence
    assert len(strategies) == 2
    assert "Boundary Value Analysis" in strategies[0]
    assert "Equivalence Partitioning" in strategies[1]


@pytest.mark.asyncio
async def test_scenario_generator_prioritization(learning_service, mock_store):
    async def mock_get_exp(module, ext_type):
        if ext_type == "exploratory_branch":
            return LearnedExplorationOutcome(
                module=module, exploration_type=ext_type, executions=5, findings=5, confidence=1.0
            )
        return None

    mock_store.get_exploration_outcome.side_effect = mock_get_exp

    mock_llm = AsyncMock(spec=OpenAILLMClient)
    mock_llm.complete_json.return_value = {
        "scenarios": [
            {
                "id": "scen-1",
                "title": "Normal Path",
                "description": "Standard",
                "steps": [],
                "expected_outcome": "Ok",
                "is_exploratory": False,
                "risk_score": 5,
                "strategies_applied": [],
            },
            {
                "id": "scen-2",
                "title": "Exploratory Path",
                "description": "Exploration",
                "steps": [],
                "expected_outcome": "Ok",
                "is_exploratory": True,
                "risk_score": 7,
                "strategies_applied": [],
            },
        ],
        "reasoning": "Test reasoning",
    }

    selector = StrategySelector(learning_service=learning_service)
    generator = ScenarioGenerator(
        llm_client=mock_llm, strategy_selector=selector, learning_service=learning_service
    )

    scenarios = await generator.generate_scenarios("Req", fields=[])

    # Exploratory scenario should be prioritized first due to high learned yield
    assert len(scenarios) == 2
    assert scenarios[0].is_exploratory is True
    assert scenarios[1].is_exploratory is False
