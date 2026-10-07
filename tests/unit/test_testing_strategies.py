"""Tests for Test Intelligence Strategy Selector."""

import json
import tempfile
from pathlib import Path

import pytest

from agent.testing.strategy_selector import StrategySelector


@pytest.mark.asyncio
async def test_strategy_selector_composition():
    # Setup temporary strategies JSON
    strategies = {
        "field_strategies": {
            "numeric": ["Boundary Value Analysis"],
            "mandatory": ["Negative Testing"],
        },
        "workflow_strategies": {"approval": ["Decision Table", "State Transition Testing"]},
    }

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(strategies, f)
        temp_path = Path(f.name)

    try:
        selector = StrategySelector(strategies_path=temp_path)

        # Test composition
        fields = [
            {"name": "amount", "type": "numeric", "mandatory": True},
            {"name": "description", "type": "string", "mandatory": False},
        ]

        selected = await selector.select_strategies(fields, workflow_type="approval")

        # Should contain field level and workflow level additively
        assert "[Boundary Value Analysis for 'amount' (numeric field)]" in selected
        assert "[Negative Testing for 'amount' (mandatory field)]" in selected
        assert "[Decision Table for workflow 'approval']" in selected
        assert "[State Transition Testing for workflow 'approval']" in selected

    finally:
        temp_path.unlink()
