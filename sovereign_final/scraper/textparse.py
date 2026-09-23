"""
scraper/textparse.py — tiny shared text-parsing helpers for the scrapers.

rooms_from_title() exists because the rooms-aware rent multiplier in
engine/financial (1-izb 1.15×, 3-izb 0.92×, …) only fires when a listing has a
rooms count — but bazos/topreality never provide one structurally, and
nehnutelnosti only sometimes ships it in JSON-LD. The count is almost always
sitting in the title ("3-izbový byt", "2-izb. byt", "garsónka"), so parse it
from there as a fallback.

EXCLUDE_KEYWORDS is shared for the same reason: each site's search page mixes
apartments-for-sale with rentals, houses, land, garages and non-residential
space, and a keyword added to catch one of those on one site needs to catch it
on every site — otherwise the list quietly drifts out of sync per scraper.
"""

import re
import unicodedata

# Skip these — a site's "apartments for sale" search/category still mixes in
# rentals, houses, land, garages, and non-residential/commercial space. Matched
# as a case-insensitive substring against a listing's title and URL, so a
# single entry catches every Slovak grammatical declension of the word
# (e.g. "nebytov" catches nebytový/nebytové/nebytovej/nebytových priestor(y)).
EXCLUDE_KEYWORDS = (
    "prenajom",   # rental
    "rodinn",     # rodinný dom = house
    "pozem",      # pozemok/pozemku/pozemky — land plot in any declension
    "zahrad",     # garden / land plot (záhrada)
    "garaz",      # garage
    "kancelar",   # office
    "chal", "chat",  # cottages
    "obchodn",    # commercial
    "sklado",     # storage
    "administr",  # administrative space
    "statie",     # parking spot
    "vikend",     # weekend cottage
    "budov",      # building (budova)
    "kaviar",     # café (kaviareň)
    "reštaur",    # restaurant
    "hotel",      # hotel
    "penzion",    # guesthouse
    "zrub",       # log cabin / chalet (zrub, zrubu)
    "zastavan",   # "v zastavanom území" — construction-zone/built-up-area plots
    "dražb",      # dražba — auction (often non-apartment property)
    "viacúčelov", "viacucelov",  # multi-purpose building, not apartment
    "nebytov",    # nebytový priestor / nebytové priestory — non-residential unit
)


def is_excluded_listing(*texts: str) -> bool:
    """True when any of the given strings (title, URL, …) names a
    non-apartment listing per EXCLUDE_KEYWORDS."""
    for t in texts:
        low = (t or "").lower()
        if any(kw in low for kw in EXCLUDE_KEYWORDS):
            return True
    return False

# "3-izbový", "3 izbový", "3-izb.", "3izb", "3 - izbovy" … (diacritics stripped
# before matching, so izbový/izbovy both hit).
_IZB_RE = re.compile(r"\b([1-6])\s*[-–]?\s*izb", re.I)
# Garsónka / garzónka == studio == 1 room.
_GARSONKA_RE = re.compile(r"\bgar[sz]onk", re.I)


def strip_diacritics(text: str) -> str:
    """Fold Slovak diacritics away so "Voľný"/"Volny" and "izbový"/"izbovy"
    match the same pattern."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


# Kept for callers that used the private name before it was made public.
_strip_diacritics = strip_diacritics


# Plausible apartment floor area. Anything outside this is some other number
# that happens to be followed by "m" — a balcony, a cellar, a distance.
APARTMENT_MIN_M2 = 15.0
APARTMENT_MAX_M2 = 500.0

# "58 m²", "58m2". The unit is explicit, so this is the trustworthy form.
_AREA_M2_RE = re.compile(r"(\d{1,4}(?:[.,]\d+)?)\s*m(?:²|2)\b", re.I)
# "58 m" with no superscript. Also matches "s 6m logiou" — a 6 m² loggia, not
# a 6 m² flat — so this form is only consulted after the one above fails.
_AREA_BARE_M_RE = re.compile(r"(\d{1,4}(?:[.,]\d+)?)\s*m\b", re.I)


def area_from_text(text: str, min_m2: float = APARTMENT_MIN_M2,
                   max_m2: float = APARTMENT_MAX_M2) -> float:
    """First plausible apartment area in `text`, or 0.0.

    Every match is checked against the plausible range rather than just the
    first one, because listings routinely state a balcony or cellar area
    before the flat's own ("1,5-izb. byt s 6m logiou" put a 6 m² flat, priced
    at €182,000, into the database).
    """
    if not text:
        return 0.0
    for pattern in (_AREA_M2_RE, _AREA_BARE_M_RE):
        for m in pattern.finditer(text):
            try:
                v = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            if min_m2 <= v <= max_m2:
                return v
    return 0.0


def rooms_from_title(title: str) -> int | None:
    """Extract a room count from a Slovak listing title.

    Returns 1–6, or None when the title doesn't state one. Intended as a
    fallback for listings whose structured data carries no rooms count — pass
    the result only where rooms would otherwise be None.
    """
    if not title:
        return None
    text = _strip_diacritics(title)
    m = _IZB_RE.search(text)
    if m:
        return int(m.group(1))
    if _GARSONKA_RE.search(text):
        return 1
    return None
