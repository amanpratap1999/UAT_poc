"""Independent incident state verifier — fresh browser session, no agent loop.

Prints a JSON snapshot of a selected Incident's key fields so an external observer can
prove the lifecycle final state without trusting the agent's own report.
Usage: python scripts/diagnostics/verify_incident_state.py --incident-number INC0012345
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from agent.api.v1.dependencies import get_browser_manager, get_cached_settings
from incident_navigation import open_incident_by_number


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Incident state snapshot")
    parser.add_argument("--incident-number", required=True, help="Exact Incident number to inspect")
    parser.add_argument("--output", help="Optional JSON evidence output path")
    args = parser.parse_args()
    settings = get_cached_settings()
    bm = get_browser_manager(settings)
    await bm.launch()
    page = await open_incident_by_number(bm, settings, args.incident_number)

    async def field_value(selectors: str) -> str:
        loc = page.locator(selectors)
        try:
            if await loc.count() > 0:
                return (await loc.first.input_value()).strip()
        except Exception:
            return ""
        return ""

    async def select_info(selectors: str) -> dict:
        loc = page.locator(selectors)
        try:
            if await loc.count() > 0:
                v = await loc.first.input_value()
                label = await loc.first.locator(f"option[value='{v}']").first.inner_text()
                return {"value": v, "label": label.strip()}
        except Exception:
            pass
        return {}

    snapshot = {
        "observed_at": datetime.now(UTC).isoformat(),
        "observation_type": "read_only_ui_inspection",
        "agent_workflow_executed": False,
        "persona_role_verified": False,
        "configured_persona": settings.servicenow.active_persona,
        "url": page.url,
        "title": await page.title(),
        "number": await field_value("input#incident\\.number, input[name='incident.number']"),
        "state": await select_info("select#incident\\.state, select[name='incident.state']"),
        "hold_reason": await select_info(
            "select#incident\\.hold_reason, select[name='incident.hold_reason']"
        ),
        "priority": await select_info(
            "select#incident\\.priority, select[name='incident.priority']"
        ),
    }
    shot = await bm.take_screenshot("verify_incident_state")
    snapshot["screenshot"] = str(shot)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else Path("reports") / f"live_incident_observation_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    snapshot["evidence_file"] = str(output_path.resolve())
    print(json.dumps(snapshot, indent=2))
    await bm.close()


if __name__ == "__main__":
    asyncio.run(main())
