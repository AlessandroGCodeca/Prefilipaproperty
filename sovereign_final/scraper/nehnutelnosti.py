"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk.

The site is a React/MUI SPA — static HTML has no listing cards and the
internal JSON API requires a session token (returns 403 or HTML shell to
unauthenticated requests). The only reliable approach is JS-rendered HTML
via ScraperAPI render=True (headless Chrome).
"""

import hashlib, time, re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC, SCRAPER_API_KEY
from database import upsert_listing, init_db
from scraper._http import get, make_session

BASE        = "https://www.nehnutelnosti.sk"
SEARCH_PAGE = BASE + "/slovensko/byty/predaj/?p[page]={page}"

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


def _scrape_page(page: int, session=None) -> list[dict]:
    """Fetch one page using ScraperAPI render=True and parse the rendered DOM."""
    url = SEARCH_PAGE.format(page=page)
    try:
        r = get(url, session=session, timeout=90, render=True)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Page {page}: {e}", flush=True)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # After JS rendering, listing detail-page links appear as a[href*='/nehnutelnost/']
    links = soup.select("a[href*='/nehnutelnost/']")

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

        # Walk up to find a card-like container (article/li/div with substantial text)
        card = link.parent
        for _ in range(5):
            if card is None:
                break
            text_len = len(card.get_text(" ", strip=True))
            if card.name in ("article", "li") or text_len > 60:
                break
            card = card.parent

        card_text = card.get_text(" ", strip=True) if card else link.get_text(" ", strip=True)

        price = 0.0
        m = re.search(r"([\d\s ]{4,})\s*(?:€|EUR)", card_text, re.I)
        if m:
            price = _price(m.group(1))

        size = _size(card_text)
        title = link.get_text(strip=True) or card_text[:80]

        # Try to find an address fragment (text often contains city, district)
        addr_match = re.search(r"(Bratislava|Košice|Žilina|Nitra|Trnava|Trenčín|Prešov|Banská Bystrica|Martin|Poprad)[^,€]{0,60}", card_text)
        addr = addr_match.group(0).strip() if addr_match else ""

        img_tag = card.select_one("img[src]") if card else None
        img = img_tag.get("src", "") if img_tag else ""

        uid = hashlib.md5(href.encode()).hexdigest()
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


def run(max_pages: int = 10) -> int:
    if not SCRAPER_API_KEY:
        raise RuntimeError(
            "Nehnutelnosti.sk is a React SPA and requires JavaScript rendering. "
            "Set SCRAPER_API_KEY in sovereign_final/.env to enable scraping."
        )

    status, snippet = check_reachable()
    if status != 200:
        raise RuntimeError(
            f"Nehnutelnosti blocked or unreachable: HTTP {status} — {snippet[:120]}"
        )

    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages, JS-rendered)...", flush=True)
    session = make_session(warmup_url=BASE)
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
            "Nehnutelnosti: render=True returned pages but 0 listings parsed. "
            "The DOM structure may have changed — inspect a rendered page."
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=2)
