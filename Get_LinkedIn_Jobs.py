import asyncio
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).parent / 'OxyMouse'))
from oxymouse.oxymouse import OxyMouse

from BrowserSetup import open_session

DB_URL = os.environ["DB_URL"]


url = "https://www.linkedin.com/jobs/"


@dataclass
class ScrollBehaviorParams:
    # Primary chain: probability of a break after each click
    base_break_prob: float = 0.10
    break_prob_increment: float = 0.15
    forced_break_at: int = 5

    # Break type split (relative weights for B vs C)
    minor_scroll_weight: float = 0.65
    idle_weight: float = 0.35

    # Consecutive B/C chain within one break episode
    consecutive_break_prob: float = 0.45
    consecutive_decay: float = 0.50
    max_consecutive_breaks: int = 3

    # State B params
    micro_scroll_delta: tuple = (30, 80)    # pixels per nudge
    micro_scroll_delay: tuple = (0.4, 0.9)  # seconds after nudge

    # State C params
    idle_duration: tuple = (1.0, 3.5)       # seconds

    # Counter reset values after a break episode
    b_resets_to: int = 0
    c_resets_to: int = 2


async def oxy_click(page, element, duration: float = None):
    box = await element.bounding_box()
    target_x = int(box['x'] + box['width'] / 2)
    target_y = int(box['y'] + box['height'] / 2)

    if duration is None:
        duration = random.uniform(0.5, 3.0)

    mouse = OxyMouse(algorithm="oxy")
    path = mouse.generate_coordinates(from_x=0, from_y=0, to_x=target_x, to_y=target_y)

    delay = duration / len(path) if path else 0
    for x, y in path:
        await page.mouse.move(x, y)
        await asyncio.sleep(delay)

    await page.mouse.click(target_x, target_y)


async def human_scroll_to(page, element):
    await element.evaluate("el => el.scrollIntoView({block: 'center'})")
    await asyncio.sleep(random.uniform(0.3, 0.6))


async def do_minor_scroll(page, params: ScrollBehaviorParams):
    viewport = page.viewport_size or await page.evaluate(
        "() => ({width: window.innerWidth, height: window.innerHeight})"
    )
    list_x = viewport['width'] // 4
    center_y = viewport['height'] // 2
    await page.mouse.move(list_x, center_y)

    delta = random.randint(*params.micro_scroll_delta) * random.choice([-1, 1])
    await page.mouse.wheel(0, delta)
    print(f"    [B] nudge {delta:+}px")
    await asyncio.sleep(random.uniform(*params.micro_scroll_delay))


async def do_idle(params: ScrollBehaviorParams):
    duration = random.uniform(*params.idle_duration)
    print(f"    [C] idle {duration:.2f}s")
    await asyncio.sleep(duration)


async def inter_card_behavior(page, click_count: int, params: ScrollBehaviorParams) -> int:
    break_prob = params.base_break_prob + (click_count - 1) * params.break_prob_increment
    forced = click_count >= params.forced_break_at

    if not forced and random.random() >= break_prob:
        return click_count

    print(f"  -> Break triggered (click_count={click_count}, forced={forced})")

    consecutive_prob = 1.0
    episode_count = 0
    last_state = None

    while episode_count < params.max_consecutive_breaks and random.random() < consecutive_prob:
        total_weight = params.minor_scroll_weight + params.idle_weight
        if random.random() < params.minor_scroll_weight / total_weight:
            await do_minor_scroll(page, params)
            last_state = 'B'
        else:
            await do_idle(params)
            last_state = 'C'

        episode_count += 1
        consecutive_prob = params.consecutive_break_prob * (params.consecutive_decay ** (episode_count - 1))

    reset_to = params.b_resets_to if last_state == 'B' else params.c_resets_to
    print(f"  -> Episode done ({episode_count} step(s), last={last_state}), counter -> {reset_to}")
    return reset_to


def fetch_existing_urls() -> set:
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT job_url FROM linkedin_jobs")
            return {row[0] for row in cur.fetchall()}


def bulk_upsert(rows):
    if not rows:
        return
    rows = list({row[0]: row for row in rows if row[0]}.values())
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO linkedin_jobs (job_url, title, employer, posted, description, applicants)
                VALUES %s
                ON CONFLICT (job_url) DO UPDATE SET
                    title       = EXCLUDED.title,
                    employer    = EXCLUDED.employer,
                    posted      = EXCLUDED.posted,
                    description = EXCLUDED.description,
                    applicants  = EXCLUDED.applicants,
                    scraped_at  = NOW()
            """, rows)
        conn.commit()
    print(f"Upserted {len(rows)} rows to linkedin_jobs")


async def click_all_job_cards(page, params: ScrollBehaviorParams):
    for attempt in range(5):
        try:
            cards = await page.query_selector_all('div[role="button"]:has(button[aria-label^="Dismiss"])')
            break
        except Exception as e:
            if 'context was destroyed' in str(e).lower() and attempt < 4:
                print(f"  Page still navigating, retrying in 2s... ({attempt + 1}/5)")
                await asyncio.sleep(2)
            else:
                raise

    print(f"Found {len(cards)} job cards")
    existing_urls = fetch_existing_urls()
    click_count = 0
    rows = []

    for i, card in enumerate(cards, 1):
        title, employer, posted = await card.evaluate("""el => {
            const titleSpan = el.querySelector('span[aria-hidden="true"]');
            const title = titleSpan ? titleSpan.textContent.trim() : 'Unknown';
            const titleDiv = titleSpan?.closest('div[data-display-contents]');
            const employer = titleDiv?.nextElementSibling?.querySelector('p')?.textContent.trim() || 'Unknown';
            const dateSpan = Array.from(el.querySelectorAll('span')).find(s => s.textContent.trim().startsWith('Posted'));
            const posted = dateSpan ? dateSpan.textContent.trim() : 'Unknown';
            return [title, employer, posted];
        }""")

        print(f"  [A] Card {i}/{len(cards)}: {title}")
        await human_scroll_to(page, card)
        await oxy_click(page, card)

        try:
            await page.wait_for_selector('span[data-testid="expandable-text-box"]', timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.5, 1.0))

        job_url = await page.evaluate("""() => {
            const a = document.querySelector('a[href*="/jobs/view/"]');
            if (!a) return null;
            const match = a.href.match(/\\/jobs\\/view\\/(\\d+)/);
            return match ? `https://www.linkedin.com/jobs/view/${match[1]}/` : null;
        }""")

        if job_url in existing_urls:
            print(f"  [{i}/{len(cards)}] SKIP (already in DB): {job_url}")
        else:
            description = await page.evaluate("""() => {
                const el = document.querySelector('span[data-testid="expandable-text-box"]');
                return el ? el.innerText.trim() : null;
            }""")

            applicants = await page.evaluate("""() => {
                const span = Array.from(document.querySelectorAll('span')).find(
                    s => s.textContent.includes('clicked apply') || s.textContent.includes('applicants')
                );
                return span ? span.textContent.trim() : null;
            }""")

            print(f"  [{i}/{len(cards)}] title={title} | employer={employer} | {posted} | {applicants} | {job_url}")
            rows.append((job_url, title, employer, posted, description, applicants))

        click_count += 1
        click_count = await inter_card_behavior(page, click_count, params)

    return rows


async def get_next_page_button(page, current_page: int):
    next_num = str(current_page + 1)
    buttons = await page.query_selector_all('button')
    for btn in buttons:
        if (await btn.inner_text()).strip() == next_num:
            return btn
    return None


async def scrape_jobs():
    params = ScrollBehaviorParams()

    async with open_session(url) as page:
        print(f"Browser open at: {page.url}")

        search_bar = await page.query_selector('input[data-testid="typeahead-input"]')
        if search_bar:
            print("Search bar found — moving to it")
            await oxy_click(page, search_bar)
            print("Clicked search bar — waiting for dropdown")

            await page.wait_for_selector('[role="listbox"] a', timeout=5000)
            items = await page.query_selector_all('[role="listbox"] a')
            first_item = None
            for el in items:
                text = (await el.inner_text()).strip().lower()
                if text != "show all":
                    first_item = el
                    break
            if first_item:
                text = await first_item.inner_text()
                print(f"Clicking: {text.strip()}")
                await oxy_click(page, first_item)
                print("Clicked first dropdown item — waiting for page to settle")
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(3)
            else:
                print("No dropdown items found")
        else:
            print("Search bar not found")

        current_page = 1
        while current_page <= 20:
            print(f"\n--- Page {current_page} ---")
            rows = await click_all_job_cards(page, params)
            bulk_upsert(rows)

            next_btn = await get_next_page_button(page, current_page)
            if not next_btn:
                print(f"No page {current_page + 1} button found — done.")
                break

            print(f"Navigating to page {current_page + 1}...")
            await human_scroll_to(page, next_btn)
            await oxy_click(page, next_btn)
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(2.0, 4.0))
            current_page += 1

        input("\nPress Enter to close...")


if __name__ == '__main__':
    asyncio.run(scrape_jobs())
