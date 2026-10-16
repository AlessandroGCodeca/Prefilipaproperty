"""
engine/regional_prices_cz.py — Czech sale-price medians (Kč/m²): the
benchmark a Czech listing's price is judged against.

engine.regional_prices delegates here for market="cz". The lookup runs
most specific first, as the Slovak one does:

  1. a Prague district ("Praha 1" … "Praha 22")
  2. a Brno city district (one of its 29 městské části)
  3. an okres (one of the 76, recognised by its name or its town)
  4. a kraj (one of the 14)

THE MEDIAN TABLES ARE EMPTY. No source could be read whole while this was
built (no .cz host was reachable), and a median is never invented: a Czech
listing without a benchmark is WHITE — never a guessed GREEN. Medians are
loaded from data/cz_regional_prices.csv when that file exists:

    level,name,median_czk_m2,period,source
    kraj,Jihomoravský kraj,117223,2026-09,<where the figure comes from>
    okres,Sokolov,27862,2022-2024,ČSÚ Ceny nemovitostí 2022–2024
    praha,Praha 7,…,…,…
    brno,Brno-střed,…,…,…

`level` is kraj / okres / praha / brno; `name` as in the tables below. Take
every row from one source and period (ČSÚ's "Ceny nemovitostí" tables by
okres, or one broker's asking-price index), so a listing is never judged
against two different measures. The README lists the figures found so far
and where the full tables are.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import unicodedata

log = logging.getLogger(__name__)

# The fourteen kraje (zákon 129/2000 Sb. o krajích), under short codes of
# this app's own.
KRAJ_NAMES: dict[str, str] = {
    "PHA": "Hlavní město Praha",
    "STC": "Středočeský kraj",
    "JHC": "Jihočeský kraj",
    "PLK": "Plzeňský kraj",
    "KVK": "Karlovarský kraj",
    "ULK": "Ústecký kraj",
    "LBK": "Liberecký kraj",
    "HKK": "Královéhradecký kraj",
    "PAK": "Pardubický kraj",
    "VYS": "Kraj Vysočina",
    "JHM": "Jihomoravský kraj",
    "OLK": "Olomoucký kraj",
    "ZLK": "Zlínský kraj",
    "MSK": "Moravskoslezský kraj",
}

# The 76 okresy and Prague, each with its kraj. An okres is named for its
# town ("Plzeň-jih" and "Plzeň-sever" around Plzeň-město), so a listing in
# the town matches its okres.
OKRES_KRAJ: dict[str, str] = {
    "Hlavní město Praha": "PHA",
    "Benešov": "STC", "Beroun": "STC", "Kladno": "STC", "Kolín": "STC",
    "Kutná Hora": "STC", "Mělník": "STC", "Mladá Boleslav": "STC", "Nymburk": "STC",
    "Praha-východ": "STC", "Praha-západ": "STC", "Příbram": "STC", "Rakovník": "STC",
    "České Budějovice": "JHC", "Český Krumlov": "JHC", "Jindřichův Hradec": "JHC",
    "Písek": "JHC", "Prachatice": "JHC", "Strakonice": "JHC", "Tábor": "JHC",
    "Domažlice": "PLK", "Klatovy": "PLK", "Plzeň-město": "PLK", "Plzeň-jih": "PLK",
    "Plzeň-sever": "PLK", "Rokycany": "PLK", "Tachov": "PLK",
    "Cheb": "KVK", "Karlovy Vary": "KVK", "Sokolov": "KVK",
    "Děčín": "ULK", "Chomutov": "ULK", "Litoměřice": "ULK", "Louny": "ULK",
    "Most": "ULK", "Teplice": "ULK", "Ústí nad Labem": "ULK",
    "Česká Lípa": "LBK", "Jablonec nad Nisou": "LBK", "Liberec": "LBK", "Semily": "LBK",
    "Hradec Králové": "HKK", "Jičín": "HKK", "Náchod": "HKK",
    "Rychnov nad Kněžnou": "HKK", "Trutnov": "HKK",
    "Chrudim": "PAK", "Pardubice": "PAK", "Svitavy": "PAK", "Ústí nad Orlicí": "PAK",
    "Havlíčkův Brod": "VYS", "Jihlava": "VYS", "Pelhřimov": "VYS", "Třebíč": "VYS",
    "Žďár nad Sázavou": "VYS",
    "Blansko": "JHM", "Brno-město": "JHM", "Brno-venkov": "JHM", "Břeclav": "JHM",
    "Hodonín": "JHM", "Vyškov": "JHM", "Znojmo": "JHM",
    "Jeseník": "OLK", "Olomouc": "OLK", "Prostějov": "OLK", "Přerov": "OLK",
    "Šumperk": "OLK",
    "Kroměříž": "ZLK", "Uherské Hradiště": "ZLK", "Vsetín": "ZLK", "Zlín": "ZLK",
    "Bruntál": "MSK", "Frýdek-Místek": "MSK", "Karviná": "MSK", "Nový Jičín": "MSK",
    "Opava": "MSK", "Ostrava-město": "MSK",
}

# Brno's 29 městské části (statutory city districts).
BRNO_DISTRICTS = (
    "Brno-střed", "Brno-sever", "Brno-jih", "Bohunice", "Bosonohy", "Bystrc",
    "Černovice", "Chrlice", "Ivanovice", "Jehnice", "Jundrov", "Kníničky",
    "Kohoutovice", "Komín", "Královo Pole", "Líšeň", "Maloměřice a Obřany",
    "Medlánky", "Nový Lískovec", "Ořešín", "Řečkovice a Mokrá Hora", "Slatina",
    "Starý Lískovec", "Tuřany", "Útěchov", "Vinohrady", "Žabovřesky", "Žebětín",
    "Židenice",
)

# Kč/m² medians, filled from data/cz_regional_prices.csv (see the docstring).
PRAHA_DISTRICT_MEDIAN: dict[str, float] = {}
BRNO_DISTRICT_MEDIAN: dict[str, float] = {}
OKRES_MEDIAN: dict[str, float] = {}
KRAJ_MEDIAN: dict[str, float] = {}
MEDIAN_SOURCE: dict[tuple[str, str], str] = {}

SOURCE = {
    "source": ("UNVERIFIED — no complete Czech price table could be read; the medians "
               "are empty unless data/cz_regional_prices.csv supplies them"),
    "checked": "2026-10-16",
}
_DEFAULT_SOURCE = dict(SOURCE)          # before any CSV is read (the tests' baseline)

# A median's room basis and the adjustment for other room counts: no source
# states the Czech spread, so 1.0 for every count (UNVERIFIED).
ROOMS_MULTIPLIER = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _words(text: str) -> str:
    """Folded, with hyphens and punctuation as spaces: "Brno-střed" and
    "Brno - Střed" read the same."""
    return " ".join(re.findall(r"\w+", _fold(text)))


def _pattern(name: str) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(_words(name))}(?!\w)")


# An okres matches by its own name or its town's ("Plzeň-jih" → "plzen jih";
# "Brno-město" also by "brno"). Longest first, so "Nový Jičín" beats "Jičín"
# and "Praha-východ" beats Prague itself.
def _okres_needles() -> list[tuple[re.Pattern, str]]:
    needles: dict[str, str] = {}
    for okres in OKRES_KRAJ:
        needles[_words(okres)] = okres
        town = re.sub(r"-(?:město|jih|sever|venkov)$", "", okres)
        if town != okres and okres.endswith("-město"):
            needles.setdefault(_words(town), okres)
    needles["praha"] = "Hlavní město Praha"
    needles["prague"] = "Hlavní město Praha"
    return [(_pattern(n), okres) for n, okres in
            sorted(needles.items(), key=lambda kv: len(kv[0]), reverse=True)]


_OKRES_NEEDLES = _okres_needles()
_PRAHA_RE = re.compile(r"(?<!\w)praha\s*[-–]?\s*(\d{1,2})(?!\d)")
_BRNO_NEEDLES = sorted(((_pattern(d), d) for d in BRNO_DISTRICTS),
                       key=lambda pd: len(pd[0].pattern), reverse=True)


def okres_for_district(district: str) -> str | None:
    """The okres a Czech district string names, or None."""
    text = _words(district)
    if not text:
        return None
    for rx, okres in _OKRES_NEEDLES:
        if rx.search(text):
            return okres
    return None


def kraj_for_district(district: str) -> str | None:
    """The kraj code (PHA, STC, …) for a Czech district string, or None."""
    okres = okres_for_district(district)
    return OKRES_KRAJ[okres] if okres else None


def praha_district(district: str) -> str | None:
    """"Praha 7" for "Praha 7 - Holešovice", else None (Praha 1–22)."""
    m = _PRAHA_RE.search(_fold(district or ""))
    if m and 1 <= int(m.group(1)) <= 22:
        return f"Praha {int(m.group(1))}"
    return None


def brno_district(district: str) -> str | None:
    """Brno's městská část a district string names, or None. Only within
    Brno: "Vinohrady" alone is Prague's Vinohrady as often as Brno's."""
    text = _words(district)
    if "brno" not in text:
        return None
    for rx, name in _BRNO_NEEDLES:
        if rx.search(text):
            return name
    return None


def median_source(district: str) -> tuple[float | None, str]:
    """(Kč/m² median for the district's region, what it is the median of),
    or (None, "") when no median is known — Prague district, Brno district,
    okres, kraj, most specific first."""
    if not district:
        return None, ""
    p = praha_district(district)
    if p and p in PRAHA_DISTRICT_MEDIAN:
        return PRAHA_DISTRICT_MEDIAN[p], p
    b = brno_district(district)
    if b and b in BRNO_DISTRICT_MEDIAN:
        return BRNO_DISTRICT_MEDIAN[b], f"{b}, Brno"
    okres = okres_for_district(district)
    if okres and okres in OKRES_MEDIAN:
        return OKRES_MEDIAN[okres], f"okres {okres}"
    if okres and KRAJ_NAMES[OKRES_KRAJ[okres]] in KRAJ_MEDIAN:
        name = KRAJ_NAMES[OKRES_KRAJ[okres]]
        return KRAJ_MEDIAN[name], f"{name} (no median for the okres itself)"
    return None, ""


def rooms_multiplier(rooms: int) -> float:
    return ROOMS_MULTIPLIER.get(min(int(rooms), 4), 1.0)


def benchmark_note(district: str, rooms=None) -> str:
    median, where = median_source(district)
    if median is None:
        return "No regional median for this district."
    period = MEDIAN_SOURCE.get(("where", where), "")
    note = f"median of {where}: {median:,.0f} Kč/m²".replace(",", " ")
    return note + (f" ({period})" if period else "")


# ── Loading the medians ───────────────────────────────────────────────────────
_TABLES = {"kraj": KRAJ_MEDIAN, "okres": OKRES_MEDIAN,
           "praha": PRAHA_DISTRICT_MEDIAN, "brno": BRNO_DISTRICT_MEDIAN}


def load_medians(path: str) -> int:
    """Read medians from a CSV (see the module docstring) into the tables.
    Returns the number of rows taken; a row naming no known place, or with
    no positive median, is skipped with a warning."""
    known = {"kraj": set(KRAJ_NAMES.values()), "okres": set(OKRES_KRAJ),
             "praha": {f"Praha {i}" for i in range(1, 23)}, "brno": set(BRNO_DISTRICTS)}
    taken = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            level = (row.get("level") or "").strip().lower()
            name = (row.get("name") or "").strip()
            try:
                median = float((row.get("median_czk_m2") or "").replace(" ", "").replace(",", "."))
            except ValueError:
                median = 0.0
            if level not in _TABLES or name not in known[level] or median <= 0:
                log.warning(f"cz_regional_prices.csv: skipped {row}")
                continue
            _TABLES[level][name] = median
            where = (name if level == "praha" else f"{name}, Brno" if level == "brno"
                     else f"okres {name}" if level == "okres"
                     else f"{name} (no median for the okres itself)")
            MEDIAN_SOURCE[("where", where)] = " · ".join(
                x for x in ((row.get("period") or "").strip(),
                            (row.get("source") or "").strip()) if x)
            taken += 1
    if taken:
        SOURCE.update(source=f"{path} ({taken} medians)", checked=None)
    return taken


def _default_csv() -> str:
    from config import DATA_DIR
    return os.path.join(DATA_DIR, "cz_regional_prices.csv")


if os.path.exists(_default_csv()):
    try:
        load_medians(_default_csv())
    except (OSError, csv.Error) as e:
        log.warning(f"cz_regional_prices.csv not read: {e}")
