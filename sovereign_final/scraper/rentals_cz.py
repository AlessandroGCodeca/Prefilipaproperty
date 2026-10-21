"""
scraper/rentals_cz.py — Czech rental (pronájem) listings for live rent comps.

The sale scrapers drop every rental ("pronájem" is excluded); this one reads
only rentals, into rental_listings with market "cz" and the rent in crowns —
evidence about rent, never deals. engine/rent_comps_cz turns them into a live
Kč/m² per rent key.

Sources (robots.txt checked before each, as for the sale scrapers):
  reality.bazos.cz   /pronajmu/byt/ — the same card template as /prodam/byt/,
                     so a card carries the rent, the place and usually the
                     size; no detail page needed.
  bezrealitky.cz     the sitemap's "nabidka-pronajem-bytu" listings, each
                     page's __NEXT_DATA__ advert (price = monthly rent,
                     surface, disposition, place), capped per run.

A rental whose ad says energies are included, a room or a short let, or one
outside the Czech bounds (3 000–150 000 Kč, 70–1 100 Kč/m²) is not a comp.

  python3 -m scraper.rentals_cz        # direct run, a few pages each
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_rental, init_db
from scraper.textparse import bazos_title_link
from scraper._http import get, make_session
from scraper.cz_common import (
    warmup_url,
    MARKET, CURRENCY, PortalBlocked, require_robots, robots_allows,
    area_cz, rooms_cz, place_from_text, fold,
)

log = logging.getLogger(__name__)

BAZOS_BASE = "https://reality.bazos.cz"
BAZOS_CATEGORY = "/pronajmu/byt/"
BAZOS_PAGE_SIZE = 20
BEZREALITKY_PER_PAGE = 20

# Not a flat to let: a sale, a share, non-residential space.
_NOT_A_RENTAL = ("prodej", "prodam", "drazb", "nebytov", "kancelar", "garaz",
                 "sklad", "obchodni prostor")


# What an amount is when it is not the rent: a deposit (kauce, jistina), an
# advance for services or energy (zálohy, služby, energie), fees, commission.
_NOT_RENT = r"kauc|zaloh|poplat|proviz|vratn|jistin|sluzb|energi|depozit"
# ... named just before it — "Kauce: 30 000 Kč", "služby 4 500 Kč", "vratná
# kauce ve výši 30 000 Kč" (a word or two may stand between), or a total
# ("Celkem k úhradě 60 000 Kč") ...
_NOT_RENT_BEFORE_RE = re.compile(
    rf"(?:{_NOT_RENT}|celkem|celkov|k\s+uhrade|vstupni)\w*\W{{0,3}}(?:\w{{1,6}}\W{{1,3}}){{0,2}}$")
# ... unless the label only says what the rent covers: "Nájem bez energií
# 14 000 Kč", "nájemné včetně služeb".
_RENT_COVERS_RE = re.compile(
    rf"(?:bez|vcetne|vc\.?)\s+(?:{_NOT_RENT})\w*\W{{0,3}}(?:\w{{1,6}}\W{{1,3}}){{0,2}}$")
# ... or right after it — "4 500 Kč měsíčně energie", "3 000 Kč na služby"
# (not "15 000 Kč/měs. + služby", where the label is the next amount's).
_NOT_RENT_AFTER_RE = re.compile(
    rf"^[ \t]*(?:/[ \t]*)?(?:(?:za[ \t]+)?mes\w*\.?[ \t]*)?(?:(?:na|za)[ \t]+)?(?:{_NOT_RENT})")


def rent_from_text(text: str) -> float:
    """The monthly rent in Kč a text states: an amount marked per month
    first, else the first plain one — never a deposit (kauce), an advance
    for services or energy (zálohy, služby, energie), fees or commission,
    nor a per-m² figure."""
    from scraper.cz_common import _CZK_RE
    monthly, plain = [], []
    for m in _CZK_RE.finditer(text or ""):
        after = fold(text[m.end():m.end() + 16])
        # The words before the amount, within its own clause ("Kauce: 30 000
        # Kč" keeps its label; "…energie, nájem 12 000 Kč" is the rent's).
        before = re.split(r"[,;\n+]", fold(text[max(0, m.start() - 30):m.start()]))[-1]
        if re.match(r"\s*(?:/|za)\s*m(?:2|²)", after):
            continue
        # The words after it, up to the end of its clause: a full stop before a
        # capital ends one ("15 000 Kč/měs. Kauce 30 000 Kč" — the kauce is
        # the next amount's), "měs. energie" does not.
        clause = re.split(r"\.(?=\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])|[,;\n+]",
                          text[m.end():m.end() + 40])[0]
        if (_NOT_RENT_BEFORE_RE.search(before) and not _RENT_COVERS_RE.search(before)) \
                or _NOT_RENT_AFTER_RE.match(fold(clause)):
            continue
        try:
            v = float(re.sub(r"[\s\xa0  .]", "", m.group(1)))
        except ValueError:
            continue
        if v < 1000:
            continue
        (monthly if re.match(r"\s*(?:/|za|\s)\s*(?:mes|mesic)", after) else plain).append(v)
    return (monthly + plain)[0] if monthly or plain else 0.0


def build_rental(source: str, url: str, title: str, text: str, location: str = "",
                 rent: float | None = None, size: float | None = None,
                 now: str | None = None) -> dict | None:
    """One Czech rental_listings row, or None when it is not a long-term
    whole-flat let with a usable rent, size and place."""
    from engine.rent_comps_cz import (
        energies_included, furnishing_from_text, is_long_term_flat, is_plausible_rent,
    )
    from engine.rent_cz import match_rent_key
    folded = fold(f"{title} {url}")
    if any(w in folded for w in _NOT_A_RENTAL) or not is_long_term_flat(title, text):
        return None
    if not rent:
        rent = rent_from_text(f"{title} {text}")
    size = size or area_cz(title) or area_cz(text)
    if not is_plausible_rent(rent or 0, size or 0):
        return None
    from scraper.bazos_cz import place
    district = place(location) if location else ""
    district = district or place_from_text(f"{title} {text}")
    if not district:
        return None                      # a comp with no place is no comp
    now = now or datetime.now(timezone.utc).isoformat()
    return {
        "id": hashlib.md5(url.encode()).hexdigest(), "source": source, "url": url,
        "title": (title or "")[:200], "rent_eur": float(rent), "size_m2": float(size),
        "rooms": rooms_cz(title) or rooms_cz(text), "district": district,
        "rent_key": match_rent_key(district),
        "energies_included": 1 if energies_included(f"{title} {text}") else 0,
        "furnished": furnishing_from_text(f"{title} {text}"),
        "scraped_at": now, "last_seen_at": now, "market": MARKET, "currency": CURRENCY,
    }


# ── Bazoš ─────────────────────────────────────────────────────────────────────
def parse_bazos_page(html: str, now: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select("div.inzeratyflex") or soup.select("div[class*='inzeratyflex']")
    out = []
    for card in cards:
        link = bazos_title_link(card)
        if not link or not link.get_text(strip=True):
            continue                     # no title: no telling a room from a flat
        href = link.get("href", "")
        if not href.startswith("http"):
            href = BAZOS_BASE + "/" + href.lstrip("/")
        text = card.get_text(" ", strip=True)
        price_el = card.select_one("div.inzeratycena, [class*='cena']")
        rent = rent_from_text(price_el.get_text(" ", strip=True)) if price_el else 0.0
        loc = card.select_one("div.inzeratylok, [class*='lokalita']")
        rec = build_rental("bazos_cz", href, link.get_text(strip=True), text,
                           location=loc.get_text(" ", strip=True) if loc else "",
                           rent=rent or None, now=now)
        if rec:
            out.append(rec)
    return out


def scrape_bazos(max_pages: int = 5) -> int:
    first = BAZOS_BASE + BAZOS_CATEGORY
    require_robots(first + f"{BAZOS_PAGE_SIZE}/")
    session = make_session(warmup_url(BAZOS_BASE))
    stored = 0
    for p in range(max_pages):
        offset = p * BAZOS_PAGE_SIZE
        try:
            r = get(first + (f"{offset}/" if offset else ""), session=session, timeout=20)
        except Exception as e:
            log.warning(f"  bazos.cz rentals offset {offset}: {e}")
            break
        if r.status_code != 200:
            log.warning(f"  bazos.cz rentals offset {offset}: HTTP {r.status_code}")
            break
        rows = parse_bazos_page(r.text)
        for row in rows:
            try:
                upsert_rental(row)
                stored += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
        log.info(f"  bazos.cz rentals page {p + 1}: {len(rows)} comps")
        if not rows and p > 0:
            break
        time.sleep(SCRAPE_DELAY_SEC)
    return stored


# ── Bezrealitky ───────────────────────────────────────────────────────────────
def rental_from_advert(advert: dict, url: str, now: str | None = None) -> dict | None:
    from scraper.bezrealitky import _num, _place, layout
    if not isinstance(advert, dict):
        return None
    if str(advert.get("estateType") or "BYT").upper() != "BYT" or \
            str(advert.get("offerType") or "PRONAJEM").upper() != "PRONAJEM":
        return None
    if str(advert.get("currency") or "CZK").upper() not in ("CZK", "KČ", "KC"):
        return None
    district, address = _place(advert)
    lay = layout(advert.get("disposition"))
    title = str(advert.get("title") or "").strip() or f"Pronájem bytu {lay}".strip()
    return build_rental("bezrealitky", url, title, str(advert.get("description") or ""),
                        location=district or address, rent=_num(advert.get("price")),
                        size=_num(advert.get("surface")), now=now)


def scrape_bezrealitky(max_pages: int = 5) -> int:
    from scraper import bezrealitky as bz
    require_robots(bz.SITEMAP_INDEX)
    session = make_session(warmup_url(bz.BASE))
    urls = bz.walk_sitemap(session, offer="pronajem")[:max_pages * BEZREALITKY_PER_PAGE]
    stored = 0
    for _, url in urls:
        if not robots_allows(url)[0]:
            continue
        try:
            r = get(url, session=session, timeout=25)
        except Exception as e:
            log.warning(f"    {url}: {e}")
            continue
        if r.status_code == 200:
            rec = rental_from_advert(bz.advert_from_html(r.text), url)
            if rec:
                upsert_rental(rec)
                stored += 1
        time.sleep(0.5)
    log.info(f"  bezrealitky rentals: {stored} comps from {len(urls)} pages")
    return stored


def run(max_pages: int = 5) -> dict:
    """Read both sources, then rebuild the Czech comps. Each source fails on
    its own — one being blocked still leaves the other's comps."""
    counts = {}
    for name, fn in (("bazos_cz", scrape_bazos), ("bezrealitky", scrape_bezrealitky)):
        try:
            counts[name] = fn(max_pages)
        except (PortalBlocked, Exception) as e:
            log.warning(f"  ⚠️ {name} rentals: {e}")
            counts[name] = 0
    from engine.rent_comps_cz import rebuild_rent_comps
    summary = rebuild_rent_comps()
    log.info(f"✅ Czech rent comps: {sum(counts.values())} rentals read, "
             f"{summary['keys']} keys, {len(summary['changed'])} rates moved, "
             f"{summary['rescored']} scores queued for re-scoring.")
    return {**counts, **summary}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=2)
