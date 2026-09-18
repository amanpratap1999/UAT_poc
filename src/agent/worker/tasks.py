"""Celery tasks for executing agent runs asynchronously."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from celery.utils.log import get_task_logger  # type: ignore
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agent.api.v1.dependencies import get_knowledge_store, get_learning_store
from agent.core.celery_app import celery_app
from agent.core.config import get_settings
from agent.domain.models import Finding, Run
from agent.events.publisher import RunControlReceiver, RunEventPublisher

logger = get_task_logger(__name__)

# Runs stuck in queued/running longer than this are considered orphaned by a
# worker restart and get marked failed during worker startup reconciliation.
_STALE_RUN_CUTOFF = timedelta(hours=2)


def _build_perception_evidence(run_id: str, orchestrator: Any) -> str | None:
    """Write per-run perception evidence (screenshot frames + grounding boxes + observed values).

    Reads the completed steps from the orchestrator's session memory and
    persists a JSON file ``<reports_dir>/<run_id>_perception.json`` that the
    API serves via ``GET /api/v1/runs/{run_id}/perception``. Screenshot files
    are referenced by safe basename only — they live in the shared screenshots
    volume and are served by ``GET /api/v1/screenshots/{filename}``.
    Only frames with physically existing screenshot files are referenced.
    """
    try:
        memory = getattr(orchestrator, "memory", None)
        if memory is None:
            return None

        screenshot_dir = Path(get_settings().screenshot_dir).resolve()
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        frames: list[dict[str, Any]] = []
        for step in getattr(memory, "completed_steps", []):
            result = getattr(step, "result", None)
            action = getattr(step, "action", None)

            perception: dict[str, Any] = {}
            details = getattr(result, "details", None)
            if isinstance(details, dict):
                maybe_p = details.get("perception")
                if isinstance(maybe_p, dict):
                    perception = maybe_p

            # Candidate paths in order of preference: post-action screenshot, perception evidence (after/before)
            candidate_paths: list[str] = []
            sp = getattr(result, "screenshot_path", None)
            if isinstance(sp, str) and sp.strip():
                candidate_paths.append(sp.strip())
            for key in ("after_screenshot", "before_screenshot"):
                v = perception.get(key)
                if isinstance(v, str) and v.strip():
                    candidate_paths.append(v.strip())

            screenshot_file: str | None = None
            for cand in candidate_paths:
                cand_path = Path(cand)
                cand_name = cand_path.name
                # Reject invalid or directory-traversal filenames
                if not re.fullmatch(r"[A-Za-z0-9._-]+", cand_name) or cand_name.startswith(".") or ".." in cand_name:
                    continue

                # Check if it physically exists in screenshot_dir
                target_in_dir = (screenshot_dir / cand_name).resolve()
                if target_in_dir.is_file():
                    screenshot_file = cand_name
                    break

                # If candidate path exists as an absolute path or relative to screenshot_dir, copy to screenshot_dir
                resolved_cand = cand_path if cand_path.is_file() else (screenshot_dir / cand_name).resolve()
                if resolved_cand.is_file():
                    try:
                        if resolved_cand != target_in_dir:
                            shutil.copy2(resolved_cand, target_in_dir)
                        screenshot_file = cand_name
                        break
                    except Exception as copy_err:
                        logger.debug("screenshot_copy_to_shared_failed: %s", copy_err)

            # If not screenshot_file, load_error will explain that it was not captured
            bbox = perception.get("bounding_box")
            ts = getattr(step, "timestamp", None)
            step_idx = getattr(step, "step_index", len(frames))

            observed = (
                perception.get("observed_values")
                or (details.get("observed_values") if isinstance(details, dict) else {})
                or getattr(getattr(step, "validation", None), "precondition_details", {})
                or getattr(step, "observed_values", {})
                or {}
            )
            expected = (
                perception.get("expected_values")
                or (details.get("expected_values") if isinstance(details, dict) else {})
                or (getattr(action, "metadata", {}).get("expected_state") if hasattr(action, "metadata") else None)
                or getattr(step, "expected_values", {})
                or {}
            )

            frame_id = f"frame_{run_id}_{step_idx}"
            load_error = None if screenshot_file else "Screenshot not captured for this step"

            frames.append(
                {
                    "frame_id": frame_id,
                    "run_id": run_id,
                    "step_index": step_idx,
                    "timestamp": ts.isoformat() if ts is not None and hasattr(ts, "isoformat") else (str(ts) if ts is not None else datetime.now(UTC).isoformat()),
                    "action_taken": (
                        f"{getattr(action, 'action_type', 'action')}: "
                        f"{getattr(action, 'target', '')}"
                    )[:120],
                    "action_reasoning": (getattr(action, "reasoning", "") or "")[:400],
                    "screenshot_file": screenshot_file,
                    "screenshot_url": f"/api/v1/screenshots/{screenshot_file}" if screenshot_file else None,
                    "load_error": load_error,
                    "observed_values": observed if isinstance(observed, dict) else {"value": observed},
                    "expected_values": expected if isinstance(expected, dict) else ({"state": expected} if expected else {}),
                    "perception": {
                        "route": perception.get("route"),
                        "confidence": perception.get("confidence"),
                        "target": perception.get("target") or getattr(action, "target", ""),
                        "bounding_box": bbox if isinstance(bbox, dict) else None,
                        "locator": perception.get("locator"),
                    },
                }
            )

        out_dir = Path(get_settings().report_output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{run_id}_perception.json"
        path.write_text(
            json.dumps({"run_id": run_id, "frames": frames}, indent=2, default=str), encoding="utf-8"
        )
        return str(path)
    except Exception as e:  # Evidence capture must never fail the run
        logger.warning(f"perception_evidence_write_failed: {e}")
        return None


def _build_result_snapshot(run_id: str, orchestrator: Any, report: Any) -> dict[str, Any]:
    """Build the run result snapshot consumed by the reporting/export layer.

    Preserves the imported test case (with story/sheet traceability and
    persona) alongside the execution outcome so XLSX export, persona
    comparison, and the API can all work off one artifact.
    """
    memory = getattr(orchestrator, "memory", None)
    tc_data = getattr(memory, "test_case_data", None) or {}
    snapshot: dict[str, Any] = {
        "run_id": run_id,
        "goal": getattr(report, "goal", "") or getattr(memory, "goal", ""),
        "status": getattr(report, "status", "unknown"),
        "persona": getattr(memory, "persona", None),
        "test_case": tc_data,
        "summary": getattr(report, "summary", ""),
        "total_validations": getattr(report, "total_validations", 0),
        "passed_validations": getattr(report, "passed_validations", 0),
        "failed_validations": getattr(report, "failed_validations", 0),
        "defects": [],
        "agent_issues": [],
        "started_at": getattr(report, "started_at", None),
        "completed_at": getattr(report, "completed_at", None),
        "duration_seconds": getattr(report, "duration_seconds", None),
    }
    for d in getattr(report, "defects", []) or []:
        snapshot["defects"].append(
            {
                "defect_id": getattr(d, "defect_id", ""),
                "title": getattr(d, "title", ""),
                "description": getattr(d, "description", ""),
                "severity": str(getattr(d, "severity", "")),
                "expected": getattr(d, "expected_behavior", ""),
                "actual": getattr(d, "actual_behavior", ""),
                "related_step_index": getattr(d, "related_step_index", None),
            }
        )
    for i in getattr(report, "agent_issues", []) or []:
        snapshot["agent_issues"].append(
            {
                "issue_id": getattr(i, "issue_id", ""),
                "title": getattr(i, "title", ""),
                "description": getattr(i, "description", ""),
                "category": getattr(i, "category", ""),
            }
        )
    return snapshot


def _save_result_snapshot(run_id: str, orchestrator: Any, report: Any) -> str | None:
    """Persist the result snapshot as ``<reports_dir>/<run_id>_result.json``."""
    try:
        out_dir = Path(get_settings().report_output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{run_id}_result.json"
        path.write_text(
            json.dumps(_build_result_snapshot(run_id, orchestrator, report), indent=2, default=str),
            encoding="utf-8",
        )
        return str(path)
    except Exception as e:  # Snapshot must never fail the run
        logger.warning("result_snapshot_write_failed: %s", e)
        return None


async def _run_agent_async(run_id: str, goal: str, tenant_id: str, test_case_id: str | None = None, persona: str | None = None, tc_data: dict[str, Any] | None = None) -> None:
    """Async wrapper to run the orchestrator and update the DB."""

    settings = get_settings()
    engine = create_async_engine(
        settings.domain.postgres_url,
        poolclass=NullPool,
        future=True,
    )
    task_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    publisher = RunEventPublisher(settings.session.redis_url, run_id)
    control_receiver = RunControlReceiver(settings.session.redis_url, run_id)

    try:
        # Update status to running
        async with task_session_maker() as session:
            await session.execute(update(Run).where(Run.id == run_id).values(status="running"))
            await session.commit()

        orchestrator = None
        try:
            from agent.main import create_orchestrator

            orchestrator = create_orchestrator()
            # Attach event publisher and control receiver for desktop interactivity
            if hasattr(orchestrator, "set_event_publisher"):
                orchestrator.set_event_publisher(publisher)
            if hasattr(orchestrator, "set_control_receiver"):
                orchestrator.set_control_receiver(control_receiver)

            # Hook incremental perception writes after each step
            def _on_step(step: Any, mem: Any) -> None:
                _build_perception_evidence(run_id, orchestrator)

            setattr(orchestrator, "_on_step_complete", _on_step)

            # If test_case_id is provided, load structured test case
            if test_case_id:
                try:
                    from agent.api.v1.dependencies import get_test_intelligence_store
                    test_store = get_test_intelligence_store(settings)
                    if not tc_data:
                        tc_data = await test_store.get_test_case_async(test_case_id, tenant_id=tenant_id)
                    if tc_data and hasattr(orchestrator, "set_test_case"):
                        orchestrator.set_test_case(tc_data)
                except Exception as tc_load_err:
                    logger.warning("failed_loading_test_case: %s", tc_load_err)

            # Keep report/evidence/session identifiers aligned with the API run.
            orchestrator.memory.session_id = run_id
            logger.info(
                "agent_browser_configuration run_id=%s headless=%s slow_mo=%s "
                "show_mouse_cursor=%s keep_browser_open=%s",
                run_id,
                orchestrator._settings.browser.headless,
                orchestrator._settings.browser.slow_mo,
                orchestrator._settings.browser.show_mouse_cursor,
                orchestrator._settings.browser.keep_browser_open,
            )

            # Execute the full agent loop
            await orchestrator.run(goal, persona=persona)

            # Persist perception evidence (screenshots + grounding boxes + observed values)
            evidence_path = _build_perception_evidence(run_id, orchestrator)
            if evidence_path:
                logger.info(f"perception_evidence_saved: {evidence_path}")

            # Persist the result snapshot for the reporting/export layer
            snapshot_path = _save_result_snapshot(run_id, orchestrator, orchestrator.report)
            if snapshot_path:
                logger.info(f"result_snapshot_saved: {snapshot_path}")

            # Once finished, fetch the final report and save metrics/findings/screenshots to DB
            async with task_session_maker() as session:
                from agent.domain.models import Screenshot

                try:
                    ev_p = Path(evidence_path) if evidence_path else None
                    if ev_p and ev_p.is_file():
                        ev_data = json.loads(ev_p.read_text(encoding="utf-8"))
                        for f in ev_data.get("frames", []):
                            sc_name = f.get("screenshot_file")
                            if sc_name:
                                sc_exists = await session.execute(
                                    select(Screenshot).where(Screenshot.filename == sc_name)
                                )
                                if not sc_exists.scalars().first():
                                    session.add(
                                        Screenshot(
                                            id=str(uuid.uuid4()),
                                            tenant_id=tenant_id or "unknown",
                                            run_id=run_id,
                                            filename=sc_name,
                                        )
                                    )
                except Exception as sc_reg_err:
                    logger.warning("screenshot_registration_failed: %s", sc_reg_err)

                report = orchestrator.report if orchestrator else None
                defects = report.defects if report else []
                agent_issues = report.agent_issues if report else []

                for defect in defects:
                    finding_id = str(uuid.uuid4())
                    finding = Finding(
                        id=finding_id,
                        tenant_id=tenant_id or "unknown",
                        run_id=run_id,
                        capability="Application Bug",
                        description=(f"{defect.title}: {defect.description}" if defect.title else defect.description),
                        is_defect=True,
                        severity=defect.severity.value if hasattr(defect.severity, "value") else str(defect.severity),
                        evidence={
                            "evidence": defect.evidence,
                            "expected": defect.expected_behavior,
                            "actual": defect.actual_behavior,
                            "hypothesis": defect.root_cause_hypothesis,
                        },
                    )
                    session.add(finding)

                for issue in agent_issues:
                    finding_id = str(uuid.uuid4())
                    finding = Finding(
                        id=finding_id,
                        tenant_id=tenant_id or "unknown",
                        run_id=run_id,
                        capability=f"Agent Issue ({issue.category})",
                        description=(f"{issue.title}: {issue.description}" if issue.title else issue.description),
                        is_defect=False,
                        severity=None,
                        evidence={
                            "issue_id": issue.issue_id,
                            "category": issue.category,
                            "error_type": issue.error_type,
                            "related_step_index": issue.related_step_index,
                        },
                    )
                    session.add(finding)

                end_time = datetime.now(UTC)
                start_row = await session.execute(
                    select(Run.start_time).where(Run.id == run_id)
                )
                start_time = start_row.scalar_one_or_none()
                if start_time is not None:
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=UTC)
                    duration_seconds = max(0, int((end_time - start_time).total_seconds()))
                else:
                    duration_seconds = None

                terminal_status = report.status if (report and report.status) else "completed"

                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status=terminal_status,
                        end_time=end_time,
                        duration_seconds=duration_seconds,
                        findings_count=len(defects) + len(agent_issues),
                        defect_count=len(defects),
                    )
                )
                await session.commit()

            # Keep headed browser visible for manual inspection with safe guardrail timeout
            # Note: Browser inspection wait must NEVER mutate or flip finalized run status to failed.
            if orchestrator:
                try:
                    timeout = settings.browser.interactive_timeout_seconds
                    await orchestrator.wait_for_manual_browser_close(timeout_seconds=timeout)
                except Exception as browser_wait_err:
                    logger.warning("manual_browser_inspection_ended run_id=%s error=%s", run_id, str(browser_wait_err))

        except Exception as err:
            logger.exception("Agent run failed")
            async with task_session_maker() as session:
                end_time = datetime.now(UTC)
                duration_seconds = None
                try:
                    start_row = await session.execute(
                        select(Run.start_time).where(Run.id == run_id)
                    )
                    start_time = start_row.scalar_one_or_none()
                    if start_time is not None:
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=UTC)
                        duration_seconds = max(0, int((end_time - start_time).total_seconds()))
                except Exception:
                    duration_seconds = None

                # Persist Runtime Error finding so failures are visible in UI
                finding_id = str(uuid.uuid4())
                session.add(
                    Finding(
                        id=finding_id,
                        tenant_id=tenant_id or "unknown",
                        run_id=run_id,
                        capability="Runtime Error",
                        description=f"Agent execution failed: {str(err)}",
                        is_defect=False,
                        severity="high",
                        evidence={"error": str(err), "type": type(err).__name__},
                    )
                )

                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        status="failed",
                        end_time=end_time,
                        duration_seconds=duration_seconds,
                        findings_count=1,
                    )
                )
                await session.commit()
    finally:
        await publisher.close()
        await control_receiver.close()
        await engine.dispose()
        store = get_knowledge_store()
        await store.close()
        learning_store = get_learning_store()
        await learning_store.close()
        from agent.api.v1.dependencies import get_test_intelligence_store

        test_store = get_test_intelligence_store()
        await test_store.close()


def _reconcile_stale_runs() -> None:
    """Mark runs orphaned by a worker restart (stuck queued/running) as failed.

    Runs only when this module is imported by an actual Celery worker process
    (detected via sys.argv) so API/test imports stay side-effect free.
    """

    async def _mark_stale() -> int:
        settings = get_settings()
        reconcile_engine = create_async_engine(
            settings.domain.postgres_url, poolclass=NullPool, future=True
        )
        try:
            cutoff = datetime.now(UTC) - _STALE_RUN_CUTOFF
            async with reconcile_engine.begin() as conn:
                result = await conn.execute(
                    update(Run)
                    .where(Run.status.in_(("queued", "running")), Run.start_time < cutoff)
                    .values(status="failed", end_time=datetime.now(UTC))
                )
                return int(result.rowcount or 0)
        finally:
            await reconcile_engine.dispose()

    try:
        count = asyncio.run(_mark_stale())
        if count:
            logger.info(
                f"reconciled_stale_runs: {count} run(s) older than "
                f"{_STALE_RUN_CUTOFF} marked failed"
            )
    except Exception as e:  # DB not reachable at import time — non-fatal
        logger.warning(f"stale_run_reconciliation_failed: {e}")


@celery_app.task(bind=True, name="agent.worker.tasks.execute_run")  # type: ignore[untyped-decorator]
def execute_run(self, run_id: str, goal: str, tenant_id: str, test_case_id: str | None = None, persona: str | None = None, tc_data: dict[str, Any] | None = None) -> str:  # type: ignore[no-untyped-def]
    """Synchronous Celery task that drives the async agent run."""
    logger.info(f"Starting execution for run_id={run_id} tenant={tenant_id} test_case_id={test_case_id}")

    # Run the async agent inside a new event loop
    asyncio.run(_run_agent_async(run_id, goal, tenant_id, test_case_id=test_case_id, persona=persona, tc_data=tc_data))

    return "done"


# Startup reconciliation — only inside a real Celery worker process.
if any("celery" in arg for arg in sys.argv):
    _reconcile_stale_runs()


