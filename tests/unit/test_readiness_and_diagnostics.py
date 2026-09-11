"""Unit tests for readiness probe and diagnostics endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent.main import app


@pytest.mark.asyncio
async def test_diagnostic_paths_endpoint() -> None:
    """Verify /api/v1/diagnostics/paths requires auth and returns resolved paths without secrets."""
    # 1. Unauthenticated request must return 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthed_resp = await client.get("/api/v1/diagnostics/paths")
    assert unauthed_resp.status_code == 401

    # 2. Authenticated request must return 200 with resolved paths and no secrets
    from agent.api.v1.auth import create_access_token

    token = create_access_token({"sub": "admin", "role": "admin", "tenant_id": "default", "user_id": "u1"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/diagnostics/paths",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "runtime_mode" in data
    assert "repo_root" in data
    assert "report_output_dir" in data
    assert "screenshot_dir" in data
    # Ensure no passwords/secrets in output
    assert "password" not in data
    assert "secret" not in data


@pytest.mark.asyncio
async def test_readiness_probe_healthy() -> None:
    """Verify /api/v1/ready returns 200 when all dependencies are healthy."""
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = 1
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = mock_res
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_engine.connect.return_value = mock_ctx

    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    mock_embedding = AsyncMock()
    mock_embedding.startup_health_check.return_value = True

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("agent.api.v1.dependencies.get_embedding_client", return_value=mock_embedding),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/ready")

    print(response.json())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"]["status"] == "ok"
    assert data["checks"]["database"]["pgvector"] is True
    assert data["checks"]["redis"]["status"] == "ok"
    assert data["checks"]["directories"]["status"] == "ok"
    assert data["checks"]["embedding_client"]["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_probe_unhealthy_when_db_down() -> None:
    """Verify /api/v1/ready returns 503 when database is unreachable."""
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    with (
        patch(
            "sqlalchemy.ext.asyncio.create_async_engine",
            side_effect=ConnectionRefusedError("Database refused connection"),
        ),
        patch("redis.asyncio.from_url", return_value=mock_redis),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["database"]["status"] == "unhealthy"
    assert "Database refused connection" in data["checks"]["database"]["error"]
