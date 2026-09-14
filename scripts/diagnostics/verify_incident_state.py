"""Independent incident state verifier — fresh browser session, no agent loop.

Prints a JSON snapshot of INC0000007's key fields so an external observer can
prove the lifecycle final state without trusting the agent's own report.
Usage: .venv/Scripts/python.exe scripts/diagnostics/verify_incident_state.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from agent.api.v1.dependencies import get_browser_manager, get_cached_settings

SYS_ID = "8d6353eac0a8016400d8a125ca14fc1f"


async def main() -> None:
    settings = get_cached_settings()
    bm = get_browser_manager(settings)
    await bm.launch()
    page = bm.get_page()
    url = f"{settings.servicenow.instance_url.rstrip('/')}/incident.do?sys_id={SYS_ID}"
    await bm.navigate(url)
    await page.wait_for_timeout(3000)

    login_user = page.locator("input#user_name, input[name='user_name']")
    if await login_user.count() > 0:
        await login_user.first.fill(settings.servicenow.username)
        await page.locator("input#user_password, input[name='user_password']").first.fill(
            settings.servicenow.password
        )
        await page.locator(
            "button#sysverb_login, button:has-text('Log in'), input[type='submit']"
        ).first.click()
        await bm.wait_for_load()
        await page.wait_for_timeout(4000)
        await bm.navigate(url)
        await page.wait_for_timeout(4000)

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
        "url": page.url,
        "title": await page.title(),
        "number": await field_value("input#incident\\.number, input[name='incident.number']"),
        "state": await select_info("select#incident\\.state, select[name='incident.state']"),
        "hold_reason": await select_info(
            "select#incident\\.hold_reason, select[name='incident.hold_reason']"
        ),
        "short_description": await field_value(
            "input#incident\\.short_description, input[name='incident.short_description'],"
            " textarea[name='incident.short_description']"
        ),
        "caller": await field_value(
            "input#sys_display\\.incident\\.caller_id, input[name='sys_display.incident.caller_id']"
        ),
        "assigned_to": await field_value(
            "input#sys_display\\.incident\\.assigned_to, input[name='sys_display.incident.assigned_to']"
        ),
        "priority": await select_info(
            "select#incident\\.priority, select[name='incident.priority']"
        ),
    }
    shot = await bm.take_screenshot("verify_incident_state")
    snapshot["screenshot"] = str(shot)
    print(json.dumps(snapshot, indent=2))
    await bm.close()


if __name__ == "__main__":
    asyncio.run(main())
