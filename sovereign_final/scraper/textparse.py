"""
scraper/textparse.py — tiny shared text-parsing helpers for the scrapers.

rooms_from_title() exists because the rooms-aware rent multiplier in
engine/financial (1-izb 1.15×, 3-izb 0.92×, …) only fires when a listing has a
rooms count — but bazos/topreality never provide one structurally, and
nehnutelnosti only sometimes ships it in JSON-LD. The count is almost always
sitting in the title ("3-izbový byt", "2-izb. byt", "garsónka"), so parse it
from there as a fallback.
"""

import re
import unicodedata

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
