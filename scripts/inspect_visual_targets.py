import asyncio
import sys

# Add src to sys.path
sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_cached_settings, get_browser_manager

async def inspect_ui_targets():
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)
    
    print("Launching browser...")
    await browser_manager.launch()
    page = browser_manager.get_page()
    
    # 1. Inspect Login page password toggle
    print("\n--- 1. Testing Login Page Password Toggle ---")
    login_url = f"{settings.servicenow.instance_url.rstrip('/')}/login.do"
    await browser_manager.navigate(login_url)
    await page.wait_for_timeout(3000)
    
    pass_input = page.locator("input#user_password")
    if await pass_input.count() > 0:
        pass_type_before = await pass_input.first.get_attribute("type")
        print(f"Password field initial type: {pass_type_before}")
        
        # Check toggle icons around password
        icons = page.locator(".icon-view, .icon-unview, button[aria-label*='password' i], [data-original-title*='password' i]")
        print(f"Password toggle icons found: {await icons.count()}")
        for i in range(await icons.count()):
            box = await icons.nth(i).bounding_box()
            visible = await icons.nth(i).is_visible()
            print(f"  Icon {i}: box={box}, visible={visible}")
            
    # 2. Inspect Incident Form Tabs
    print("\n--- 2. Testing Incident Form Tabs ---")
    inc_url = f"{settings.servicenow.instance_url.rstrip('/')}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    await browser_manager.navigate(inc_url)
    await page.wait_for_timeout(3000)
    
    # Authenticate if needed
    login_user = page.locator("input#user_name")
    if await login_user.count() > 0:
        await login_user.first.fill(settings.servicenow.username)
        await page.locator("input#user_password").first.fill(settings.servicenow.password)
        await page.locator("button#sysverb_login").first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(3000)
        await browser_manager.navigate(inc_url)
        await page.wait_for_timeout(3000)
        
    tabs = page.locator(".tab_header, [role='tab'], span.tab_caption_text")
    print(f"Incident Form Tabs found: {await tabs.count()}")
    for i in range(await tabs.count()):
        text = await tabs.nth(i).inner_text()
        box = await tabs.nth(i).bounding_box()
        visible = await tabs.nth(i).is_visible()
        if visible and text.strip():
            print(f"  Tab {i}: text='{text.strip()}', box={box}, visible={visible}")
            
    await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(inspect_ui_targets())
