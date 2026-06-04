"""
iPad Pro Browser Session Setup with Playwright
Demonstrates launching a tablet-emulated browser session for LinkedIn scraping
"""

import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import subprocess
import os
import platform
from contextlib import asynccontextmanager




# iPad Pro 12.9-inch specifications
IPAD_PRO_CONFIG = {
    'user_agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'viewport': {'width': 1024, 'height': 1366},  # Portrait orientation
    'device_scale_factor': 2,  # Retina display
    'is_mobile': True,  # Enables mobile meta viewport
    'has_touch': True,  # Critical: enables touch events
    'locale': 'en-US',
    'timezone_id': 'America/New_York',  # Match your Miami location or vary
}

# Alternative: Landscape mode (swap width/height)
IPAD_PRO_LANDSCAPE = {
    'user_agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'viewport': {'width': 1366, 'height': 1024},  # Landscape
    'device_scale_factor': 2,
    'is_mobile': True,
    'has_touch': True,
    'locale': 'en-US',
    'timezone_id': 'America/New_York',
}


async def connect_to_chrome(
        playwright,
        cdp_url: str = "http://localhost:9222",
        timeout: int = 30000
) -> Browser:
    """
    Connect to existing Chrome instance via CDP

    Args:
        playwright: Playwright instance
        cdp_url: CDP endpoint URL
        timeout: Connection timeout in milliseconds

    Returns:
        Browser instance connected to existing Chrome
    """
    try:
        print(f"🔌 Connecting to Chrome via CDP at {cdp_url}...")
        browser = await playwright.chromium.connect_over_cdp(
            cdp_url,
            timeout=timeout
        )
        print("✅ Successfully connected to Chrome via CDP")
        return browser
    except Exception as e:
        print(f"❌ Failed to connect to Chrome via CDP: {e}")
        print("\n💡 Make sure Chrome is running with debugging enabled:")
        raise


async def setup_ipad_context_on_cdp(
        browser: Browser,
        orientation: str = 'portrait'
) -> tuple[BrowserContext, Page]:
    """
    Configure existing Chrome browser to emulate iPad Pro

    Args:
        browser: CDP-connected browser
        orientation: 'portrait' or 'landscape'

    Returns:
        Tuple of (context, page) configured as iPad Pro
    """
    # Get the default context (your logged-in session)
    contexts = browser.contexts

    if not contexts:
        print("⚠️  No existing contexts found, creating new one")
        context = await browser.new_context()
    else:
        print(f"✅ Found {len(contexts)} existing context(s)")
        context = contexts[0]

    # Get existing page or create new one, skipping internal chrome:// pages
    pages = context.pages
    page = next((p for p in pages if not p.url.startswith("chrome://")), None)
    if page:
        print(f"✅ Using existing page: {page.url}")
    else:
        page = await context.new_page()
        print("📄 Created new page")

    # Apply iPad Pro emulation settings to the page
    config = (IPAD_PRO_CONFIG if orientation == 'portrait'
              else IPAD_PRO_LANDSCAPE)

    # Inject iPad-specific properties via JavaScript
    await page.evaluate(f"""
        // Set user agent
        Object.defineProperty(navigator, 'userAgent', {{
            get: () => '{config['user_agent']}'
        }});

        // Remove webdriver
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined,
        }});

        // Set touch points
        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: () => 5,
        }});

        // Set platform
        Object.defineProperty(navigator, 'platform', {{
            get: () => 'iPad',
        }});

        // Add mobile check
        Object.defineProperty(navigator, 'userAgentData', {{
            get: () => ({{
                mobile: true,
                platform: 'iPad'
            }}),
        }});
    """)

    print("✅ Applied iPad Pro emulation to existing session")

    return context, page





async def launch_and_wait_for_chrome():
    """
    Launch Chrome with debugging and wait until it's ready for CDP connection
    Checks if Chrome is already running first to avoid duplicates

    Returns:
        bool: True if Chrome is ready, False if failed to launch
    """
    # Check if Chrome is already running with debugging enabled
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(
                "http://localhost:9222",
                timeout=2000
            )
            await browser.close()
            print("✅ Chrome already running with debugging - ready to use")
            return True
    except:
        pass  # Not running, proceed to launch

    # Determine Chrome path based on OS
    print("🚀 Launching Chrome with debugging...")

    system = platform.system()

    if system == "Darwin":  # macOS
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        user_data_dir = os.path.expanduser("~/ChromeProfile/LinkedIn")
    elif system == "Windows":
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        user_data_dir = r"C:\ChromeProfile\LinkedIn"
    elif system == "Linux":
        chrome_path = "google-chrome"
        user_data_dir = os.path.expanduser("~/ChromeProfile/LinkedIn")
    else:
        print(f"❌ Unsupported OS: {system}")
        return False

    # Build launch command
    cmd = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={user_data_dir}"
    ]

    # Launch Chrome process
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        print(f"❌ Chrome not found at: {chrome_path}")
        return False
    except Exception as e:
        print(f"❌ Failed to launch Chrome: {e}")
        return False

    # Wait for Chrome to be ready with retry mechanism
    print("⏳ Waiting for Chrome to start...")

    max_retries = 15  # Try for up to 15 seconds
    for i in range(max_retries):
        await asyncio.sleep(1)  # Wait 1 second between attempts

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(
                    "http://localhost:9222",
                    timeout=3000
                )
                await browser.close()
                print(f"✅ Chrome ready after {i + 1} second(s)!")
                return True
        except Exception as e:
            if i < max_retries - 1:
                print(f"   Still waiting... ({i + 1}/{max_retries})")
            else:
                print(f"❌ Chrome failed to start within {max_retries} seconds")
                print(f"   Last error: {e}")
            continue

    return False




@asynccontextmanager
async def open_session(url: str, emulate_ipad: bool = True):
    """
    Context manager for LinkedIn scraping session
    Keeps browser/page alive during entire session

    Usage:
        async with linkedin_session(url) as page:
            # page stays alive here
            await page.keyboard.press('Tab')
    """
    # Ensure Chrome is running
    await launch_and_wait_for_chrome()

    # Start Playwright (don't use 'async with' here)
    p = await async_playwright().start()

    try:
        # Connect to Chrome
        print("🔌 Connecting to Chrome via CDP...")
        browser = await connect_to_chrome(p)

        if emulate_ipad:
            # Apply iPad emulation
            print("📱 Applying iPad Pro emulation...")
            context, page = await setup_ipad_context_on_cdp(
                browser,
                orientation='portrait'
            )
        else:
            # Use default context and page as-is
            print("🖥️  Using default browser context...")
            contexts = browser.contexts
            context = contexts[0] if contexts else await browser.new_context()
            pages = context.pages
            page = next((p for p in pages if not p.url.startswith("chrome://")), None)
            if page:
                print(f"✅ Using existing page: {page.url}")
            else:
                page = await context.new_page()
                print("📄 Created new page")

        # Navigate to URL
        print(f"🌐 Navigating to {url}...")
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(3)
        print("✅ Page loaded and ready!")

        # Give page to caller (page stays alive)
        yield page

    finally:
        # Cleanup when done
        print("\n🔚 Closing session...")
        await p.stop()