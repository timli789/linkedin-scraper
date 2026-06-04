import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

IPAD_PRO_CONFIG = {
    'user_agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'viewport': {'width': 1024, 'height': 1366},
    'device_scale_factor': 2,
    'is_mobile': True,
    'has_touch': True,
    'locale': 'en-US',
    'timezone_id': 'America/New_York',
}

PROFILE_DIR = Path.home() / "ChromeProfile" / "LinkedIn"


@asynccontextmanager
async def open_session(url: str, emulate_ipad: bool = True):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    launch_kwargs = dict(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )

    if emulate_ipad:
        launch_kwargs.update({
            'user_agent': IPAD_PRO_CONFIG['user_agent'],
            'viewport': IPAD_PRO_CONFIG['viewport'],
            'device_scale_factor': IPAD_PRO_CONFIG['device_scale_factor'],
            'is_mobile': IPAD_PRO_CONFIG['is_mobile'],
            'has_touch': IPAD_PRO_CONFIG['has_touch'],
            'locale': IPAD_PRO_CONFIG['locale'],
            'timezone_id': IPAD_PRO_CONFIG['timezone_id'],
        })

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            **launch_kwargs
        )

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print(f"Navigating to {url}...")
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(2)

        if any(x in page.url for x in ('login', 'authwall', 'signup', 'uas/authenticate')):
            print("\nNot logged in. Please log in to LinkedIn in the browser window.")
            print("Waiting up to 2 minutes for login...")
            await page.wait_for_url('**/feed**', timeout=120000)
            print("Login detected! Continuing...")
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(3)

        print("Page loaded and ready!")

        try:
            yield page
        finally:
            print("\nClosing session...")
            await context.close()
