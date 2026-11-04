"""
engine/rent_cz.py — the Czech baseline rent table (Kč/m²/month) and how a
district resolves to one of its keys.

engine.financial delegates here for a Czech listing (market="cz"): the
Slovak RENT_PER_M2 keys and matching rules don't apply to Czech places.

The table holds the figures one source published for one period — the
Deloitte Rent Index for the 2nd quarter of 2026 (released August 2026) — for
the places it named: Prague (and Praha 7, its dearest district), Brno, Hradec
Králové, Pardubice, Jihlava, Ostrava and Ústí nad Labem. Plzeň, Liberec,
České Budějovice, Olomouc, Zlín, Karlovy Vary and the rest have no figure
here: nothing was found for that quarter, and no figure is borrowed from a
neighbour or invented. Such a place still gets its own key (its town's
name), so live rental comps (engine.rent_comps_cz) can supply its rate; with
neither, the listing is not scored and the run says why.

Deloitte's index is an average over flats advertised on the portals (whether
asking or achieved rents is described differently by the reports that cite
it: UNVERIFIED), across all sizes — so the Czech rooms multiplier is 1.0.
"""

from __future__ import annotations

import re
import unicodedata

# Kč per m² per month (Deloitte Rent Index, Q2 2026).
RENT_PER_M2_CZ: dict[str, float] = {
    "praha 7":        493.0,
    "praha":          462.0,
    "brno":           390.0,
    "hradec králové": 318.0,
    "pardubice":      314.0,
    "jihlava":        257.0,
    "ostrava":        254.0,
    "ústí nad labem": 221.0,
}
# The national average the same release gives — shown for context, never
# used as a rent: it is pulled up by Prague and would overstate every small
# town's.
NATIONAL_AVERAGE_CZ = 343.0

RENT_SOURCE = {
    "source": ("Deloitte Rent Index, Q2 2026 (released August 2026), as reported by "
               "hrot24.cz, ceskenoviny.cz and MAX Reality and Deloitte's own press "
               "release list (deloitte.com/cz-sk … rent-index) — read via web search, "
               "the index's own table not fetched. Whether its figures are asking or "
               "achieved rents is UNVERIFIED."),
    "checked": "2026-10-16 (web search)",
}

# Okresy around a city that are not the city: a "Praha-východ", "Brno-venkov"
# or "Plzeň-jih" town must not take Prague's, Brno's or Plzeň's rent — however
# the okres is written ("Praha - východ", "Praha – východ", "Praha východ").
_SUBURBAN_OKRES_RE = re.compile(
    r"(?<!\w)(?:praha\s*[-–]?\s*(?:vychod|zapad)|brno\s*[-–]?\s*venkov|"
    r"plzen\s*[-–]?\s*(?:jih|sever))(?!\w)")
_OKRES_NAME = {"praha": "Praha", "brno": "Brno", "plzen": "Plzeň", "vychod": "východ",
               "zapad": "západ", "venkov": "venkov", "jih": "jih", "sever": "sever"}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _keys_by_specificity() -> list[str]:
    return sorted(RENT_PER_M2_CZ, key=len, reverse=True)


def _town_key(district: str) -> str:
    """The town a district string names, as a key: "Plzeň-město" → "plzeň",
    "Říčany, Praha-východ" → "říčany", "Kladno - Kročehlavy" → "kladno"."""
    first = (district or "").split(",")[0]
    first = re.split(r"\s+[-–]\s+", first)[0].strip()
    # "Plzeň 2-Slovany", "Liberec XIV-Kunratice": the numbered part's town.
    first = re.sub(r"\s+(?:\d{1,2}|[ivx]{1,4})\s*[-–]\s*\S.*$", "", first, flags=re.I)
    first = re.sub(r"\s*-\s*město$", "", first, flags=re.I)
    # "Plzeň-Slovany", "Zlín-Malenovice": a known town and its part — but
    # "Frýdek-Místek" is one town.
    if re.search(r"[-–]", first) and not _known_place(first):
        head = re.split(r"\s*[-–]\s*", first)[0]
        if _known_place(head):
            first = head
    # A numbered city part ("Plzeň 3", "Pardubice II") is its town's.
    first = re.sub(r"\s+(\d{1,2}|[ivx]{1,4})$", "", first, flags=re.I)
    return re.sub(r"\s+", " ", first).lower().strip()


def _known_place(name: str) -> bool:
    """A town (or obec) the Czech place table knows by this exact name."""
    from scraper.cz_common import _place_table
    from modules.lv_screen import fold as pfold
    return ("N:" + pfold(name).replace("-", " ").replace("–", " ").strip()) in _place_table()


def match_rent_key(district: str) -> str:
    """The rent key for a Czech district string: a table key found in it as
    whole words (longest first, with or without diacritics), else the name
    of the town it names — or "default" for a blank one."""
    folded = _fold(district or "").strip()
    if not folded:
        return "default"
    searchable = _SUBURBAN_OKRES_RE.sub(" ", folded)
    for key in _keys_by_specificity():
        if re.search(rf"(?<!\w){re.escape(_fold(key))}(?!\w)", searchable):
            return key
    town = _town_key(district)
    okres = _SUBURBAN_OKRES_RE.search(folded)
    if okres and not re.search(r"\w", folded[:okres.start()]):
        # The okres comes first ("Praha - východ", "Brno-venkov, Šlapanice"):
        # its own key, written one way.
        city, part = re.findall(r"[a-z]+", okres.group())
        return f"{_OKRES_NAME[city]}-{_OKRES_NAME[part]}".lower()
    return town or "default"


def baseline_rent(key: str) -> float | None:
    """Kč/m² for a key with a published figure; None for any other."""
    return RENT_PER_M2_CZ.get(key)


def rent_fallback_kind(key: str) -> str | None:
    """Czech rents never fall back to another place's figure: a key either
    has its own (published or live) rate or none at all. "default" only for
    a blank district."""
    return "default" if not key or key == "default" else None
