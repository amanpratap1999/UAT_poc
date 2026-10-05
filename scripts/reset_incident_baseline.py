"""Explicitly reset a selected Incident to the On Hold test baseline.

Uses the ServiceNow g_form client API (not raw DOM select mutation) so the
form model actually registers the change and the Update save persists.
Verifies the persisted state by re-reading the record in the same session
and exits non-zero if the baseline was not established.

Usage: python scripts/reset_incident_baseline.py --incident-number INC0012345 --apply
"""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "diagnostics"))

from agent.api.v1.dependencies import get_browser_manager, get_cached_settings
from incident_navigation import open_incident_by_number

settings = get_cached_settings()
if not settings.servicenow.instance_url:
    raise ValueError("SERVICENOW_INSTANCE_URL is not set.")

async def read_state(page) -> tuple[str, str]:
    """Read (value, label) of the incident state select."""
    sel = page.locator("select#incident\\.state")
    value = await sel.first.input_value()
    label = await sel.first.locator(f"option[value='{value}']").first.inner_text()
    return value, label.strip()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident-number", required=True)
    parser.add_argument("--apply", action="store_true", help="Confirm that this record may be changed")
    args = parser.parse_args()
    settings = get_cached_settings()
    if not args.apply:
        parser.error("refusing to mutate ServiceNow without --apply")
    if not settings.servicenow.is_subproduction or not settings.servicenow.allow_mutations:
        raise RuntimeError("Reset requires SERVICENOW_IS_SUBPRODUCTION=true and SERVICENOW_ALLOW_MUTATIONS=true")
    browser_manager = get_browser_manager(settings)

    print(f"Launching browser to restore baseline state on {args.incident_number}...")
    await browser_manager.launch()
    page = await open_incident_by_number(browser_manager, settings, args.incident_number)

    # 1. Navigate + authenticate if required
    # The helper verifies the exact visible Incident number before we allow edits.
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
        page = await open_incident_by_number(browser_manager, settings, args.incident_number)

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
    page = await open_incident_by_number(browser_manager, settings, args.incident_number)

    value, label = await read_state(page)
    print(f"State after reset: {value} ({label})")

    hold_val = ""
    hold_sel = page.locator("select#incident\\.hold_reason")
    if await hold_sel.count() > 0:
        hold_val = await hold_sel.first.input_value()
    print(f"Hold reason after reset: {hold_val}")

    await browser_manager.close()

    if value != "3" or hold_val != "1":
        print(
            "FAILED: expected state=3 (On Hold) and hold_reason=1 "
            f"(Awaiting Caller); observed state={value} ({label}), hold_reason={hold_val!r}"
        )
        raise SystemExit(1)
    print(f"Baseline restored: {args.incident_number} is On Hold (3) with hold reason Awaiting Caller (1).")


if __name__ == "__main__":
    asyncio.run(main())
