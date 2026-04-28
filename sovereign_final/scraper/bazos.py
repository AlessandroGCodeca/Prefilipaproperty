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
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "sk-SK,sk;q=0.9",
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


def scrape_page(offset: int) -> list[dict]:
    url = SEARCH.format(offset=offset)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Offset {offset}: {e}")
        return []

    soup  = BeautifulSoup(r.text, "html.parser")
    cards = soup.select("div.inzeraty div.inzerat, div.maincontent div.inzerat")
    now   = datetime.now(timezone.utc).isoformat()
    results = []

    for card in cards:
        try:
            link = card.select_one("h2 a, h3 a, a.nadpis")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")

            title      = link.get_text(strip=True)
            price_tag  = card.select_one(".cena, [class*='price']")
            desc_tag   = card.select_one(".popis, p")
            loc_tag    = card.select_one(".lokalita, [class*='location']")
            img_tag    = card.select_one("img[src]")

            price = _price(price_tag.get_text() if price_tag else "")
            desc  = desc_tag.get_text(" ", strip=True) if desc_tag else title
            size  = _size(desc) or _size(title)
            addr  = loc_tag.get_text(strip=True) if loc_tag else ""
            img   = img_tag.get("src","") if img_tag else ""

            uid = hashlib.md5(href.encode()).hexdigest()

            results.append({
                "id":               uid,
                "source":           "bazos",
                "url":              href,
                "url_hash":         uid,
                "title":            title[:200],
                "description":      desc[:500],
                "price_eur":        price,
                "size_m2":          size,
                "rooms":            None,
                "floor":            None,
                "year_built":       None,
                "energy_class":     "UNKNOWN",
                "address_raw":      addr or title,
                "district":         _district(addr),
                "city":             "",
                "primary_image_url":img,
                "image_urls":       img,
                "classification":   "PENDING",
                "lv_status":        "PENDING",
                "scraped_at":       now,
                "last_seen_at":     now,
            })
        except Exception as e:
            print(f"    ⚠️ Card error: {e}")

    return results


def run(max_pages: int = 10) -> int:
    print(f"🔍 Bazos.sk ({max_pages} pages)...")
    total = 0
    for p in range(max_pages):
        listings = scrape_page(p * 20)
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
