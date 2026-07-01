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


def _strip_diacritics(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


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
