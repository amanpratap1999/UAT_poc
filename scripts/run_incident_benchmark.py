#!/usr/bin/env python3
"""Execute the Incident UAT golden-scenario benchmark (INC-UAT-10).

Runs each golden scenario 3 times, collects TP/FN/FP/misclassification/
consistency metrics, and saves the results to a JSON file.

INC-UAT-10 (Major): 3-run consistency benchmark exists but actual results
are absent. This script provides the execution entry point that operators
run against a live ServiceNow subproduction instance with the golden
environment seeded.

P0-02 (Blocker, I12; persona gate): the local QA-API token used to enqueue
and poll runs is now obtained and validated SEPARATELY from the ServiceNow
persona credentials. The QA API authenticates against the local FastAPI
``/api/v1/token`` endpoint using a QA Engineer / QA Manager account
configured on the API host — never the ServiceNow persona account. The
ServiceNow persona credentials live in ``SERVICENOW_PERSONAS`` and are
used ONLY by the worker to drive the browser. No admin-account run is
counted as persona evidence — see ``verify_persona_for_benchmark`` gate
preserved below.

Usage:
    python scripts/run_incident_benchmark.py \
        --instance-url https://devXXXXX.service-now.com \
        --persona <persona_name> \
        --api-base-url http://localhost:8000 \
        --qa-api-username <qa_engineer_or_manager_username> \
        --qa-api-password <qa_engineer_or_manager_password> \
        [--runs 3] [--output reports/benchmark_results.json]

    # Or supply a pre-issued QA API JWT directly:
    python scripts/run_incident_benchmark.py \
        --instance-url https://devXXXXX.service-now.com \
        --persona <persona_name> \
        --qa-api-token <JWT> \
        [--api-base-url http://localhost:8000] [--runs 3]

Environment variables (preferred over CLI for secrets):
    QA_API_USERNAME     QA Engineer or QA Manager username on the local API
    QA_API_PASSWORD     matching password
    QA_API_TOKEN        pre-issued JWT (skips the login round-trip)

Prerequisites:
    1. Seed the golden environment first:
       python scripts/seed_golden_environment.py --instance-url ... --username ... --password ...
    2. Configure .env.local with LLM API keys + persona credentials
    3. Start the API + worker services
    4. Run this script
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from datetime import datetime, UTC

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.testing.benchmark_runner import IncidentBenchmarkRunner, BenchmarkMetrics
from agent.testing.golden_environment import get_default_manifest


_DEFECT_SIGNATURES: dict[str, tuple[str, ...]] = {
    "wrong_priority": ("priority", "impact", "urgency"),
    "bad_assignment": ("assignment", "group"),
    "missing_mandatory_field": ("close code", "close_code", "resolution code"),
    "illegal_transition": ("state", "transition", "closed"),
    "acl_violation": ("acl", "access", "work notes", "another user"),
    "notification_failure": ("notification", "email", "recipient"),
    "dependent_choice_error": ("subcategory", "category"),
    "by_design_customization": ("x_custom_flag", "by-design"),
    "sla_breach": ("sla", "breach", "deadline"),
    "prompt_injection": ("injection", "ignore your instructions", "untrusted"),
    "fix_retest": ("retest", "regression", "fixed"),
    "interruption_recovery": ("resume", "interruption", "duplicate"),
    "repeatability": ("consistency", "repeat"),
    "clean_incident": ("mandatory", "valid"),
}


def _finding_matches_seed(
    finding: dict,
    defect,
    target_number: str,
    target_sys_id: str,
) -> bool:
    """Require a target-record reference and a defect-specific signal.

    The benchmark never treats an empty description, a generic PASS/FAIL, or
    the scenario prompt itself as evidence that a defect was detected.
    """
    evidence_parts = [
        finding.get("title", ""), finding.get("description", ""),
        finding.get("expected", ""), finding.get("actual", ""),
        finding.get("expected_behavior", ""), finding.get("actual_behavior", ""),
        *finding.get("steps_to_reproduce", []), *finding.get("evidence", []),
    ]
    text = " ".join(str(part) for part in evidence_parts).lower()
    target_linked = (
        target_number.lower() in text
        or target_sys_id.lower() in text
    )
    if not text.strip() or not target_linked:
        return False
    if defect.defect_type == "clean_incident":
        return True  # any target-linked product-defect report is a false alarm on the control
    signature = _DEFECT_SIGNATURES.get(defect.defect_type, ())
    return any(term in text for term in signature)


async def _obtain_qa_api_token(
    api_base_url: str,
    username: str,
    password: str,
) -> str:
    """Authenticate against the LOCAL QA API and return a JWT.

    P0-02 (persona gate): this is the local FastAPI ``/api/v1/token``
    endpoint with OAuth2 password flow. The credentials here belong to a
    QA Engineer / QA Manager account provisioned on the local API host
    (see ``scripts/bootstrap_admin.py``) and are SEPARATE from the
    ServiceNow persona credentials (``SERVICENOW_PERSONAS``) used by the
    worker to drive the browser. We never accept the ServiceNow persona
    password as a QA API password.
    """
    import httpx

    async with httpx.AsyncClient(base_url=api_base_url, timeout=15.0) as client:
        response = await client.post(
            "/api/v1/token",
            data={"username": username, "password": password, "grant_type": "password"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise ValueError(
                f"QA API login failed (HTTP {response.status_code}): "
                f"{response.text[:200]}. Verify the local API service is running "
                f"and that QA_API_USERNAME/QA_API_PASSWORD belong to a QA Engineer or "
                f"QA Manager user (NOT the ServiceNow persona)."
            )
        token = response.json().get("access_token")
        if not token:
            raise ValueError("QA API token response did not contain access_token.")
        return token


async def _verify_runtime_services(api_base_url: str, qa_token: str) -> None:
    """P0-02 (I12; benchmark cannot currently start): probe readiness before
    any benchmark run is enqueued. Raises ``RuntimeError`` if the local API,
    Postgres+pgvector, Redis, or embedding client is not healthy — so we
    never silently enqueue runs against an unhealthy worker and then
    interpret the resulting timeouts as agent failures.
    """
    import httpx

    async with httpx.AsyncClient(base_url=api_base_url, timeout=15.0) as client:
        try:
            response = await client.get("/api/v1/ready")
        except Exception as e:
            raise RuntimeError(
                f"QA API readiness probe failed: {e}. "
                f"Start the API service (e.g. scripts/start-local.ps1) and try again."
            ) from e
        if response.status_code != 200:
            raise RuntimeError(
                f"QA API is not ready (HTTP {response.status_code}): {response.text[:300]}. "
                f"Resolve Postgres/Redis/embedding health before running the benchmark."
            )
        body = response.json() if response.content else {}
        if isinstance(body, dict) and body.get("status") not in (None, "ok", "healthy", "ready"):
            raise RuntimeError(
                f"QA API readiness probe returned non-healthy status: {body}. "
                f"Check Postgres+pgvector, Redis, and embedding client configuration."
            )

        # Confirm the API can see this worker (so queued runs actually execute)
        try:
            worker_probe = await client.get("/api/v1/health")
            if worker_probe.status_code != 200:
                raise RuntimeError(
                    f"QA API /health returned HTTP {worker_probe.status_code}."
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"QA API /health probe failed: {e}. The API is up but the "
                f"/health endpoint is unreachable — confirm the service is stable."
            ) from e

        # Confirm the QA token is actually valid for enqueuing runs
        try:
            auth_check = await client.get(
                "/api/v1/runs",
                headers={"Authorization": f"Bearer {qa_token}"},
            )
            if auth_check.status_code == 401:
                raise RuntimeError(
                    "QA API token is invalid or expired. Re-issue with QA_API_USERNAME/QA_API_PASSWORD."
                )
            if auth_check.status_code == 403:
                raise RuntimeError(
                    "QA API account lacks the QA Engineer / QA Manager role required to enqueue runs."
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to validate QA API token against /api/v1/runs: {e}"
            ) from e


async def run_benchmark(
    instance_url: str,
    persona: str | None,
    runs: int = 3,
    api_base_url: str = "http://localhost:8000",
    qa_api_token: str | None = None,
    seed_manifest_path: str = "reports/golden_environment_manifest.json",
) -> BenchmarkMetrics:
    """Execute the benchmark by calling the API for each scenario + run.

    P0-02: the ``qa_api_token`` parameter REPLACES the legacy
    ``admin_token`` parameter. It is the local QA-API JWT, NOT a
    ServiceNow admin credential. The benchmark refuses to start without it.
    """
    import httpx
    from urllib.parse import urlparse
    from agent.core.config import get_settings

    if not persona:
        raise ValueError(
            "A named non-admin ServiceNow persona is required for an Incident benchmark."
        )
    if not qa_api_token:
        raise ValueError(
            "A local QA-API token is required to enqueue and poll benchmark runs. "
            "Provide --qa-api-token or set QA_API_USERNAME/QA_API_PASSWORD. "
            "The QA-API token is separate from the ServiceNow persona credentials."
        )
    if runs < 3:
        raise ValueError("At least three runs per scenario are required for a scored benchmark.")

    settings = get_settings()
    requested_host = (urlparse(instance_url).hostname or "").lower()
    configured_host = (urlparse(settings.servicenow.instance_url).hostname or "").lower()
    if not requested_host or requested_host != configured_host:
        raise ValueError("Requested instance does not match SERVICENOW_INSTANCE_URL in the worker configuration.")

    # Preserve the existing safety gates — these are the persona/sub-production
    # /mutation/fixture gates called out in the table. We MUST NOT relax them.
    settings.servicenow.active_persona = persona
    settings.servicenow.require_persona_for_benchmark = True
    settings.servicenow.verify_persona_for_benchmark()
    if not settings.servicenow.is_subproduction:
        raise ValueError("Scored benchmarks require SERVICENOW_IS_SUBPRODUCTION=true.")
    if not settings.servicenow.allow_mutations:
        raise ValueError("Scored benchmarks require explicit SERVICENOW_ALLOW_MUTATIONS=true.")
    if requested_host not in {host.lower() for host in settings.servicenow.allowed_instances}:
        raise ValueError("Requested host is not listed in SERVICENOW_ALLOWED_INSTANCES.")

    # P0-02: probe runtime services BEFORE enqueuing any runs. A failed
    # readiness check is an INFRA_ERROR, not a silent PASS.
    await _verify_runtime_services(api_base_url, qa_api_token)

    seed_path = Path(seed_manifest_path)
    if not seed_path.is_file():
        raise FileNotFoundError(f"Seed manifest not found: {seed_path}")
    seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
    if seed_data.get("dry_run"):
        raise ValueError("A dry-run seed manifest cannot be used for scored results.")
    seed_host = (urlparse(seed_data.get("instance_url", "")).hostname or "").lower()
    if seed_host != requested_host:
        raise ValueError("Seed manifest instance does not match the requested instance.")
    seeded_records = seed_data.get("defects", {})

    manifest = get_default_manifest()
    missing_targets = [
        d.defect_id for d in manifest.defects
        if not str(seeded_records.get(d.defect_id, {}).get("incident_number", "")).strip()
        or not str(seeded_records.get(d.defect_id, {}).get("sys_id", "")).strip()
        or seeded_records.get(d.defect_id, {}).get("verification_status") != "PERSISTED"
        or seeded_records.get(d.defect_id, {}).get("defect_verification_status")
        != ("VERIFIED_DECOY" if d.is_decoy else "VERIFIED_DEFECT")
        or seeded_records.get(d.defect_id, {}).get("error")
    ]
    if missing_targets:
        raise ValueError(
            "Seed manifest is not scoreable; every entry needs a persisted record and an "
            "independently verified seeded condition (VERIFIED_DEFECT or VERIFIED_DECOY): "
            + ", ".join(missing_targets)
        )
    runner = IncidentBenchmarkRunner(manifest=manifest)

    async def scenario_executor(scenario: str, run_num: int):
        """Execute a single golden scenario via the API."""
        from agent.testing.benchmark_runner import ScenarioResult

        # Build the goal for this scenario
        defect = next(
            (d for d in manifest.defects if d.test_scenario == scenario),
            None,
        )
        if not defect:
            return ScenarioResult(
                test_scenario=scenario,
                run_number=run_num,
                verdict="BLOCKED",
                detection_description=f"Unknown scenario: {scenario}",
            )

        seeded = seeded_records.get(defect.defect_id, {})
        target_number = str(seeded.get("incident_number", "")).strip()
        target_sys_id = str(seeded.get("sys_id", "")).strip()
        if not target_number or not target_sys_id or seeded.get("error"):
            return ScenarioResult(
                test_scenario=scenario,
                run_number=run_num,
                verdict="INFRA_ERROR",
                detection_description=f"No successfully seeded target for {defect.defect_id}.",
            )
        goal = (
            f"Incident UAT scenario {scenario}. Inspect incident "
            f"{target_number} through the assigned persona UI. Inspect its configured UAT conditions "
            "and report any observed deviation from expected ServiceNow behavior. "
            "Do not treat the tracking ID or description as proof of a defect. Re-read the record "
            "after actions and report only observed outcomes."
        )

        print(f"  [{scenario}] Run {run_num}/{runs}: {goal[:60]}...")

        # P0-05: validate authentication before executing the benchmark.
        # Return a clear setup error if credentials are absent or invalid.
        # Do NOT report an unexecuted benchmark as a pass.
        if not qa_api_token:
            print(f"    [ERROR] no QA API token — benchmark cannot execute")
            return ScenarioResult(
                test_scenario=scenario,
                run_number=run_num,
                verdict="INFRA_ERROR",
                detection_description="No QA API token provided — benchmark setup error. Do not count this as a pass.",
            )

        try:
            async with httpx.AsyncClient(base_url=api_base_url, timeout=300) as client:
                # Start a run with the persona
                response = await client.post(
                    "/api/v1/runs",
                    json={
                        "goal": goal,
                        "persona": persona,
                    },
                    headers={"Authorization": f"Bearer {qa_api_token}"},
                )
                response.raise_for_status()
                run_data = response.json()
                run_id = run_data.get("session_id") or run_data.get("run_id", "")
                if not run_id:
                    return ScenarioResult(
                        test_scenario=scenario,
                        run_number=run_num,
                        verdict="INFRA_ERROR",
                        detection_description="Run creation response did not contain a run_id.",
                    )

                # Poll for completion
                finished = False
                for _ in range(120):  # max 10 min
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        f"/api/v1/runs/{run_id}",
                        headers={"Authorization": f"Bearer {qa_api_token}"},
                    )
                    status_resp.raise_for_status()
                    run_status = status_resp.json()
                    if run_status.get("status") in (
                        "completed", "passed", "failed", "cancelled", "blocked",
                        "precondition_failed", "error", "infra_error",
                    ):
                        finished = True
                        break

                if not finished:
                    return ScenarioResult(
                        test_scenario=scenario,
                        run_number=run_num,
                        verdict="INFRA_ERROR",
                        detection_description=f"Run {run_id} exceeded the 10-minute benchmark timeout.",
                    )

                # Get the report
                report_resp = await client.get(
                    f"/api/v1/runs/{run_id}",
                    headers={"Authorization": f"Bearer {qa_api_token}"},
                )
                report = report_resp.json()

                # Determine the verdict
                status = report.get("status", "unknown")
                exit_criteria = report.get("exit_criteria", {})
                verdict = str(exit_criteria.get("verdict", "")).upper()
                if verdict not in {"PASS", "FAIL", "BLOCKED", "CANNOT_VERIFY"}:
                    verdict = "INFRA_ERROR" if status not in {"completed", "passed"} else "CANNOT_VERIFY"

                # Check if the agent detected the defect
                findings = report.get("defects", report.get("findings", []))
                detected_defect_id = None
                for finding in findings:
                    if _finding_matches_seed(finding, defect, target_number, target_sys_id):
                        detected_defect_id = defect.defect_id
                        break

                return ScenarioResult(
                    test_scenario=scenario,
                    run_number=run_num,
                    verdict=verdict,
                    detected_defect_id=detected_defect_id,
                    detection_description=(
                        f"Matched {defect.defect_id} on {target_number}"
                        if detected_defect_id
                        else f"No target-linked finding matched {defect.defect_id} on {target_number}"
                    ),
                    actions_taken=report.get("total_actions", 0),
                    evidence_count=len(report.get("step_evidence", [])),
                    # P3-07: event-based human intervention counting.
                    # Count actual approval/clarification/escalation events
                    # from the run timeline, not a hardcoded 0.
                    # Missing event instrumentation is unknown, not zero human help.
                    human_intervention_steps=(
                        int(report["human_intervention_steps"])
                        if report.get("human_intervention_steps") is not None
                        else None
                    ),
                )
        except Exception as e:
            print(f"    ERROR: {e}")
            return ScenarioResult(
                test_scenario=scenario,
                run_number=run_num,
                verdict="ERROR",
                detection_description=str(e),
            )

    metrics = await runner.run_benchmark(
        scenario_executor=scenario_executor,
        runs_per_scenario=runs,
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the Incident UAT golden-scenario benchmark")
    parser.add_argument("--instance-url", required=True, help="ServiceNow instance URL")
    parser.add_argument("--persona", required=True, help="Configured non-admin persona name (e.g., itil_user)")
    parser.add_argument("--runs", type=int, default=3, help="Runs per scenario (default 3)")
    parser.add_argument("--api-base-url", default="http://localhost:8000", help="Local QA API base URL")
    # P0-02: the QA API token is now obtained SEPARATELY from the ServiceNow
    # persona creds. Accept either a pre-issued JWT or QA-API login
    # credentials (env-separated from the ServiceNow persona configuration).
    parser.add_argument(
        "--qa-api-token",
        default=os.environ.get("QA_API_TOKEN", ""),
        help=(
            "Pre-issued local QA-API JWT (preferred for CI). If omitted, the "
            "script will authenticate against /api/v1/token using QA_API_USERNAME "
            "and QA_API_PASSWORD. This is NOT the ServiceNow persona credential."
        ),
    )
    parser.add_argument(
        "--qa-api-username",
        default=os.environ.get("QA_API_USERNAME", ""),
        help="Local QA-API username (QA Engineer or QA Manager). Env: QA_API_USERNAME",
    )
    parser.add_argument(
        "--qa-api-password",
        default=os.environ.get("QA_API_PASSWORD", ""),
        help="Local QA-API password. Env: QA_API_PASSWORD",
    )
    parser.add_argument("--seed-manifest", default="reports/golden_environment_manifest.json", help="Verified seed manifest produced by seed_golden_environment.py")
    parser.add_argument("--output", default="reports/benchmark_results.json", help="Output results file")
    args = parser.parse_args()

    print(f"[*] Starting Incident UAT Benchmark")
    print(f"    Instance: {args.instance_url}")
    print(f"    Persona: {args.persona or '(default)'}")
    print(f"    Runs per scenario: {args.runs}")
    print(f"    API: {args.api_base_url}")

    # P0-02: obtain the QA-API token via the LOCAL API, completely separate
    # from the ServiceNow persona credentials. We never accept a ServiceNow
    # persona password as the QA API password.
    qa_api_token = args.qa_api_token.strip()
    if not qa_api_token:
        if not (args.qa_api_username and args.qa_api_password):
            raise SystemExit(
                "Benchmark cannot start: no QA API credentials supplied. "
                "Provide --qa-api-token, or set QA_API_USERNAME and QA_API_PASSWORD "
                "(QA Engineer or QA Manager account on the local API). These are "
                "SEPARATE from the ServiceNow persona credentials in SERVICENOW_PERSONAS."
            )
        print(f"[*] Authenticating to local QA API as {args.qa_api_username}...")
        qa_api_token = asyncio.run(_obtain_qa_api_token(
            api_base_url=args.api_base_url,
            username=args.qa_api_username,
            password=args.qa_api_password,
        ))
        print(f"    QA-API token obtained (len={len(qa_api_token)})")
    else:
        print(f"[*] Using supplied QA-API token (len={len(qa_api_token)})")

    metrics = asyncio.run(run_benchmark(
        instance_url=args.instance_url,
        persona=args.persona,
        runs=args.runs,
        api_base_url=args.api_base_url,
        qa_api_token=qa_api_token,
        seed_manifest_path=args.seed_manifest,
    ))

    # P2-11 (D8/D10/D11): build a human-baseline comparison + run-to-run
    # variance section so a reviewer can see agent-vs-human time / defect
    # yield, plus run-to-run consistency. Requires the benchmark metrics'
    # per-scenario results.
    try:
        from agent.testing.human_baseline import (
            AgentRunMeasurement,
            build_baseline_comparison_section,
        )
        measurements_by_scenario: dict[str, list[AgentRunMeasurement]] = {}
        for sr in metrics.scenario_results:
            scenario_id = sr.test_scenario
            measurements_by_scenario.setdefault(scenario_id, []).append(
                AgentRunMeasurement(
                    run_id=f"{scenario_id}#run{sr.run_number}",
                    scenario_id=scenario_id,
                    agent_time_seconds=float(sr.duration_seconds or 0.0),
                    agent_defects_found=int(
                        1 if (sr.detected_defect_id and sr.verdict == "PASS") else 0
                    ),
                    verdict=sr.verdict,
                )
            )
        baseline_comparison = build_baseline_comparison_section(measurements_by_scenario)
    except Exception as e:
        baseline_comparison = {
            "human_baseline_loaded": False,
            "error": f"baseline comparison failed: {e}",
        }

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_data = {
        "executed_at": datetime.now(UTC).isoformat(),
        "instance_url": args.instance_url,
        "persona": args.persona,
        "runs_per_scenario": args.runs,
        "qa_api_username": args.qa_api_username or "(token-supplied)",
        "seed_manifest_sha256": hashlib.sha256(Path(args.seed_manifest).read_bytes()).hexdigest(),
        "metrics": metrics.to_dict(),
        # P2-11 (D8/D10/D11): variance + human-baseline comparison
        "baseline_comparison": baseline_comparison,
    }
    output_path.write_text(json.dumps(results_data, indent=2, default=str))

    print(f"\n[+] Benchmark complete!")
    print(f"    Results saved to: {output_path}")
    print(f"    Recall: {metrics.recall:.1%}")
    print(f"    Precision: {metrics.precision:.1%}")
    print(f"    Consistency: {metrics.consistency_rate:.1%}")
    print(f"    TP: {metrics.true_positives}, FN: {metrics.false_negatives}, FP: {metrics.false_positives}")


if __name__ == "__main__":
    main()
