"""Unit tests for TestIntelligenceStore."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.testing.store import TestIntelligenceStore


@pytest.mark.asyncio
async def test_save_finding_with_evidence():
    # Setup mock pool
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Properly mock the async context manager
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_ctx

    from agent.core.config import DomainConfig

    config = DomainConfig(postgres_url="postgres://fake")
    store = TestIntelligenceStore(config=config)

    with patch.object(store, "_init_pool", return_value=mock_pool):
        store._pool = mock_pool
        await store.save_finding(
            scenario_id="scen-1",
            finding_type="visual",
            description="Button shifted",
            evidence_reference="/tmp/after.png",
            before_evidence_reference="/tmp/before.png",
        )

        # Verify the execute call contains the evidence references
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT INTO test_findings" in call_args[0]
        assert call_args[1] == "scen-1"
        assert call_args[2] == "visual"
        assert call_args[3] == "Button shifted"
        assert call_args[4] == "/tmp/after.png"
        assert call_args[5] == "/tmp/before.png"
