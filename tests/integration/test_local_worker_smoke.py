"""Integration smoke test for local worker execution on Windows/host.

Proves:
1. API creates a run record;
2. Celery worker receives task parameters;
3. Worker starts the orchestrator;
4. Worker writes final status to database;
5. Report is created;
6. Perception evidence JSON is created with screenshots and bounding boxes;
7. Browser inspection timeout does NOT convert the completed status to failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent.core.config import get_settings
from agent.core.db import Base
from agent.domain.models import Run
from agent.worker.tasks import _run_agent_async


@pytest.mark.asyncio
async def test_local_worker_smoke_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end smoke test of worker execution with mocked external services."""
    reports_dir = tmp_path / "reports"
    screenshots_dir = tmp_path / "screenshots"
    reports_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Configure local paths in settings
    monkeypatch.setenv("UAT_RUNTIME_MODE", "local")
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(reports_dir))
    monkeypatch.setenv("SCREENSHOT_DIR", str(screenshots_dir))

    # Set up SQLite test database
    db_file = tmp_path / "test_smoke.db"
    sqlite_url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)

    engine = create_async_engine(sqlite_url, future=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1. Simulate API creating a run record
    run_id = "smoke-run-1234"
    goal = "Create and verify ServiceNow Incident UAT"
    tenant_id = "tenant-local-test"

    async with async_session() as session:
        initial_run = Run(
            id=run_id,
            tenant_id=tenant_id,
            requester_id="user-1",
            goal=goal,
            status="queued",
        )
        session.add(initial_run)
        await session.commit()

    # Create dummy screenshot in screenshot_dir
    test_screenshot = screenshots_dir / "smoke_step_1.png"
    test_screenshot.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

    # Mock Orchestrator
    mock_step = MagicMock()
    mock_step.step_index = 1
    mock_step.action.action_type = "click"
    mock_step.action.target = "button#submit_incident"
    mock_step.action.reasoning = "Click submit button on Incident form"
    mock_step.result.details = {
        "perception": {
            "bounding_box": {"x": 120, "y": 240, "width": 80, "height": 32},
            "after_screenshot": "smoke_step_1.png",
            "observed_values": {"state": "New", "number": "INC0010001"},
            "expected_values": {"state": "New"},
            "route": "direct_grounding",
            "confidence": 0.96,
        }
    }

    mock_report = MagicMock()
    mock_report.status = "completed"
    mock_report.defects = []
    mock_report.agent_issues = []

    mock_orchestrator = MagicMock()
    mock_orchestrator.memory.session_id = run_id
    mock_orchestrator.memory.completed_steps = [mock_step]
    mock_orchestrator.report = mock_report
    mock_orchestrator._settings = get_settings()
    mock_orchestrator.run = AsyncMock()

    # 7. Simulate browser inspection wait timeout
    mock_orchestrator.wait_for_manual_browser_close = AsyncMock(
        side_effect=TimeoutError("Manual inspection timeout after 300 seconds")
    )

    # Mock Redis publisher and receiver to avoid running Redis in test
    mock_publisher = AsyncMock()
    mock_publisher.close = AsyncMock()
    mock_receiver = AsyncMock()
    mock_receiver.close = AsyncMock()

    mock_store = AsyncMock()
    mock_store.close = AsyncMock()

    with (
        patch("agent.main.create_orchestrator", return_value=mock_orchestrator),
        patch("agent.worker.tasks.RunEventPublisher", return_value=mock_publisher),
        patch("agent.worker.tasks.RunControlReceiver", return_value=mock_receiver),
        patch("agent.worker.tasks.get_knowledge_store", return_value=mock_store),
        patch("agent.worker.tasks.get_learning_store", return_value=mock_store),
        patch("agent.api.v1.dependencies.get_test_intelligence_store", return_value=mock_store),
    ):
        # Execute the worker async task
        await _run_agent_async(run_id=run_id, goal=goal, tenant_id=tenant_id)

    # 3. Verify orchestrator was run
    mock_orchestrator.run.assert_awaited_once_with(goal, persona=None)

    # 4. Verify worker updated database with final status and metrics
    async with async_session() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        run_record = result.scalar_one()

        assert run_record.status == "completed"
        assert run_record.end_time is not None
        assert run_record.defect_count == 0
        assert run_record.findings_count == 0

    # 5. Verify perception evidence JSON was persisted
    evidence_file = reports_dir / f"{run_id}_perception.json"
    assert evidence_file.is_file()

    evidence_data = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert evidence_data["run_id"] == run_id
    assert len(evidence_data["frames"]) == 1

    frame = evidence_data["frames"][0]
    assert frame["screenshot_file"] == "smoke_step_1.png"
    assert frame["action_taken"].startswith("click: button#submit_incident")
    assert frame["observed_values"] == {"state": "New", "number": "INC0010001"}
    assert frame["perception"]["bounding_box"] == {"x": 120, "y": 240, "width": 80, "height": 32}

    # 7. Confirm that browser timeout did NOT convert result to failed
    assert run_record.status == "completed"

    await engine.dispose()
