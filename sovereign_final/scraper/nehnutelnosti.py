"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk.

Strategy (in order):
1. ScraperAPI render=True (headless Chrome) with retry — works when render
   service is up; costs 25 credits/page.
2. Plain HTML + embedded-JSON extraction — the 1 MB HTML contains the JS
   bundle; we regex-search it for listing URLs and JSON state blobs.
"""

import hashlib, time, re, json
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC, SCRAPER_API_KEY
from database import upsert_listing, init_db
from scraper._http import get, make_session, SCRAPER_API_BASE, BROWSER_HEADERS

import requests as _requests

BASE        = "https://www.nehnutelnosti.sk"
# The actual listings page (NOT /slovensko/byty/predaj/ — that's a redirect shell)
SEARCH_PAGE = BASE + "/vysledky/byty/slovensko/predaj?page={page}"

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


def check_reachable() -> tuple[int, str]:
    try:
        r = get(SEARCH_PAGE.format(page=1), timeout=10)
        return r.status_code, r.text[:300].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def _render_url(url: str) -> str:
    """Build ScraperAPI render URL with Slovak country code and 3s wait."""
    encoded = _requests.utils.quote(url, safe="")
    return (
        f"{SCRAPER_API_BASE}?api_key={SCRAPER_API_KEY}"
        f"&url={encoded}&render=true&country_code=sk&wait=3000"
    )


def _parse_rendered_html(html: str, now: str) -> list[dict]:
    """Extract listings from a fully JS-rendered page."""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("a[href*='/nehnutelnost/']")
    results, seen = [], set()

    for link in links:
        href = link.get("href", "")
        if not href.startswith("http"):
            href = BASE + href
        if "/nehnutelnost/" not in href or href in seen:
            continue
        seen.add(href)

        card = link.parent
        for _ in range(5):
            if card is None:
                break
            if card.name in ("article", "li") or len(card.get_text(" ", strip=True)) > 60:
                break
            card = card.parent

        card_text = card.get_text(" ", strip=True) if card else link.get_text(" ", strip=True)
        price = 0.0
        m = re.search(r"([\d\s ]{4,})\s*(?:€|EUR)", card_text, re.I)
        if m:
            price = _price(m.group(1))
        size  = _size(card_text)
        title = link.get_text(strip=True) or card_text[:80]
        addr_m = re.search(
            r"(Bratislava|Košice|Žilina|Nitra|Trnava|Trenčín|Prešov|"
            r"Banská Bystrica|Martin|Poprad)[^,€]{0,60}",
            card_text
        )
        addr = addr_m.group(0).strip() if addr_m else ""
        img_tag = card.select_one("img[src]") if card else None
        img  = img_tag.get("src", "") if img_tag else ""
        uid  = hashlib.md5(href.encode()).hexdigest()
        results.append({
            "id": uid, "source": "nehnutelnosti", "url": href, "url_hash": uid,
            "title": title[:200], "description": "",
            "price_eur": price, "size_m2": size,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": "UNKNOWN",
            "address_raw": addr, "district": _district(addr), "city": "",
            "primary_image_url": img, "image_urls": img,
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        })
    return results


def _parse_embedded_json(html: str, now: str) -> list[dict]:
    """
    Fallback: search the raw (non-rendered) HTML for any JSON blobs or
    listing URLs embedded in the JS bundle. Works without a render step.
    """
    results = []

    # 1. Look for listing detail-page URLs directly in the source
    raw_urls = re.findall(
        r'"(https?://www\.nehnutelnosti\.sk/nehnutelnost/[^"]{10,})"', html
    )
    # Also relative hrefs like "/nehnutelnost/..."
    raw_urls += [BASE + u for u in re.findall(r'"/nehnutelnost/([^"]{10,})"', html)]

    seen = set()
    for url in raw_urls:
        url = url.rstrip("/") + "/"
        if url in seen:
            continue
        seen.add(url)
        uid = hashlib.md5(url.encode()).hexdigest()
        results.append({
            "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
            "title": "", "description": "",
            "price_eur": 0.0, "size_m2": 0.0,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": "UNKNOWN",
            "address_raw": "", "district": "", "city": "",
            "primary_image_url": "", "image_urls": "",
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        })
        if len(results) >= 50:
            break

    if results:
        return results

    # 2. Look for JSON arrays that look like listing collections
    json_blobs = re.findall(r'\[(\{["\'](?:id|advertId|url)["\'][^\]]{50,})\]', html)
    for blob in json_blobs[:3]:
        try:
            items = json.loads("[" + blob + "]")
            for item in items[:30]:
                url = (item.get("url") or item.get("seoUrl") or "")
                if not url or "nehnutelnost" not in url:
                    continue
                if not url.startswith("http"):
                    url = BASE + url
                uid = hashlib.md5(url.encode()).hexdigest()
                price = float(item.get("price") or item.get("priceValue") or 0)
                size  = float(item.get("area") or item.get("floorArea") or 0)
                results.append({
                    "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
                    "title": item.get("title", "")[:200], "description": "",
                    "price_eur": price, "size_m2": size,
                    "rooms": None, "floor": None, "year_built": None,
                    "energy_class": "UNKNOWN",
                    "address_raw": "", "district": "", "city": "",
                    "primary_image_url": "", "image_urls": "",
                    "classification": "PENDING", "lv_status": "PENDING",
                    "scraped_at": now, "last_seen_at": now,
                })
        except Exception:
            pass

    return results


def _scrape_page(page: int, session=None) -> list[dict]:
    url = SEARCH_PAGE.format(page=page)
    now = datetime.now(timezone.utc).isoformat()

    # ── Strategy 1: render=True with retries ─────────────────────────────────
    if SCRAPER_API_KEY:
        render_url = _render_url(url)
        for attempt in range(3):
            try:
                r = session.get(render_url, timeout=90) if session else _requests.get(render_url, timeout=90)
                if r.status_code == 200:
                    listings = _parse_rendered_html(r.text, now)
                    if listings:
                        return listings
                    print(f"    ⚠️ Render OK but 0 links found (page {page})", flush=True)
                    break  # page rendered but no links — no point retrying
                else:
                    wait = 2 ** attempt
                    print(f"    ⚠️ Render HTTP {r.status_code} (attempt {attempt+1}/3), retrying in {wait}s...", flush=True)
                    time.sleep(wait)
            except Exception as e:
                wait = 2 ** attempt
                print(f"    ⚠️ Render error (attempt {attempt+1}/3): {e}", flush=True)
                time.sleep(wait)

    # ── Strategy 2: plain fetch + embedded JSON/URL extraction ────────────────
    print(f"  Page {page}: trying plain HTML extraction...", flush=True)
    try:
        r = get(url, session=session, timeout=20)
        if r.status_code == 200:
            listings = _parse_embedded_json(r.text, now)
            if listings:
                print(f"  Page {page}: found {len(listings)} URLs in HTML bundle", flush=True)
                return listings
    except Exception as e:
        print(f"    ⚠️ Plain fetch error: {e}", flush=True)

    return []


def run(max_pages: int = 10) -> int:
    status, snippet = check_reachable()
    if status != 200:
        raise RuntimeError(
            f"Nehnutelnosti blocked or unreachable: HTTP {status} — {snippet[:120]}"
        )

    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages)...", flush=True)
    session = _requests.Session()
    session.headers.update(BROWSER_HEADERS)
    total = 0

    for p in range(1, max_pages + 1):
        listings = _scrape_page(p, session=session)
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
            "Nehnutelnosti: 0 listings after render and HTML-extraction attempts.\n"
            "To debug: open browser DevTools → Network tab → reload nehnutelnosti.sk "
            "→ find the XHR/fetch request that returns listing JSON → paste the URL here."
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=2)
