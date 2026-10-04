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
# rentals, houses, land, garages, and non-residential/commercial space. Each
# entry is a word stem matched at the start of a word in a listing's title and
# URL, so a single entry catches every Slovak grammatical declension of the
# word (e.g. "nebytov" catches nebytový/nebytové/nebytovej/nebytových
# priestor(y)). See matches_keywords for when a match counts.
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

# The keywords that exclude wherever they stand. They say what kind of deal or
# what legal kind of unit this is, and that stays true when the title also
# says "byt": "Byt v dražbe" is an auction, "Prenájom bytu" a rental, an
# "apartmán" in a hotel or an administrative building a non-residential unit.
# Every other keyword names a kind of property, and those also turn up in a
# flat's own listing — as what comes with it ("byt s garážou", "so záhradou")
# or as its street (Obchodná, Záhradnícka, Skladová).
ALWAYS_EXCLUDE_KEYWORDS = (
    "prenajom", "dražb", "nebytov", "zastavan", "hotel", "penzion",
    "administr", "viacúčelov", "viacucelov",
)


def strip_diacritics(text: str) -> str:
    """Fold Slovak diacritics away so "Voľný"/"Volny" and "izbový"/"izbovy"
    match the same pattern."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


# Kept for callers that used the private name before it was made public.
_strip_diacritics = strip_diacritics


def _fold(text: str) -> str:
    return strip_diacritics((text or "").lower())


_ALWAYS_STEMS = frozenset(_fold(k) for k in ALWAYS_EXCLUDE_KEYWORDS)

# The flat itself, as a noun: byt in every case (bytu, byte, bytom, byty,
# bytov, bytmi, bytoch) and bytík, garsónka/garzónka/garsoniéra, apartmán,
# mezonet, loft, penthouse. Whole words only, so the adjective "bytový" (as in
# "bytový dom", a block of flats) and "nebytový" are not the noun.
_APARTMENT_NOUN_RE = re.compile(
    r"(?<![^\W\d_])(?:"
    r"byt(?:u|e|om|y|ov|mi|och|ik|ika|iku|iky|ikom|ikov)?"
    r"|gar[sz]on(?:k|ier)[^\W\d_]*"
    r"|apartman(?:u|e|om|y|ov|mi|och)?"
    r"|mezonet[^\W\d_]*|loft[^\W\d_]*|penthouse[^\W\d_]*"
    r")(?![^\W\d_])")

_WORD_REST_RE = re.compile(r"[^\W\d_]*")
# A street name is followed by "ulica"/"ul." or by a house number that ends the
# phrase ("Záhradnícka 45, Ružinov" — not "Garáž 18 m2"), or comes after
# "ul."/"ulica"/"na ulici".
_STREET_AFTER_RE = re.compile(
    r"[\s\-–]+(?:ul|ulic[^\W\d_]*)(?![^\W\d_])"
    r"|\s+\d{1,4}[a-z]?(?:/(?:\d{1,4}[a-z]?|[a-z]))?\s*(?:[,;)]|$)",
    re.M)
_STREET_BEFORE_RE = re.compile(r"(?<![^\W\d_])(?:ul|ulic[^\W\d_]*)[\s.\-–]*$")


def keyword_pattern(keywords) -> "re.Pattern[str]":
    """One regex for a list of word stems, matched against diacritic-folded
    lowercase text. A stem may carry any ending (that is how a single entry
    catches every declension) but must START a word: matched anywhere, "chal"
    excluded every flat in Michalovce and on Michalská, and "budov" every
    "novovybudovaný" new build. A digit or punctuation before the stem still
    counts as a boundary, so URL slugs ("predaj-garaz") match."""
    stems = sorted({_fold(k) for k in keywords}, key=len, reverse=True)
    return re.compile(r"(?<![^\W\d_])(?:" + "|".join(map(re.escape, stems)) + ")")


def _is_street_name(text: str, start: int) -> bool:
    end = _WORD_REST_RE.match(text, start).end()
    return bool(_STREET_AFTER_RE.match(text, end)
                or _STREET_BEFORE_RE.search(text, 0, start))


def _excludes(text: str, m: "re.Match[str]") -> bool:
    """Whether one keyword hit in `text` (folded) makes it a non-apartment.

    A property keyword after the flat's own noun describes the flat — "3-izbový
    byt s garážou", "byt so záhradou", "2-izb. byt, Obchodná" — while one before
    it is what the listing is: "Garáž pri byte", "Rodinný dom s 2 bytmi". A
    street name ("Obchodná ulica", "ul. Skladová", "Záhradnícka 45") is never
    the property. ALWAYS_EXCLUDE_KEYWORDS count wherever they are."""
    if m.group(0) in _ALWAYS_STEMS:
        return True
    if _APARTMENT_NOUN_RE.search(text, 0, m.start()):
        return False
    return not _is_street_name(text, m.start())


def matches_keywords(pattern: "re.Pattern[str]", *texts: str) -> bool:
    """True when `pattern` (from keyword_pattern) names any of the texts as a
    non-apartment listing — see _excludes for when a hit counts.

    Text and keywords are both diacritic-folded: most keywords are ASCII
    ("garaz", "kancelar") while titles keep their diacritics ("Predaj garáže",
    "Kancelárske priestory"), and a nehnutelnosti URL (/detail/{id}) carries no
    ASCII slug to fall back on. Folding the keywords too keeps the diacritic
    ones ("reštaur", "dražb") matching, with or without the accents."""
    for t in texts:
        folded = _fold(t)
        if any(_excludes(folded, m) for m in pattern.finditer(folded)):
            return True
    return False


_EXCLUDE_RE = keyword_pattern(EXCLUDE_KEYWORDS)


def is_excluded_listing(*texts: str) -> bool:
    """True when any of the given strings (title, URL, …) names a
    non-apartment listing per EXCLUDE_KEYWORDS (see matches_keywords)."""
    return matches_keywords(_EXCLUDE_RE, *texts)


# "3-izbový", "3 izbový", "3-izb.", "3izb", "3 - izbovy" … (diacritics stripped
# before matching, so izbový/izbovy both hit).
_IZB_RE = re.compile(r"\b([1-6])\s*[-–]?\s*izb", re.I)
# Garsónka / garzónka == studio == 1 room.
_GARSONKA_RE = re.compile(r"\bgar[sz]onk", re.I)


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
