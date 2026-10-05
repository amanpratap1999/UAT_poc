#!/usr/bin/env python3
"""Execute the Incident UAT golden-scenario benchmark (INC-UAT-10).

Runs each golden scenario 3 times, collects TP/FN/FP/misclassification/
consistency metrics, and saves the results to a JSON file.

INC-UAT-10 (Major): 3-run consistency benchmark exists but actual results
are absent. This script provides the execution entry point that operators
run against a live ServiceNow subproduction instance with the golden
environment seeded.

Usage:
    python scripts/run_incident_benchmark.py \
        --instance-url https://devXXXXX.service-now.com \
        --username <persona_username> --password <persona_password> \
        --persona <persona_name> \
        [--runs 3] [--output reports/benchmark_results.json]

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


async def run_benchmark(
    instance_url: str,
    persona: str | None,
    runs: int = 3,
    api_base_url: str = "http://localhost:8000",
    admin_token: str | None = None,
    seed_manifest_path: str = "reports/golden_environment_manifest.json",
) -> BenchmarkMetrics:
    """Execute the benchmark by calling the API for each scenario + run."""
    import httpx
    from urllib.parse import urlparse
    from agent.core.config import get_settings

    if not persona:
        raise ValueError("A named non-admin ServiceNow persona is required for an Incident benchmark.")
    if not admin_token:
        raise ValueError("A local QA-engineer API token is required to start and read benchmark runs.")
    if runs < 3:
        raise ValueError("At least three runs per scenario are required for a scored benchmark.")
    settings = get_settings()
    requested_host = (urlparse(instance_url).hostname or "").lower()
    configured_host = (urlparse(settings.servicenow.instance_url).hostname or "").lower()
    if not requested_host or requested_host != configured_host:
        raise ValueError("Requested instance does not match SERVICENOW_INSTANCE_URL in the worker configuration.")
    settings.servicenow.active_persona = persona
    settings.servicenow.require_persona_for_benchmark = True
    settings.servicenow.verify_persona_for_benchmark()
    if not settings.servicenow.is_subproduction:
        raise ValueError("Scored benchmarks require SERVICENOW_IS_SUBPRODUCTION=true.")
    if not settings.servicenow.allow_mutations:
        raise ValueError("Scored benchmarks require explicit SERVICENOW_ALLOW_MUTATIONS=true.")
    if requested_host not in {host.lower() for host in settings.servicenow.allowed_instances}:
        raise ValueError("Requested host is not listed in SERVICENOW_ALLOWED_INSTANCES.")

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
        if not admin_token:
            print(f"    [ERROR] no admin token — benchmark cannot execute")
            return ScenarioResult(
                test_scenario=scenario,
                run_number=run_num,
                verdict="INFRA_ERROR",
                detection_description="No API token provided — benchmark setup error. Do not count this as a pass.",
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
                    headers={"Authorization": f"Bearer {admin_token}"},
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
                        headers={"Authorization": f"Bearer {admin_token}"},
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
                    headers={"Authorization": f"Bearer {admin_token}"},
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
    parser.add_argument("--api-base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--admin-token", help="Admin JWT token for API calls")
    parser.add_argument("--seed-manifest", default="reports/golden_environment_manifest.json", help="Verified seed manifest produced by seed_golden_environment.py")
    parser.add_argument("--output", default="reports/benchmark_results.json", help="Output results file")
    args = parser.parse_args()

    print(f"[*] Starting Incident UAT Benchmark")
    print(f"    Instance: {args.instance_url}")
    print(f"    Persona: {args.persona or '(default)'}")
    print(f"    Runs per scenario: {args.runs}")
    print(f"    API: {args.api_base_url}")

    metrics = asyncio.run(run_benchmark(
        instance_url=args.instance_url,
        persona=args.persona,
        runs=args.runs,
        api_base_url=args.api_base_url,
        admin_token=args.admin_token,
        seed_manifest_path=args.seed_manifest,
    ))

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_data = {
        "executed_at": datetime.now(UTC).isoformat(),
        "instance_url": args.instance_url,
        "persona": args.persona,
        "runs_per_scenario": args.runs,
        "seed_manifest_sha256": hashlib.sha256(Path(args.seed_manifest).read_bytes()).hexdigest(),
        "metrics": metrics.to_dict(),
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
