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
import os
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
        seen_rule = False
        text = text or ""
        for bom in ("\ufeff", "\u00ef\u00bb\u00bf"):    # a UTF-8 BOM, decoded or not
            if text.startswith(bom):
                text = text[len(bom):]
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if seen_rule:                   # a new group starts
                    groups.append((agents, rules))
                    agents, rules, seen_rule = [], [], False
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                seen_rule = True                # an empty one still ends the agents
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
# When each fetched entry goes stale (time.monotonic()). A copy is used for a
# day at most (RFC 9309 §2.4); a 4xx — which allows everything, and may be a
# passing 429 or WAF answer — for an hour. An entry with no expiry (one a
# test seeds) never goes stale.
_robots_expires: dict[str, float] = {}
ROBOTS_TTL_SEC = 24 * 3600
ROBOTS_MISSING_TTL_SEC = 3600


def robots_allows(url: str, fetch=None) -> tuple[bool, str]:
    """(allowed, why) for `url` under its host's robots.txt. `fetch(url)`
    returns (status, text); the default goes through scraper._http.get.
    An unreachable robots.txt (network error, 5xx) is not a permission: the
    caller learns why. A missing one (4xx) allows everything, by the
    standard's own rule."""
    import time
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    stale = time.monotonic() >= _robots_expires.get(root, float("inf"))
    if root not in _robots_cache or stale:
        if fetch is None:
            def fetch(u):
                from scraper._http import get
                r = get(u, timeout=15)
                # Bytes as UTF-8 (the RFC's encoding), any BOM dropped.
                return r.status_code, r.content.decode("utf-8-sig", errors="replace")
        try:
            status, text = fetch(root + "/robots.txt")
        except Exception as e:
            return False, f"robots.txt unreachable ({type(e).__name__})"
        if 400 <= status < 500:
            _robots_cache[root] = None
            _robots_expires[root] = time.monotonic() + ROBOTS_MISSING_TTL_SEC
        elif status != 200:
            return False, f"robots.txt answered HTTP {status}"
        else:
            _robots_cache[root] = Robots(text, ROBOTS_AGENT)
            _robots_expires[root] = time.monotonic() + ROBOTS_TTL_SEC
    rules = _robots_cache[root]
    if rules is None or rules.allows(url):
        return True, ""
    return False, f"blocked by robots.txt ({parts.netloc}{parts.path})"


def require_robots(url: str, fetch=None) -> None:
    ok, why = robots_allows(url, fetch)
    if not ok:
        raise PortalBlocked(why)


def warmup_url(base: str) -> str | None:
    """The homepage make_session may fetch for cookies — None when robots.txt
    does not allow it, so the session starts without."""
    return base if robots_allows(base.rstrip("/") + "/")[0] else None


# ── Text ──────────────────────────────────────────────────────────────────────
def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


# "3 450 000 Kč", "3.450.000 Kč", "3450000 CZK", "3 450 000,- Kč". An amount
# starts a number: "52 m2 850 000 Kč" is 850 000, never 2 850 000.
_CZK_RE = re.compile(
    r"(?<![\w²+])(\d{1,3}(?:[\s\xa0  .]\d{3})+|\d{4,10})\s*(?:,-\s*)?(?:Kč|CZK)", re.I)
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
# The class is a capital letter, as every portal writes it: "PENB a revize"
# is "PENB and wiring check", not class A.
_ENERGY_RE = re.compile(
    r"(?i:penb|energetick[aáeé]\s+n[aá]ro[cč]nost\w*(?:\s+budovy)?|t[rř][ií]d[ay])"
    r"[\W_]{0,12}(?:(?i:t[rř][ií]da)\s+)?([A-G])(?![^\W\d_])")


def energy_cz(text: str) -> str:
    """The PENB class (A–G — the same scale as Slovakia's) from text such as
    "Třída G - Mimořádně nehospodárná" or "PENB: C", else "UNKNOWN"."""
    m = _ENERGY_RE.search(unicodedata.normalize("NFC", text or ""))
    if m and m.group(1).upper() in ENERGY_VALID:
        return m.group(1).upper()
    return "UNKNOWN"


def area_cz(text: str) -> float:
    from scraper.textparse import area_from_text
    return area_from_text(text or "")


# ── What a sale-flat listing is not ───────────────────────────────────────────
# Stems matched at the start of a word in diacritic-folded text (as the
# Slovak EXCLUDE_KEYWORDS are). The first group excludes wherever it stands —
# a rental, an auction, a share of a flat (_SHARE_RE below), non-residential
# space; the second only when it comes before the flat's own noun or layout
# ("Prodej garáže", not "byt s garáží" nor "Prodej 2+kk s garáží").
CZ_ALWAYS_EXCLUDE = ("pronajem", "podnajem", "drazb", "aukc",
                     "spoluvlastnick", "nebytov", "ubytovn", "hotel", "penzion")
CZ_PROPERTY_EXCLUDE = ("rodinn", "pozem", "garaz", "parkovac", "kancelar", "chat",
                       "chalup", "komercn", "sklad", "obchodn", "restaura", "vil")
_ALWAYS_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(CZ_ALWAYS_EXCLUDE) + ")")
_PROPERTY_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(CZ_PROPERTY_EXCLUDE) + ")")
# A share of a flat, not the flat: "Prodám podíl na bytě", "Prodej 1/2 podílu",
# "1/2 bytu", "id. 1/2", "podíl 1/3". A flat's land share — "s podílem na
# pozemku", "včetně podílu" — is no sale of a share and does not count.
_SHARE_RE = re.compile(
    r"(?<![^\W\d_])(?:prodej\w*|proda[mv]\w*|nabiz\w*)\s+(?:(?:id\.?|idealn\w*)\s*)?"
    r"(?:\d{1,2}\s*/\s*\d{1,2}\s+)?podil"
    r"|(?<![^\W\d_])(?:id\.|idealn\w*)\s*\d{1,2}\s*/\s*\d{1,2}(?!\d)"
    r"|(?<![\w/])\d{1,2}\s*/\s*\d{1,2}\s+"
    r"(?:podil\w*(?!\w)(?!\s+(?:na\s+)?pozem)|(?:na\s+)?(?:byt[ue]|jednotk))"
    r"|(?<![^\W\d_])podil\w*\s+\d{1,2}\s*/\s*\d{1,2}(?![\d/])(?!\s+(?:na\s+)?pozem)")
# A layout names the flat as "byt" does; a URL slug drops the "+" ("2kk"). It
# keeps a flat sold with its garage, parking space or land share ("Prodej 2+kk
# s garáží") — never a house, cottage, villa or office ("Prodej 4+1 rodinného
# domu"), which only "byt" before it keeps.
_SLUG_LAYOUT_RE = re.compile(r"(?<![^\W\d_])[1-9]-?kk(?![^\W\d_])")
CZ_ACCESSORY_STEMS = ("garaz", "parkovac", "pozem")
_STREET_ADJ_RE = re.compile(r"(?:hotel|penzion)ova(?![^\W\d_])")


def is_excluded_cz(*texts: str) -> bool:
    """True when a title / URL names something other than a flat for sale."""
    from scraper.textparse import _APARTMENT_NOUN_RE, _is_street_name
    for t in texts:
        folded = fold(t)
        if _SHARE_RE.search(folded):
            return True
        for m in _ALWAYS_RE.finditer(folded):
            # A street named after one ("Hotelová", Ostrava-Hrabůvka) is no hotel.
            if _STREET_ADJ_RE.match(folded, m.start()) or _is_street_name(folded, m.start()):
                continue
            return True
        for m in _PROPERTY_RE.finditer(folded):
            if (_APARTMENT_NOUN_RE.search(folded, 0, m.start())
                    or (m.group().startswith(CZ_ACCESSORY_STEMS)
                        and (_LAYOUT_RE.search(folded, 0, m.start())
                             or _SLUG_LAYOUT_RE.search(folded, 0, m.start())))):
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


# ── Places ────────────────────────────────────────────────────────────────────
# The places a Czech listing's text is matched against: the towns that name
# the okresy (RÚIAN's okres names, engine/regional_prices_cz), Prague and its
# 22 numbered districts, Brno's city districts — and, when the file exists,
# every municipality in data/cz_obce.csv (a RÚIAN export of the obce: one
# name per row, column "nazev" or the first column).
CZ_OBCE_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cz_obce.csv")
_RURAL_OKRES_RE = re.compile(r"-(?:venkov|vychod|zapad|jih|sever)$")
_places: dict[str, tuple[str, int]] | None = None


def _load_obce() -> list[str]:
    import csv
    if not os.path.exists(CZ_OBCE_CSV):
        return []
    with open(CZ_OBCE_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    col = head.index("nazev") if "nazev" in head else (head.index("name") if "name" in head else 0)
    # A header names a column, or is not a capitalised town name ("kod", "1").
    first = rows[0][0].strip() if rows[0] else ""
    has_header = "nazev" in head or "name" in head or not first[:1].isupper()
    body = rows[1:] if has_header else rows
    return [r[col].strip() for r in body if len(r) > col and r[col].strip()]


def _place_table() -> dict[str, tuple[str, int]]:
    """{folded phrase: (district to store, rank)} — rank 0 is the most
    specific (a city district), 2 a town."""
    global _places
    if _places is not None:
        return _places
    from engine.regional_prices_cz import OKRES_KRAJ, BRNO_DISTRICTS
    from scraper.czech_cases import locative_phrases
    from modules.lv_screen import fold as pfold
    entries: list[tuple[str, str, int]] = []      # (name, district, rank)
    for n in range(1, 23):
        entries.append((f"Praha {n}", f"Praha {n}", 0))
    for part in BRNO_DISTRICTS:
        entries.append((part, part if part.lower().startswith("brno") else f"Brno - {part}", 1))
    towns = {"Praha"}
    for okres in OKRES_KRAJ:
        if okres.startswith("Hlavní město"):
            continue
        if _RURAL_OKRES_RE.search(fold(okres)):
            # "Praha-východ", "Brno-venkov": the okres around a city is not
            # the city — named whole, it is its own place.
            entries.append((okres, okres, 1))
            continue
        towns.add(re.sub(r"-město$", "", okres))
    towns.update(_load_obce())
    entries += [(t, t, 2) for t in sorted(towns)]
    table: dict[str, tuple[str, int]] = {}
    for name, district, rank in entries:
        nom = "N:" + pfold(name).replace("-", " ")
        if nom not in table or table[nom][1] > rank:
            table[nom] = (district, rank)
        for phrase in locative_phrases(name):
            loc = "L:" + pfold(phrase).replace("-", " ")
            if loc not in table or table[loc][1] > rank:
                table[loc] = (district, rank)
    _places = table
    return table


_TOKEN_RE = re.compile(r"\w+")          # "Ostrava-Poruba" is two words
_LOC_PREP = {"v", "ve", "na"}
# A bare Brno city part ("Vinohrady", "Komín", "Černovice") is Brno's only
# when the text names Brno: Prague has its Vinohrady, Tábor its Černovice.
_BRNO_NAMED_RE = re.compile(r"(?<!\w)brn(?:o|e|a|em|u)(?!\w)")
# "Praha 2" is a district; "Praha 2+kk", "Praha, 5 minut od metra" are not.
_NOT_A_DISTRICT_NO_RE = re.compile(r"\s*(?:\+|kk(?!\w)|min)")


def place_from_text(text: str) -> str:
    """The Czech place a listing's text names, as a district string ("Praha
    2", "Brno - Žabovřesky", "Kladno"), or "". A name counts in the
    nominative (capitalised, so "most" — a bridge — is not Most) or in the
    locative after "v" / "ve" / "na" ("v Praze 2", "ve Zlíně", "na
    Vinohradech"). The longest name wins, then the most specific."""
    from modules.lv_screen import fold as pfold
    snippet = (text or "")[:4000]
    if not snippet:
        return ""
    table = _place_table()
    low = pfold(snippet)
    brno_named = bool(_BRNO_NAMED_RE.search(low))
    tokens = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(low)]
    best = None                                   # (-words, rank, start, district)
    for i, (start, _) in enumerate(tokens):
        prev = low[tokens[i - 1][0]:tokens[i - 1][1]] if i else ""
        for n in range(min(4, len(tokens) - i), 0, -1):
            phrase = " ".join(low[s:e] for s, e in tokens[i:i + n])
            hit = None
            if prev in _LOC_PREP and ("L:" + phrase) in table:
                hit = table["L:" + phrase]
            elif ("N:" + phrase) in table and snippet[start].isupper():
                hit = table["N:" + phrase]
            if hit and hit[0].startswith("Brno - ") and not brno_named:
                hit = None
            if hit and n > 1 and low[tokens[i + n - 1][0]:tokens[i + n - 1][1]].isdigit():
                # A district number follows its city's name directly (a
                # space or a hyphen) and is no layout or minute count.
                gap = low[tokens[i + n - 2][1]:tokens[i + n - 1][0]]
                rest = low[tokens[i + n - 1][1]:]
                if not re.fullmatch(r"\s*(?:[-–]\s*)?", gap) or _NOT_A_DISTRICT_NO_RE.match(rest):
                    hit = None
            if hit:
                cand = (-n, hit[1], start, hit[0])
                if best is None or cand < best:
                    best = cand
                break
    return best[3] if best else ""
