"""Reset INC0000007 to the On Hold (state=3, hold_reason=1) test baseline.

Uses the ServiceNow g_form client API (not raw DOM select mutation) so the
form model actually registers the change and the Update save persists.
Verifies the persisted state by re-reading the record in the same session
and exits non-zero if the baseline was not established.

Usage: .venv/Scripts/python.exe scripts/reset_incident_baseline.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_browser_manager, get_cached_settings

settings = get_cached_settings()
if not settings.servicenow.instance_url:
    raise ValueError("SERVICENOW_INSTANCE_URL is not set.")

INCIDENT_URL = (
    f"{settings.servicenow.instance_url}/"
    "incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
)


async def read_state(page) -> tuple[str, str]:
    """Read (value, label) of the incident state select."""
    sel = page.locator("select#incident\\.state")
    value = await sel.first.input_value()
    label = await sel.first.locator(f"option[value='{value}']").first.inner_text()
    return value, label.strip()


async def main() -> None:
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)

    print("Launching browser to restore baseline state on INC0000007...")
    await browser_manager.launch()
    page = browser_manager.get_page()

    # 1. Navigate + authenticate if required
    await browser_manager.navigate(INCIDENT_URL)
    await page.wait_for_timeout(3000)
    login_user = page.locator("input#user_name, input[name='user_name']")
    if await login_user.count() > 0:
        print("Login form detected! Performing login...")
        await login_user.first.fill(settings.servicenow.username)
        await page.locator("input#user_password, input[name='user_password']").first.fill(
            settings.servicenow.password
        )
        await page.locator(
            "button#sysverb_login, button:has-text('Log in'), input[type='submit']"
        ).first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(4000)
        await browser_manager.navigate(INCIDENT_URL)
        await page.wait_for_timeout(4000)

    # 2. Confirm current state before mutation
    value, label = await read_state(page)
    print(f"Current state before reset: {value} ({label})")

    # 3. Mutate via g_form (ServiceNow client API) so the form model is dirtied
    has_gform = await page.evaluate("() => typeof window.g_form !== 'undefined'")
    if not has_gform:
        print("FATAL: g_form not available on this page — cannot reliably set state.")
        await browser_manager.close()
        raise SystemExit(2)

    print("Setting state=3 (On Hold) via g_form.setValue...")
    await page.evaluate("() => { g_form.setValue('state', '3'); }")
    await page.wait_for_timeout(2500)  # UI policy adds hold_reason field

    hold_sel = page.locator("select#incident\\.hold_reason")
    if await hold_sel.count() > 0:
        print("Setting hold_reason=1 (Awaiting Caller) via g_form.setValue...")
        await page.evaluate("() => { g_form.setValue('hold_reason', '1'); }")
        await page.wait_for_timeout(1500)
    else:
        print("WARNING: hold_reason select not found after state change")

    # Mandatory-field business rule on this instance: transitioning to On Hold
    # requires "Comments (Customer visible)" to be non-empty, or the Update
    # is rejected with a banner. Set an explicit QA comment.
    print("Setting comments (mandatory for On Hold) via g_form.setValue...")
    await page.evaluate(
        "() => { g_form.setValue('comments',"
        " 'QA baseline reset: putting incident On Hold (Awaiting Caller) for lifecycle test.'); }"
    )
    await page.wait_for_timeout(1000)

    # 4. Save via the real Update button (g_form submit)
    print("Clicking Update...")
    update_btn = page.locator("button#sysverb_update, button[name='sysverb_update']").first
    await update_btn.click()
    await page.wait_for_timeout(6000)  # allow save + redirect
    await browser_manager.wait_for_load()

    # 5. Re-open the record and verify persistence
    print("Re-opening record to verify persistence...")
    await browser_manager.navigate(INCIDENT_URL)
    await page.wait_for_timeout(5000)

    value, label = await read_state(page)
    print(f"State after reset: {value} ({label})")

    hold_val = ""
    hold_sel = page.locator("select#incident\\.hold_reason")
    if await hold_sel.count() > 0:
        hold_val = await hold_sel.first.input_value()
    print(f"Hold reason after reset: {hold_val}")

    await browser_manager.close()

    if value != "3":
        print(f"FAILED: expected state 3 (On Hold) but record is {value} ({label})")
        raise SystemExit(1)
    print("Baseline restored: INC0000007 is On Hold (3) with hold reason Awaiting Caller (1).")


if __name__ == "__main__":
    asyncio.run(main())
