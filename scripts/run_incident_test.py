"""Standalone Manual Acceptance Test Runner for ServiceNow IncidentSkill.

Executes natural language goals against a configured ServiceNow instance.
Usage:
    python scripts/run_incident_test.py --goal "Open any existing Incident in New state and validate the complete Incident flow."  # noqa: E501
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent.api.v1.dependencies import get_cached_settings
from agent.main import create_orchestrator


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ServiceNow IncidentSkill QA Agent against live instance."
    )
    parser.add_argument(
        "--goal",
        type=str,
        default="Open any existing Incident in New state and validate the complete Incident flow.",
        help="Natural language testing goal",
    )
    args = parser.parse_args()

    print("=== Starting Autonomous Incident QA Agent ===")
    print(f"Goal: {args.goal}")

    settings = get_cached_settings()
    orchestrator = create_orchestrator(settings)

    report = await orchestrator.run(args.goal)

    print("\n=== Execution Completed ===")
    print(f"Report ID: {report.report_id}")
    print(f"Status: {report.status.upper()}")
    print(f"Validations Passed: {report.passed_validations}/{report.total_validations}")
    print(f"Defects Identified: {len(report.defects)}")
    print(f"Report File: {orchestrator.report_file}")

    # Keep a headed local Playwright window and its visual cursor alive for
    # manual inspection until the user closes that browser window.
    await orchestrator.wait_for_manual_browser_close()


if __name__ == "__main__":
    asyncio.run(main())
