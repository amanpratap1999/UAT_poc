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
    from agent.core.redaction import redact_string

    def _json_items(items: Any) -> list[Any]:
        serialized: list[Any] = []
        for item in items or []:
            if hasattr(item, "model_dump"):
                serialized.append(item.model_dump(mode="json"))
            elif hasattr(item, "dict"):
                serialized.append(item.dict())
            else:
                serialized.append(item)
        return serialized

    snapshot: dict[str, Any] = {
        "evidence_schema_version": 2,
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
        "cleanup_status": getattr(memory, "cleanup_status", "not_run"),
        "cleanup_details": redact_string(str(getattr(memory, "cleanup_details", "") or "")),
        "api_verification_status": getattr(memory, "api_verification_status", "not_attempted"),
        "environment": getattr(report, "environment", {}) or {},
        "requirement_ids_covered": list(getattr(report, "requirement_ids_covered", []) or []),
        "exit_criteria": getattr(report, "exit_criteria", None),
        "reproducibility": getattr(report, "reproducibility", None),
        "screenshots": list(getattr(report, "screenshots", []) or []),
        "step_evidence": _json_items(getattr(report, "step_evidence", [])),
        "timeline": _json_items(getattr(report, "timeline", [])),
        "telemetry": {
            "planner_calls": getattr(memory, "planner_calls", 0),
            "moondream_calls": getattr(memory, "moondream_calls", 0),
            "gemini_calls": getattr(memory, "gemini_calls", 0),
            "verification_calls": getattr(memory, "verification_calls", 0),
        },
    }
    for d in getattr(report, "defects", []) or []:
        snapshot["defects"].append(
            {
                "defect_id": getattr(d, "defect_id", ""),
                "title": getattr(d, "title", ""),
                "description": getattr(d, "description", ""),
                "steps_to_reproduce": list(getattr(d, "steps_to_reproduce", []) or []),
                "severity": str(getattr(d, "severity", "")),
                "expected": getattr(d, "expected_behavior", ""),
                "actual": getattr(d, "actual_behavior", ""),
                "evidence": list(getattr(d, "evidence", []) or []),
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
    # Bind the evidence bundle to the exact screenshot bytes so a reviewer can
    # detect accidental or later substitution of a capture.
    import hashlib
    screenshot_hashes: dict[str, str] = {}
    for raw_path in snapshot["screenshots"]:
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = Path(get_settings().report_output_dir) / path
        try:
            if path.is_file():
                screenshot_hashes[str(raw_path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            logger.warning("screenshot_hash_failed", run_id=run_id, path=str(raw_path), error=str(exc))
    snapshot["screenshot_sha256"] = screenshot_hashes
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


# ── P1-09 (D9): session persistence + resume across worker restarts ──
#
# The previous implementation relied on in-memory SessionMemory, which is
# lost when the Celery worker process restarts (deployment, crash, OOM).
# We now snapshot SessionMemory to the configured SessionStore after every
# step, and restore it on worker startup. This proves that an interrupted
# run resumes safely without duplicate record changes or lost evidence.
#
# The snapshot key is ``session:<run_id>`` (Redis when store_type=redis;
# in-memory dict otherwise). The restore is idempotent — if no snapshot
# exists, the run starts fresh.

_SESSION_SNAPSHOT_TTL_SECONDS = 24 * 3600  # 24 hours


def _session_snapshot_key(run_id: str) -> str:
    return f"session:{run_id}"


def _serialize_session_memory(memory: Any) -> dict[str, Any]:
    """Serialize SessionMemory to a JSON-safe dict for the SessionStore."""
    try:
        return memory.model_dump(mode="json")
    except Exception:
        # Fallback: only persist the fields that are strictly JSON-safe
        return {
            "session_id": getattr(memory, "session_id", ""),
            "tenant_id": getattr(memory, "tenant_id", "unknown"),
            "goal": getattr(memory, "goal", ""),
            "persona": getattr(memory, "persona", None),
            "current_step_index": getattr(memory, "current_step_index", 0),
            "current_url": getattr(memory, "current_url", ""),
            "completed_steps_count": len(getattr(memory, "completed_steps", [])),
            "snapshot_at": datetime.now(UTC).isoformat(),
        }


async def _persist_session_snapshot(orchestrator: Any) -> bool:
    """Persist the orchestrator's SessionMemory to the SessionStore (async).

    P1-09: called after every completed step so an interrupted run can
    resume from the last persisted step. Uses the SessionStore abstraction
    so Redis is preferred (production) and in-memory is the dev fallback.
    """
    try:
        memory = getattr(orchestrator, "memory", None)
        if memory is None:
            return False
        from agent.api.v1.dependencies import get_session_store
        store = get_session_store(get_settings())
        payload = _serialize_session_memory(memory)
        await store.save(_session_snapshot_key(memory.session_id), payload)
        return True
    except Exception as e:
        logger.warning("session_snapshot_persist_failed: %s", e)
        return False


def _persist_session_snapshot_sync(orchestrator: Any) -> bool:
    """Sync fallback for contexts without a running event loop."""
    try:
        memory = getattr(orchestrator, "memory", None)
        if memory is None:
            return False
        from agent.api.v1.dependencies import get_session_store
        store = get_session_store(get_settings())
        payload = _serialize_session_memory(memory)
        # SessionStore.save is async — try to run it in a transient loop
        try:
            asyncio.run(store.save(_session_snapshot_key(memory.session_id), payload))
        except RuntimeError:
            # Already in a loop — fire-and-forget; the next async hook will
            # catch up. We do NOT block the run on this.
            pass
        return True
    except Exception as e:
        logger.warning("session_snapshot_persist_sync_failed: %s", e)
        return False


async def _restore_session_snapshot(orchestrator: Any) -> bool:
    """Restore SessionMemory from the persistent store (if any snapshot exists).

    Returns ``True`` if a snapshot was found and applied, ``False`` otherwise.
    On a successful restore, the orchestrator's memory is updated in place
    so the cognitive loop resumes from the last persisted step index.
    """
    try:
        memory = getattr(orchestrator, "memory", None)
        if memory is None:
            return False
        from agent.api.v1.dependencies import get_session_store
        store = get_session_store(get_settings())
        key = _session_snapshot_key(memory.session_id)
        if not await store.exists(key):
            return False
        payload = await store.load(key)
        if not isinstance(payload, dict):
            return False
        # Validate the snapshot is for this run (defense-in-depth against
        # key collisions or store corruption).
        if str(payload.get("session_id", "")) != str(memory.session_id):
            logger.warning(
                "session_snapshot_session_id_mismatch run_id=%s snapshot_id=%s",
                memory.session_id,
                payload.get("session_id"),
            )
            return False
        # P1-09: do NOT blindly overwrite the live memory — instead,
        # restore the persisted completed_steps, current_step_index,
        # failures, recovery_attempts, defect_verdicts, and timeline so
        # the cognitive loop skips already-completed steps and resumes
        # from where the run was interrupted. Goal, plan, and persona
        # come from the live orchestrator (they may have been refreshed
        # by set_test_case between snapshots).
        for field_name in (
            "completed_steps",
            "completed_validations",
            "failures",
            "recovery_attempts",
            "defect_verdicts",
            "timeline",
            "retest_packages",
        ):
            persisted_value = payload.get(field_name)
            if persisted_value is not None:
                try:
                    setattr(memory, field_name, persisted_value)
                except Exception:
                    pass
        # Restore step index — must match the persisted completed_steps
        # so the loop does not re-execute already-completed steps.
        persisted_step_index = payload.get("current_step_index")
        if isinstance(persisted_step_index, int) and persisted_step_index > 0:
            memory.current_step_index = persisted_step_index
        # Restore telemetry counters so the report isn't double-counting.
        for counter_name in (
            "total_actions_executed",
            "total_validations_run",
            "total_failures",
            "total_recoveries",
            "planner_calls",
            "moondream_calls",
            "gemini_calls",
            "verification_calls",
        ):
            persisted = payload.get(counter_name)
            if isinstance(persisted, int):
                setattr(memory, counter_name, persisted)
        retest_manager = getattr(orchestrator, "_retest_chain_manager", None)
        if retest_manager is not None:
            retest_manager.restore_packages(memory.retest_packages)
        return True
    except Exception as e:
        logger.warning("session_snapshot_restore_failed: %s", e)
        return False


async def _clear_session_snapshot(orchestrator: Any) -> None:
    """Clear the persisted session snapshot (called when the run completes)."""
    try:
        memory = getattr(orchestrator, "memory", None)
        if memory is None:
            return
        from agent.api.v1.dependencies import get_session_store
        store = get_session_store(get_settings())
        await store.delete(_session_snapshot_key(memory.session_id))
    except Exception as e:
        logger.warning("session_snapshot_clear_failed: %s", e)


async def _run_agent_async(run_id: str, goal: str, tenant_id: str, test_case_id: str | None = None, persona: str | None = None, tc_data: dict[str, Any] | None = None) -> None:
    """Async wrapper to run the orchestrator and update the DB."""

    settings = get_settings()

    # INC-UAT-01 (Blocker): verify benchmark is running under a declared
    # persona, NOT administrator credentials. If require_persona_for_benchmark
    # is True and no valid persona is set, the run is rejected before
    # touching the ServiceNow instance.
    if persona:
        settings.servicenow.active_persona = persona
        # API callers cannot bypass the safety policy by omitting the process
        # environment flag. Any explicitly persona-scoped run is held to the
        # non-admin and declared-role checks.
        settings.servicenow.require_persona_for_benchmark = True
    settings.servicenow.verify_persona_for_benchmark()

    # The declared role is a local persona label. Do not query sys_user_has_role
    # through Table API: that table is not necessarily visible to this UAT
    # persona in the ServiceNow UI. Actual permissions are tested through the
    # persona's browser-visible Incident actions and ACL negative scenarios.
    if settings.servicenow.require_persona_for_benchmark and not settings.servicenow.get_persona_role():
        raise RuntimeError("A benchmark persona must declare its expected Incident role.")

    # INC-UAT-03 (Major): enforce oracle persona constraint when a
    # persona is active — the API oracle should only query persona-visible
    # fields, not privileged server-side audit data.
    if settings.servicenow.active_persona:
        settings.servicenow.oracle_persona_constrained = True
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

            # Hook incremental perception writes after each step AND
            # snapshot session memory to the persistent store so an
            # interrupted run (worker restart, crash) can resume without
            # losing completed-step evidence.
            def _on_step(step: Any, mem: Any) -> None:
                _build_perception_evidence(run_id, orchestrator)
                # P1-09 (D9): persist session memory snapshot to the
                # SessionStore so resume-after-restart is possible.
                try:
                    asyncio.ensure_future(_persist_session_snapshot(orchestrator))
                except RuntimeError:
                    # No running loop — fall back to fire-and-forget
                    try:
                        _persist_session_snapshot_sync(orchestrator)
                    except Exception as persist_err:
                        logger.warning(
                            "session_snapshot_persist_failed: %s", persist_err
                        )

            setattr(orchestrator, "_on_step_complete", _on_step)

            # P1-09 (D9): if a prior session snapshot exists in the
            # SessionStore (e.g., the worker was restarted mid-run),
            # restore it so the agent resumes from the interrupted step
            # instead of restarting from scratch. Without this, a worker
            # crash mid-run would silently re-execute all completed steps
            # and could cause duplicate record mutations.
            try:
                restored = await _restore_session_snapshot(orchestrator)
                if restored:
                    logger.info(
                        "session_restored_from_persistent_store run_id=%s "
                        "completed_steps=%d",
                        run_id,
                        len(orchestrator.memory.completed_steps),
                    )
                    await publisher.publish(
                        "run_resumed",
                        {
                            "reason": "session_restored_from_persistent_store",
                            "completed_steps": len(orchestrator.memory.completed_steps),
                        },
                    )
            except Exception as restore_err:
                logger.warning(
                    "session_restore_failed run_id=%s: %s", run_id, restore_err
                )

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
            # Propagate tenant_id to SessionMemory so StepCache (audit issue I25)
            # and other tenant-scoped consumers can scope their caches correctly.
            orchestrator.memory.tenant_id = tenant_id or "unknown"
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
        # P1-09 (D9): clear the persisted session snapshot once the run
        # has reached a terminal state. A resumed run will start fresh;
        # a snapshot left in Redis would falsely suggest an in-progress run
        # on the next worker startup.
        if orchestrator is not None:
            try:
                await _clear_session_snapshot(orchestrator)
            except Exception as clear_err:
                logger.warning("session_snapshot_clear_failed: %s", clear_err)


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


