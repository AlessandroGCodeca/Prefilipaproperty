"""
scraper/bezrealitky.py — flats for sale on bezrealitky.cz (Czech market,
private sellers).

Bezrealitky's data sits behind a GraphQL API on api.bezrealitky.cz, whose
robots.txt is "User-agent: * / Disallow: /" — so that host is never read.
The website's robots.txt disallows only its search (/vyhledat*, /search*)
and account pages, and points to a sitemap. This scraper takes that route:

  sitemap  GET https://www.bezrealitky.cz/sitemap/sitemap.xml  (an index of
           child sitemaps, plain or gzipped) → listing URLs of the shape
           /nemovitosti-byty-domy/<id>-nabidka-prodej-bytu-<place>
  detail   GET the listing URL → its <script id="__NEXT_DATA__"> JSON holds
           the advert: id, offerType, estateType, price, surface,
           disposition, etage, gps {lat, lng}, street, houseNumber, city,
           cityDistrict, description

The route, the URL shape and the advert's field names are the ones an
open-source collector (ZMAN-91/prague-reality-scraper) documented against
the live site in September–October 2026; they could not be checked from
here (no .cz host was reachable), so everything is read defensively.

The slug carries the offer and estate type, so a sale flat is picked out
before its page is fetched. Newest ids first; a listing read within
DETAIL_REFRESH_DAYS is only marked seen.

  python3 -m scraper.bezrealitky       # direct run, 2 pages' worth
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DETAIL_REFRESH_DAYS
from database import (
    upsert_listing, init_db, get_fresh_detail_urls, mark_details_enriched,
    touch_listings,
)
from scraper._http import get, make_session
from scraper.cz_common import (
    PortalBlocked, require_robots, listing_record, sale_price, energy_cz,
    is_excluded_cz, cleanup,
)
from scraper.geo import pin_from_item

log = logging.getLogger(__name__)

SOURCE = "bezrealitky"
BASE = "https://www.bezrealitky.cz"
SITEMAP_INDEX = BASE + "/sitemap/sitemap.xml"
# Detail pages read per "page" of max_pages — the unit the other scrapers
# are budgeted in.
DETAILS_PER_PAGE = 30
MAX_CHILD_SITEMAPS = 40

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_SLUG_RE = re.compile(r"/nemovitosti-byty-domy/(\d+)-([a-z0-9\-]+)/?$", re.I)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ADVERT_MARKERS = {"offerType", "estateType", "surface", "disposition", "uri"}
_DISPOSITION_RE = re.compile(r"(\d)\s*[+_\-]?\s*(kk|\d)\b", re.I)
OWNERSHIP = {"OSOBNI": "osobní", "DRUZSTEVNI": "družstevní", "OBECNI": "obecní"}


def sale_flat_url(url: str) -> str | None:
    """The advert id of a sale-flat listing URL, else None."""
    m = _SLUG_RE.search(url or "")
    if not m:
        return None
    parts = m.group(2).lower().split("-")
    if "prodej" not in parts or not ({"bytu", "byt"} & set(parts)):
        return None
    return m.group(1)


def sitemap_locs(xml: str) -> list[str]:
    return _LOC_RE.findall(xml or "")


def _xml(body: bytes) -> str:
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return ""
    return body.decode("utf-8", errors="replace")


def walk_sitemap(session, fetch=None) -> list[tuple[int, str]]:
    """(id, url) of every sale-flat listing the sitemap names, newest first.
    `fetch(url)` returns (status, bytes); the default uses scraper._http."""
    if fetch is None:
        def fetch(u):
            r = get(u, session=session, timeout=30)
            return r.status_code, r.content
    status, body = fetch(SITEMAP_INDEX)
    if status != 200:
        raise PortalBlocked(f"Bezrealitky.cz sitemap answered HTTP {status}")
    index = _xml(body)
    found: dict[int, str] = {}

    def collect(xml):
        for loc in sitemap_locs(xml):
            key = sale_flat_url(loc)
            if key:
                found[int(key)] = loc
    collect(index)
    children = [u for u in sitemap_locs(index)
                if u.split("?")[0].endswith((".xml", ".xml.gz")) and u != SITEMAP_INDEX]
    for child in children[:MAX_CHILD_SITEMAPS]:
        try:
            st, b = fetch(child)
        except Exception as e:
            log.warning(f"    sitemap {child}: {e}")
            continue
        if st == 200:
            collect(_xml(b))
        time.sleep(0.5)
    return sorted(found.items(), reverse=True)


def advert_from_html(html: str) -> dict | None:
    """The page's own advert from its __NEXT_DATA__: the richest object with
    an id and at least two advert fields (related adverts carry fewer)."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    best, stack = None, [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("id") is not None and len(_ADVERT_MARKERS & node.keys()) >= 2:
                if best is None or len(node) > len(best):
                    best = node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return best


def layout(raw) -> str:
    """"2+kk" from the Disposition enum (DISP_2_KK) or text; "" if none."""
    text = str(raw or "")
    if text.upper() in ("", "UNDEFINED", "DISP_UNDEFINED"):
        return ""
    m = _DISPOSITION_RE.search(text.replace("DISP_", ""))
    if m:
        return f"{m.group(1)}+{m.group(2).lower()}"
    return "1+kk" if "GARSON" in text.upper() else ""


def _penb(value) -> str:
    """"C" from a PENB value such as "C" or "PENB_C"; else via the text reader."""
    s = str(value or "").upper().replace("PENB", "").strip("_ -:")
    if len(s) == 1 and s in "ABCDEFG":
        return s
    return energy_cz(f"PENB {value}") if value else "UNKNOWN"


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".").replace("\xa0", "").replace(" ", ""))
    except (TypeError, ValueError):
        return 0.0


def _place(advert: dict) -> tuple[str, str]:
    """(district, address): "Praha - Praha 10" style city + city part, the
    street and number in front for the address."""
    city = str(advert.get("city") or "").strip()
    part = str(advert.get("cityDistrict") or "").strip()
    if part and city and city.lower() not in part.lower():
        district = f"{city} - {part}"
    else:
        district = part or city
    street = " ".join(str(advert.get(k) or "").strip()
                      for k in ("street", "houseNumber")).strip()
    address = ", ".join(x for x in (street, district) if x)
    return district, address or str(advert.get("address") or "").strip()


def listing_from_advert(advert: dict, url: str, now: str | None = None) -> dict | None:
    """A listings row from a page's advert, or None when it is not a flat
    for sale in crowns."""
    if not isinstance(advert, dict) or advert.get("id") is None:
        return None
    estate = str(advert.get("estateType") or "BYT").upper()
    offer = str(advert.get("offerType") or "PRODEJ").upper()
    if estate != "BYT" or offer != "PRODEJ":
        return None
    currency = str(advert.get("currency") or "CZK").upper()
    if currency not in ("CZK", "KČ", "KC"):
        return None
    lay = layout(advert.get("disposition"))
    size = _num(advert.get("surface"))
    if not 15 <= size <= 500:
        size = 0.0
    district, address = _place(advert)
    title = str(advert.get("title") or "").strip() or " ".join(
        x for x in ("Prodej bytu", lay, f"{size:g} m²" if size else "", district) if x)
    if is_excluded_cz(title, url):
        return None
    price = sale_price([_num(advert.get("price"))], size, district)
    floor = None
    m = re.search(r"-?\d+", str(advert.get("etage") if advert.get("etage") is not None else ""))
    if m:
        floor = int(m.group())
    text = str(advert.get("description") or "").strip()
    owner = advert.get("ownership")
    if owner:
        text = f"Vlastnictví: {OWNERSHIP.get(str(owner).upper(), str(owner).lower())}. {text}"
    image = ""
    for key in ("mainImage", "publicImages", "images"):
        img = advert.get(key)
        if isinstance(img, list) and img:
            img = img[0]
        if isinstance(img, dict):
            img = img.get("url") or img.get("src")
        if isinstance(img, str) and img.startswith("http"):
            image = img
            break
    rooms = int(lay.split("+")[0]) if lay else None
    return listing_record(SOURCE, str(advert["id"]), url, title=title, price=price,
                          size=size, rooms=rooms, district=district, address=address,
                          description=text, floor=floor, energy=_penb(advert.get("penb")),
                          image=image, pin=pin_from_item(advert.get("gps"), market="cz"),
                          now=now)


def run(max_pages: int = 10) -> int:
    require_robots(SITEMAP_INDEX)
    log.info(f"🔍 Bezrealitky.cz (sitemap, up to {max_pages * DETAILS_PER_PAGE} pages)...")
    session = make_session(BASE)
    urls = walk_sitemap(session)
    if not urls:
        raise PortalBlocked("Bezrealitky.cz: the sitemap named no flats for sale — "
                            "its URL shape may have changed")
    fresh = get_fresh_detail_urls(SOURCE, max_age_days=DETAIL_REFRESH_DAYS)
    # In the sitemap = still published: keep every known one alive.
    touched = touch_listings([u for _, u in urls])
    todo = [(k, u) for k, u in urls if u not in fresh][:max_pages * DETAILS_PER_PAGE]
    total, enriched, statuses = 0, [], []
    for key, url in todo:
        try:
            require_robots(url)
            r = get(url, session=session, timeout=25)
        except PortalBlocked:
            raise
        except Exception as e:
            log.warning(f"    {url}: {e}")
            continue
        statuses.append(r.status_code)
        if r.status_code != 200:
            continue
        listing = listing_from_advert(advert_from_html(r.text),
                                      url, datetime.now(timezone.utc).isoformat())
        if listing:
            try:
                upsert_listing(listing)
                enriched.append(listing["id"])
                total += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
        time.sleep(0.5)
    mark_details_enriched(enriched)
    if total == 0 and touched == 0:
        why = (f"HTTP {statuses[0]}" if statuses and statuses[0] != 200 else
               "no advert found in the pages — __NEXT_DATA__ may have changed")
        raise PortalBlocked(f"Bezrealitky.cz returned nothing: {why}")
    cleanup(SOURCE)
    log.info(f"✅ Bezrealitky done. {total} upserted, {touched} seen in the sitemap.")
    return total + len([u for _, u in urls if u in fresh])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=2)
