"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk.

nehnutelnosti.sk uses Imperva WAF that blocks all Python HTTP clients
regardless of TLS fingerprint. The only working approach is a real
headless browser via Playwright, which intercepts the /api/v2 XHR
responses as they flow through the genuine Chromium browser.

Install once:  pip install playwright && playwright install chromium
"""

import hashlib, time, re, json
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db

BASE        = "https://www.nehnutelnosti.sk"
SEARCH_PAGE = BASE + "/vysledky/byty/slovensko/predaj?page={page}"

ENERGY_VALID = {"A0", "A1", "A", "B", "C", "D", "E", "F", "G"}


def _check_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa
        return True
    except ImportError:
        return False


def _price(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(address: str) -> str:
    parts = [p.strip() for p in (address or "").split(",")]
    return parts[-1] if parts else ""


def _parse_api_item(item: dict, now: str) -> dict | None:
    """Convert one /api/v2 response object to our DB schema."""
    try:
        url = item.get("url") or item.get("seoUrl") or item.get("link") or ""
        advert_id = item.get("id") or item.get("advertId") or ""
        if not url and advert_id:
            url = f"{BASE}/nehnutelnost/{advert_id}/"
        if not url:
            return None
        if not url.startswith("http"):
            url = BASE + url

        price = 0.0
        price_obj = item.get("price") or item.get("priceInfo") or {}
        if isinstance(price_obj, dict):
            price = float(price_obj.get("value") or price_obj.get("amount") or 0)
        elif isinstance(price_obj, (int, float)):
            price = float(price_obj)

        size = 0.0
        for key in ("usableArea", "floorArea", "area", "size"):
            v = item.get(key) or (item.get("parameters") or {}).get(key)
            if v:
                size = float(v)
                break

        title = item.get("title") or item.get("name") or item.get("heading") or ""
        addr_obj = item.get("location") or item.get("address") or {}
        addr = (addr_obj.get("fullAddress") or addr_obj.get("address") or
                addr_obj.get("city") or "") if isinstance(addr_obj, dict) else str(addr_obj)

        energy_raw = (item.get("energyRating") or item.get("energyClass") or "").upper()
        energy = energy_raw if energy_raw in ENERGY_VALID else "UNKNOWN"

        imgs = item.get("images") or item.get("photos") or []
        img = ""
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            img = (first.get("url") or first.get("src") or first) if isinstance(first, dict) else str(first)

        uid = hashlib.md5(url.encode()).hexdigest()
        return {
            "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
            "title": str(title)[:200], "description": "",
            "price_eur": price, "size_m2": size,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": energy,
            "address_raw": addr, "district": _district(addr), "city": "",
            "primary_image_url": img, "image_urls": img,
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        }
    except Exception as e:
        print(f"    ⚠️  parse error: {e}", flush=True)
        return None


def _extract_items_from_json(data) -> list[dict]:
    """Try common response shapes to find the listing array."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "adverts", "data", "listings", "offers"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return v
    return []


def _scrape_page_playwright(page_num: int) -> list[dict]:
    """Use Playwright to load one page and capture /api/v2 responses."""
    from playwright.sync_api import sync_playwright

    url = SEARCH_PAGE.format(page=page_num)
    captured: list[dict] = []

    def _on_response(response):
        if "/api/v2" in response.url and response.status == 200:
            try:
                data = response.json()
                items = _extract_items_from_json(data)
                if items:
                    captured.extend(items)
            except Exception:
                pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="sk-SK",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.on("response", _on_response)

        page.goto(url, wait_until="networkidle", timeout=60000)
        # Give XHR a moment to settle
        page.wait_for_timeout(2000)

        # If no API responses captured, try DOM extraction as fallback
        if not captured:
            links = page.eval_on_selector_all(
                "a[href*='/nehnutelnost/']",
                "els => els.map(e => ({href: e.href, text: e.innerText}))"
            )
            now = datetime.now(timezone.utc).isoformat()
            for l in links:
                href = l.get("href", "")
                if href and "/nehnutelnost/" in href:
                    uid = hashlib.md5(href.encode()).hexdigest()
                    captured.append({
                        "id": uid, "source": "nehnutelnosti",
                        "url": href, "url_hash": uid,
                        "title": l.get("text", "")[:200],
                    })

        browser.close()

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for item in captured:
        # Items from DOM fallback are already minimal dicts
        if "source" in item and "url_hash" in item:
            results.append(item)
            continue
        parsed = _parse_api_item(item, now)
        if parsed:
            results.append(parsed)
    return results


def check_reachable() -> tuple[int, str]:
    try:
        import requests as _req
        r = _req.get(SEARCH_PAGE.format(page=1), timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code, ""
    except Exception as e:
        return 0, str(e)


def run(max_pages: int = 10) -> int:
    if not _check_playwright():
        raise RuntimeError(
            "Playwright is required for nehnutelnosti.sk (Imperva WAF bypass).\n"
            "Run:  pip install playwright && playwright install chromium"
        )

    status, _ = check_reachable()
    if status not in (200, 403):
        raise RuntimeError(f"Nehnutelnosti unreachable: HTTP {status}")

    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages, Playwright)...", flush=True)
    total = 0

    for p in range(1, max_pages + 1):
        listings = _scrape_page_playwright(p)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}", flush=True)
        print(f"  Page {p}: {len(listings)} found", flush=True)
        time.sleep(SCRAPE_DELAY_SEC)

    if total == 0:
        raise RuntimeError(
            "Nehnutelnosti: 0 listings after Playwright scrape.\n"
            "Try: headless=False in _scrape_page_playwright to see what's happening."
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=2)
