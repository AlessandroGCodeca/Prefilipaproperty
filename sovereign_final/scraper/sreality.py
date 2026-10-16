"""
scraper/sreality.py — flats for sale on sreality.cz (Czech market).

Sreality's own frontend reads a JSON API, and so does this scraper:

  search   GET https://www.sreality.cz/api/v1/estates/search
               ?category_main_cb=1   (byty — flats)
               &category_type_cb=1   (prodej — for sale)
               &per_page=…&offset=…
           → {"results": [estate, …], "pagination": {"total": n}}
  detail   GET https://www.sreality.cz/api/v1/estates/{hash_id}
           → {"result": {…}}

The old /api/cs/v2/estates answers 404 since the API moved to v1. The shape
above is the one open-source collectors verified against the live API in
July–October 2026 (peterdedo/sreality-platform, ZMAN-91/prague-reality-
scraper); it could not be checked from here (no .cz host was reachable), so
every field is read defensively and the v2 shape (_embedded.estates) is
still understood.

An estate carries its own GPS pin (gps / locality.gps_lat, gps_lon), which
the LV check resolves to a building parcel, like a Slovak portal's pin.

NOT IN THE DAILY RUN: sreality's robots.txt gives every crawler other than
the named search engines "User-agent: * / Disallow: /" — the whole site,
the API included (as captured on 2026-09-15 by the collector named above;
not re-read from here). The pipeline reads only portals whose robots.txt
allows it, so scheduler.SCRAPERS["cz"] leaves Sreality out (it is listed
in scheduler.BLOCKED with the reason) and run() checks robots.txt first:
while the rule stands, it stops with "blocked by robots.txt" before any
request to the API. 🔗 TEST CZ SITES shows the live answer; should
sreality's robots.txt ever allow it, add it to SCRAPERS["cz"].

  python3 -m scraper.sreality          # direct run, 2 pages
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC, DETAIL_REFRESH_DAYS
from database import (
    upsert_listing, init_db, get_fresh_detail_urls, mark_details_enriched,
    touch_listings,
)
from scraper._http import get, make_session
from scraper.cz_common import (
    PortalBlocked, require_robots, listing_record, sale_price, rooms_cz, layout_cz,
    area_cz, energy_cz, is_excluded_cz, cleanup, fold,
)
from scraper.geo import pin_from_item

log = logging.getLogger(__name__)

SOURCE = "sreality"
BASE = "https://www.sreality.cz"
SEARCH_API = BASE + "/api/v1/estates/search"
DETAIL_API = BASE + "/api/v1/estates/{hash_id}"
PER_PAGE = 60
SEARCH_PARAMS = {"category_main_cb": 1, "category_type_cb": 1}
HEADERS = {"Accept": "application/json, text/plain, */*",
           "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
           "Referer": BASE + "/hledani/prodej/byty"}

# Sreality's category_sub_cb for a flat's layout (its public URL carries it).
LAYOUTS = {2: "1+kk", 3: "1+1", 4: "2+kk", 5: "2+1", 6: "3+kk", 7: "3+1", 8: "4+kk",
           9: "4+1", 10: "5+kk", 11: "5+1", 12: "6-a-vice", 16: "atypicky"}


def _get(d, *path):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _val(v):
    """Sreality wraps many values as {"value": …, "name": …}."""
    if isinstance(v, dict):
        return v.get("value", v.get("value_raw", v.get("name")))
    return v


def estates_in(payload) -> list[dict]:
    """The estate list of a search answer — v1 "results", or v2 _embedded."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("results")
    if items is None:
        items = _get(payload, "_embedded", "estates")
    return [i for i in (items or []) if isinstance(i, dict)]


def _locality(item: dict) -> tuple[str, str]:
    """(district, address) from an estate's locality: "Praha 2 - Vinohrady"
    from city + city part; the street in front for the address."""
    loc = item.get("locality")
    if isinstance(loc, str):
        return loc.strip(), loc.strip()
    if not isinstance(loc, dict):
        return "", ""
    city = (loc.get("city") or loc.get("municipality") or "").strip()
    part = (loc.get("citypart") or loc.get("quarter") or loc.get("ward") or "").strip()
    okres = (loc.get("district") or "").strip()
    district = city + (f" - {part}" if part and part.lower() not in city.lower() else "")
    if okres and fold(okres) not in fold(district):
        district = f"{district}, {okres}" if district else okres
    street = (loc.get("street") or "").strip()
    return district, ", ".join(x for x in (street, district) if x)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def public_url(item: dict) -> str:
    """https://www.sreality.cz/detail/prodej/byt/2+kk/praha-vinohrady/{hash_id}"""
    hash_id = item.get("hash_id")
    sub = item.get("category_sub_cb") or _get(item, "seo", "category_sub_cb")
    layout = LAYOUTS.get(_val(sub)) or layout_cz(item.get("advert_name") or item.get("name") or "")
    loc = item.get("locality")
    seo = _get(item, "seo", "locality")
    if not seo and isinstance(loc, dict):
        seo = "-".join(x for x in (loc.get(k) for k in (
            "city_seo_name", "citypart_seo_name", "street_seo_name")) if x)
    if not seo:
        seo = _slug(_locality(item)[0]) or "detail"
    return f"{BASE}/detail/prodej/byt/{layout or 'atypicky'}/{seo}/{hash_id}"


def _price(item: dict) -> float:
    """The price in Kč, unless it is stated per m² or per month."""
    p = item.get("price_czk")
    unit = fold(str(_get(p, "unit") or _get(item, "price_unit") or ""))
    if "m2" in unit or "m²" in unit or "mes" in unit:
        return 0.0
    raw = _get(p, "value_raw") if isinstance(p, dict) else p
    if raw is None:
        raw = _val(item.get("price"))
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def listing_from_estate(item: dict, now: str | None = None) -> dict | None:
    """A listings row from one search result, or None when it isn't a flat
    for sale with an id."""
    hash_id = item.get("hash_id")
    if not hash_id:
        return None
    title = (item.get("advert_name") or item.get("name") or "").strip()
    if is_excluded_cz(title):
        return None
    district, address = _locality(item)
    size = area_cz(title)
    price = _price(item)
    price = sale_price([price], size, district) if price else 0.0
    pin = pin_from_item(item, market="cz") or pin_from_item(item.get("locality"), market="cz")
    img = ""
    images = item.get("advert_images") or _get(item, "_links", "images") or []
    if isinstance(images, list) and images:
        first = images[0]
        img = first if isinstance(first, str) else (first.get("url") or first.get("href") or "")
    return listing_record(SOURCE, str(hash_id), public_url(item), title=title,
                          price=price, size=size, rooms=rooms_cz(title),
                          district=district, address=address, image=img, pin=pin,
                          now=now)


def apply_detail(listing: dict, payload: dict) -> None:
    """Fill a listing from its detail answer: size, floor, energy class,
    description, a better pin. Never clears what the search gave."""
    raw = payload.get("result", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        return
    items = {fold(str(i.get("name") or "")): i.get("value")
             for i in raw.get("items") or [] if isinstance(i, dict)}

    def item(*names):
        for n in names:
            if fold(n) in items and items[fold(n)] not in (None, ""):
                return items[fold(n)]
        return None
    size = (_val(raw.get("usable_area")) or _val(raw.get("floor_area"))
            or item("Užitná plocha", "Plocha podlahová"))
    try:
        if size and 15 <= float(str(size).replace(",", ".")) <= 500:
            listing["size_m2"] = float(str(size).replace(",", "."))
    except ValueError:
        pass
    floor = _val(raw.get("floor_number")) or item("Podlaží")
    m = re.search(r"-?\d+", str(floor or ""))
    if m:
        listing["floor"] = int(m.group())
    energy = energy_cz(str(_val(raw.get("energy_efficiency_rating_cb")) or "")
                       + " " + str(item("Energetická náročnost budovy") or ""))
    if energy != "UNKNOWN":
        listing["energy_class"] = energy
    text = (raw.get("advert_description") or raw.get("description")
            or _get(raw, "text", "value") or raw.get("meta_description") or "")
    ownership = str(_val(raw.get("ownership")) or item("Vlastnictví") or "")
    if ownership:
        text = f"Vlastnictví: {ownership}. {text}"
    if text:
        listing["description"] = str(text)[:8000]
    pin = (pin_from_item(raw.get("locality"), market="cz")
           or pin_from_item(raw.get("recommendations_data"), market="cz"))
    if pin:
        listing["lat"], listing["lng"] = pin
    if not listing.get("price_eur"):
        listing["price_eur"] = sale_price([_price(raw)], listing.get("size_m2") or 0,
                                          listing.get("district") or "")


def _fetch_json(url: str, session, params=None):
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    r = get(url, session=session, timeout=25)
    if r.status_code != 200:
        return r.status_code, None
    try:
        return 200, r.json()
    except ValueError:
        return 200, None


def run(max_pages: int = 10) -> int:
    require_robots(SEARCH_API)
    log.info(f"🔍 Sreality.cz ({max_pages} pages)...")
    session = make_session(BASE)
    session.headers.update(HEADERS)
    fresh = get_fresh_detail_urls(SOURCE, max_age_days=DETAIL_REFRESH_DAYS)
    total = touched = 0
    statuses = []
    for p in range(max_pages):
        status, payload = _fetch_json(SEARCH_API, session,
                                      {**SEARCH_PARAMS, "per_page": PER_PAGE,
                                       "offset": p * PER_PAGE})
        statuses.append(status)
        estates = estates_in(payload) if payload else []
        if not estates:
            log.info(f"  Page {p + 1}: {'HTTP ' + str(status) if status != 200 else 'no results'}")
            break
        now = datetime.now(timezone.utc).isoformat()
        enriched = []
        for estate in estates:
            listing = listing_from_estate(estate, now)
            if not listing:
                continue
            if listing["url"] in fresh:
                touched += touch_listings([listing["url"]])
                continue
            d_status, detail = _fetch_json(DETAIL_API.format(hash_id=estate["hash_id"]), session)
            if d_status == 200 and detail:
                apply_detail(listing, detail)
                enriched.append(listing["id"])
            try:
                upsert_listing(listing)
                total += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
            time.sleep(0.4)
        mark_details_enriched(enriched)
        log.info(f"  Page {p + 1}: {len(estates)} estates")
        time.sleep(SCRAPE_DELAY_SEC)
    if total == 0 and touched == 0:
        why = (f"HTTP {statuses[0]}" if statuses and statuses[0] != 200 else
               "0 estates — the API shape may have changed")
        raise PortalBlocked(f"Sreality.cz returned nothing: {why}")
    cleanup(SOURCE)
    log.info(f"✅ Sreality done. {total} upserted, {touched} unchanged.")
    return total + touched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=2)
