import asyncio
import sys

sys.path.insert(0, r"c:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src")
from agent.api.v1.dependencies import get_cached_settings, get_browser_manager

async def test():
    s = get_cached_settings()
    bm = get_browser_manager(s)
    await bm.launch()
    p = bm.get_page()
    base_url = s.servicenow.instance_url.rstrip('/')
    url = f"{base_url}/incident.do?sys_id=8d6353eac0a8016400d8a125ca14fc1f"
    await bm.navigate(url)
    await p.wait_for_timeout(3000)
    
    # Login
    login_user = p.locator('input#user_name')
    if await login_user.count() > 0:
        await login_user.first.fill(s.servicenow.username)
        await p.locator('input#user_password').first.fill(s.servicenow.password)
        await p.locator('button#sysverb_login').first.click()
        await bm.wait_for_load()
        await p.wait_for_timeout(3000)
        await bm.navigate(url)
        await p.wait_for_timeout(3000)

    # Click Resolution tab at (419, 734)
    print("Clicking Resolution tab at (419, 734)...")
    await p.mouse.click(419, 734)
    await p.wait_for_timeout(1500)
    
    # Check tab sections and fields
    data = await p.evaluate("""() => {
        const sections = Array.from(document.querySelectorAll('.tabs2_section, div[id*="section"], [data-section-name], div.tab_section')).map(e => ({
            id: e.id,
            className: e.className,
            display: window.getComputedStyle(e).display,
            text_preview: (e.innerText || '').slice(0, 100).replace(/\\n/g, ' ')
        }));
        const fields = Array.from(document.querySelectorAll('input, select, textarea')).filter(i => 
            i.id.includes('close') || i.name.includes('close') || i.id.includes('resolution') || (i.labels && Array.from(i.labels).some(l => l.innerText.includes('Resolution')))
        ).map(i => ({
            id: i.id,
            name: i.name,
            visible: i.offsetParent !== null
        }));
        return { sections, fields };
    }""")
    print("SECTIONS:", data["sections"])
    print("FIELDS:", data["fields"])
    await bm.close()

if __name__ == "__main__":
    asyncio.run(test())
