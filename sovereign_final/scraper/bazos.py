"""
scraper/bazos.py — Sovereign Investor Dashboard
Scrapes private-seller listings from bazos.sk/reality
"""

import hashlib, time, re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db

BASE    = "https://reality.bazos.sk"
SEARCH  = BASE + "/predaj/byt/?hledat=&rubriky=byt&hlokalita=&humkreis=25&cenaod=&cenado=&Submit=Hledat&kitems=20&offset={offset}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Referer": BASE + "/",
}


def _price(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(text: str) -> str:
    parts = [p.strip() for p in (text or "").split(",")]
    return parts[-1] if parts else ""


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(BASE, timeout=10)
        time.sleep(1)
    except Exception:
        pass
    return s


def scrape_page(offset: int, session: requests.Session = None) -> list[dict]:
    url = SEARCH.format(offset=offset)
    sess = session or requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Offset {offset}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Try multiple selector strategies
    cards = (
        soup.select("div.inzeraty div.inzerat")
        or soup.select("div.maincontent div.inzerat")
        or soup.select("div.inzerat")
        or soup.select("div[class*='inzerat']")
        or soup.select("article.inzerat, article[class*='ad']")
        or soup.select("div.item, div[class*='item']")
    )

    now = datetime.now(timezone.utc).isoformat()
    results = []

    for card in cards:
        try:
            link = card.select_one("h2 a, h3 a, a.nadpis, a[href*='/inzerat/']")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")

            title      = link.get_text(strip=True)
            price_tag  = card.select_one(".cena, [class*='price'], [class*='cena']")
            desc_tag   = card.select_one(".popis, p, [class*='desc'], [class*='popis']")
            loc_tag    = card.select_one(".lokalita, [class*='location'], [class*='lokalita'], [class*='mesto']")
            img_tag    = card.select_one("img[src]")

            price = _price(price_tag.get_text() if price_tag else "")
            desc  = desc_tag.get_text(" ", strip=True) if desc_tag else title
            size  = _size(desc) or _size(title)
            addr  = loc_tag.get_text(strip=True) if loc_tag else ""
            img   = img_tag.get("src", "") if img_tag else ""

            if not href:
                continue

            uid = hashlib.md5(href.encode()).hexdigest()

            results.append({
                "id":                uid,
                "source":            "bazos",
                "url":               href,
                "url_hash":          uid,
                "title":             title[:200],
                "description":       desc[:500],
                "price_eur":         price,
                "size_m2":           size,
                "rooms":             None,
                "floor":             None,
                "year_built":        None,
                "energy_class":      "UNKNOWN",
                "address_raw":       addr or title,
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
            print(f"    ⚠️ Card error: {e}")

    return results


def run(max_pages: int = 10) -> int:
    print(f"🔍 Bazos.sk ({max_pages} pages)...")
    session = _make_session()
    total = 0
    for p in range(max_pages):
        listings = scrape_page(p * 20, session=session)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}")
        print(f"  Page {p+1}: {len(listings)} found")
        time.sleep(SCRAPE_DELAY_SEC)
    print(f"✅ Bazos done. {total} upserted.\n")
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
