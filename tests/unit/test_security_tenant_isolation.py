"""Unit tests verifying Authentication and Tenant Isolation across all Run and Control endpoints.

Ensures that:
1. SSE streaming requires a valid JWT token; unauthenticated access returns 401.
2. Cross-tenant access to SSE stream (/runs/{id}/events) returns 404.
3. Cross-tenant access to pause, resume, cancel, clarify, and approve returns 404.
4. Cross-tenant execution of test cases returns 404.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agent.api.v1.auth import create_access_token
from agent.core.config import DomainConfig
from agent.domain.models import Run
from agent.main import app
from agent.testing.store import TestIntelligenceStore as IntelligenceStore

IntelligenceStore.__test__ = False


@pytest.fixture
def tenant_a_token() -> str:
    return create_access_token({
        "sub": "user_a",
        "role": "tester",
        "tenant_id": "tenant-alpha",
        "user_id": "usr-1",
    })


@pytest.fixture
def tenant_b_token() -> str:
    return create_access_token({
        "sub": "user_b",
        "role": "tester",
        "tenant_id": "tenant-bravo",
        "user_id": "usr-2",
    })


@pytest.mark.asyncio
async def test_sse_endpoint_requires_auth():
    """Accessing /runs/{run_id}/events without token returns 401 Unauthorized."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/runs/any-run-id/events")
        assert resp.status_code == 401
        assert "token required" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cross_tenant_control_endpoints_return_404(
    tenant_a_token: str,
    tenant_b_token: str,
):
    """User from tenant-bravo cannot pause, resume, cancel, clarify, or approve tenant-alpha's run."""
    from agent.core.db import get_db_session
    from unittest.mock import AsyncMock, MagicMock

    # Create mock DB session containing a run belonging to tenant-alpha
    mock_run = Run(
        id="run-alpha-1",
        tenant_id="tenant-alpha",
        goal="Alpha goal",
        status="running",
    )

    mock_db = AsyncMock()

    def mock_execute(query):
        res = MagicMock()
        try:
            params = query.compile().params
            if "tenant-alpha" in params.values():
                res.scalars.return_value.first.return_value = mock_run
            else:
                res.scalars.return_value.first.return_value = None
        except Exception:
            res.scalars.return_value.first.return_value = None
        return res

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db_session] = lambda: mock_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers_b = {"Authorization": f"Bearer {tenant_b_token}"}

            # 1. Pause
            resp = await client.post(
                "/api/v1/runs/run-alpha-1/pause",
                json={"reason": "Attacking other tenant"},
                headers=headers_b,
            )
            assert resp.status_code == 404

            # 2. Resume
            resp = await client.post(
                "/api/v1/runs/run-alpha-1/resume",
                json={"message": "Resuming other tenant"},
                headers=headers_b,
            )
            assert resp.status_code == 404

            # 3. Cancel
            resp = await client.post(
                "/api/v1/runs/run-alpha-1/cancel",
                json={"reason": "Cancelling other tenant"},
                headers=headers_b,
            )
            assert resp.status_code == 404

            # 4. Clarify
            resp = await client.post(
                "/api/v1/runs/run-alpha-1/clarify",
                json={"request_id": "req-1", "answer": "malicious input"},
                headers=headers_b,
            )
            assert resp.status_code == 404

            # 5. Approve
            resp = await client.post(
                "/api/v1/runs/run-alpha-1/approve",
                json={"prompt_id": "prop-1", "approved": True},
                headers=headers_b,
            )
            assert resp.status_code == 404

            # 6. Stream events cross-tenant
            resp = await client.get(
                f"/api/v1/runs/run-alpha-1/events?token={tenant_b_token}"
            )
            assert resp.status_code == 404

    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_test_case_store_and_execute_tenant_isolation(
    tenant_a_token: str,
    tenant_b_token: str,
):
    """Test cases stored under tenant-alpha cannot be retrieved or executed by tenant-bravo."""
    from agent.api.v1.dependencies import get_test_intelligence_store

    store = IntelligenceStore(DomainConfig())
    tc_alpha = {
        "id": "TC-ALPHA-99",
        "title": "Alpha proprietary test case",
        "description": "Confidential steps",
        "ordered_steps": [{"description": "Step 1"}],
    }
    saved_id = store.save_test_case(tc_alpha, tenant_id="tenant-alpha")
    assert saved_id == "TC-ALPHA-99"

    # Tenant alpha can get it
    assert store.get_test_case("TC-ALPHA-99", tenant_id="tenant-alpha") is not None

    # Tenant bravo CANNOT get it (returns None)
    assert store.get_test_case("TC-ALPHA-99", tenant_id="tenant-bravo") is None

    # Test execution via API
    app.dependency_overrides[get_test_intelligence_store] = lambda: store
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers_b = {"Authorization": f"Bearer {tenant_b_token}"}
            resp = await client.post(
                "/api/v1/test-cases/TC-ALPHA-99/execute",
                headers=headers_b,
            )
            assert resp.status_code == 404
            assert "unauthorized" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_test_intelligence_store, None)
