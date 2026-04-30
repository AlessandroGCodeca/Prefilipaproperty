#!/usr/bin/env python3
"""
Debug Playwright against nehnutelnosti.sk: visible browser, logs all
responses, saves screenshot + HTML, patches navigator.webdriver.

  python3 debug_playwright.py
"""
import sys, json
from playwright.sync_api import sync_playwright

URL = "https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj?page=1"

# Stealth init script — runs before any page JS, patches the obvious
# headless tells that Imperva checks for.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins',  { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages',{ get: () => ['sk-SK', 'sk', 'en'] });
window.chrome = { runtime: {}, loadTimes: () => ({}), csi: () => ({}) };
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
  p.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : origQuery(p);
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=False,  # visible so you can see if Imperva shows a challenge
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="sk-SK",
        viewport={"width": 1280, "height": 900},
    )
    ctx.add_init_script(STEALTH_JS)
    page = ctx.new_page()

    api_calls = []
    all_responses = []

    def on_response(response):
        all_responses.append((response.status, response.url))
        if "/api/" in response.url or "search" in response.url.lower() or "advert" in response.url.lower():
            try:
                body = response.text()
                api_calls.append({
                    "url": response.url,
                    "status": response.status,
                    "ctype": response.headers.get("content-type", ""),
                    "len": len(body),
                    "preview": body[:200],
                })
            except Exception:
                pass

    page.on("response", on_response)

    print(f"Loading {URL} ...")
    try:
        page.goto(URL, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"Load error: {e}")

    page.wait_for_timeout(3000)

    page.screenshot(path="playwright_screenshot.png", full_page=True)
    html = page.content()
    with open("playwright_dom.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"saved playwright_dom.html ({len(html):,} chars)")
    print(f"saved playwright_screenshot.png")

    print(f"\n{'='*60}")
    print(f"All responses ({len(all_responses)}):")
    print('='*60)
    for status, url in all_responses[:40]:
        if any(t in url for t in ["api", "search", "advert", "result", "listing", "v2", "graphql"]):
            print(f"  {status}  {url[:120]}")

    print(f"\n{'='*60}")
    print(f"API/search/advert calls captured ({len(api_calls)}):")
    print('='*60)
    for c in api_calls:
        print(f"\n  {c['status']}  {c['url']}")
        print(f"  type: {c['ctype']}, len: {c['len']:,}")
        print(f"  preview: {c['preview'][:300]}")

    # Check the DOM for listings
    nehnut_links = page.eval_on_selector_all(
        "a[href*='/nehnutelnost/']", "els => els.length"
    )
    print(f"\n/nehnutelnost/ links in DOM: {nehnut_links}")

    title = page.title()
    print(f"page title: {title}")

    # Check for Imperva challenge
    if "imperva" in html.lower() or "incapsula" in html.lower() or "are you a robot" in html.lower():
        print("\n⚠️  PAGE CONTAINS IMPERVA/INCAPSULA CHALLENGE")

    # Take any visible listing snippet
    bratislava_count = html.count("Bratislava")
    izbov = html.count("izbov")
    print(f"\n'Bratislava' in DOM: {bratislava_count}")
    print(f"'izbov' in DOM: {izbov}")

    print("\nKeeping browser open for 10 seconds so you can inspect...")
    page.wait_for_timeout(10000)

    browser.close()
