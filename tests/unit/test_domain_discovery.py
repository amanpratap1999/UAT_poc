"""Tests for Domain Intelligence discovery agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.config import ServiceNowConfig
from agent.domain.discovery import CustomerDiscoveryAgent


@pytest.fixture
def mock_httpx_client():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_discover_table_metadata(mock_httpx_client):
    """Test discovering a table's dictionary entries."""
    # Mock the response for sys_dictionary
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {
        "result": [
            {
                "element": "short_description",
                "column_label": "Short description",
                "internal_type": {"value": "string"},
                "mandatory": "true",
                "read_only": "false",
            },
            {
                "element": "state",
                "column_label": "State",
                "internal_type": {"value": "integer"},
                "mandatory": "false",
                "read_only": "false",
            },
        ]
    }
    mock_httpx_client.get.return_value = mock_response

    config = ServiceNowConfig(
        instance_url="https://test.service-now.com", username="test", password="test"
    )
    agent = CustomerDiscoveryAgent(config=config, client=mock_httpx_client)

    table_metadata = await agent.discover_table("incident")

    assert table_metadata.name == "incident"
    assert "short_description" in table_metadata.fields
    assert table_metadata.fields["short_description"].mandatory is True
    assert table_metadata.fields["short_description"].type == "string"

    assert "state" in table_metadata.fields
    assert table_metadata.fields["state"].mandatory is False

    await agent.close()


@pytest.mark.asyncio
async def test_discovery_http_401(mock_httpx_client):
    """Test discovery raises RuntimeError on 401 Unauthorized."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_response
    )
    mock_httpx_client.get.return_value = mock_response

    config = ServiceNowConfig(
        instance_url="https://test.service-now.com", username="test", password="test"
    )
    agent = CustomerDiscoveryAgent(config=config, client=mock_httpx_client)

    with pytest.raises(RuntimeError, match="ServiceNow Discovery Failed"):
        await agent.discover_table("incident")


@pytest.mark.asyncio
async def test_discovery_http_403(mock_httpx_client):
    """Test discovery raises RuntimeError on 403 Forbidden."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403", request=MagicMock(), response=mock_response
    )
    mock_httpx_client.get.return_value = mock_response

    config = ServiceNowConfig(
        instance_url="https://test.service-now.com", username="test", password="test"
    )
    agent = CustomerDiscoveryAgent(config=config, client=mock_httpx_client)

    with pytest.raises(RuntimeError, match="ServiceNow Discovery Failed"):
        await agent.discover_table("incident")


@pytest.mark.asyncio
async def test_discovery_empty_result(mock_httpx_client):
    """Test discovery handles HTTP 200 with no fields."""
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {"result": []}
    mock_httpx_client.get.return_value = mock_response

    config = ServiceNowConfig(
        instance_url="https://test.service-now.com", username="test", password="test"
    )
    agent = CustomerDiscoveryAgent(config=config, client=mock_httpx_client)

    table_metadata = await agent.discover_table("incident")
    assert table_metadata.name == "incident"
    assert len(table_metadata.fields) == 0

    await agent.close()
