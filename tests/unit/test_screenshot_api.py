"""Tests for screenshot serving, perception evidence persistence, and authorization."""

import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent.api.v1.auth import create_access_token
from agent.core.db import Base, get_db_session
from agent.domain.models import Run
from agent.main import app
from agent.worker.tasks import _build_perception_evidence


@pytest.fixture
async def test_env(tmp_path, monkeypatch):
    """Set up isolated report and screenshot dirs and sqlite database for testing."""
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCREENSHOT_DIR", str(screenshot_dir))
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(report_dir))

    from agent.api.v1 import dependencies
    dependencies.get_cached_settings.cache_clear()
    test_settings = dependencies.get_cached_settings()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    yield {
        "screenshot_dir": screenshot_dir,
        "report_dir": report_dir,
        "settings": test_settings,
        "async_session": async_session,
    }

    app.dependency_overrides.clear()
    dependencies.get_cached_settings.cache_clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def auth_headers(test_env):
    """Create valid auth headers for tenant-0."""
    token = create_access_token(
        data={"sub": "testuser", "tenant_id": "tenant-0", "role": "Admin", "user_id": "u1"}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tenant_b_headers(test_env):
    """Create valid auth headers for tenant-b."""
    token = create_access_token(
        data={"sub": "testuser_b", "tenant_id": "tenant-b", "role": "Admin", "user_id": "u2"}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_screenshot_authenticated_success(test_env, auth_headers):
    """Test retrieving an existing screenshot with a valid Bearer token."""
    screenshot_dir = test_env["screenshot_dir"]
    sample_png = screenshot_dir / "action_click_100.png"
    fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest_image_bytes"
    sample_png.write_bytes(fake_png_data)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/screenshots/action_click_100.png", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == fake_png_data
    assert "private" in response.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_get_screenshot_unauthorized_fails(test_env):
    """Test retrieving screenshot without auth token returns 401."""
    screenshot_dir = test_env["screenshot_dir"]
    sample_png = screenshot_dir / "action_click_100.png"
    sample_png.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/screenshots/action_click_100.png")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_screenshot_not_found_returns_404(test_env, auth_headers):
    """Test retrieving non-existent screenshot returns 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/screenshots/non_existent_file.png", headers=auth_headers)

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_filename",
    [
        "../etc/passwd",
        "..%2F..%2Fsecret.txt",
        "..\\windows\\win.ini",
        ".hidden.png",
        "sub/dir/img.png",
        "../../screenshots/test.png",
        "evil;cmd.png",
        "bad name with spaces.png",
    ],
)
async def test_get_screenshot_path_traversal_blocked(test_env, auth_headers, bad_filename):
    """Test that path traversal and invalid filenames are strictly rejected with 400/404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/screenshots/{bad_filename}", headers=auth_headers)

    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_get_run_perception_success(test_env, auth_headers):
    """Test retrieving perception evidence JSON for a completed run."""
    report_dir = test_env["report_dir"]
    async_session = test_env["async_session"]
    run_id = "run-test-perception-1"

    async with async_session() as session:
        session.add(Run(id=run_id, tenant_id="tenant-0", goal="Test Perception Goal", status="completed"))
        await session.commit()

    evidence_data = {
        "run_id": run_id,
        "frames": [
            {
                "step_index": 1,
                "timestamp": "2026-09-02T10:00:00Z",
                "action_taken": "click: #submit",
                "action_reasoning": "Clicking submit button",
                "screenshot_file": "action_click_1.png",
                "perception": {
                    "route": "DOM",
                    "confidence": 0.95,
                    "target": "#submit",
                    "bounding_box": {"x": 100, "y": 200, "width": 150, "height": 40},
                },
            }
        ],
    }
    evidence_file = report_dir / f"{run_id}_perception.json"
    evidence_file.write_text(json.dumps(evidence_data), encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run_id}/perception", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] == "completed"
    assert len(data["frames"]) == 1
    assert data["frames"][0]["screenshot_file"] == "action_click_1.png"


@pytest.mark.asyncio
async def test_get_run_perception_tenant_isolation(test_env, tenant_b_headers):
    """Test that Tenant B cannot access Tenant 0's perception evidence."""
    async_session = test_env["async_session"]
    run_id = "run-tenant-0-isolated"

    async with async_session() as session:
        session.add(Run(id=run_id, tenant_id="tenant-0", goal="Tenant 0 Only", status="completed"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run_id}/perception", headers=tenant_b_headers)

    assert response.status_code == 404


def test_build_perception_evidence_filters_nonexistent_screenshots(test_env):
    """Test that _build_perception_evidence only includes steps whose screenshots exist physically."""
    screenshot_dir = test_env["screenshot_dir"]

    # Step 1: screenshot exists
    real_screenshot = screenshot_dir / "step1_real.png"
    real_screenshot.write_bytes(b"\x89PNGreal")

    class FakeAction:
        action_type = "click"
        target = "button#submit"
        reasoning = "Clicking button"

    class FakeResult1:
        success = True
        screenshot_path = str(real_screenshot)
        details = {"perception": {"bounding_box": {"x": 10, "y": 20, "width": 50, "height": 30}}}

    class FakeStep1:
        step_index = 1
        timestamp = "2026-09-02T10:00:00Z"
        action = FakeAction()
        result = FakeResult1()

    # Step 2: screenshot does NOT exist
    class FakeResult2:
        success = True
        screenshot_path = str(screenshot_dir / "step2_missing.png")
        details = {}

    class FakeStep2:
        step_index = 2
        timestamp = "2026-09-02T10:00:05Z"
        action = FakeAction()
        result = FakeResult2()

    class FakeMemory:
        completed_steps = [FakeStep1(), FakeStep2()]

    class FakeOrchestrator:
        memory = FakeMemory()

    run_id = "run-filter-test"
    output_path = _build_perception_evidence(run_id, FakeOrchestrator())

    assert output_path is not None
    saved_json = json.loads(Path(output_path).read_text(encoding="utf-8"))
    assert saved_json["run_id"] == run_id
    assert len(saved_json["frames"]) == 2
    assert saved_json["frames"][0]["step_index"] == 1
    assert saved_json["frames"][0]["screenshot_file"] == "step1_real.png"
    assert saved_json["frames"][0]["load_error"] is None
    assert saved_json["frames"][1]["step_index"] == 2
    assert saved_json["frames"][1]["screenshot_file"] is None
    assert saved_json["frames"][1]["load_error"] == "Screenshot not captured for this step"


def test_docker_compose_screenshot_volume_consistency():
    """Verify docker-compose.yml configures shared volumes and env vars for api and worker."""
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    assert compose_path.is_file()
    content = compose_path.read_text(encoding="utf-8")

    assert "screenshots_data:/app/screenshots" in content
    assert "reports_data:/app/reports" in content
    assert "SCREENSHOT_DIR" in content and "/app/screenshots" in content
    assert "REPORT_OUTPUT_DIR" in content and "/app/reports" in content
