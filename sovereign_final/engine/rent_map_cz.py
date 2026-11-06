"""
engine/rent_map_cz.py — the Ministry of Finance's official rent map (Cenová
mapa nájemného): the Czech baseline rent for a place the Deloitte Rent Index
(engine/rent_cz) doesn't name.

MF publishes the map every quarter under zákon 151/1997 Sb. (§ 32b) and
vyhláška 456/2024 Sb., as an XLSX linked from
https://mf.gov.cz/cs/rozpoctova-politika/podpora-projektoveho-rizeni/cenova-mapa/cenova-mapa-infografika
(e.g. /assets/attachments/2026-08-15_Cenova-mapa.xlsx). Every obec has a row,
and an ORP town (and Prague) has one per katastrální území (KÚ) instead. Each
row gives, for four size categories (VK 1: 1+kk/1+1, VK 2: 2+kk/2+1, VK 3:
3+kk/3+1, VK 4: four rooms or more), the rent of a *reference flat* in Kč/m²
a month, its 95 % interval and the data coverage (1: 0–30 observations …
5: 150+). The reference flat is unfurnished, over 5 years old, with no
balcony, terrace, garage or lift; the same sheet's "Základní informace" gives
what each of those adds, in Kč/m².

The figures are read from data/cz_rent_map.csv (and the surcharges from
data/cz_rent_map_surcharges.csv), which dev/build_cz_rent_map.py extracts from
MF's file. Without the CSV this module has no figures and nothing changes.

How a listing's district finds its row (lookup):

  1. Its town (engine.rent_cz.match_rent_key's town key) names an obec. Where
     several obce share the name (575 names repeat: three are "Písek"), the
     kraj the district names (its okres, "…, okres Chrudim") picks among
     them; failing that, the one ORP town among them ("Kladno" is the city,
     not the village near Chrudim); failing that, no figure.
  2. An ORP town's KÚ: the one the district names after the town ("Kladno -
     Kročehlavy" → KÚ Kročehlavy; "Opava - Kateřinky" → KÚ Kateřinky u Opavy),
     else the town's own — the KÚ of its name ("Kladno"), or its "-město" /
     "u …" / "nad …" one ("Opava-Město", "Benešov u Prahy"). A town with no
     such KÚ ("Most": Most I and Most II) has no town-wide figure.
  3. The size category is the listing's own (from its rooms), VK 2 when the
     rooms are unknown. MF's figures differ by size; the Czech rooms
     multiplier stays 1.0 because the figure already is the size's.
  4. A figure needs a data coverage of at least MIN_COVERAGE (3: over 60
     observations) in that size category. Below that, MF's hedonic model is
     mostly pooling the surrounding areas — in effect a neighbour's figure,
     which this app never uses. A named KÚ with too little data falls back to
     its town's own figure (what a district naming no KÚ would get); a town
     with too little has none.

No figure is borrowed from a neighbouring obec or KÚ, and none is scaled
from Deloitte's: MF already pools neighbours inside its own model, and its
reference flat sits below Deloitte's all-listings average (Praha 2+kk: MF
358 vs Deloitte 462 Kč/m²), so a rent from this map is the conservative one.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# The lowest data coverage (1–5) a figure is used at. MF's classes: 1 = 0–30
# observations, 2 = 31–60, 3 = 61–90, 4 = 90–150, 5 = 150+.
MIN_COVERAGE = 3
# The size category when a listing's rooms are unknown: a two-room flat, the
# commonest let.
DEFAULT_VK = 2
VK_LAYOUTS = {1: "1+kk/1+1", 2: "2+kk/2+1", 3: "3+kk/3+1", 4: "4+ rooms"}
# What MF prices on top of the reference flat (Kč/m² a month, by VK).
SURCHARGE_FEATURES = ("balcony", "terrace", "furnished", "garage", "lift")

# A reference rent outside the market's own rent-per-m² bounds
# (markets.CZ.rent_per_m2_min / _max) is a misread cell, not a rent.
_RENT_MIN, _RENT_MAX = 70.0, 1_100.0

PLACES_COLUMNS = ("kraj", "obec", "code", "ku", "vk", "ref", "low", "high", "new_build",
                  "min", "max", "median", "coverage")
SURCHARGE_COLUMNS = ("vk",) + SURCHARGE_FEATURES + ("release",)


@dataclass(frozen=True)
class Unit:
    """One row of the map in one size category."""
    kraj: str
    obec: str
    code: str
    ku: str             # "" for an obec-level row
    vk: int
    ref: float          # the reference flat's rent, Kč/m² a month
    low: float          # the 95 % interval
    high: float
    new_build: float
    coverage: int


@dataclass
class _Obec:
    kraj: str
    name: str
    own: str | None = None                          # an obec-level row's code
    kus: dict[str, str] = field(default_factory=dict)   # KÚ name → code

    @property
    def is_orp(self) -> bool:
        return bool(self.kus)


@dataclass(frozen=True)
class MfRent:
    """The figure a listing gets from the map, and where it comes from."""
    rate: float
    vk: int
    coverage: int
    low: float
    high: float
    kraj: str
    obec: str
    ku: str
    surcharges: dict

    @property
    def where(self) -> str:
        return f"{self.obec} (KÚ {self.ku})" if self.ku else self.obec

    def note(self) -> str:
        return (f"MF rent map: {self.where}, VK {self.vk} ({VK_LAYOUTS[self.vk]}), "
                f"reference flat {self.rate:.0f} Kč/m² (95 % interval "
                f"{self.low:.0f}–{self.high:.0f}), data coverage {self.coverage}/5")


# code → {vk: Unit}; folded obec name → its obce; vk → {feature: Kč/m²}.
UNITS: dict[str, dict[int, Unit]] = {}
OBCE: dict[str, list[_Obec]] = {}
SURCHARGES: dict[int, dict[str, float]] = {}
SOURCE = {
    "source": ("MF Cenová mapa nájemného (zákon 151/1997 Sb., vyhláška 456/2024 Sb.) — not "
               "loaded: run dev/build_cz_rent_map.py to write data/cz_rent_map.csv"),
    "checked": None,
}
_DEFAULT_SOURCE = dict(SOURCE)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def norm(name: str) -> str:
    """A place name as compared: no diacritics or case, one kind of dash with
    no spaces round it, single spaces ("Frýdek - Místek" → "frydek-mistek")."""
    s = re.sub(r"\s*[-–—]\s*", "-", _fold(name))
    return re.sub(r"\s+", " ", s).strip(" -")


_QUALIFIER_RE = re.compile(r"^(.+?) (?:u|nad|pod|na|v|ve) \S.*$")


def _ku_names(ku: str, obec: str) -> set[str]:
    """The ways a district can name a KÚ: whole ("Kateřinky u Opavy"),
    without its "u …" / "nad …" ("Kateřinky"), without its town in front
    ("Opava-Předměstí" → "Předměstí")."""
    n, town = norm(ku), norm(obec)
    names = {n}
    m = _QUALIFIER_RE.match(n)
    if m:
        names.add(m.group(1))
    if n.startswith(town + "-"):
        names.add(n[len(town) + 1:])
    names.discard(town)
    return names


def _town_ku(obec: _Obec) -> str | None:
    """An ORP town's own KÚ: the one of its name, else its single "-město" /
    "Město …" / "… u|nad|pod|na|v|ve …" one."""
    town = norm(obec.name)
    for ku, code in obec.kus.items():
        if norm(ku) == town:
            return code
    core_re = re.compile(rf"{re.escape(town)}(?:-mesto| (?:u|nad|pod|na|v|ve) \S.*)")
    core = [code for ku, code in obec.kus.items()
            if core_re.fullmatch(norm(ku)) or norm(ku) == f"mesto {town}"]
    return core[0] if len(core) == 1 else None


def _named_ku(obec: _Obec, district: str) -> str | None:
    """The KÚ a district names after the town ("Kladno - Kročehlavy",
    "Opava-Kateřinky, Opava"), or None."""
    first = norm((district or "").split(",")[0])
    town = norm(obec.name)
    if not first.startswith(town):
        return None
    rest = first[len(town):].strip(" -")
    if not rest:
        return None
    hits = {code for ku, code in obec.kus.items() if rest in _ku_names(ku, obec.name)}
    return hits.pop() if len(hits) == 1 else None


def _kraj_hint(district: str) -> str | None:
    """The kraj (MF's name for it) a district names: its okres after the
    comma first ("Kladno, Chrudim"), then anywhere."""
    from engine.regional_prices_cz import KRAJ_NAMES, kraj_for_district
    parts = (district or "").split(",", 1)
    code = (kraj_for_district(parts[1]) if len(parts) > 1 else None) \
        or kraj_for_district(district or "")
    return KRAJ_NAMES[code] if code else None


def find_obec(town: str, district: str = "") -> _Obec | None:
    """The obec a town key names, disambiguated as the module docstring says."""
    found = OBCE.get(norm(town)) or []
    if len(found) > 1:
        kraj = _kraj_hint(district or town)
        if kraj:
            found = [o for o in found if o.kraj == kraj]
    if len(found) > 1:
        found = [o for o in found if o.is_orp]
    return found[0] if len(found) == 1 else None


def vk_for_rooms(rooms) -> int:
    """MF's size category for a room count; DEFAULT_VK when it's unknown."""
    try:
        r = int(rooms)
    except (TypeError, ValueError):
        return DEFAULT_VK
    return min(r, 4) if r > 0 else DEFAULT_VK


def _usable(code: str | None, vk: int) -> Unit | None:
    unit = UNITS.get(code or "", {}).get(vk)
    return unit if unit and unit.coverage >= MIN_COVERAGE else None


def lookup(town: str, district: str = "", rooms=None) -> MfRent | None:
    """The map's figure for a listing in `town` (a rent key) at `district`,
    in the size category of `rooms` — or None (no CSV loaded, no such obec,
    an ambiguous name, no town-wide KÚ, or too little data)."""
    if not UNITS:
        return None
    obec = find_obec(town, district)
    if obec is None:
        return None
    vk = vk_for_rooms(rooms)
    if obec.is_orp:
        unit = _usable(_named_ku(obec, district), vk) or _usable(_town_ku(obec), vk)
    else:
        unit = _usable(obec.own, vk)
    if unit is None:
        return None
    return MfRent(rate=unit.ref, vk=vk, coverage=unit.coverage, low=unit.low, high=unit.high,
                  kraj=unit.kraj, obec=unit.obec, ku=unit.ku,
                  surcharges=dict(SURCHARGES.get(vk, {})))


def surcharge(mf: MfRent, furnished=None, balcony=None) -> tuple[float, set[str]]:
    """(Kč/m² MF adds for the features a listing has, the features priced).
    Only what both MF publishes and the description tells apart: a balcony
    and a furnished flat. A semi-furnished flat (no MF class) and the parking
    flag (garage +, outdoor space nothing: the flag mixes them) are left to
    the market's % premiums, as on any Czech rate."""
    extra, priced = 0.0, set()
    s = mf.surcharges
    if balcony and "balcony" in s:
        extra += s["balcony"]
        priced.add("balcony")
    if (furnished or "").strip().lower() == "furnished" and "furnished" in s:
        extra += s["furnished"]
        priced.add("furnished")
    return extra, priced


# ── Loading the CSVs ──────────────────────────────────────────────────────────
def _num(raw) -> float | None:
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def clear() -> None:
    UNITS.clear()
    OBCE.clear()
    SURCHARGES.clear()
    SOURCE.clear()
    SOURCE.update(_DEFAULT_SOURCE)


def load_map(path: str, surcharges_path: str | None = None) -> int:
    """Read the places CSV (PLACES_COLUMNS) — and the surcharges CSV beside
    it, when there is one — into the tables, replacing what they held.
    Returns the number of rows taken; a row with an unknown size category,
    coverage outside 1–5 or an implausible rent is skipped with a warning."""
    units: dict[str, dict[int, Unit]] = {}
    obce: dict[tuple, _Obec] = {}
    taken = 0
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            kraj, obec = (row.get("kraj") or "").strip(), (row.get("obec") or "").strip()
            code, ku = (row.get("code") or "").strip(), (row.get("ku") or "").strip()
            vals = {k: _num(row.get(k)) for k in ("vk", "ref", "low", "high", "new_build",
                                                    "coverage")}
            if not (kraj and obec and code) or vals["vk"] not in (1, 2, 3, 4) \
                    or vals["coverage"] not in (1, 2, 3, 4, 5) \
                    or not (vals["ref"] and _RENT_MIN <= vals["ref"] <= _RENT_MAX):
                log.warning(f"cz_rent_map.csv: skipped {row}")
                continue
            vk = int(vals["vk"])
            units.setdefault(code, {})[vk] = Unit(
                kraj=kraj, obec=obec, code=code, ku=ku, vk=vk, ref=vals["ref"],
                low=vals["low"] or vals["ref"], high=vals["high"] or vals["ref"],
                new_build=vals["new_build"] or 0.0, coverage=int(vals["coverage"]))
            # An ORP town's KÚ rows are one obec (kraj + name); an obec-level
            # row is its own, even where a namesake shares the kraj.
            o = obce.setdefault((kraj, obec) if ku else (kraj, obec, code),
                                _Obec(kraj=kraj, name=obec))
            if ku:
                o.kus[ku] = code
            else:
                o.own = code
            taken += 1
    sur: dict[int, dict[str, float]] = {}
    release = ""
    if surcharges_path and os.path.exists(surcharges_path):
        with open(surcharges_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                vk = _num(row.get("vk"))
                if vk not in (1, 2, 3, 4):
                    log.warning(f"cz_rent_map_surcharges.csv: skipped {row}")
                    continue
                sur[int(vk)] = {k: v for k in SURCHARGE_FEATURES
                                if (v := _num(row.get(k))) is not None and 0 <= v <= 200}
                release = release or (row.get("release") or "").strip()
    clear()
    UNITS.update(units)
    for o in obce.values():
        OBCE.setdefault(norm(o.name), []).append(o)
    SURCHARGES.update(sur)
    if taken:
        SOURCE.update(
            source=(f"MF Cenová mapa nájemného{' ' + release if release else ''} "
                    f"({path}: {len(units)} places; zákon 151/1997 Sb., vyhláška 456/2024 "
                    f"Sb.) — the reference flat: unfurnished, over 5 years old, no balcony, "
                    f"terrace, garage or lift"
                    + ("" if sur else "; no surcharges file, so the market's % premiums apply")),
            checked=None)
    return taken


def _default_paths() -> tuple[str, str]:
    from config import DATA_DIR
    return (os.path.join(DATA_DIR, "cz_rent_map.csv"),
            os.path.join(DATA_DIR, "cz_rent_map_surcharges.csv"))


if os.path.exists(_default_paths()[0]):
    try:
        load_map(*_default_paths())
    except (OSError, csv.Error) as e:
        log.warning(f"cz_rent_map.csv not read: {e}")
