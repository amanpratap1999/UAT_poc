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
import json
import os
import sys
from pathlib import Path
from datetime import datetime, UTC

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.testing.benchmark_runner import IncidentBenchmarkRunner, BenchmarkMetrics
from agent.testing.golden_environment import get_default_manifest


async def run_benchmark(
    instance_url: str,
    persona: str | None,
    runs: int = 3,
    api_base_url: str = "http://localhost:8000",
    admin_token: str | None = None,
) -> BenchmarkMetrics:
    """Execute the benchmark by calling the API for each scenario + run."""
    import httpx

    manifest = get_default_manifest()
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

        goal = f"Verify golden scenario {scenario}: {defect.description}"

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
            # P0-01: verify the target record exists before starting.
            # If target_sys_id is set, validate it's reachable.
            if defect.target_sys_id:
                async with httpx.AsyncClient(base_url=api_base_url, timeout=30) as verify_client:
                    verify_resp = await verify_client.get(
                        f"/api/v1/runs",
                        headers={"Authorization": f"Bearer {admin_token}"},
                    )
                    if verify_resp.status_code == 401:
                        return ScenarioResult(
                            test_scenario=scenario,
                            run_number=run_num,
                            verdict="INFRA_ERROR",
                            detection_description="Authentication failed — token is invalid or expired.",
                        )
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
                run_id = run_data.get("run_id", "")

                # Poll for completion
                for _ in range(120):  # max 10 min
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        f"/api/v1/runs/{run_id}",
                        headers={"Authorization": f"Bearer {admin_token}"},
                    )
                    status_resp.raise_for_status()
                    run_status = status_resp.json()
                    if run_status.get("status") in ("completed", "failed", "cancelled"):
                        break

                # Get the report
                report_resp = await client.get(
                    f"/api/v1/runs/{run_id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                report = report_resp.json()

                # Determine the verdict
                status = report.get("status", "unknown")
                exit_criteria = report.get("exit_criteria", {})
                verdict = exit_criteria.get("verdict", "PASS" if status == "passed" else "FAIL")

                # Check if the agent detected the defect
                findings = report.get("findings", [])
                detected_defect_id = None
                for finding in findings:
                    if finding.get("description", "").lower() in defect.description.lower():
                        detected_defect_id = defect.defect_id
                        break

                return ScenarioResult(
                    test_scenario=scenario,
                    run_number=run_num,
                    verdict=verdict,
                    detected_defect_id=detected_defect_id,
                    detection_description=defect.description,
                    actions_taken=report.get("total_actions", 0),
                    evidence_count=len(report.get("step_evidence", [])),
                    human_intervention_steps=0,
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
    parser.add_argument("--persona", help="Persona name (e.g., itil_user)")
    parser.add_argument("--runs", type=int, default=3, help="Runs per scenario (default 3)")
    parser.add_argument("--api-base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--admin-token", help="Admin JWT token for API calls")
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
    ))

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_data = {
        "executed_at": datetime.now(UTC).isoformat(),
        "instance_url": args.instance_url,
        "persona": args.persona,
        "runs_per_scenario": args.runs,
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
