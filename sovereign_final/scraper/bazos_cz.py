"""
scraper/bazos_cz.py — flats for sale on reality.bazos.cz (Czech market,
mostly private sellers).

Bazoš runs the same software in both countries: the Czech site's flats for
sale are at /prodam/byt/, paginated by an offset in the path (/prodam/byt/20/),
with the result cards scraper/bazos.py reads on the Slovak site
(div.inzeratyflex, the title link to /inzerat/<id>/…, div.inzeratycena,
div.inzeratylok). That the Czech markup matches the Slovak one could not be
checked from here (no .cz host was reachable); the parser falls back to any
/inzerat/ link, as the Slovak one does.

The Czech robots.txt disallows the query-string search (hledat=, rubriky=,
cenaod= …), which the Slovak scraper uses as a fallback — so only the path
URLs are read here. A listing's own page adds its full text (its
og:description / description meta — the Slovak scraper reads cards only).
Bazoš gives no coordinates.

  python3 -m scraper.bazos_cz          # direct run, 3 pages
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC, DETAIL_REFRESH_DAYS
from database import (
    upsert_listing, init_db, get_fresh_detail_urls, mark_details_enriched,
    touch_listings,
)
from scraper._http import get, make_session
from scraper.cz_common import (
    PortalBlocked, require_robots, listing_record, sale_price, rooms_cz,
    area_cz, energy_cz, is_excluded_cz, cleanup, place_from_text,
)

log = logging.getLogger(__name__)

SOURCE = "bazos_cz"
BASE = "https://reality.bazos.cz"
CATEGORY = "/prodam/byt/"
PAGE_SIZE = 20
_ID_RE = re.compile(r"/inzerat/(\d+)/")
_PSC_RE = re.compile(r"\b\d{3}\s?\d{2}\b")
_META_DESC = re.compile(
    r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]*)"', re.I)


def page_url(offset: int) -> str:
    return BASE + CATEGORY + (f"{offset}/" if offset else "")


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def place(text: str) -> str:
    """"Praha 4 140 00" → "Praha 4": the town without its postcode."""
    return re.sub(r"\s+", " ", _PSC_RE.sub(" ", text or "")).strip(" ,-")


def listing_from_card(card, link, now: str | None = None) -> dict | None:
    href = link.get("href", "")
    if not href.startswith("http"):
        href = BASE + "/" + href.lstrip("/")
    m = _ID_RE.search(href)
    if not m:
        return None
    title = _text(link) or _text(card)[:120]
    card_text = _text(card)
    if is_excluded_cz(title, href):
        return None
    size = area_cz(title) or area_cz(card_text)
    loc = card.select_one("div.inzeratylok, .lokalita, [class*='lokalita']")
    district = place(_text(loc)) or place_from_text(f"{title} {card_text}")
    price_el = card.select_one("div.inzeratycena, .cena, [class*='cena']")
    price = sale_price(_text(price_el), size, district) if price_el else 0.0
    if not price:
        price = sale_price(card_text, size, district)
    img = card.select_one("img[src]")
    image = img.get("src", "") if img else ""
    if image.startswith("//"):
        image = "https:" + image
    return listing_record(SOURCE, m.group(1), href, title=title, price=price, size=size,
                          rooms=rooms_cz(title) or rooms_cz(card_text), district=district,
                          address=_text(loc) or district, description=card_text,
                          energy=energy_cz(card_text),
                          image=image if image.startswith("http") else "", now=now)


def parse_page(html: str, now: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    cards = soup.select("div.inzeratyflex") or soup.select("div[class*='inzeratyflex']")
    pairs = []
    if cards:
        for card in cards:
            link = card.select_one("div.inzeratynadpis a, h2 a, h3 a, a[href*='/inzerat/']")
            if link:
                pairs.append((card, link))
    else:
        for link in soup.select("a[href*='/inzerat/']"):
            pairs.append((link.parent or link, link))
    for card, link in pairs:
        if link.get("href") in seen:
            continue
        seen.add(link.get("href"))
        try:
            rec = listing_from_card(card, link, now)
        except Exception as e:
            log.warning(f"    ⚠️ Card error: {e}")
            continue
        if rec:
            out.append(rec)
    return out


def apply_detail(listing: dict, html: str) -> None:
    """The listing's full text from its own page (description meta), and
    what it states: size, rooms, PENB, the price when the card had none."""
    m = _META_DESC.search(html or "")
    text = html_lib.unescape(m.group(1)).strip() if m else ""
    if not text:
        return
    if len(text) > len(listing.get("description") or ""):
        listing["description"] = text[:8000]
    if not listing.get("size_m2"):
        listing["size_m2"] = area_cz(text)
    if not listing.get("rooms"):
        listing["rooms"] = rooms_cz(text)
    energy = energy_cz(text)
    if energy != "UNKNOWN" and listing.get("energy_class") in (None, "", "UNKNOWN"):
        listing["energy_class"] = energy
    if not listing.get("price_eur"):
        listing["price_eur"] = sale_price(text, listing.get("size_m2") or 0,
                                          listing.get("district") or "")


def run(max_pages: int = 10) -> int:
    require_robots(page_url(PAGE_SIZE))
    log.info(f"🔍 Bazos.cz ({max_pages} pages)...")
    session = make_session(BASE)
    fresh = get_fresh_detail_urls(SOURCE, max_age_days=DETAIL_REFRESH_DAYS)
    total = touched = 0
    first_status = None
    for p in range(max_pages):
        try:
            r = get(page_url(p * PAGE_SIZE), session=session, timeout=20)
        except Exception as e:
            log.warning(f"  Page {p + 1}: {e}")
            first_status = first_status or 0
            break
        first_status = first_status or r.status_code
        if r.status_code != 200:
            log.info(f"  Page {p + 1}: HTTP {r.status_code}")
            break
        now = datetime.now(timezone.utc).isoformat()
        listings = parse_page(r.text, now)
        if not listings:
            break
        enriched = []
        for listing in listings:
            if listing["url"] in fresh:
                touched += touch_listings([listing["url"]])
                continue
            try:
                require_robots(listing["url"])
                d = get(listing["url"], session=session, timeout=20)
                if d.status_code == 200:
                    apply_detail(listing, d.text)
                    enriched.append(listing["id"])
            except PortalBlocked:
                pass
            except Exception as e:
                log.warning(f"    detail {listing['url']}: {e}")
            try:
                upsert_listing(listing)
                total += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
            time.sleep(0.4)
        mark_details_enriched(enriched)
        log.info(f"  Page {p + 1}: {len(listings)} listings")
        time.sleep(SCRAPE_DELAY_SEC)
    if total == 0 and touched == 0:
        why = (f"HTTP {first_status}" if first_status not in (None, 200) else
               "0 listings — the page markup may have changed")
        raise PortalBlocked(f"Bazos.cz returned nothing: {why}")
    cleanup(SOURCE)
    log.info(f"✅ Bazos.cz done. {total} upserted, {touched} unchanged.")
    return total + touched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=3)
