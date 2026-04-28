"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk.
The site is a React/MUI SPA — static HTML has no listing cards.
When ScraperAPI key is set we use render=True (headless Chrome) to get the
fully executed DOM; otherwise we fall back to their public JSON search API.
"""

import hashlib, time, re, json
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db
from scraper._http import get, make_session
from config import SCRAPER_API_KEY

BASE        = "https://www.nehnutelnosti.sk"
SEARCH_PAGE = BASE + "/slovensko/byty/predaj/?p[page]={page}"

# Candidate JSON API endpoints — tried in order until one returns listings.
# Run analyze2.py to find the confirmed endpoint from the site's own HTML/JS.
API_CANDIDATES = [
    (
        "https://www.nehnutelnosti.sk/api/v1/adverts/search"
        "?transaction=SELL&category=BYTY&page={page}&limit=24&location=SLOVENSKO"
    ),
    (
        "https://www.nehnutelnosti.sk/api/v2/search"
        "?offerType=SELL&estateType=BYTY&page={page}&pageSize=24"
    ),
    (
        "https://www.nehnutelnosti.sk/api/v1/search"
        "?transaction=SELL&category=BYTY&page={page}"
    ),
]

ENERGY_VALID = {"A0", "A1", "A", "B", "C", "D", "E", "F", "G"}


def _price(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(address: str) -> str:
    parts = [p.strip() for p in (address or "").split(",")]
    return parts[-1] if parts else ""


def _parse_listing_from_json(item: dict) -> dict | None:
    """Convert one API result object to our DB schema."""
    try:
        url = item.get("url") or item.get("seoUrl") or item.get("link") or ""
        if not url:
            advert_id = item.get("id") or item.get("advertId") or ""
            if advert_id:
                url = f"{BASE}/nehnutelnost/{advert_id}/"
        if not url:
            return None
        if not url.startswith("http"):
            url = BASE + url

        price = 0.0
        price_obj = item.get("price") or item.get("priceInfo") or {}
        if isinstance(price_obj, dict):
            price = float(price_obj.get("value") or price_obj.get("amount") or
                          price_obj.get("priceValue") or 0)
        elif isinstance(price_obj, (int, float)):
            price = float(price_obj)

        size = 0.0
        params = item.get("parameters") or item.get("attrs") or {}
        if isinstance(params, dict):
            area = params.get("usableArea") or params.get("floorArea") or params.get("area") or 0
            size = float(area)
        if not size:
            size = float(item.get("floorArea") or item.get("area") or item.get("size") or 0)

        title = (item.get("title") or item.get("name") or item.get("heading") or "")
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
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
            "title": title[:200], "description": "",
            "price_eur": price, "size_m2": size,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": energy,
            "address_raw": addr, "district": _district(addr), "city": "",
            "primary_image_url": img, "image_urls": img,
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        }
    except Exception as e:
        print(f"    ⚠️ JSON parse error: {e}", flush=True)
        return None


def _scrape_via_api(page: int) -> list[dict]:
    """Try candidate JSON API endpoints in order until one returns listings."""
    for api_template in API_CANDIDATES:
        url = api_template.format(page=page)
        try:
            r = get(url, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:
            continue

        # The API might return {items:[...]}, {results:[...]}, {adverts:[...]}, or a list
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (data.get("items") or data.get("results") or
                     data.get("adverts") or data.get("data") or [])
        else:
            items = []

        if items:
            results = []
            for item in items:
                parsed = _parse_listing_from_json(item)
                if parsed:
                    results.append(parsed)
            if results:
                return results

    return []


def _scrape_via_render(page: int, session=None) -> list[dict]:
    """Fetch one page using ScraperAPI render=True (headless Chrome) then parse DOM."""
    url = SEARCH_PAGE.format(page=page)
    try:
        r = get(url, session=session, timeout=60, render=True)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Render page {page}: {e}", flush=True)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # After JS rendering, listing links should be present
    links = soup.select("a[href*='/nehnutelnost/']")
    if not links:
        # Fallback: try any card-like containers
        links = soup.select("a[href*='nehnutelnosti.sk']")

    results = []
    now = datetime.now(timezone.utc).isoformat()
    seen = set()

    for link in links:
        href = link.get("href", "")
        if not href.startswith("http"):
            href = BASE + href
        if "/nehnutelnost/" not in href or href in seen:
            continue
        seen.add(href)

        # Walk up to find the card container (usually 2-4 levels up from the link)
        card = link.parent
        for _ in range(4):
            if card and card.name in ("article", "li", "div"):
                text = card.get_text(" ", strip=True)
                if len(text) > 40:
                    break
            if card:
                card = card.parent

        card_text = card.get_text(" ", strip=True) if card else link.get_text(" ", strip=True)
        price = _price(re.search(r"[\d\s]{5,}(?:\s*€|\s*EUR)", card_text, re.I).group(0) if re.search(r"[\d\s]{5,}(?:\s*€|\s*EUR)", card_text, re.I) else "")
        size  = _size(card_text)
        title = link.get_text(strip=True) or card_text[:80]

        uid = hashlib.md5(href.encode()).hexdigest()
        results.append({
            "id": uid, "source": "nehnutelnosti", "url": href, "url_hash": uid,
            "title": title[:200], "description": "",
            "price_eur": price, "size_m2": size,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": "UNKNOWN",
            "address_raw": "", "district": "", "city": "",
            "primary_image_url": "", "image_urls": "",
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        })

    return results


def check_reachable() -> tuple[int, str]:
    try:
        r = get(SEARCH_PAGE.format(page=1), timeout=10)
        return r.status_code, r.text[:300].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def run(max_pages: int = 10) -> int:
    status, snippet = check_reachable()
    if status != 200:
        raise RuntimeError(
            f"Nehnutelnosti blocked or unreachable: HTTP {status} — {snippet[:120]}"
        )

    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages)...", flush=True)
    session = make_session(warmup_url=BASE)
    total = 0

    for p in range(1, max_pages + 1):
        # Try JSON API first (fastest, no credits); fall back to render if it returns nothing
        listings = _scrape_via_api(p)
        if not listings and SCRAPER_API_KEY:
            print(f"  Page {p}: API returned 0, trying render...", flush=True)
            listings = _scrape_via_render(p, session=session)

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
            "Nehnutelnosti: 0 listings after trying both JSON API and HTML render. "
            "The API path may have changed — check https://www.nehnutelnosti.sk/api/v1/adverts/search"
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
