"""Integration tests for Phase 7 Multi-Tenant APIs."""

import os

os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"


import pytest
from httpx import AsyncClient

# Use pytest-asyncio auto mode
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def async_client():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from agent.core.db import Base, get_db_session
    from agent.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def mock_db_tenant_id():
    return "tenant-0"


async def test_api_health(async_client: AsyncClient):
    """Test health endpoint is unprotected."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_auth_login_success(async_client: AsyncClient):
    """Test login issues a valid JWT."""
    response = await async_client.post(
        "/api/v1/token",
        data={"username": "admin", "password": "admin"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_protected_routes_require_token(async_client: AsyncClient):
    """Test protected routes return 401 without token."""
    response = await async_client.get("/api/v1/runs")
    assert response.status_code == 401


async def test_create_and_list_runs(async_client: AsyncClient, mocker):
    """Test queuing a run via Celery and verifying it belongs to the tenant."""
    # Mock celery delay so it doesn't actually try to run
    mocker.patch("agent.api.v1.router.execute_run.delay")

    # Login
    auth_res = await async_client.post(
        "/api/v1/token", data={"username": "admin", "password": "admin"}
    )
    token = auth_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create run
    run_res = await async_client.post("/api/v1/runs", json={"goal": "Test Goal"}, headers=headers)
    assert run_res.status_code == 200
    run_id = run_res.json()["session_id"]

    # List runs
    list_res = await async_client.get("/api/v1/runs", headers=headers)
    assert list_res.status_code == 200
    runs = list_res.json()
    assert len(runs) >= 1
    assert runs[0]["id"] == run_id
    assert runs[0]["tenant_id"] == "tenant-0"


async def test_tenant_isolation(async_client: AsyncClient, mocker):
    """Test that Tenant A cannot see Tenant B's runs."""
    mocker.patch("agent.api.v1.router.execute_run.delay")

    # Login as admin to get token
    auth_res = await async_client.post(
        "/api/v1/token", data={"username": "admin", "password": "admin"}
    )
    token = auth_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create run for admin (tenant-0)
    await async_client.post("/api/v1/runs", json={"goal": "Tenant 0 Goal"}, headers=headers)

    # Mock decode to simulate Tenant B
    mocker.patch(
        "agent.api.v1.auth.jwt.decode",
        return_value={
            "sub": "user_b",
            "role": "Admin",
            "tenant_id": "tenant-B",
            "user_id": "user-b-id",
        },
    )

    # List runs as Tenant B
    list_res = await async_client.get("/api/v1/runs", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 0  # Tenant B should see no runs


async def test_tenant_isolation_findings(async_client: AsyncClient, mocker):
    """Test that Tenant A cannot see Tenant B's findings."""
    auth_res = await async_client.post(
        "/api/v1/token", data={"username": "admin", "password": "admin"}
    )
    token = auth_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    list_res = await async_client.get("/api/v1/findings", headers=headers)
    assert list_res.status_code == 200

    # Mock decode to simulate Tenant B
    mocker.patch(
        "agent.api.v1.auth.jwt.decode",
        return_value={
            "sub": "user_b",
            "role": "Admin",
            "tenant_id": "tenant-B",
            "user_id": "user-b-id",
        },
    )
    list_res_b = await async_client.get("/api/v1/findings", headers=headers)
    assert list_res_b.status_code == 200


async def test_tenant_isolation_metrics(async_client: AsyncClient, mocker):
    """Test that Tenant A metrics are scoped to Tenant A."""
    auth_res = await async_client.post(
        "/api/v1/token", data={"username": "admin", "password": "admin"}
    )
    token = auth_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Admin is Tenant-0
    metrics_res = await async_client.get("/api/v1/metrics", headers=headers)
    assert metrics_res.status_code == 200
    assert metrics_res.json()["tenant_id"] == "tenant-0"

    # Mock decode to simulate Tenant B
    mocker.patch(
        "agent.api.v1.auth.jwt.decode",
        return_value={
            "sub": "user_b",
            "role": "QA Manager",  # Role required for metrics
            "tenant_id": "tenant-B",
            "user_id": "user-b-id",
        },
    )
    metrics_res_b = await async_client.get("/api/v1/metrics", headers=headers)
    assert metrics_res_b.status_code == 200
    assert metrics_res_b.json()["tenant_id"] == "tenant-B"
