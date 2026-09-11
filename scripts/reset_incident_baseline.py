import asyncio
import sys

# Add src to sys.path
sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_cached_settings, get_browser_manager

async def main():
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)
    
    print("Launching browser to restore baseline state on INC0000007...")
    await browser_manager.launch()
    page = browser_manager.get_page()
    
    # 1. Navigate to ServiceNow and authenticate
    url = f"{settings.servicenow.instance_url.rstrip('/')}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    print(f"Navigating to {url}...")
    await browser_manager.navigate(url)
    await page.wait_for_timeout(3000)
    
    # Login if needed
    login_user = page.locator("input#user_name, input[name='user_name']")
    if await login_user.count() > 0:
        print("Login form detected! Performing login...")
        await login_user.first.fill(settings.servicenow.username)
        login_pass = page.locator("input#user_password, input[name='user_password']")
        await login_pass.first.fill(settings.servicenow.password)
        login_btn = page.locator("button#sysverb_login, button:has-text('Log in'), input[type='submit']")
        await login_btn.first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(4000)
        
        print(f"Navigating back to incident: {url}")
        await browser_manager.navigate(url)
        await page.wait_for_timeout(4000)
    
    # 2. Set State to On Hold (3) and hold_reason to 1 (Awaiting Caller)
    print("Setting State to On Hold (3)...")
    state_select = page.locator("select#incident\\.state, select[name='incident.state'], select[id$='.state']")
    await state_select.first.select_option(value="3")
    await state_select.first.dispatch_event("change")
    await page.wait_for_timeout(2000)
    
    hold_reason_select = page.locator("select#incident\\.hold_reason, select[name='incident.hold_reason'], select[id$='.hold_reason']")
    if await hold_reason_select.count() > 0:
        print("Setting Hold Reason to Awaiting Caller (1)...")
        await hold_reason_select.first.select_option(value="1")
        await hold_reason_select.first.dispatch_event("change")
        await page.wait_for_timeout(1000)
    
    # 3. Click Update
    print("Clicking Update...")
    update_btn = page.locator("button#sysverb_update, button[name='sysverb_update']").first
    await update_btn.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(4000)
    
    # 4. Re-verify baseline state
    await browser_manager.navigate(url)
    await page.wait_for_timeout(4000)
    
    state_val = await page.locator("select#incident\\.state, select[name='incident.state'], select[id$='.state']").first.input_value()
    print(f"Baseline state restored on INC0000007! Current State value = {state_val}")
    
    await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
