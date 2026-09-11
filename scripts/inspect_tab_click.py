import asyncio
import sys

# Add src to sys.path
sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")

from agent.api.v1.dependencies import get_cached_settings, get_browser_manager

async def inspect_tab_click():
    settings = get_cached_settings()
    browser_manager = get_browser_manager(settings)
    await browser_manager.launch()
    page = browser_manager.get_page()
    
    inc_url = f"{settings.servicenow.instance_url.rstrip('/')}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    await browser_manager.navigate(inc_url)
    await page.wait_for_timeout(3000)
    
    # Login if needed
    login_user = page.locator("input#user_name")
    if await login_user.count() > 0:
        await login_user.first.fill(settings.servicenow.username)
        await page.locator("input#user_password").first.fill(settings.servicenow.password)
        await page.locator("button#sysverb_login").first.click()
        await browser_manager.wait_for_load()
        await page.wait_for_timeout(3000)
        await browser_manager.navigate(inc_url)
        await page.wait_for_timeout(3000)

    # Inspect element at (419, 734)
    el_info = await page.evaluate("""() => {
        const el = document.elementFromPoint(419, 734);
        if (!el) return null;
        return {
            tag: el.tagName,
            id: el.id,
            className: el.className,
            text: el.innerText || el.textContent,
            outerHTML: el.outerHTML.slice(0, 200),
            rect: el.getBoundingClientRect()
        };
    }""")
    print(f"Element at (419, 734): {el_info}")

    # Also inspect all tab elements and their exact HTML/classes
    all_tabs = await page.evaluate("""() => {
        return Array.from(document.querySelectorAll('.tab_header, [role="tab"], .tabs2_tab, span.tab_caption_text')).map(el => ({
            tag: el.tagName,
            id: el.id,
            className: el.className,
            text: (el.innerText || el.textContent || '').trim(),
            rect: el.getBoundingClientRect()
        }));
    }""")
    print("\nAll Tab elements found:")
    for t in all_tabs:
        print(" ", t)
        
    await browser_manager.close()

if __name__ == "__main__":
    asyncio.run(inspect_tab_click())
