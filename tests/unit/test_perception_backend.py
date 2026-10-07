from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.perception.backends import LocalUiTarsBackend
from agent.perception.models import GroundingFailure


@pytest.mark.asyncio
async def test_puter_backend_success():
    backend = LocalUiTarsBackend(endpoint_url="http://test.puter", api_key="testkey")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Thought: Found it\nAction: click(point='<point>10 20</point>')"
                }
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        cand = await backend.ground_element(b"screenshot", "Submit Button")

        assert cand is not None
        assert cand.source == "vision"
        assert cand.confidence is None
        assert cand.bounding_box is not None
        assert cand.bounding_box.x == 10
        assert cand.bounding_box.center_x == 10  # 10 + 0 for 1x1 box

@pytest.mark.asyncio
async def test_puter_backend_no_point():
    backend = LocalUiTarsBackend(endpoint_url="http://test.puter", api_key="testkey")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Thought: I can't find the element\nAction: wait()"
                }
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(GroundingFailure) as exc:
            await backend.ground_element(b"screenshot", "Submit Button")

        assert "Failed to extract point" in str(exc.value)

@pytest.mark.asyncio
async def test_puter_backend_failure():
    import httpx
    backend = LocalUiTarsBackend(endpoint_url="http://test.puter", api_key="testkey")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.RequestError("Connection failed", request=MagicMock())

        with pytest.raises(GroundingFailure) as exc:
            await backend.ground_element(b"screenshot", "Submit Button")

        assert "Connection failed" in str(exc.value)
