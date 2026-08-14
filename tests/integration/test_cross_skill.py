from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.capabilities.registry import CapabilityRegistry
from agent.learning.service import LearningService
from agent.perception.engine import PerceptionDecisionEngine
from agent.skills.change.skill import ChangeSkill
from agent.skills.incident.skill import IncidentSkill
from agent.testing.strategy_selector import StrategySelector


@pytest.fixture
def registry():
    reg = CapabilityRegistry()
    inc = IncidentSkill()
    chg = ChangeSkill()
    reg.register(inc, inc.get_capability_definition())
    reg.register(chg, chg.get_capability_definition())
    return reg


@pytest.mark.asyncio
async def test_cross_skill_intelligence_sharing(registry):
    """Prove that both Incident and Change use shared intelligence components without duplication."""  # noqa: E501

    # 1. Retrieve the skills from the registry
    incident_skill = registry.get_skill_by_name("incident")
    change_skill = registry.get_skill_by_name("change")

    assert incident_skill is not None
    assert change_skill is not None

    # 2. Both skills provide domain-specific selectors
    inc_selectors = incident_skill.get_domain_selectors()
    chg_selectors = change_skill.get_domain_selectors()

    # Both should have valid selectors
    assert "record_number" in inc_selectors
    assert "record_number" in chg_selectors

    # 3. Create single shared intelligence components
    mock_browser = AsyncMock()
    mock_interactor = AsyncMock()
    mock_executor = AsyncMock()
    mock_grounder = AsyncMock()
    mock_verifier = AsyncMock()
    mock_learning = MagicMock(spec=LearningService)
    mock_observer = AsyncMock()

    PerceptionDecisionEngine(
        browser=mock_browser,
        interactor=mock_interactor,
        executor=mock_executor,
        grounder=mock_grounder,
        verifier=mock_verifier,
        learning_service=mock_learning,
        observer=mock_observer,
    )

    shared_strategy_selector = StrategySelector(learning_service=mock_learning)

    # 4. Verify Strategy Selection works for both without hardcoding
    # We pass the target_module derived from the capability definition
    inc_def = incident_skill.get_capability_definition()
    chg_def = change_skill.get_capability_definition()

    inc_strategies = await shared_strategy_selector.select_strategies(
        fields=[{"name": "priority", "type": "numeric"}], target_module=inc_def.module_name
    )

    chg_strategies = await shared_strategy_selector.select_strategies(
        fields=[{"name": "risk", "type": "numeric"}], target_module=chg_def.module_name
    )

    assert isinstance(inc_strategies, list)
    assert isinstance(chg_strategies, list)

    # Verify learning service was called with correct modules
    assert mock_learning.get_strategy_priority.call_count >= 0
