import asyncio
import sys

# Add src to sys.path
sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_cached_settings, get_browser_manager

async def main():
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)
    
    print("Launching browser...")
    await browser_manager.launch()
    page = browser_manager.get_page()
    
    url = f"{settings.servicenow.instance_url.rstrip('/')}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    await browser_manager.navigate(url)
    await page.wait_for_timeout(3000)
    
    # Login
    login_user = page.locator("input#user_name, input[name='user_name']")
    if await login_user.count() > 0:
        await login_user.first.fill(settings.servicenow.username)
        login_pass = page.locator("input#user_password, input[name='user_password']")
        await login_pass.first.fill(settings.servicenow.password)
        login_btn = page.locator("button#sysverb_login, button:has-text('Log in'), input[type='submit']")
        await login_btn.first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(4000)
        await browser_manager.navigate(url)
        await page.wait_for_timeout(4000)
    
    print("Setting State=3, hold_reason=1, comments='Awaiting caller response.'...")
    await page.evaluate("""
        () => {
            if (typeof g_form !== 'undefined') {
                g_form.setValue('state', '3');
                g_form.setValue('hold_reason', '1');
                g_form.setValue('comments', 'Awaiting caller response for UAT baseline test.');
                g_form.save();
            }
        }
    """)
    await page.wait_for_timeout(5000)
    
    # Re-navigate and verify
    await browser_manager.navigate(url)
    await page.wait_for_timeout(4000)
    
    state_val = await page.evaluate("() => typeof g_form !== 'undefined' ? g_form.getValue('state') : 'none'")
    hold_val = await page.evaluate("() => typeof g_form !== 'undefined' ? g_form.getValue('hold_reason') : 'none'")
    print(f"Verified Baseline State = {state_val}, Hold Reason = {hold_val}")
    
    await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
