"""Shared, number-based Incident navigation for live diagnostics."""

from __future__ import annotations

import re
from urllib.parse import quote


async def open_incident_by_number(browser_manager, settings, incident_number: str):
    """Open exactly one Incident by its visible number, then verify form identity."""
    number = incident_number.strip().upper()
    if not re.fullmatch(r"INC[0-9]+", number):
        raise ValueError("Incident number must match INC followed by digits")

    page = browser_manager.get_page()
    base = settings.servicenow.instance_url.rstrip("/")
    await browser_manager.navigate(base)
    login = page.locator("input#user_name, input[name='user_name']")
    if await login.count() > 0:
        username, password = settings.servicenow.get_active_credentials()
        await login.first.fill(username)
        await page.locator("input#user_password, input[name='user_password']").first.fill(password)
        await page.locator(
            "button#sysverb_login, button:has-text('Log in'), input[type='submit']"
        ).first.click()
        await browser_manager.wait_for_load()
    query = quote(f"number={number}", safe="")
    await browser_manager.navigate(f"{base}/incident.do?sysparm_query={query}")
    await page.wait_for_timeout(1500)

    actual = await page.evaluate(
        "() => window.g_form ? window.g_form.getValue('number') : ''"
    )
    if actual.strip().upper() != number:
        raise RuntimeError(f"Record identity mismatch: requested {number}, opened {actual!r}")
    return page
