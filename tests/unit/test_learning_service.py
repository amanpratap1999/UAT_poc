"""Unit tests for the LearningService."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.learning.service import LearningService
from agent.learning.store import LearningStore
from agent.learning.types import (
    LearnedRecovery,
    LearnedStrategyEffectiveness,
)


@pytest.fixture
def mock_store() -> LearningStore:
    store = MagicMock(spec=LearningStore)
    store.get_recovery = AsyncMock(return_value=None)
    store.save_recovery = AsyncMock()
    store.delete_recovery = AsyncMock()
    store.get_strategy_effectiveness = AsyncMock(return_value=None)
    store.save_strategy_effectiveness = AsyncMock()
    store.get_exploration_outcome = AsyncMock(return_value=None)
    store.save_exploration_outcome = AsyncMock()
    store.query_experiences = AsyncMock(return_value=[])
    store.save_experience = AsyncMock()
    return store


@pytest.fixture
def learning_service(mock_store: LearningStore) -> LearningService:
    return LearningService(store=mock_store)


@pytest.mark.asyncio
async def test_get_valid_recovery_success(learning_service, mock_store):
    recovery = LearnedRecovery(
        id="test-1",
        target_description="test target",
        page_fingerprint="test-fp",
        original_locator=None,
        successful_locator="div.test",
        confidence=0.8,
        verification_count=5,
        failure_count=0,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    mock_store.get_recovery.return_value = recovery

    res = await learning_service.get_valid_recovery("test target", "test-fp")
    assert res is not None
    assert res.id == "test-1"


@pytest.mark.asyncio
async def test_get_valid_recovery_expired(learning_service, mock_store):
    recovery = LearnedRecovery(
        id="test-1",
        target_description="test target",
        page_fingerprint="test-fp",
        original_locator=None,
        successful_locator="div.test",
        confidence=0.8,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    mock_store.get_recovery.return_value = recovery

    res = await learning_service.get_valid_recovery("test target", "test-fp")
    assert res is None
    mock_store.delete_recovery.assert_called_once_with("test-1")


@pytest.mark.asyncio
async def test_get_valid_recovery_untrustworthy(learning_service, mock_store):
    recovery = LearnedRecovery(
        id="test-1",
        target_description="test target",
        page_fingerprint="test-fp",
        original_locator=None,
        successful_locator="div.test",
        confidence=0.1,  # Too low
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    mock_store.get_recovery.return_value = recovery

    res = await learning_service.get_valid_recovery("test target", "test-fp")
    assert res is None
    mock_store.delete_recovery.assert_called_once_with("test-1")


@pytest.mark.asyncio
async def test_record_strategy_execution_success(learning_service, mock_store):
    eff = LearnedStrategyEffectiveness(
        module="incident",
        field_type="numeric",
        workflow_type=None,
        strategy="Boundary Value Analysis",
        executions=10,
        findings=2,
        confidence=0.5,
    )
    mock_store.get_strategy_effectiveness.return_value = eff

    await learning_service.record_strategy_execution(
        module="incident", strategy="Boundary Value Analysis", is_finding=True, field_type="numeric"
    )

    # Should increase findings and confidence
    mock_store.save_strategy_effectiveness.assert_called_once()
    saved_eff = mock_store.save_strategy_effectiveness.call_args[0][0]
    assert saved_eff.executions == 11
    assert saved_eff.findings == 3
    assert saved_eff.confidence > 0.5
