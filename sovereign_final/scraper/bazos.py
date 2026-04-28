"""
scraper/bazos.py — Sovereign Investor Dashboard
Scrapes private-seller listings from bazos.sk/reality
"""

import hashlib, time, re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db
from scraper._http import get, make_session

BASE   = "https://reality.bazos.sk"
SEARCH = BASE + "/predaj/byt/?hledat=&rubriky=byt&hlokalita=&humkreis=25&cenaod=&cenado=&Submit=Hledat&kitems=20&offset={offset}"


def _price(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(text: str) -> str:
    parts = [p.strip() for p in (text or "").split(",")]
    return parts[-1] if parts else ""


def check_reachable() -> tuple[int, str]:
    try:
        r = get(SEARCH.format(offset=0), timeout=10)
        return r.status_code, r.text[:300].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def scrape_page(offset: int, session=None) -> list[dict]:
    url = SEARCH.format(offset=offset)
    try:
        r = get(url, session=session, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠️ Offset {offset}: {e}", flush=True)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

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

            title     = link.get_text(strip=True)
            price_tag = card.select_one(".cena, [class*='price'], [class*='cena']")
            desc_tag  = card.select_one(".popis, p, [class*='desc'], [class*='popis']")
            loc_tag   = card.select_one(".lokalita, [class*='location'], [class*='lokalita'], [class*='mesto']")
            img_tag   = card.select_one("img[src]")

            price = _price(price_tag.get_text() if price_tag else "")
            desc  = desc_tag.get_text(" ", strip=True) if desc_tag else title
            size  = _size(desc) or _size(title)
            addr  = loc_tag.get_text(strip=True) if loc_tag else ""
            img   = img_tag.get("src", "") if img_tag else ""

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
            print(f"    ⚠️ Card error: {e}", flush=True)

    return results


def run(max_pages: int = 10) -> int:
    status, snippet = check_reachable()
    if status != 200:
        raise RuntimeError(
            f"Bazos blocked or unreachable: HTTP {status} — {snippet[:120]}"
        )

    print(f"🔍 Bazos.sk ({max_pages} pages)...", flush=True)
    session = make_session(warmup_url=BASE)
    total = 0
    for p in range(max_pages):
        listings = scrape_page(p * 20, session=session)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}", flush=True)
        print(f"  Page {p+1}: {len(listings)} found", flush=True)
        time.sleep(SCRAPE_DELAY_SEC)
    if total == 0:
        raise RuntimeError(
            "Site responded but 0 listing cards matched the CSS selectors — "
            "the site layout may have changed."
        )
    print(f"✅ Bazos done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
