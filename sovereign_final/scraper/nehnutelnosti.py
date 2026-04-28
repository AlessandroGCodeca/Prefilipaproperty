"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk
"""

import hashlib, time, re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db

BASE    = "https://www.nehnutelnosti.sk"
SEARCH  = BASE + "/slovensko/byty/predaj/?p[page]={page}"

# Full browser headers — avoids basic bot-detection blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

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


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    # Warm up with the homepage so we get session cookies before hitting search
    try:
        s.get(BASE, timeout=10)
        time.sleep(1)
    except Exception:
        pass
    return s


def scrape_page(page: int, session: requests.Session = None) -> list[dict]:
    url = SEARCH.format(page=page)
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Page {page}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Try multiple selector strategies in order of specificity
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

            if not href or "/nehnutelnost/" not in href:
                continue

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
            print(f"    ⚠️ Card parse error: {e}")

    return results


def run(max_pages: int = 10) -> int:
    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages)...")
    session = _make_session()
    total = 0
    for p in range(1, max_pages + 1):
        listings = scrape_page(p, session=session)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}")
        print(f"  Page {p}: {len(listings)} found")
        time.sleep(SCRAPE_DELAY_SEC)
    print(f"✅ Nehnutelnosti done. {total} upserted.\n")
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
