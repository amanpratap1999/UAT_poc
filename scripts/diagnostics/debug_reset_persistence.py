"""Diagnose why the On Hold reset fails to persist on INC0000007.

Step-by-step evidence:
 1. Open form, read current state.
 2. g_form.setValue('state','3') -> read back via g_form.getValue + DOM select.
 3. g_form.setValue('hold_reason','1') -> read back.
 4. Click Update -> capture URL before/after, error banners, form messages.
 5. Re-open record -> read persisted state.
Prints every intermediate value; exits 0 only if persistence is proven.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_browser_manager, get_cached_settings

INCIDENT_URL = (
    "https://aelumconsultingpvtltddemo3.service-now.com/"
    "incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
)


async def main() -> None:
    settings = get_cached_settings()
    bm = get_browser_manager(settings)
    await bm.launch()
    page = bm.get_page()

    await bm.navigate(INCIDENT_URL)
    await page.wait_for_timeout(3000)
    if await page.locator("input#user_name").count() > 0:
        await page.locator("input#user_name").first.fill(settings.servicenow.username)
        await page.locator("input#user_password").first.fill(settings.servicenow.password)
        await page.locator("button#sysverb_login").first.click()
        await bm.wait_for_load()
        await page.wait_for_timeout(4000)
        await bm.navigate(INCIDENT_URL)
        await page.wait_for_timeout(4000)

    print("STEP1 url:", page.url)

    # Read current state via both g_form and DOM
    cur = await page.evaluate(
        "() => ({ state: g_form.getValue('state'),"
        " hold: g_form.getValue('hold_reason'),"
        " number: g_form.getValue('number'),"
        " dirty: g_form.isChanged ? g_form.isChanged() : 'n/a' })"
    )
    print("STEP1 form state:", cur)

    # Set state=3 via g_form
    await page.evaluate("() => { g_form.setValue('state', '3'); }")
    await page.wait_for_timeout(3000)
    after_set = await page.evaluate(
        "() => ({ state: g_form.getValue('state'), hold: g_form.getValue('hold_reason') })"
    )
    print("STEP2 after setValue(state,3):", after_set)

    hold_sel_count = await page.locator("select#incident\\.hold_reason").count()
    print("STEP3 hold_reason select count:", hold_sel_count)
    if hold_sel_count > 0:
        await page.evaluate("() => { g_form.setValue('hold_reason', '1'); }")
        await page.wait_for_timeout(2000)
        after_hold = await page.evaluate(
            "() => ({ state: g_form.getValue('state'), hold: g_form.getValue('hold_reason') })"
        )
        print("STEP3 after setValue(hold_reason,1):", after_hold)

    # Check missing mandatory fields before clicking update
    missing = await page.evaluate(
        "() => { try { return g_form.getMissingMandatoryFields"
        " ? g_form.getMissingMandatoryFields() : 'api-unavailable'; } catch (e) { return 'err: ' + e; } }"
    )
    print("STEP4 missing mandatory fields:", missing)

    url_before = page.url
    # Click the Update button via the ServiceNow UI action (same as user)
    btn = page.locator("button#sysverb_update").first
    btn_visible = await btn.is_visible()
    btn_enabled = await btn.is_enabled()
    print("STEP5 update button visible:", btn_visible, "enabled:", btn_enabled)
    await btn.click()
    await page.wait_for_timeout(8000)  # save + redirect
    try:
        await bm.wait_for_load()
    except Exception:
        pass
    print("STEP5 url before:", url_before)
    print("STEP5 url after :", page.url)

    # Detect mandatory/error banners ServiceNow may have shown
    for sel in (".form-group.has-error", "#status_messages", ".notification-text",
                "div[id*='error']", ".outputmsg"):
        cnt = await page.locator(sel).count()
        if cnt:
            txt = await page.locator(sel).first.inner_text()
            print(f"STEP5 banner {sel}: count={cnt} text={txt[:200]!r}")

    await bm.take_screenshot("reset_debug_after_update")

    # Re-open and read persisted state
    await bm.navigate(INCIDENT_URL)
    await page.wait_for_timeout(5000)
    final = await page.evaluate(
        "() => ({ number: g_form ? g_form.getValue('number') : 'no g_form',"
        " state: g_form ? g_form.getValue('state') : 'no g_form',"
        " hold: g_form ? g_form.getValue('hold_reason') : '' })"
    )
    print("STEP6 persisted state:", final)
    await bm.close()

    if final.get("state") == "3":
        print("RESULT: RESET PERSISTED")
        raise SystemExit(0)
    print("RESULT: RESET FAILED — state is", final.get("state"))
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
