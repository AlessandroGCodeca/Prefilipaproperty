"""
scraper/bazos.py — Sovereign Investor Dashboard
Scrapes private-seller listings from reality.bazos.sk
"""

import hashlib, time, re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db
from scraper._http import get, make_session
from scraper.nehnutelnosti import _extract_location_from_text

BASE         = "https://reality.bazos.sk"
CATEGORY     = "/predam/byt/"
# Bazos paginates with an offset number appended to the path: /predam/byt/20/
PAGE_URL     = BASE + CATEGORY + "{offset}/"
PAGE_URL_QS  = BASE + CATEGORY + "?hledat=&rubriky=byt&hlokalita=&humkreis=25&cenaod=&cenado=&Submit=Hledat&kitems=20&offset={offset}"
PAGE_SIZE    = 20

# Plausible apartment sale prices — anything outside this range is treated as
# a deposit, monthly rent, or fee rather than a real sale price.
_PRICE_MIN = 30_000
_PRICE_MAX = 10_000_000


def _is_plausible_price(v: float) -> bool:
    return _PRICE_MIN <= v <= _PRICE_MAX


def _price(text: str) -> float:
    if not text:
        return 0.0
    candidates: list[float] = []
    # Match prices with a € or EUR suffix and either grouped digits or 4–8 plain digits.
    for m in re.finditer(r"(\d{1,3}(?:[\s\xa0  ]\d{3})+|\d{4,8})\s*(?:€|EUR)", text, re.I):
        try:
            v = float(re.sub(r"[\s\xa0  ]", "", m.group(1)))
            if _is_plausible_price(v):
                candidates.append(v)
        except Exception:
            pass
    if candidates:
        return max(candidates)
    # Fallback: bare digits (no currency symbol) — only accept if plausible.
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        try:
            v = float(digits)
            if _is_plausible_price(v):
                return v
        except Exception:
            pass
    return 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(text: str) -> str:
    parts = [p.strip() for p in (text or "").split(",")]
    return parts[-1] if parts else ""


def check_reachable() -> tuple[int, str]:
    try:
        r = get(BASE + CATEGORY, timeout=10)
        return r.status_code, r.text[:300].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def _build_listing_from_card(card, link) -> dict | None:
    """Build a listing record from a known card element + the listing link inside it."""
    href = link.get("href", "")
    if not href.startswith("http"):
        href = BASE + "/" + href.lstrip("/")
    if "/inzerat/" not in href:
        return None

    card_text = card.get_text(" ", strip=True)
    title = link.get_text(strip=True) or card_text[:80]

    # Price — bazos uses div.inzeratycena. _price() validates the value falls
    # within a plausible apartment sale-price range, rejecting deposits/fees.
    price = 0.0
    price_tag = card.select_one("div.inzeratycena, .cena, [class*='cena']")
    if price_tag:
        price = _price(price_tag.get_text())
    if not price:
        price = _price(card_text)

    # Size — search the card description text for m² patterns
    size = _size(card_text) or _size(title)

    # Location — bazos uses div.inzeratylok
    loc = card.select_one("div.inzeratylok, .lokalita, [class*='lokalita'], [class*='mesto']")
    addr = loc.get_text(" ", strip=True) if loc else ""
    # Bazos location strings often trail in a postcode ("821 01") or a region
    # ("okr. Bratislava II") that _district() then returns as the district —
    # garbage for rent estimates. Scan the card text for a known Slovak
    # city/suburb name and prefer that when found.
    matched = _extract_location_from_text(addr) or _extract_location_from_text(card_text)

    # Image
    img_tag = card.select_one("img[src]")
    img = img_tag.get("src", "") if img_tag else ""
    if img and not img.startswith("http"):
        img = "https:" + img if img.startswith("//") else BASE + img

    uid = hashlib.md5(href.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": uid, "source": "bazos", "url": href, "url_hash": uid,
        "title": title[:200], "description": card_text[:500],
        "price_eur": price, "size_m2": size,
        "rooms": None, "floor": None, "year_built": None,
        "energy_class": "UNKNOWN",
        "address_raw": matched or addr or title,
        "district": matched or _district(addr),
        "city": "",
        "primary_image_url": img, "image_urls": img,
        "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
    }


def _build_listing_from_link(link) -> dict | None:
    """Fallback: walk up from a stray /inzerat/ link to find a card-like ancestor."""
    card = link.parent
    for _ in range(6):
        if card is None:
            return None
        cls = " ".join(card.get("class") or [])
        if "inzeratyflex" in cls or "inzerat" in cls and card.name == "div":
            break
        card = card.parent
    return _build_listing_from_card(card, link) if card else None


def scrape_page(offset: int, session=None) -> list[dict]:
    # Try the path-based URL first, fall back to query-string URL
    for url in [PAGE_URL.format(offset=offset) if offset else BASE + CATEGORY,
                PAGE_URL_QS.format(offset=offset)]:
        try:
            r = get(url, session=session, timeout=20)
            if r.status_code == 200:
                break
        except Exception as e:
            print(f"    ⚠️ Offset {offset} ({url}): {e}", flush=True)
            r = None
    else:
        return []

    if not r or r.status_code != 200:
        print(f"    ⚠️ Offset {offset}: HTTP {r.status_code if r else '?'}", flush=True)
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Primary: real card class is "inzeraty inzeratyflex" (confirmed from live DOM)
    cards = (
        soup.select("div.inzeratyflex")
        or soup.select("div.inzeraty.inzeratyflex")
        or soup.select("div[class*='inzeratyflex']")
    )

    results = []

    if cards:
        for card in cards:
            try:
                link = card.select_one("div.inzeratynadpis a, h2 a, h3 a, a[href*='/inzerat/']")
                if not link:
                    continue
                rec = _build_listing_from_card(card, link)
                if rec:
                    results.append(rec)
            except Exception as e:
                print(f"    ⚠️ Card error: {e}", flush=True)
    else:
        # Fallback: collect all /inzerat/ links (avoids missing listings)
        links = soup.select("a[href*='/inzerat/']")
        seen = set()
        for link in links:
            href = link.get("href", "")
            if href in seen:
                continue
            seen.add(href)
            try:
                rec = _build_listing_from_link(link)
                if rec:
                    results.append(rec)
            except Exception as e:
                print(f"    ⚠️ Link error: {e}", flush=True)

    return results


def _backfill_blank_districts() -> int:
    """Re-extract district from address_raw/description for existing rows that
    have a blank district. Older scraper versions stored postcodes or empty
    strings; the location helper finds the real city/suburb name."""
    from database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, address_raw, description, title FROM listings "
        "WHERE source='bazos' AND (district IS NULL OR district='')"
    ).fetchall()
    updated = 0
    for row_id, addr, desc, title in rows:
        for text in (addr, desc, title):
            matched = _extract_location_from_text(text or "")
            if matched:
                conn.execute(
                    "UPDATE listings SET district=? WHERE id=?",
                    (matched, row_id),
                )
                updated += 1
                break
    conn.commit()
    conn.close()
    if updated:
        print(f"  ↳ backfilled district on {updated} bazos rows from card text")
    return updated


def _zero_bogus_prices() -> int:
    """Reset prices below the plausible-apartment threshold (deposits, monthly
    rents, fees) on existing bazos rows so they re-classify as PENDING."""
    from database import get_conn
    conn = get_conn()
    n = conn.execute(
        "UPDATE listings SET price_eur=0, classification='PENDING' "
        "WHERE source='bazos' AND price_eur > 0 AND price_eur < ?",
        (_PRICE_MIN,),
    ).rowcount
    conn.commit()
    conn.close()
    if n:
        print(f"  ↳ zeroed {n} bazos listings with bogus prices (< €{_PRICE_MIN:,})")
    return n


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
        offset = p * PAGE_SIZE
        listings = scrape_page(offset, session=session)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}", flush=True)
        print(f"  Page {p+1} (offset={offset}): {len(listings)} found", flush=True)
        if not listings and p > 0:
            break  # stop early if a page returns nothing (end of results)
        time.sleep(SCRAPE_DELAY_SEC)

    if total == 0:
        raise RuntimeError(
            "Bazos responded but 0 listings found — "
            "URL or selectors may have changed."
        )
    _zero_bogus_prices()
    _backfill_blank_districts()
    from engine.regional_prices import zero_below_regional_floor
    zero_below_regional_floor("bazos")
    print(f"✅ Bazos done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
