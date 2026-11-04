"""
scraper/idnes.py — flats for sale on reality.idnes.cz (Czech market).

  search   GET https://reality.idnes.cz/s/prodej/byty/          (page 1)
               https://reality.idnes.cz/s/prodej/byty/?page=N   (page N)
           one <div class="c-products__item"> per listing:
             <h2 class="c-products__title">prodej bytu 1+kk 38 m²</h2>
             <p class="c-products__info">Univerzitní, Praha 10 - Malešice</p>
             <p class="c-products__price"><strong>7 752 704 Kč</strong></p>
             <a href="https://reality.idnes.cz/detail/prodej/byt/<slug>/<24 hex>/">
           Past the last page the site answers 404.
  detail   the listing URL; its og:description reads "Prodej bytu 2+kk 65 m²,
           <address>. Cena 23 600 000 Kč. <agency>. <description>", and its
           parameter list (dt / dd) carries ownership, floor and PENB.

robots.txt allows plain ?page=N on a search and every detail page (it
disallows sorted, multi-value and some filter searches, none used here).
The card markup, the og:description shape and the 404 at the end are the
ones an open-source collector (ZMAN-91/prague-reality-scraper) documented
for Prague's branch of the same search in September 2026; the country-wide
branch and the dt / dd parameter list could not be checked from here (no
.cz host was reachable). iDNES publishes no coordinates, so its listings
are placed by their address (Location IQ geocodes it).

  python3 -m scraper.idnes             # direct run, 2 pages
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
    warmup_url,
    PortalBlocked, require_robots, robots_allows, listing_record, sale_price, rooms_cz,
    area_cz, energy_cz, is_excluded_cz, cleanup, fold, czk_amounts, place_from_text,
)
from scraper.geo import pin_from_meta

log = logging.getLogger(__name__)

SOURCE = "idnes"
BASE = "https://reality.idnes.cz"
SEARCH = BASE + "/s/prodej/byty/"
_DETAIL_RE = re.compile(r"/detail/prodej/byt/[^/\"]+/([0-9a-f]{24})/?", re.I)
_PSC_RE = re.compile(r"\b\d{3}\s?\d{2}\b")
_OG_RE = re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.I)
# "Prodej bytu 2+kk 65 m², <address>. Cena 23 600 000 Kč. <the rest>"
_OG_PARSE = re.compile(r"^Prodej\s+bytu\s+(?P<layout>\S+)\s+(?P<area>[\d\s]+)\s*m[²2],\s*(?P<rest>.*)$",
                       re.I | re.S)
_CENA_RE = re.compile(r"\bCena\s+[\d\s\xa0]+\s*K[čc]\.?\s*", re.I)


def page_url(page: int) -> str:
    return SEARCH if page <= 1 else f"{SEARCH}?page={page}"


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def split_place(info: str) -> tuple[str, str]:
    """(district, address) from "Univerzitní, Praha 10 - Malešice": the
    part after the street is the district; an "okres …" part is dropped."""
    parts = [p.strip() for p in (info or "").split(",") if p.strip()]
    parts = [p for p in parts if not fold(p).startswith("okres")] or parts
    district = parts[-1] if parts else ""
    return _PSC_RE.sub("", district).strip(" -"), info.strip()


def listing_from_card(card, now: str | None = None) -> dict | None:
    """A listings row from one result card, or None."""
    link = None
    for a in card.find_all("a", href=True):
        if _DETAIL_RE.search(a["href"]):
            link = a
            break
    if link is None:
        return None
    href = link["href"]
    if not href.startswith("http"):
        href = BASE + "/" + href.lstrip("/")
    key = _DETAIL_RE.search(href).group(1).lower()
    title = _text(card.select_one(".c-products__title")) or _text(link)
    if is_excluded_cz(title, href):
        return None
    district, address = split_place(_text(card.select_one(".c-products__info")))
    if not district:
        district = place_from_text(title)
    size = area_cz(title)
    price_el = card.select_one(".c-products__price strong") or card.select_one(".c-products__price")
    price = sale_price(_text(price_el), size, district)
    img = card.find("img")
    image = ""
    if img:
        image = img.get("data-src") or img.get("src") or ""
        if image.startswith("//"):
            image = "https:" + image
    return listing_record(SOURCE, key, href, title=title, price=price, size=size,
                          rooms=rooms_cz(title), district=district, address=address,
                          image=image if image.startswith("http") else "", now=now)


def parse_search(html: str, now: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    for card in soup.select("div.c-products__item"):
        try:
            rec = listing_from_card(card, now)
        except Exception as e:
            log.warning(f"    ⚠️ Card error: {e}")
            continue
        if rec:
            out.append(rec)
    return out


def _params(soup) -> dict[str, str]:
    """The detail page's parameter list (dt → dd), keys diacritic-folded."""
    out = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            out[fold(_text(dt)).rstrip(":")] = _text(dd)
    return out


def apply_detail(listing: dict, html: str) -> None:
    """Fill a listing from its detail page: description, size, floor,
    ownership, PENB, the price when the card hid it. Never clears a field.
    The description is og:description's own text (after the price
    sentence) — no guess at the page's description markup."""
    og = _OG_RE.search(html or "")
    text = html_lib.unescape(og.group(1)) if og else ""
    m = _OG_PARSE.match(text.strip())
    if m:
        if not listing.get("size_m2"):
            size = area_cz(f"{m.group('area')} m²")
            if size:
                listing["size_m2"] = size
        rest = m.group("rest")
        if not listing.get("price_eur"):
            listing["price_eur"] = sale_price(czk_amounts(rest[:200]),
                                              listing.get("size_m2") or 0,
                                              listing.get("district") or "")
        cena = _CENA_RE.search(rest)
        text = rest[cena.end():] if cena else rest
    soup = BeautifulSoup(html or "", "html.parser")
    params = _params(soup)
    description = text
    ownership = params.get("vlastnictvi")
    if ownership:
        description = f"Vlastnictví: {ownership}. {description}"
    if description:
        listing["description"] = description[:8000]
    floor = params.get("podlazi")
    fm = re.search(r"-?\d+", floor or "")
    if fm:
        listing["floor"] = int(fm.group())
    energy = energy_cz(" ".join(f"{k} {v}" for k, v in params.items()
                                if "energet" in k or "penb" in k))
    if energy != "UNKNOWN":
        listing["energy_class"] = energy
    if not listing.get("size_m2"):
        size = area_cz(params.get("uzitna plocha", ""))
        if size:
            listing["size_m2"] = size
    pin = pin_from_meta(html, market="cz")
    if pin:
        listing["lat"], listing["lng"] = pin


def run(max_pages: int = 10) -> int:
    require_robots(page_url(2))
    log.info(f"🔍 Reality.iDNES.cz ({max_pages} pages)...")
    session = make_session(warmup_url(BASE))
    fresh = get_fresh_detail_urls(SOURCE, max_age_days=DETAIL_REFRESH_DAYS)
    total = touched = 0
    first_status = None
    for p in range(1, max_pages + 1):
        url = page_url(p)
        try:
            r = get(url, session=session, timeout=25)
        except Exception as e:
            log.warning(f"  Page {p}: {e}")
            first_status = first_status or 0
            break
        first_status = first_status or r.status_code
        if r.status_code == 404 and p > 1:
            break                       # past the last page
        if r.status_code != 200:
            log.info(f"  Page {p}: HTTP {r.status_code}")
            break
        now = datetime.now(timezone.utc).isoformat()
        listings = parse_search(r.text, now)
        if not listings:
            break
        enriched = []
        for listing in listings:
            if listing["url"] in fresh:
                touched += touch_listings([listing["url"]])
                continue
            try:
                if robots_allows(listing["url"])[0]:
                    d = get(listing["url"], session=session, timeout=25)
                    if d.status_code == 200:
                        apply_detail(listing, d.text)
                        enriched.append(listing["id"])
            except Exception as e:
                log.warning(f"    detail {listing['url']}: {e}")
            try:
                upsert_listing(listing)
                total += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
            time.sleep(0.4)
        mark_details_enriched(enriched)
        log.info(f"  Page {p}: {len(listings)} listings")
        time.sleep(SCRAPE_DELAY_SEC)
    if total == 0 and touched == 0:
        why = (f"HTTP {first_status}" if first_status not in (None, 200) else
               "0 cards — the page markup may have changed")
        raise PortalBlocked(f"Reality.iDNES.cz returned nothing: {why}")
    cleanup(SOURCE)
    log.info(f"✅ iDNES done. {total} upserted, {touched} unchanged.")
    return total + touched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=2)
