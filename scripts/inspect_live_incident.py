import asyncio
import sys

# Add src to sys.path
sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_cached_settings, get_browser_manager, get_observation_engine

async def inspect_live_incident():
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)
    get_observation_engine()
    
    print("Launching browser...")
    await browser_manager.launch()
    page = browser_manager.get_page()
    
    from agent.api.v1.dependencies import get_cached_settings
    settings = get_cached_settings()
    if not settings.servicenow.instance_url:
        raise ValueError("SERVICENOW_INSTANCE_URL is not set.")
    incident_url = f"{settings.servicenow.instance_url}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    print(f"Navigating to {incident_url}...")
    await browser_manager.navigate(incident_url)
    await page.wait_for_timeout(3000)
    
    # Check for login inputs
    user_input = page.locator("input#user_name, input[name='user_name']")
    if await user_input.count() > 0:
        print("Login form detected! Performing login...")
        username = settings.servicenow.username
        password = settings.servicenow.password
        
        await user_input.first.fill(username)
        pass_input = page.locator("input#user_password, input[name='user_password']")
        await pass_input.first.fill(password)
        
        login_btn = page.locator("button#sysverb_login, button:has-text('Log in'), input[type='submit']")
        await login_btn.first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(4000)
        
    print(f"Navigating directly to incident: {incident_url}")
    await browser_manager.navigate(incident_url)
    await page.wait_for_timeout(4000)
    
    print(f"Incident Page URL: {page.url}")
    print(f"Incident Page Title: {await page.title()}")
    
    # Check State Select element across frames
    print("\n--- State Field Analysis ---")
    for frame in [page] + page.frames:
        frame_name = getattr(frame, "name", "main")
        state_sels = frame.locator("select[name$='.state'], select[id$='.state']")
        count = await state_sels.count()
        if count > 0:
            for s_idx in range(count):
                sel = state_sels.nth(s_idx)
                sel_id = await sel.get_attribute("id")
                sel_name = await sel.get_attribute("name")
                val = await sel.input_value()
                opt_vals = await sel.locator("option").evaluate_all(
                    "opts => opts.map(o => ({text: o.text, value: o.value, selected: o.selected}))"
                )
                print(f"State select in frame '{frame_name}' (id={sel_id}, name={sel_name}): current_value='{val}', options={opt_vals}")
                
    # Check Resolution fields
    print("\n--- Resolution / Additional fields ---")
    for field_name in ["Resolution code", "Resolution notes", "Assignment group", "Assigned to", "Short description", "Caller"]:
        cand = await page.locator(f"[id*='{field_name.lower().replace(' ', '_')}'], [name*='{field_name.lower().replace(' ', '_')}']").count()
        print(f"  Field query '{field_name}': {cand} elements found")
        
    # Check update button
    update_btn = page.locator("button#sysverb_update, button:has-text('Update')")
    print(f"Update button count: {await update_btn.count()}")
    if await update_btn.count() > 0:
        for idx in range(await update_btn.count()):
            btn = update_btn.nth(idx)
            print(f"  Update button {idx}: id={await btn.get_attribute('id')}, text={await btn.inner_text()}, visible={await btn.is_visible()}")

    screenshot_path = await browser_manager.take_screenshot("live_incident_state_details")
    print(f"Screenshot taken: {screenshot_path}")
    await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(inspect_live_incident())
