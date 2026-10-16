"""
scraper/cz_common.py — what the Czech portal scrapers share.

Every Czech listing is stored with market "cz" and its price in crowns
(currency "CZK"); the Slovak scrapers are untouched. Each Czech scraper
follows the Slovak interface — scrape the result pages, enrich from the
detail page (skipped while its last read is DETAIL_REFRESH_DAYS fresh),
take the portal's own map pin when it ships one, upsert_listing, then the
regional floor / ceiling cleanup — and fails soft: a blocked or empty
portal raises a RuntimeError saying why, which fails that pipeline step
only.

Before reading a portal, each scraper checks the portal's robots.txt for
the path it is about to fetch (require_robots). A path robots.txt
disallows is not fetched: the step fails with "blocked by robots.txt".
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MARKET = "cz"
CURRENCY = "CZK"
# The user agent robots.txt is checked for — the one the requests carry.
ROBOTS_AGENT = "*"


class PortalBlocked(RuntimeError):
    """A portal (or one of its paths) can't be read: robots.txt, HTTP, WAF."""


# ── robots.txt ────────────────────────────────────────────────────────────────
# Read as RFC 9309 says, not as urllib.robotparser does: robotparser takes the
# first rule that matches and treats "*" and "$" literally, so it reads
# "Allow: /" ahead of a narrower Disallow as allowing everything, and
# "Disallow: /*hledat=" (Bazoš) as never matching. Here the longest matching
# rule wins, Allow on a tie, and "*" / "$" are wildcards.
class Robots:
    """The rules of one robots.txt that apply to user agent `agent`: the
    groups naming it, else the "*" groups (merged, as the RFC says)."""

    def __init__(self, text: str, agent: str = "*"):
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules:                       # a new group starts
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                if value:                       # an empty Disallow allows all
                    rules.append((key == "allow", value))
        if agents:
            groups.append((agents, rules))
        mine = [r for a, rs in groups if agent.lower() in a and agent != "*" for r in rs]
        self.rules = mine or [r for a, rs in groups if "*" in a for r in rs]

    @staticmethod
    def _pattern(path: str) -> re.Pattern:
        end = path.endswith("$")
        body = re.escape(path[:-1] if end else path).replace(r"\*", ".*")
        return re.compile(body + ("$" if end else ""))

    def allows(self, url: str) -> bool:
        parts = urlparse(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best_len, best_allow = -1, True
        for allow, path in self.rules:
            if self._pattern(path).match(target):
                n = len(path)
                if n > best_len or (n == best_len and allow):
                    best_len, best_allow = n, allow
        return best_allow


_robots_cache: dict[str, Robots | None] = {}


def robots_allows(url: str, fetch=None) -> tuple[bool, str]:
    """(allowed, why) for `url` under its host's robots.txt. `fetch(url)`
    returns (status, text); the default goes through scraper._http.get.
    An unreachable robots.txt (network error, 5xx) is not a permission: the
    caller learns why. A missing one (4xx) allows everything, by the
    standard's own rule."""
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots_cache:
        if fetch is None:
            def fetch(u):
                from scraper._http import get
                r = get(u, timeout=15)
                return r.status_code, r.text
        try:
            status, text = fetch(root + "/robots.txt")
        except Exception as e:
            return False, f"robots.txt unreachable ({type(e).__name__})"
        if 400 <= status < 500:
            _robots_cache[root] = None
        elif status != 200:
            return False, f"robots.txt answered HTTP {status}"
        else:
            _robots_cache[root] = Robots(text, ROBOTS_AGENT)
    rules = _robots_cache[root]
    if rules is None or rules.allows(url):
        return True, ""
    return False, f"blocked by robots.txt ({parts.netloc}{parts.path})"


def require_robots(url: str, fetch=None) -> None:
    ok, why = robots_allows(url, fetch)
    if not ok:
        raise PortalBlocked(why)


# ── Text ──────────────────────────────────────────────────────────────────────
def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


# "3 450 000 Kč", "3.450.000 Kč", "3450000 CZK", "3 450 000,- Kč".
_CZK_RE = re.compile(
    r"(\d{1,3}(?:[\s\xa0  .]\d{3})+|\d{4,10})\s*(?:,-\s*)?(?:Kč|CZK)", re.I)
# An amount stated per month or per m² is a rent or a rate, not the price.
_PER_RE = re.compile(r"^\s*(?:/|za)\s*(?:m[ěe]s|m2|m²|m\b|noc|den)", re.I)


def czk_amounts(text: str) -> list[float]:
    """Every whole-flat Kč amount in `text` (per-month and per-m² ones left out)."""
    out = []
    for m in _CZK_RE.finditer(text or ""):
        if _PER_RE.match((text or "")[m.end():m.end() + 12]):
            continue
        try:
            out.append(float(re.sub(r"[\s\xa0  .]", "", m.group(1))))
        except ValueError:
            continue
    return out


def plausible_price(v) -> bool:
    import markets
    m = markets.get(MARKET)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return m.sale_price_min <= v <= m.sale_price_max


def sale_price(candidates, size_m2: float = 0.0, district: str = "") -> float:
    """The sale price among Kč figures (or a text holding them): the largest
    plausible one whose Kč/m² the region's ceiling allows — as the Slovak
    scrapers choose — or 0.0."""
    from engine.regional_prices import pick_sale_price
    if isinstance(candidates, str):
        candidates = czk_amounts(candidates)
    values = [float(v) for v in (candidates or []) if plausible_price(v)]
    return pick_sale_price(values, size_m2, district, market=MARKET) if values else 0.0


# Czech layouts: "2+kk", "3+1", "1 + kk"; a garsoniéra is one room; "6 pokojů
# a více" six; "atypický" says nothing.
_LAYOUT_RE = re.compile(r"(?<!\d)([1-9])\s*\+\s*(kk|[0-9])(?![\w])", re.I)
_GARSONIERA_RE = re.compile(r"garson|garzon", re.I)
_MANY_RE = re.compile(r"([5-9])\s*(?:a\s*vic|pokoj)", re.I)


def rooms_cz(text: str) -> int | None:
    """Room count from a Czech title or layout, or None."""
    folded = fold(text)
    m = _LAYOUT_RE.search(folded)
    if m:
        return int(m.group(1))
    if _GARSONIERA_RE.search(folded):
        return 1
    m = _MANY_RE.search(folded)
    if m:
        return int(m.group(1))
    return None


def layout_cz(text: str) -> str:
    """"2+kk" as written in a title, or ""."""
    m = _LAYOUT_RE.search(fold(text))
    return f"{m.group(1)}+{m.group(2).lower()}" if m else ""


ENERGY_VALID = {"A", "B", "C", "D", "E", "F", "G"}
_ENERGY_RE = re.compile(
    r"(?:penb|energeticka\s+narocnost(?:\s+budovy)?|trida)\W{0,12}(?:trida\s+)?([a-g])(?![a-z])")


def energy_cz(text: str) -> str:
    """The PENB class (A–G — the same scale as Slovakia's) from text such as
    "Třída G - Mimořádně nehospodárná" or "PENB: C", else "UNKNOWN"."""
    m = _ENERGY_RE.search(fold(text))
    if m and m.group(1).upper() in ENERGY_VALID:
        return m.group(1).upper()
    return "UNKNOWN"


def area_cz(text: str) -> float:
    from scraper.textparse import area_from_text
    return area_from_text(text or "")


# ── What a sale-flat listing is not ───────────────────────────────────────────
# Stems matched at the start of a word in diacritic-folded text (as the
# Slovak EXCLUDE_KEYWORDS are). The first group excludes wherever it stands —
# a rental, an auction, a share of a flat ("prodej podílu", a co-ownership
# share — "s podílem na pozemku" is an ordinary flat's land share and does
# not count), non-residential space; the second only when
# it comes before the flat's own noun ("Prodej garáže", not "byt s garáží").
CZ_ALWAYS_EXCLUDE = ("pronajem", "podnajem", "drazb", "aukc", r"prodej\s+podil",
                     "spoluvlastnick", "nebytov", "ubytovn", "hotel", "penzion")
CZ_PROPERTY_EXCLUDE = ("rodinn", "pozem", "garaz", "parkovac", "kancelar", "chat",
                       "chalup", "komercn", "sklad", "obchodn", "restaura", "vil")
_ALWAYS_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(CZ_ALWAYS_EXCLUDE) + ")")
_PROPERTY_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(CZ_PROPERTY_EXCLUDE) + ")")


def is_excluded_cz(*texts: str) -> bool:
    """True when a title / URL names something other than a flat for sale."""
    from scraper.textparse import _APARTMENT_NOUN_RE, _is_street_name
    for t in texts:
        folded = fold(t)
        if _ALWAYS_RE.search(folded):
            return True
        for m in _PROPERTY_RE.finditer(folded):
            if _APARTMENT_NOUN_RE.search(folded, 0, m.start()):
                continue
            if not _is_street_name(folded, m.start()):
                return True
    return False


# ── The record ────────────────────────────────────────────────────────────────
def listing_id(source: str, key: str) -> str:
    """A stable id from the portal's own listing id — a slug in the URL can
    change, the id doesn't."""
    return hashlib.md5(f"{source}:{key}".encode()).hexdigest()


def listing_record(source: str, key: str, url: str, *, title: str = "",
                   price: float = 0.0, size: float = 0.0, rooms=None,
                   district: str = "", address: str = "", description: str = "",
                   floor=None, energy: str = "UNKNOWN", image: str = "",
                   pin=None, now: str | None = None) -> dict:
    """One listings row, shaped as the Slovak scrapers' (database.upsert_listing),
    in the Czech market and in crowns."""
    now = now or datetime.now(timezone.utc).isoformat()
    lid = listing_id(source, key)
    row = {
        "id": lid, "source": source, "url": url, "url_hash": lid,
        "title": (title or "")[:200], "description": (description or "")[:8000],
        "price_eur": float(price or 0), "size_m2": float(size or 0),
        "rooms": rooms if rooms is not None else rooms_cz(title),
        "floor": floor, "year_built": None, "energy_class": energy or "UNKNOWN",
        "address_raw": address or district or title, "district": district or "",
        "city": "", "primary_image_url": image or "", "image_urls": image or "",
        "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
        "market": MARKET, "currency": CURRENCY,
    }
    if pin:
        row["lat"], row["lng"] = pin
    return row


def cleanup(source: str) -> None:
    """The regional floor / ceiling pass the Slovak scrapers run, in Czechia's
    terms (engine.regional_prices, market "cz")."""
    from engine.regional_prices import zero_above_regional_ceiling, zero_below_regional_floor
    zero_below_regional_floor(source, market=MARKET)
    zero_above_regional_ceiling(source, market=MARKET)
