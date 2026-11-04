"""
scraper/tax_coefficients_cz.py — every Czech municipality's property-tax
coefficients for a flat, from the official sources.

A Czech flat (zdanitelná jednotka in the group "ostatní zdanitelné jednotky")
pays (zákon 338/1992 Sb.)

    floor area × 1.22 × 3.50 Kč × size coefficient × local coefficient

  - the size coefficient follows the municipality's population (§ 11 odst. 4:
    1.0 / 1.4 / 1.6 / 2.0 / 2.5 / 3.5, every statutory city and four spa towns
    3.5, Prague 4.5), counted as in the Finance Ministry's decree in force on
    1 January of the tax year (§ 12f) — the Czech Statistical Office's count
    on 1 January of the year before. An ordinance may raise it one category
    in chosen cadastral areas or city parts (§ 11 odst. 5);
  - the local coefficient (0.5–5.0, § 12) is 1.0 unless an ordinance sets one
    for the whole municipality, a cadastral area or city part, or the group
    of flats.

Since 2021 every Czech municipal ordinance is published in the Sbírka
právních předpisů územních samosprávných celků (sbirkapp.gov.cz), one site
for all 6,258 municipalities. This lists the valid ones on the coefficients,
reads each (Word, ODT or PDF) and parses what it sets for flats. Population
comes from the Czech Statistical Office's open data (DataStat, set OBY02A),
and an ordinance's publisher (by its IČO) is tied to its municipality through
ARES, the Czech business register.

An ordinance counts for tax year Y only if it was published (nabyla
platnosti) by 1 October of Y−1 and is in effect on 1 January of Y (§ 16a).

What it can't do: read an ordinance older than 2021 that is still in force
but was never put in the collection, or an old Word (.doc) file. Those
municipalities keep the defaults (local coefficient 1.0).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.property_tax_rates import _normalize, doc_from_bytes, fold

log = logging.getLogger(__name__)

SBIRKA = "https://sbirkapp.gov.cz"
# The collection's own subject tags for these ordinances, and a title search
# for those filed under another subject (Prague's is under none of these).
SUBJECTS = ("dan-z-nemovitych-veci-mistni-koeficient",
            "dan-z-nemovitych-veci-koeficient-u-staveb-a-jednotek")
TITLE_WORDS = ("koeficient",)
POPULATION_CSV = "https://data.csu.gov.cz/opendata/sady/OBY02A/distribuce/csv"
ARES = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"

# § 11 odst. 4: the coefficient categories, and who takes which.
SIZE_BANDS = ((1_000, 1.0), (6_000, 1.4), (10_000, 1.6), (25_000, 2.0), (50_000, 2.5))
SIZE_STEPS = (1.0, 1.4, 1.6, 2.0, 2.5, 3.5, 4.5, 5.0)
STATUTORY = {"kladno", "ceske budejovice", "plzen", "karlovy vary", "usti nad labem",
             "liberec", "jablonec nad nisou", "hradec kralove", "pardubice", "jihlava",
             "brno", "zlin", "olomouc", "prerov", "chomutov", "decin", "frydek-mistek",
             "ostrava", "opava", "havirov", "most", "teplice", "karvina", "mlada boleslav",
             "prostejov", "trinec"}                     # zákon 128/2000 § 4 odst. 1
SPA_TOWNS = {"frantiskovy lazne", "luhacovice", "marianske lazne", "podebrady"}
PRAGUE_CODE = "554782"
LOCAL_MIN, LOCAL_MAX = 0.5, 5.0


def size_coefficient(name: str, population: int | None) -> float:
    """The § 11 odst. 4 coefficient of a municipality."""
    key = fold(name)
    if key in ("praha", "hlavni mesto praha"):
        return 4.5
    # A namesake village isn't the statutory city: Kladno in okres Chrudim has
    # 232 people (every statutory city has well over 20,000).
    if key in SPA_TOWNS or (key in STATUTORY and (population is None or population > 20_000)):
        return 3.5
    if population is None:
        return 3.5
    for upper, coef in SIZE_BANDS:
        if population <= upper:
            return coef
    return 3.5


def raised(coef: float) -> float:
    """One category up (§ 11 odst. 5): 4.5 → 5.0."""
    for i, c in enumerate(SIZE_STEPS[:-1]):
        if abs(c - coef) < 1e-9:
            return SIZE_STEPS[i + 1]
    return coef


def first_tax_year(published: date | None, effective: date | None) -> int | None:
    """§ 16a: the first tax year an ordinance counts for — published by
    1 October of the year before, in effect on 1 January."""
    if not effective:
        return None
    y = effective.year if (effective.month, effective.day) == (1, 1) else effective.year + 1
    if published:
        by_publication = published.year + 1 if (published.month, published.day) <= (10, 1) \
            else published.year + 2
        y = max(y, by_publication)
    return y


def cz_date(s: str) -> date | None:
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# ── Parsing an ordinance ──────────────────────────────────────────────────────
@dataclass
class Parsed:
    """What one ordinance sets that a flat pays."""
    municipality: float | None = None            # local coefficient for the whole municipality
    units: float | None = None                   # … for the group of flats (ostatní zdanitelné jednotky)
    areas: dict[str, float] = field(default_factory=dict)        # … by cadastral area / city part
    raise_areas: list[str] = field(default_factory=list)          # § 11/5: size raised one step here
    raise_all: bool = False                      # … everywhere in the municipality
    size_areas: dict[str, float] = field(default_factory=dict)   # … or set outright (Prague)
    annex_role: dict[str, str] = field(default_factory=dict)     # annex no. → "areas" / "size_areas"
    annexes: dict[str, dict] = field(default_factory=dict)       # an amendment's new annex tables
    amends: list[str] = field(default_factory=list)              # numbers of ordinances it changes
    repeals: list[str] = field(default_factory=list)             # numbers it repeals
    notes: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return (self.municipality is None and self.units is None and not self.areas
                and not self.raise_areas and not self.raise_all and not self.size_areas)

    def to_json(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_json(cls, d: dict) -> "Parsed":
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


_NUM = r"(\d(?:\s?[,.]\s?\d)?)(?!\s?[,.]?\s?\d)"


def _coef(s: str) -> float | None:
    try:
        v = float(re.sub(r"\s", "", s).replace(",", "."))
    except ValueError:
        return None
    return v if LOCAL_MIN <= v <= LOCAL_MAX + 1e-9 else None


def _sp(word: str) -> str:
    """A word as a pattern that tolerates the stray spaces Word runs leave in
    it ("m istni", "zastupite lstvo")."""
    return r"\s?".join(re.escape(c) for c in word)


_LOCAL = _sp("mistni") + r"\s+" + _sp("koeficient")
_TABLE_END = re.compile(
    r"tento mistni|mistni koeficient pro jednotliv\w* (?:katastr|mestsk)\w*[^.]{0,40}se vztahuje|"
    r"se vztahuje na vsechny|s vyjimkou|(?:cl|clanek|§)\s?\.?\s?\d|pokud se na nemovitou|"
    r"\(\d\)|" + _sp("priloha") + r"\s?c|\.\s+mistni koeficient")
_AREA_ROW = re.compile(
    r"(?:katastralni uzemi\s+|k\.\s?u\.\s+|mestska cast\s+|mestsky obvod\s+)?"
    r"(?P<name>[a-z][a-z\-]*(?:\s(?:u|nad|pod|pri|v|na)\s[a-z][a-z\-]*|\s[a-z][a-z\-]*){0,4}"
    r"(?:\s\d{1,2})?)\s*(?:-\s*)?(?:koeficient|ve vysi|vysi|:)?\s*(?:\.{2,}\s*)?" + _NUM)
_STOP_WORDS = {"a", "ve", "vysi", "koeficient", "koeficientem", "ktera", "ktere", "v", "pro",
               "nasledujici", "to", "uzemi", "katastralni", "mestska", "cast", "obvod",
               "mistni", "nazev", "ucinnosti", "podle", "dle", "po"}
_TRAILING = re.compile(r"(?:\s+(?:koeficient\w*|ve vysi|vysi|ve|v|je|cini|:))+$")


def _area_table(body: str) -> dict[str, float]:
    """Rows "name value" of an area table ("cernetice koeficient ... 0, 8",
    "valtice ve vysi 2", "praha 3 2", "praha-kolovraty 2")."""
    out: dict[str, float] = {}
    for m in _AREA_ROW.finditer(body):
        name = _TRAILING.sub("", re.sub(r"\s+", " ", m.group("name")).strip(" -"))
        words = name.split()
        while words and words[0] in _STOP_WORDS:
            words.pop(0)
        name = " ".join(words)
        v = _coef(m.group(2))
        if not name or v is None or name in _STOP_WORDS or len(name) < 3:
            continue
        out.setdefault(name, v)
    return out


def _annex(f: str, n: str) -> str:
    """The body of annex (příloha) n, if the text has it."""
    for m in re.finditer(_sp("priloha") + rf"\s?c\.\s?{n}\b", f):
        tail = f[m.end():m.end() + 6000]
        if re.match(r"\s*k\s|\s*(?:zni|:)", tail) or "koeficient" in tail[:300]:
            nxt = re.search(_sp("priloha") + r"\s?c\.\s?\d", tail[30:])
            return tail[:30 + nxt.start()] if nxt else tail
    return ""


def parse(text: str) -> Parsed:
    """What an ordinance sets for flats. Reads the Interior Ministry's model
    wording that nearly every municipality uses."""
    f, _ = _normalize(text)
    f = re.sub(r"(\d)\s([,.])\s?(\d)", r"\1\2\3", f)          # "2 , 6" → "2,6"
    # "č. 11/20 2 4" → "č. 11/2024": an ordinance's number, split by Word.
    f = re.sub(r"(c\.\s?\d{1,3}\s?/\s?)((?:\d\s?){4})",
               lambda m: m.group(1) + re.sub(r"\s", "", m.group(2)), f)
    out = Parsed()

    # Ordinances it changes or repeals: "kterou se mění … č. 11/2024",
    # "zrušuje se obecně závazná vyhláška … č. 2/2008".
    num = r"c\.\s?(\d{1,3}\s?/\s?\d{4})"
    for m in re.finditer(r"kterou se (?:meni|meni a doplnuje|doplnuje)[^;]{0,200}?" + num, f):
        out.amends.append(re.sub(r"\s", "", m.group(1)))
    for m in re.finditer(r"zrusuj\w* se[^;]{0,200}?" + num, f):
        out.repeals.append(re.sub(r"\s", "", m.group(1)))
    # An amendment that replaces an annex: "Příloha č. 1 zní: „…“".
    for m in re.finditer(_sp("priloha") + r"\s?c\.\s?(\d)\s+zni\s*:", f):
        body = f[m.end():m.end() + 6000]
        end = re.search(r"[“\"]\s*\.?\s*(?:" + _sp("priloha") + r"|cl\.|clanek|§)", body)
        table = _area_table(body[:end.start()] if end else body)
        if table:
            out.annexes[m.group(1)] = table

    # The whole municipality: "stanovuje místní koeficient pro obec ve výši 2".
    m = re.search(_LOCAL + r"\s+pro\s+(?:obec|mesto|mestys|statutarni mesto|cele uzemi[a-z ]{0,40})"
                  r"(?:\s[a-z]+){0,4}?\s*(?:,\s*a to\s*)?(?:ve\s+vysi|v\s+nasledujici\s+vysi:?)\s*"
                  + _NUM, f)
    if m:
        out.municipality = _coef(m.group(1))
    else:
        m = re.search(r"(?:obec|mesto|mestys)[a-z ]{0,60} stanovuje " + _LOCAL
                      + r"\s+(?:pro obec\s+)?ve\s+vysi\s*" + _NUM, f)
        # The wording before 2024 (§ 12 as it then read): "stanovuje místní
        # koeficient ve výši 2, kterým se násobí daň poplatníka za jednotlivé
        # druhy pozemků, zdanitelných staveb nebo zdanitelných jednotek" —
        # one coefficient for everything in the municipality.
        m = m or re.search(r"stanovuje\s+" + _LOCAL + r"\s+(?:ve\s+vysi\s*)?" + _NUM
                           + r"[^.]{0,60}?kterym\s+se\s+nasob\s?i\s+dan\s+poplatnika", f)
        # … and older still: "Obec Ejpovice stanovuje místní koeficient 2."
        m = m or re.search(r"stanovuje\s+" + _LOCAL + r"\s+" + _NUM + r"\s*(?:[.,(]|cl\b)", f)
        if m:
            out.municipality = _coef(m.group(1))

    # The group of flats: "… ostatní zdanitelné jednotky koeficient 1,5".
    for m in re.finditer(r"ostatni\w*\s+zdanitelne?\w*\s+jednot\w*\s*(?:-\s*)?"
                         r"(?:koeficient|ve\s+vysi|vysi|:)\s*(?:\.{2,}\s*)?" + _NUM, f):
        ctx = f[max(0, m.start() - 600):m.start()]
        if re.search(_LOCAL + r"\s+pro\s+jednotliv\w*\s+skupin", ctx):
            out.units = _coef(m.group(1))
            break

    # By cadastral area or city part, inline or in an annex.
    for m in re.finditer(_LOCAL + r"\s+pro\s+jednotliv\w*\s+(?:katastralni\w*\s+uzemi|mestsk\w*\s+"
                         r"(?:cast\w*|obvod\w*))", f):
        body = f[m.end():m.end() + 3000]
        ann = re.match(r"[^.]{0,120}?(?:podle|po dle|dle)\s+" + _sp("prilohy") + r"\s?c\.\s?(\d)", body)
        if ann:
            out.annex_role[ann.group(1)] = "areas"
            body = _annex(f, ann.group(1))
        else:
            end = _TABLE_END.search(body[20:])
            body = body[:20 + end.start()] if end else body[:1500]
        if re.match(r"[\s.,]*(?:mistni koeficient pro jednotliv|cl\.|clanek)", body):
            continue                                # the summary list in Article 1
        out.areas.update(_area_table(body))

    # § 11 odst. 5 for flats: "u zdanitelných jednotek zařazených ve skupině
    # ostatních zdanitelných jednotek se koeficient, jímž se násobí sazba daně,
    # zvyšuje o jednu kategorii … na území katastrálního území X, Y".
    for m in re.finditer(r"(?:skupin\w*|u zdanitelnych jednotek[a-z ]{0,40})\s+ostatnich\s+zdanitelnych"
                         r"\s+jednotek[^;]{0,160}?se\s+koeficient,?\s+(?:jimz|kterym)\s+se\s+nasobi\s+"
                         r"sazba\s+dane,?\s+(?P<how>zvysuje|stanovuje)", f):
        body = f[m.end():m.end() + 1500]
        if m.group("how") == "stanovuje":           # Prague: values in an annex
            ann = re.match(r"[^.]{0,200}?(?:podle|po dle|dle)\s+" + _sp("prilohy") + r"\s?c\.\s?(\d)", body)
            if ann:
                out.annex_role[ann.group(1)] = "size_areas"
                out.size_areas.update(_area_table(_annex(f, ann.group(1))))
            continue
        at = body.find("na uzemi")
        where = body[at + len("na uzemi"):at + 600] if 0 <= at < 400 else ""
        stop = re.search(r"\s*\.\s*(?:cl\b|cl\.|clanek|§|\(\d|$)|\.\s+(?:tento|toto|pokud|u zdanit)", where)
        where = where[:stop.start()] if stop else where
        if re.match(r"\s*(?:cel\w+\s+(?:obce|mesta|mestyse)|obce\b|mesta\b|mestyse\b)", where):
            out.raise_all = True
            continue
        where = re.sub(r"^(?:jednotliv\w*\s+)?(?:katastralni\w*\s+uzemi|mestsk\w*\s+(?:cast\w*|obvod\w*))"
                       r"\s*:?\s*", "", where.strip())
        names = [re.sub(r"^(?:[a-z]\)\s*)?(?:katastralni uzemi\s+)?(?:mesta|obce|mestyse)?\s*"
                        r"|\s*koeficient.*$", "", w.strip()).strip()
                 for w in re.split(r",|\sa\s(?=[a-z])|;", where)]
        out.raise_areas += [n for n in names if 2 < len(n) < 40 and not re.search(r"\d", n)]
    return out


# ── A municipality's coefficients for a tax year ──────────────────────────────
@dataclass
class Ordinance:
    """A listed ordinance with what it sets."""
    id: str
    number: str
    published: date | None
    effective: date | None
    parsed: Parsed
    title: str = ""


@dataclass
class Coefficients:
    """What a flat in a municipality pays in a tax year: the size and local
    coefficients for its main part ("") and for any area that differs."""
    size: dict[str, float]
    local: dict[str, float]
    sources: list[str]                          # the ordinances used, "1/2024 (from 2025)"

    @property
    def zoned(self) -> bool:
        return len(set(self.size.values())) > 1 or len(set(self.local.values())) > 1


def _norm_no(n: str) -> str:
    return re.sub(r"\s", "", n or "").lstrip("0")


def coefficients(name: str, population: int | None, ordinances: list[Ordinance],
                 year: int) -> Coefficients:
    """A flat's coefficients in municipality `name` for tax year `year`
    (zákon 338/1992 § 11 odst. 4–5, § 12, § 16a). The ordinances that count
    are those in force by then (§ 16a) and not repealed by another that
    counts; a later one overrides an earlier one on what both set, and an
    amendment's new annex replaces the table its base ordinance points to."""
    counts = [o for o in ordinances
              if (first_tax_year(o.published, o.effective) or 9999) <= year]
    repealed = {_norm_no(n) for o in counts for n in o.parsed.repeals}
    counts = [o for o in counts if _norm_no(o.number) not in repealed]
    counts.sort(key=lambda o: (first_tax_year(o.published, o.effective) or 0,
                               o.effective or date.min, o.published or date.min))
    merged = Parsed()
    by_number: dict[str, Parsed] = {}
    used: list[str] = []
    for o in counts:
        p = o.parsed
        if p.empty() and not p.annexes:
            continue
        used.append(f"{o.number} (from {first_tax_year(o.published, o.effective)})")
        by_number[_norm_no(o.number)] = p
        for base_no in p.amends:                 # an annex replaced in the base ordinance
            base = by_number.get(_norm_no(base_no))
            for n, table in p.annexes.items():
                role = (base.annex_role.get(n) if base else None)
                if role == "areas":
                    merged.areas = dict(table)
                elif role == "size_areas":
                    merged.size_areas = dict(table)
        if p.municipality is not None:
            merged.municipality = p.municipality
        if p.units is not None:
            merged.units = p.units
        if p.areas:
            merged.areas = dict(p.areas)
        if p.size_areas:
            merged.size_areas = dict(p.size_areas)
        if p.raise_all or p.raise_areas:
            merged.raise_all, merged.raise_areas = p.raise_all, list(p.raise_areas)

    key = fold(name)
    base = size_coefficient(name, population)
    size: dict[str, float] = {"": base}
    if merged.size_areas:                        # Prague: set per city part
        size.update(merged.size_areas)
    if merged.raise_all or key in merged.raise_areas:
        size[""] = raised(base)
    for area in merged.raise_areas:
        size[area] = raised(base)

    # § 12 odst. 5–8: the group of flats or an area replaces the municipality's
    # coefficient; where both a group and an area apply, the higher counts.
    whole = merged.municipality if merged.municipality is not None else 1.0
    if merged.units is not None:
        local = {"": merged.units}
        local.update({a: max(merged.units, v) for a, v in merged.areas.items()})
    else:
        local = {"": merged.areas.get(key, whole)}
        local.update(merged.areas)
    return Coefficients(size=size, local=local, sources=used)


# ── Fetching ──────────────────────────────────────────────────────────────────
@dataclass
class Listed:
    """One valid ordinance as the collection lists it."""
    id: str
    publisher: str
    ico: str
    number: str
    title: str
    published: date | None
    effective: date | None


def _cell(row: str, title: str) -> str:
    import html as _h
    m = re.search(r'data-title="%s"\s*>(.*?)</td>' % re.escape(title), row, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", _h.unescape(re.sub(r"<br\s*/?>", " | ",
                                                   re.sub(r"<(?!br)[^>]+>", "", m.group(1))))).strip()


def _list_page(session, params: dict, page: int) -> tuple[list[Listed], int]:
    r = session.get(f"{SBIRKA}/vyhledavani/vysledek",
                    params=dict(hlavni_typ="pp", typ="ozv", platnost="ano", page=page, **params),
                    timeout=60)
    r.raise_for_status()
    out = []
    for row in re.findall(r'<tr class="gov-journal__link">(.*?)</tr>', r.text, re.S):
        link = re.search(r'href="/detail/([^"/]+)"', row)
        if not link:
            continue
        pub = _cell(row, "Publikující")
        ico = re.search(r"IČO:\s*(\d{6,8})", pub)
        out.append(Listed(link.group(1), pub.split(" | ")[0].strip(),
                          ico.group(1).zfill(8) if ico else "",
                          _cell(row, "Číslo právního předpisu"), _cell(row, "Název právního předpisu"),
                          cz_date(_cell(row, "Datum vyhlášení")),
                          cz_date(_cell(row, "Datum nabytí účinnosti"))))
    last = max([int(v) for v in re.findall(r"[?&](?:amp;)?page=(\d+)", r.text)] or [1])
    return out, last


def list_ordinances(session, progress=None) -> list[Listed]:
    """Every valid ordinance on the coefficients, from the collection's
    subject filters and a title search, each once."""
    from concurrent.futures import ThreadPoolExecutor
    queries = [{"oblast": s} for s in SUBJECTS] + [{"nazev": w} for w in TITLE_WORDS]
    found: dict[str, Listed] = {}
    for q in queries:
        first, last = _list_page(session, q, 1)
        rows = list(first)
        with ThreadPoolExecutor(max_workers=6) as ex:
            for page_rows, _ in ex.map(lambda n: _list_page(session, q, n), range(2, last + 1)):
                rows += page_rows
        for r in rows:
            found.setdefault(r.id, r)
        if progress:
            progress(q, len(found))
    return list(found.values())


def fetch_text(session, ordinance_id: str):
    """The ordinance's own file (Word, ODT or PDF) as a scraper Doc."""
    r = session.get(f"{SBIRKA}/detail/{ordinance_id}/text", timeout=90)
    r.raise_for_status()
    return doc_from_bytes(f"{SBIRKA}/detail/{ordinance_id}", r.content,
                          r.headers.get("content-type", ""))


def split_name(label: str) -> tuple[str, str]:
    """"Brno (okr. Brno-město)" → ("Brno", "Brno-město"): the Statistical
    Office names a municipality with its district."""
    m = re.match(r"\s*(.*?)\s*\(okr\.\s*([^)]*)\)\s*$", label or "")
    return (m.group(1), m.group(2)) if m else ((label or "").strip(), "")


def populations(session, years: tuple[int, ...]) -> dict[int, dict[str, tuple[str, str, int]]]:
    """{year: {municipality code: (name, district, population on 1 January)}}
    for all Czech municipalities and each of `years`, streamed from the
    Statistical Office's open data (one large CSV, read once; only the
    municipality totals are kept)."""
    wanted = {str(y) for y in years}
    out: dict[int, dict[str, tuple[str, str, int]]] = {int(y): {} for y in wanted}
    with session.get(POPULATION_CSV, stream=True, timeout=300) as r:
        r.raise_for_status()
        lines = (ln.decode("utf-8-sig", "replace") for ln in r.iter_lines())
        rows = csv.reader(lines)
        head = next(rows)
        col = {h: i for i, h in enumerate(head)}
        for row in rows:
            try:
                if (row[col["POHL2"]] != "0" or row[col["CasR"]] not in wanted
                        or row[col["IndicatorType"]] != "2406P"):
                    continue
                code = row[col["UZ01234596C"]]
                if len(code) == 6 and code.isdigit():
                    name, okres = split_name(row[col["Všechna území"]])
                    out[int(row[col["CasR"]])][code] = (name, okres, int(float(row[col["Hodnota"]])))
            except (IndexError, ValueError):
                continue
    return out


def municipality_of(session, ico: str) -> dict | None:
    """ARES: the municipality an IČO belongs to — {code, name, district}."""
    r = session.get(ARES.format(ico=ico), timeout=30)
    if r.status_code != 200:
        return None
    s = (r.json() or {}).get("sidlo") or {}
    if not s.get("kodObce"):
        return None
    return {"code": str(s["kodObce"]), "name": s.get("nazevObce") or "",
            "district": s.get("nazevOkresu") or ""}


if __name__ == "__main__":
    import requests
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (compatible; property-tax-check)"
    rows = list_ordinances(s, progress=lambda q, n: print(q, n))
    print(len(rows), "ordinances")
    for r in rows[:3]:
        d = fetch_text(s, r.id)
        print(r.publisher, r.number, json.dumps(parse(d.text).to_json(), ensure_ascii=False))
    _ = io
