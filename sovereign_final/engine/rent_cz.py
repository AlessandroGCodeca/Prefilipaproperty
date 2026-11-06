"""
engine/rent_cz.py — the Czech baseline rent table (Kč/m²/month) and how a
district resolves to one of its keys.

engine.financial delegates here for a Czech listing (market="cz"): the
Slovak RENT_PER_M2 keys and matching rules don't apply to Czech places.

The table holds the figures one source published for one period — the
Deloitte Rent Index for the 2nd quarter of 2026 (released August 2026) — for
every place it names: Prague and its ten districts (Praha 1–10), the regional
capitals Brno, Ostrava, Plzeň, Olomouc, Liberec, Hradec Králové, Pardubice,
Zlín, České Budějovice, Jihlava, Karlovy Vary and Ústí nad Labem. Its
Středočeský kraj figure is a whole region's, so it is not used for any town
in it. Kladno, Opava, Písek and the rest have no Deloitte figure. Such a
place gets its own key (its town's name), and its baseline comes from the
Ministry of Finance's official rent map (engine.rent_map_cz) when
data/cz_rent_map.csv is present and MF has enough data there; live rental
comps (engine.rent_comps_cz) blend with that baseline, or supply the rate
alone. Deloitte comes first wherever it names the place, so its figures never
change. No figure is borrowed from a neighbour or invented: with none of the
three, the listing is not scored and the run says why.

What the figures are: Deloitte's own report says it "collects data from real
estate portals" and gives the "rent from realised offers" (cena nájmu ze
zrealizovaných nabídek) — the asking rent of listings that were let, as last
advertised. That is the same measure the Ministry of Finance's official rent
map uses ("realizované nabídkové nájemné": the asking rent when the listing
comes down, taken as the sign a lease was signed — vyhláška 456/2024 Sb.).
It is an asking rent, not a contract rent: no Czech source publishes those.
It is the closing ask of a flat that let, not a fresh ask, so the live comps'
asking haircut is not applied to it. The figures cover all sizes — so the
Czech rooms multiplier is 1.0.
"""

from __future__ import annotations

import re
import unicodedata

# Kč per m² per month (Deloitte Rent Index, Q2 2026: the ČR map and the
# Praha map of its report).
RENT_PER_M2_CZ: dict[str, float] = {
    "praha 1":        490.0,
    "praha 2":        482.0,
    "praha 3":        480.0,
    "praha 4":        443.0,
    "praha 5":        461.0,
    "praha 6":        454.0,
    "praha 7":        493.0,
    "praha 8":        465.0,
    "praha 9":        468.0,
    "praha 10":       442.0,
    "praha":          462.0,
    "brno":           390.0,
    "hradec králové": 318.0,
    "pardubice":      314.0,
    "plzeň":          301.0,
    "olomouc":        296.0,
    "liberec":        289.0,
    "zlín":           287.0,
    "české budějovice": 283.0,
    "jihlava":        257.0,
    "ostrava":        254.0,
    "karlovy vary":   246.0,
    "ústí nad labem": 221.0,
}
# The national average the same release gives — shown for context, never
# used as a rent: it is pulled up by Prague and would overstate every small
# town's.
NATIONAL_AVERAGE_CZ = 343.0

RENT_SOURCE = {
    "source": ("Deloitte Rent Index Q2 2026 (released August 2026), its report "
               "2026-Q2-cz-rent-index.pdf from deloitte.com/cz-sk … rent-index: the ČR "
               "map (13 regional capitals) and the Praha map (Praha 1–10). Asking rents "
               "of listings that were let, collected from the portals ('cena nájmu ze "
               "zrealizovaných nabídek') — the measure MF's official rent map uses "
               "(vyhláška 456/2024 Sb.); not contract rents."),
    "checked": "2026-11-05 (the report itself)",
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


def mf_rent(district: str, rooms=None):
    """The MF rent map's figure (engine.rent_map_cz.MfRent) for a district
    Deloitte doesn't name, in the listing's size category — or None."""
    from engine import rent_map_cz
    key = match_rent_key(district)
    if key == "default" or key in RENT_PER_M2_CZ:
        return None
    return rent_map_cz.lookup(key, district, rooms)


def baseline_rate(district: str, rooms=None) -> tuple[float | None, str]:
    """(Kč/m², "baseline" for Deloitte's figure or "mf" for the rent map's)
    for a district: Deloitte first, then MF; (None, "baseline") for neither."""
    key = match_rent_key(district)
    if key in RENT_PER_M2_CZ:
        return RENT_PER_M2_CZ[key], "baseline"
    mf = mf_rent(district, rooms)
    return (mf.rate, "mf") if mf else (None, "baseline")


def baseline_rent(key: str) -> float | None:
    """Kč/m² for a key with a published figure — Deloitte's, else the MF rent
    map's for the town as a whole in a two-room flat's size category (what
    live comps of every size blend with); None for any other."""
    if key in RENT_PER_M2_CZ:
        return RENT_PER_M2_CZ[key]
    if not key or key == "default":
        return None
    from engine import rent_map_cz
    mf = rent_map_cz.lookup(key, key)
    return mf.rate if mf else None


def rent_fallback_kind(key: str) -> str | None:
    """Czech rents never fall back to another place's figure: a key either
    has its own (published or live) rate or none at all. "default" only for
    a blank district."""
    return "default" if not key or key == "default" else None
