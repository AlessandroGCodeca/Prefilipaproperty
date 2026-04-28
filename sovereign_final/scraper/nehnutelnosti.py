"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk
"""

import hashlib, time, re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db
from scraper._http import get, make_session

BASE   = "https://www.nehnutelnosti.sk"
SEARCH = BASE + "/slovensko/byty/predaj/?p[page]={page}"

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
        r = get(SEARCH.format(page=1), timeout=10)
        return r.status_code, r.text[:300].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def scrape_page(page: int, session=None) -> list[dict]:
    url = SEARCH.format(page=page)
    try:
        r = get(url, session=session, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Page {page}: {e}", flush=True)
        return []

    soup  = BeautifulSoup(r.text, "html.parser")

    cards = (
        soup.select("div.advertisement-item")
        or soup.select("div[class*='advertisement-item']")
        or soup.select("div[class*='property-card']")
        or soup.select("div[class*='PropertyCard']")
        or soup.select("li[class*='advertisement']")
        or soup.select("article[class*='listing']")
        or soup.select("article")
        or soup.select("a[href*='/nehnutelnost/']")
    )

    results = []
    now = datetime.now(timezone.utc).isoformat()

    for card in cards:
        try:
            link = card if card.name == "a" else card.select_one("a[href*='/nehnutelnost/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = BASE + href
            if "/nehnutelnost/" not in href:
                continue

            price_tag  = (
                card.select_one("[class*='price'],[class*='Price']")
                or card.select_one("[data-price]")
            )
            size_tag   = (
                card.select_one("[class*='size'],[class*='area'],[class*='m2']")
                or card.select_one("[class*='Size'],[class*='Area']")
            )
            addr_tag   = (
                card.select_one("[class*='address'],[class*='location']")
                or card.select_one("[class*='Address'],[class*='Location']")
            )
            energy_tag = card.select_one("[class*='energy'],[class*='Energy'],[class*='energeticka']")
            img_tag    = card.select_one("img[src]")
            title_tag  = card.select_one("h2,h3,[class*='title'],[class*='Title']")

            price  = _price(price_tag.get_text() if price_tag else "")
            size   = _size(size_tag.get_text() if size_tag else "")
            addr   = (addr_tag.get_text(strip=True) if addr_tag else "")
            raw_e  = (energy_tag.get_text(strip=True).upper() if energy_tag else "UNKNOWN")
            energy = raw_e if raw_e in ENERGY_VALID else "UNKNOWN"
            img    = img_tag.get("src", "") if img_tag else ""
            title  = (title_tag.get_text(strip=True) if title_tag else addr)

            uid = hashlib.md5(href.encode()).hexdigest()
            results.append({
                "id":                uid,
                "source":            "nehnutelnosti",
                "url":               href,
                "url_hash":          uid,
                "title":             title[:200],
                "description":       "",
                "price_eur":         price,
                "size_m2":           size,
                "rooms":             None,
                "floor":             None,
                "year_built":        None,
                "energy_class":      energy,
                "address_raw":       addr,
                "district":          _district(addr),
                "city":              "",
                "primary_image_url": img,
                "image_urls":        img,
                "classification":    "PENDING",
                "lv_status":         "PENDING",
                "scraped_at":        now,
                "last_seen_at":      now,
            })
        except Exception as e:
            print(f"    ⚠️ Card parse error: {e}", flush=True)

    return results


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
        listings = scrape_page(p, session=session)
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
            "Site responded but 0 listing cards matched the CSS selectors — "
            "the site layout may have changed."
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
