"""
scraper/rentals.py — "prenájom" (to-let) flat listings for live rent comps.

The sale scrapers drop every rental on sight (textparse.EXCLUDE_KEYWORDS has
"prenajom"). This one reads only rentals, and stores them in rental_listings,
not listings — they are evidence about rent, never deals. engine/rent_comps
turns them into a live €/m² per district.

Sources:
  bazos.sk       /prenajmu/byt/ — same card template as the /predam/byt/ pages
                 the sale scraper already reads, so a card carries the rent,
                 the location and usually the size; no detail page needed.
  topreality.sk  /vyhladavanie/byty/prenajom — search page for links, then each
                 detail page (JSON-LD price + body text), capped per run.

  python3 -m scraper.rentals            # direct run, a few pages each
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC, RENT_MIN_EUR, RENT_MAX_EUR
from database import upsert_rental, init_db
from scraper._http import get, make_session
from scraper.nehnutelnosti import _extract_location_from_text
from scraper.textparse import (
    rooms_from_title, area_from_text, EXCLUDE_KEYWORDS, keyword_pattern,
    matches_keywords, strip_diacritics,
)

log = logging.getLogger(__name__)

BAZOS_BASE = "https://reality.bazos.sk"
BAZOS_CATEGORY = "/prenajmu/byt/"
BAZOS_PAGE_SIZE = 20

TOPREALITY_BASE = "https://www.topreality.sk"
TOPREALITY_SEARCH_CANDIDATES = [
    TOPREALITY_BASE + "/vyhladavanie/byty/prenajom?page={page}",
    TOPREALITY_BASE + "/vyhladavanie-byty-prenajom/strana-{page}.html",
]
_TOPREALITY_DETAIL_RE = re.compile(r"-r\d{6,8}\.html(?:$|[?#])")

# The sale exclusion list, minus the word for "rental" itself.
_RENTAL_EXCLUDE_RE = keyword_pattern(k for k in EXCLUDE_KEYWORDS if k != "prenajom")

_AMOUNT_RE = re.compile(r"(\d{1,3}(?:[\s\xa0  ]\d{3})+|\d{2,5})(?:[.,]\d{1,2})?\s*(?:€|eur\b)", re.I)
_MONTHLY_AFTER_RE = re.compile(r"^\s*(?:/\s*mes|mesacne|za\s+mesiac|/\s*mesiac|mes\.)", re.I)
# An amount right after one of these words is not the rent.
# One short word may sit in between ("energie cca 150 €", "kaucia vo výške …").
_NOT_RENT_BEFORE_RE = re.compile(
    r"(kauci|zaloh|depozit|energi|poplat|provizi|zabezpec)\w*\W{0,3}(?:\w{1,6}\W{1,3}){0,2}$",
    re.I)


def rent_from_text(text: str) -> float:
    """The monthly rent in a rental ad's text, or 0.0.

    A rental ad carries several € amounts — the rent, a deposit (kaucia,
    usually one or two months' rent), energies ("+ 150 € energie"), a fee.
    An amount stated per month wins; otherwise the first plausible amount not
    introduced as a deposit/energies/fee.
    """
    if not text:
        return 0.0
    folded = strip_diacritics(text).lower()
    monthly, plain = [], []
    for m in _AMOUNT_RE.finditer(folded):
        try:
            v = float(re.sub(r"[\s\xa0  ]", "", m.group(1)))
        except ValueError:
            continue
        if not (RENT_MIN_EUR <= v <= RENT_MAX_EUR):
            continue
        before = folded[max(0, m.start() - 30):m.start()]
        if _NOT_RENT_BEFORE_RE.search(before):
            continue
        if _MONTHLY_AFTER_RE.match(folded[m.end():m.end() + 14]):
            monthly.append(v)
        else:
            plain.append(v)
    if monthly:
        return monthly[0]
    return plain[0] if plain else 0.0


def _is_excluded(*texts: str) -> bool:
    """EXCLUDE_KEYWORDS (minus "prenajom") against each text — see
    textparse.matches_keywords for when a keyword counts ("Prenájom 2-izb.
    bytu s garážou" is a flat to let, a "Prenájom garáže" is not)."""
    return matches_keywords(_RENTAL_EXCLUDE_RE, *texts)


def build_rental(source: str, url: str, title: str, text: str, location: str = "",
                 rent: float | None = None, size: float | None = None,
                 now: str | None = None) -> dict | None:
    """One rental_listings row from whatever a page gave us, or None when it
    is not a long-term whole-flat let with a usable rent and size."""
    from engine.rent_comps import (
        energies_included, furnishing_from_text, is_long_term_flat,
        is_plausible_rent,
    )
    from engine.financial import match_rent_key
    if _is_excluded(title, url) or not is_long_term_flat(title, text):
        return None
    rent = rent or rent_from_text(text)
    size = size or area_from_text(title) or area_from_text(text)
    if not is_plausible_rent(rent, size):
        return None
    # One pass over location + title + text: the extractor prefers a suburb
    # over a city, and the portal's location field often names only the city
    # ("Bratislava") while the title names the part ("… Petržalka").
    district = _extract_location_from_text(f"{location} {title} {text}")
    if not district:
        return None                      # a comp with no place is no comp
    now = now or datetime.now(timezone.utc).isoformat()
    uid = hashlib.md5(url.encode()).hexdigest()
    return {
        "id": uid, "source": source, "url": url, "title": (title or "")[:200],
        "rent_eur": float(rent), "size_m2": float(size),
        "rooms": rooms_from_title(title) or rooms_from_title(text),
        "district": district, "rent_key": match_rent_key(district),
        "energies_included": 1 if energies_included(f"{title} {text}") else 0,
        "furnished": furnishing_from_text(f"{title} {text}"),
        "scraped_at": now, "last_seen_at": now,
    }


# ── bazos ─────────────────────────────────────────────────────────────────────
def parse_bazos_page(html: str, now: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.inzeratyflex") or soup.select("div[class*='inzeratyflex']")
    out = []
    for card in cards:
        link = card.select_one("div.inzeratynadpis a, h2 a, h3 a, a[href*='/inzerat/']")
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("http"):
            href = BAZOS_BASE + "/" + href.lstrip("/")
        if "/inzerat/" not in href:
            continue
        text = card.get_text(" ", strip=True)
        title = link.get_text(strip=True) or text[:80]
        price_tag = card.select_one("div.inzeratycena, .cena, [class*='cena']")
        rent = rent_from_text(price_tag.get_text(" ", strip=True)) if price_tag else 0.0
        loc = card.select_one("div.inzeratylok, .lokalita, [class*='lokalita']")
        rec = build_rental("bazos", href, title, text,
                           location=loc.get_text(" ", strip=True) if loc else "",
                           rent=rent or None, now=now)
        if rec:
            out.append(rec)
    return out


def scrape_bazos(max_pages: int = 5) -> int:
    session = make_session(warmup_url=BAZOS_BASE)
    stored = 0
    for p in range(max_pages):
        offset = p * BAZOS_PAGE_SIZE
        url = BAZOS_BASE + BAZOS_CATEGORY + (f"{offset}/" if offset else "")
        try:
            r = get(url, session=session, timeout=20)
        except Exception as e:
            log.warning(f"  bazos rentals offset {offset}: {e}")
            break
        if r.status_code != 200:
            log.warning(f"  bazos rentals offset {offset}: HTTP {r.status_code}")
            break
        rows = parse_bazos_page(r.text)
        for row in rows:
            try:
                upsert_rental(row)
                stored += 1
            except Exception as e:
                log.warning(f"    DB error: {e}")
        log.info(f"  bazos rentals page {p + 1}: {len(rows)} comps")
        if not rows and p > 0:
            break
        time.sleep(SCRAPE_DELAY_SEC)
    return stored


# ── topreality ────────────────────────────────────────────────────────────────
def topreality_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    base_tag = soup.find("base")
    base_href = base_tag.get("href") if base_tag and base_tag.get("href") else TOPREALITY_BASE + "/"
    found = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base_href, a["href"].strip())
        if "topreality.sk" not in full:
            continue
        path = urlparse(full).path
        if not _TOPREALITY_DETAIL_RE.search(path) or _is_excluded(path):
            continue
        found.add(full.split("#")[0].split("?")[0])
    return sorted(found)


def parse_topreality_detail(url: str, html: str, now: str | None = None) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text(" ", strip=True)
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title:
        title = soup.title.text.strip()
    rent = size = None
    address = ""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            blob = json.loads(tag.string or "")
        except Exception:
            continue
        for b in (blob if isinstance(blob, list) else [blob]):
            if not isinstance(b, dict):
                continue
            offers = b.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict) and rent is None:
                try:
                    v = float(offers.get("price") or 0)
                    if RENT_MIN_EUR <= v <= RENT_MAX_EUR:
                        rent = v
                except (TypeError, ValueError):
                    pass
            fs = b.get("floorSize")
            if isinstance(fs, dict) and fs.get("value") and size is None:
                try:
                    size = float(fs["value"])
                except (TypeError, ValueError):
                    pass
            addr = b.get("address")
            if isinstance(addr, dict) and not address:
                address = ", ".join(str(addr.get(k, "")) for k in
                                    ("streetAddress", "addressLocality", "addressRegion")
                                    if addr.get(k))
    return build_rental("topreality", url, title, body, location=address,
                        rent=rent, size=size, now=now)


def scrape_topreality(max_pages: int = 3, max_details: int = 60) -> int:
    sess = make_session(TOPREALITY_BASE)
    fmt = ""
    for cand in TOPREALITY_SEARCH_CANDIDATES:
        try:
            r = get(cand.format(page=1), session=sess, timeout=25)
        except Exception:
            continue
        if r.status_code == 200 and topreality_links(r.text):
            fmt = cand
            break
    if not fmt:
        log.info("  topreality rentals: no search URL returned listings")
        return 0
    stored = fetched = 0
    seen: set[str] = set()
    for p in range(1, max_pages + 1):
        try:
            r = get(fmt.format(page=p), session=sess, timeout=25)
        except Exception:
            break
        if r.status_code != 200:
            break
        for link in topreality_links(r.text):
            if link in seen or fetched >= max_details:
                continue
            seen.add(link)
            fetched += 1
            try:
                d = get(link, session=sess, timeout=25)
            except Exception:
                continue
            if d.status_code != 200:
                continue
            rec = parse_topreality_detail(link, d.text)
            if rec:
                upsert_rental(rec)
                stored += 1
            time.sleep(0.4)
        log.info(f"  topreality rentals page {p}: {stored} comps so far")
        time.sleep(SCRAPE_DELAY_SEC)
    return stored


def run(max_pages: int = 5) -> dict:
    """Scrape both sources, then rebuild the comps. Each source fails on its
    own — one portal being down still leaves the other's comps."""
    counts = {}
    for name, fn in (("bazos", scrape_bazos), ("topreality", scrape_topreality)):
        try:
            counts[name] = fn(max_pages)
        except Exception as e:
            log.warning(f"  ⚠️ {name} rentals: {e}")
            counts[name] = 0
    from engine.rent_comps import rebuild_rent_comps
    summary = rebuild_rent_comps()
    log.info(f"✅ Rent comps: {sum(counts.values())} rentals read, "
             f"{summary['keys']} districts, {len(summary['changed'])} rates moved, "
             f"{summary['rescored']} scores queued for re-scoring.")
    return {**counts, **summary}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run(max_pages=2)
