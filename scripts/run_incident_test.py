"""Standalone Manual Acceptance Test Runner for ServiceNow IncidentSkill.

Executes natural language goals against a configured ServiceNow instance.

P1-06 (D2; persona gate): the runner now accepts an explicit ``--persona``
flag (defaulting to ``settings.servicenow.active_persona``), and
independently verifies the persona's role via ``RoleVerifier`` before
starting the run. For requester-role scenarios (read-only access checks),
a separate ``--requester-persona`` is supported — one itil account cannot
demonstrate role separation.

Usage:
    # itil persona (default for lifecycle / mutation tests)
    python scripts/run_incident_test.py \\
        --goal "Open any existing Incident in New state and validate the complete Incident flow." \\
        --persona itil_user

    # requester persona (for ACL / read-only access tests)
    python scripts/run_incident_test.py \\
        --goal "Read-only inspect incident INC0010041 state and priority." \\
        --persona requester_user

    # Provision multiple personas for a multi-role sweep
    python scripts/run_incident_test.py \\
        --goal "Compare itil vs requester access on INC0010041" \\
        --persona itil_user \\
        --requester-persona requester_user
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent.api.v1.dependencies import get_cached_settings
from agent.core.logging import get_logger
from agent.main import create_orchestrator

logger = get_logger(__name__)


async def _verify_persona_role(
    settings,
    persona: str,
    expected_role: str | None = None,
) -> dict:
    """P1-06: independently confirm the persona's actual ServiceNow role
    matches the declared role before starting the run. One ``itil`` account
    cannot demonstrate role separation — the verifier surfaces mismatches
    as setup errors rather than letting a requester-scoped test silently
    run with elevated privileges.
    """
    try:
        from agent.skills.incident.role_verifier import RoleVerifier
    except ImportError as e:
        logger.warning("role_verifier_unavailable", error=str(e))
        return {"verified": False, "reason": f"RoleVerifier import failed: {e}"}

    # Build a transient config with the persona selected so RoleVerifier
    # authenticates against ServiceNow as that persona.
    persona_settings = settings.model_copy(deep=True)
    persona_settings.servicenow.active_persona = persona
    persona_settings.servicenow.require_persona_for_benchmark = True
    try:
        persona_settings.servicenow.verify_persona_for_benchmark()
    except Exception as e:
        return {"verified": False, "reason": f"Persona policy violation: {e}"}

    verifier = RoleVerifier()
    try:
        result = await verifier.verify_role(
            config=persona_settings.servicenow,
            expected_role=expected_role or persona_settings.servicenow.get_persona_role(),
        )
        return {
            "verified": bool(result.get("match", False)),
            "actual_roles": result.get("actual_roles", []),
            "expected_role": result.get("expected_role", expected_role),
            "username": result.get("username", persona),
            "error": result.get("error"),
        }
    except Exception as e:
        return {"verified": False, "reason": f"RoleVerifier failed: {e}"}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ServiceNow IncidentSkill QA Agent against live instance."
    )
    parser.add_argument(
        "--goal",
        type=str,
        default=(
            "Open any existing Incident in New state and validate the complete Incident flow."
        ),
        help="Natural language testing goal",
    )
    parser.add_argument(
        "--persona",
        type=str,
        default="",
        help=(
            "ServiceNow persona name to run as (e.g., itil_user, requester_user). "
            "Defaults to settings.servicenow.active_persona."
        ),
    )
    parser.add_argument(
        "--requester-persona",
        type=str,
        default="",
        help=(
            "Optional requester persona for ACL / read-only access tests. "
            "Used when the goal requires demonstrating role separation "
            "(one itil account cannot demonstrate role separation)."
        ),
    )
    parser.add_argument(
        "--expected-role",
        type=str,
        default="",
        help=(
            "Optional expected role for the persona (e.g., itil, requester). "
            "RoleVerifier will fail the run if the actual role does not match."
        ),
    )
    parser.add_argument(
        "--skip-role-verification",
        action="store_true",
        help=(
            "Skip the independent RoleVerifier check (NOT recommended — "
            "lets requester-scoped tests silently run with elevated privileges)."
        ),
    )
    args = parser.parse_args()

    print("=== Starting Autonomous Incident QA Agent ===")
    print(f"Goal: {args.goal}")

    settings = get_cached_settings()
    persona = args.persona or settings.servicenow.active_persona or ""
    if not persona:
        raise SystemExit(
            "No persona supplied. Provide --persona or set "
            "SERVICENOW_ACTIVE_PERSONA in the environment. Benchmark runs "
            "require a named non-admin persona (INC-UAT-01)."
        )

    # P1-06: independently verify the active persona's role before running.
    # One itil account cannot demonstrate role separation — surface a
    # mismatch as a setup error rather than letting a requester-scoped
    # test silently run with elevated privileges.
    if not args.skip_role_verification:
        print(f"[*] Verifying role for persona: {persona}")
        role_check = await _verify_persona_role(
            settings=settings,
            persona=persona,
            expected_role=args.expected_role or None,
        )
        if role_check.get("verified"):
            print(
                f"    Role verified: {persona} has role(s) "
                f"{role_check.get('actual_roles')} (expected: "
                f"{role_check.get('expected_role')})"
            )
        else:
            reason = role_check.get("reason") or role_check.get("error") or "unknown"
            raise SystemExit(
                f"Persona role verification failed for {persona!r}: {reason}. "
                f"One itil account cannot demonstrate role separation — "
                f"provision a separate requester persona for ACL tests."
            )

    # Optional requester-persona verification (does not run the agent —
    # just confirms the requester account is provisioned correctly for
    # multi-role sweeps).
    if args.requester_persona:
        print(f"[*] Verifying requester persona: {args.requester_persona}")
        requester_check = await _verify_persona_role(
            settings=settings,
            persona=args.requester_persona,
            expected_role="requester",
        )
        if requester_check.get("verified"):
            print(
                f"    Requester role verified: {args.requester_persona} has "
                f"role(s) {requester_check.get('actual_roles')}"
            )
        else:
            reason = requester_check.get("reason") or requester_check.get("error") or "unknown"
            print(
                f"[!] Requester persona role verification failed: {reason}. "
                f"Multi-role sweep will be limited to the primary persona."
            )

    orchestrator = create_orchestrator(settings)

    # Preserve the selected persona in run metadata and make the orchestrator
    # apply its per-run credential isolation instead of reporting persona=None.
    report = await orchestrator.run(args.goal, persona=persona)

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
