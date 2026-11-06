"""
scraper/property_tax_rates.py — read each town's flat rate (daň z bytov) from
the town's own website.

A Slovak town sets its yearly rate per m² of a flat in its VZN o miestnych
daniach (a PDF, now and then a Word file), and many also print it on a tax
page or a rate sheet. For each town in TOWNS this starts at the town's tax or
VZN page, follows the links that look like the property-tax ordinance or a
rate sheet (skipping drafts, repealed ordinances and tax-return forms), reads
each document's text and finds the flat rate: the € per m² "za byty".

It only reads. modules/tax_rates decides what a reading means for the table
in engine/property_tax_sk: a confirmation, a new rate to apply, or something
to hold for review.

A town whose own site refuses the request but publishes its ordinances on
CUET (cuet.slovensko.sk, the state's central official notice board — Zvolen
does) is read from there instead: the town's documents about local taxes,
newest first, and their attached files.

What it can't do, and says so instead of guessing:
  - read a scanned PDF (an image without a text layer);
  - get past a site that answers automated requests with a CAPTCHA, a refused
    connection or "Access Forbidden" — from a home connection most of these
    open normally, and a document saved in the browser can be uploaded on the
    dashboard (read_upload). It does not try: a bot check is the town's
    answer, and CUET is the only other source it reads;
  - map a rate to cadastral areas: for a town rated by area (ZONED) it
    reports the set of flat rates the document lists, nothing more.
"""

from __future__ import annotations

import io
import logging
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlparse

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger(__name__)


# ── Towns ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Town:
    name: str                       # as engine/property_tax_sk names it
    start: tuple[str, ...]          # the pages the search starts from
    zoned: bool = False             # rates by cadastral area or pásmo
    areas: tuple[str, ...] = ()     # area names heading the rows of a zoned table
    cuet: str = ""                  # its name as publisher on CUET, read when its site refuses


# Where each town's search starts: its tax page, its list of ordinances or a
# search of its site for "miestnych daniach" — whichever links to the
# property-tax ordinance in force. A web page is read and its property-tax
# links followed, two levels deep (and an ordinance page's own files one
# more). Every town above the second group was read correctly from here in
# November 2026 unless its comment says otherwise. The second group answers
# automated requests from a data centre with a CAPTCHA or a reset connection;
# from a home connection most of them open, so the search starts at the home
# page and follows its menu to the ordinances.
TOWNS: dict[str, Town] = {t.name: t for t in (
    Town("Bratislava", ("https://bratislava.sk/mesto-bratislava/dane-a-poplatky/dan-z-nehnutelnosti",),
         zoned=True),
    Town("Košice", ("https://www.kosice.sk/obcan/miestne-dane",), zoned=True),
    Town("Žilina", ("https://zilina.sk/mesto-zilina/dane-a-poplatky/"
                    "podavanie-danoveho-priznania-k-dani-z-nehnutelnosti/",),
         zoned=True,
         areas=("zilina", "zavodie", "banova", "brodno", "budatin", "bytcica",
                "mojsova lucka", "povazsky chlmec", "strazov", "trnove", "vranie",
                "zadubnie", "zastranie", "zilinska lehota")),
    Town("Trnava", ("https://www.trnava.sk/zoznam-vzn?SearchModel.SearchText=dani+z+nehnute%C4%BEnost%C3%AD",)),
    Town("Banská Bystrica", ("https://www.banskabystrica.sk/sekcie/oddelenia/ekonomicky-odbor/"
                             "oddelenie-miestnych-dani-a-poplatkov/",)),
    Town("Trenčín", ("https://trencin.sk/samosprava/transparentny-trencin/vseobecne-zavazne-nariadenia/",)),
    Town("Nitra", ("https://nitra.sk/dan-z-nehnutelnosti/",)),
    Town("Pezinok", ("https://www.pezinok.sk/zoznam-vzn?SearchModel.SearchText=daniach",)),
    Town("Modra", ("https://www.modra.sk/vzn/",)),
    Town("Poprad", ("https://www.poprad.sk/zoznam-vzn?SearchModel.SearchText=daniach",)),
    Town("Piešťany", ("https://www.piestany.sk/samosprava/mestska-legislativa/"
                      "vseobecne-zavazne-nariadenia/dane-a-poplatky/",)),
    Town("Trebišov", ("https://www.trebisov.sk/vseobecne-zavazne-nariadenia",)),
    Town("Dunajská Streda", ("https://dunstreda.sk/miestne-dane-poplatky",), zoned=True),
    Town("Prievidza", ("https://prievidza.sk/obyvatel/dane-a-poplatky/",)),
    Town("Malacky", ("https://malacky.sk/mesto/samosprava-mesta/vseobecne-zavazne-nariadenia/",)),
    Town("Senec", ("https://www.senec.sk/vzn/?s=miestnych+daniach",)),
    Town("Michalovce", ("https://www.michalovce.sk/sk/clanok/dane-a-poplatky",)),
    Town("Bardejov", ("https://www.bardejov.sk/informacie-pre-vas/mestske-dane-a-poplatky",)),
    Town("Ružomberok", ("https://www.ruzomberok.sk/vzn/",)),
    # The tax page states the rate; the ordinance itself is a scan.
    Town("Spišská Nová Ves", ("https://web.spisskanovaves.eu/chcem-vybavit/obcan/dane-a-poplatky/"
                              "dan-z-nehnutelnosti",)),
    Town("Humenné", ("https://www.humenne.sk/Uvodna-stranka/VZN/",)),
    Town("Šamorín", ("https://www.samorin.sk/samosprava/vzn/vzn-platne/",)),
    # Found no rate from here: the ordinance list doesn't reach VZN 5/2023.
    Town("Stupava", ("https://www.stupava.sk/obcan/ako-vybavit/dane/dan-znehnutelnosti-/",
                     "https://www.stupava.sk/sk/samosprava/vseobecne-zavazne-nariadenia/")),
    # Only 2005–2010 ordinances found from here.
    Town("Komárno", ("https://komarno.sk/?s=miestnych+daniach",)),
    # VZN 9/2023 with its two amendments: flats 0.40 in the town's streets,
    # 0.25 in its outlying settlements (jednotlivé časti 2 and 3).
    Town("Čadca", ("https://www.mestocadca.sk/samosprava-mesta/vseobecne-zavazne-nariadenia.html",),
         zoned=True),
    # VZN 3/2025: a row per group of cadastral areas, named by its last area.
    Town("Liptovský Mikuláš", ("https://www.mikulas.sk/samosprava/zastupitelstvo/"
                               "vseobecne-zavazne-nariadenia/",),
         zoned=True, areas=("svaty stefan", "raztoky", "liptovsky mikulas")),
    # A CAPTCHA (/verify) from a data centre:
    Town("Prešov", ("https://www.presov.sk/",)),
    # … but VZN 230 and its amendments are on CUET. Rates by zone (streets).
    Town("Zvolen", ("https://www.zvolen.sk/",), zoned=True, cuet="Mesto Zvolen"),
    Town("Považská Bystrica", ("https://www.povazska-bystrica.sk/",)),
    Town("Levice", ("https://www.levice.sk/",)),
    Town("Lučenec", ("https://www.lucenec.sk/",)),
    Town("Topoľčany", ("https://www.topolcany.sk/",)),
    Town("Rimavská Sobota", ("https://www.rimavskasobota.sk/",)),
    # The connection is reset from a data centre:
    Town("Martin", ("https://www.martin.sk/",)),
    Town("Nové Zámky", ("https://www.novezamky.sk/",)),
)}


# ── Text ──────────────────────────────────────────────────────────────────────
def fold(text: str) -> str:
    """Lower case without diacritics: 'Daň z bytov' → 'dan z bytov'."""
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def _normalize(text: str) -> tuple[str, str]:
    """(folded, display): the text with whitespace collapsed, once folded for
    matching and once as written for quoting, character for character the
    same length so a match in one is the same span in the other."""
    text = unicodedata.normalize("NFKC", text or "")       # m² → m2, ligatures
    text = re.sub(r"(\w)-[ \t]*\r?\n[ \t]*(\w)", r"\1\2", text)   # nebyto-\nveho
    disp: list[str] = []
    fol: list[str] = []
    space = True
    for ch in text:
        if ch.isspace():
            if not space:
                disp.append(" ")
                fol.append(" ")
            space = True
            continue
        base = unicodedata.normalize("NFD", ch)[0].lower()[:1] or ch
        if unicodedata.category(base) == "Mn":
            continue
        space = False
        disp.append(ch)
        fol.append(base)
    f = "".join(fol)
    # "m2", "m 2" → "m²": the unit's 2 is not a number.
    f = re.sub(r"(?<=\bm)2(?!\d)|(?<=\bm )2(?!\d)", "²", f)
    return f, "".join(disp)


_NUM = r"(\d{1,2}(?:[,.]\d{1,4})?)"
_CUR = r"(?:€|eur(?:a|o|ov|ach)?(?![a-z]))"
_PER = r"(?:\s*/\s*m²)?"
# A gap between a rate and "byty" (or the other way round) may not name any
# other object of the tax.
_OTHER_OBJECT = re.compile(r"nebyt|garaz|stav(?:b|ie)|pozem|psa\b|podlazi|priestor|automat")

# "0,320 € za byty", "0,75 € byty", "0,670 €/m2 za byt",
# "0,90 eur za každý aj začatý m2 podlahovej plochy bytu"
_RATE_THEN_FLAT = re.compile(
    rf"{_NUM}\s*{_CUR}{_PER}(?P<gap>[^\d€;]{{0,70}}?)(?<![a-z])byt(?:y|u)?(?![a-z])")
# "a) byty 0,60 €", "a) byty 1,270 1,207 1,143", "i byty 1,20 1,20 1,25 1,35",
# "byt 0,68 €/m² 0,61 €/m²", "a) byty 0,675" (under an "eur/m2" header),
# "a) byty vo výške 1,00 €/m²", "… podlahovej plochy bytu 1,000 €",
# "Byty a nebytové priestory 0,4 0,25 0,25" (Čadca: one class, a column per
# part of the town), "… plochy bytu: I. zóna II. zóna III. zóna 0,636 €
# 0,588 € 0,447 €" (Zvolen)
_FLAT_THEN_RATES = re.compile(
    r"(?<![a-z])byt(?:y|u)?(?:\s+a\s+nebytov\w*\s+priestor\w*)?\s*"
    r"(?:[:–-]|vo\s+vyske|v\s+sume|sumou|je)?\s*"
    r"(?:(?:[ivx]{1,3}\s*\.?\s*(?:zona|pasmo)\s*){2,6})?"
    rf"(?P<run>(?:\d{{1,2}}(?:[,.]\d{{1,4}})?\s*(?:{_CUR})?{_PER}\s*){{1,6}})")
# "sadzbu dane z bytov za byty … vo výške 0,60 €", "za byt je 0,710 €",
# "… sa zvyšuje … za byt na 1,000 €/m" — the words whole: the "na" ending
# "III. zóna 0,447 €" is not "na 0,447 €".
_FLAT_SENTENCE = re.compile(
    rf"(?<![a-z])(?:za|pre)\s+byt(?:y|u)?(?![a-z])(?P<gap>[^\d€;]{{0,160}}?)"
    rf"(?:(?<![a-z])(?:vo\s+vyske|je|sumou|v\s+sume|na)|:)\s*{_NUM}\s*{_CUR}")
# A table of past years' rates ("byt a nebytový priestor 2023 2022-2021 2020
# … byt 1,000 0,500 0,500 0,330"): history, not zones.
_YEAR_HEADER = re.compile(r"(?:20\d\d(?:\s*[-–]\s*20\d\d)?\s+){3,}")
# "Byty" as a heading over its own list ("… 0,10 € Byty a) byty 0,60 €"): the
# number before it belongs to the item above.
_HEADING_AHEAD = re.compile(r"\s*(?:[a-z]\)|\d\.|\(\d\)|[ivx]+\.?)?\s*byty?\s*[:–-]?\s*\d")

# The flat-tax part of an ordinance: "daň z bytov" (also letter-spaced,
# "D a ň z b y t o v") with its rates within the next few hundred characters.
_FLAT_SECTION = re.compile(r"d ?a ?n ?z ?b ?y ?t ?o ?v")
_SECTION_END = re.compile(
    r"dan za psa|oslobodeni\w* od dane|znizeni\w* dane|spolocne ustanovenia|"
    r"druha cast|tretia cast|dan za (?:predajne|nevyherne|ubytovanie|uzivanie)")

# A rate for a flat is cents to a few euros per m²: the act's default is
# 0.033 (§ 16 ods. 1); the dearest town in the table charges 1.35.
RATE_MIN, RATE_MAX = 0.02, 5.0

_MONTHS = {"januara": 1, "februara": 2, "marca": 3, "aprila": 4, "maja": 5, "juna": 6,
           "jula": 7, "augusta": 8, "septembra": 9, "oktobra": 10, "novembra": 11,
           "decembra": 12}
_DATE = (r"(?:(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d\d)"
         r"|(\d{1,2})\s*\.\s*(" + "|".join(_MONTHS) + r")\s+(20\d\d))")
# "nadobúda účinnosť 1. januára 2026", "účinnosť nadobudlo dňa 23. júna 2020",
# "s účinnosťou od 1.1.2025"
# A scan may read "ť" as "t‘" (Liptovský Mikuláš: "nadobúda účinnost‘ 01.01.2026");
# Zvolen heads each ordinance "Schválené: … Vyhlásené: … Účinnosť: 01.01.2025".
_EFFECTIVE = re.compile(
    r"ucinnost\w*['‘’`]?:?\s+"
    r"(?:(?:nadobuda|nadobudlo|nadobudne|nadobudnutim|dnom|dna|od|odo|dnes)\s+)*"
    + _DATE)
# "sadzby … na rok 2026", "v roku 2026", "zdaňovacie obdobie 2026"
_YEAR_PHRASE = re.compile(
    r"(?:(?:na|pre|v)\s+(?:kalendarny\s+|zdanovaci\s+)?rok(?:u)?|zdanovacie\s+obdobie(?:\s+roku)?)"
    r"\s+(20\d\d)(?!\d)")


def _rate(s: str) -> float | None:
    try:
        v = float(s.replace(",", "."))
    except ValueError:
        return None
    return v if RATE_MIN <= v <= RATE_MAX else None


@dataclass
class Reading:
    """What one document says about the flat rate."""
    url: str
    title: str
    rates: list[float]              # each distinct flat rate, in order of appearance
    excerpt: str                    # the words around the first one, as written
    tax_year: int | None = None     # the first tax year its rates apply to
    dated: bool = False             # tax_year comes from the document itself
    kind: str = "ordinance"         # ordinance / sheet (a rate sheet) / page (a web page)
    areas: dict[str, float] = field(default_factory=dict)   # zoned: area → rate


def _flat_matches(f: str) -> list[tuple[int, int, list[float]]]:
    """(start, end, rates) of each statement of a flat rate in folded text."""
    found: list[tuple[int, int, list[float]]] = []
    for m in _RATE_THEN_FLAT.finditer(f):
        if _OTHER_OBJECT.search(m.group("gap")) or _HEADING_AHEAD.match(f, m.end()):
            continue
        if re.search(r"podlazi\w*\s*[:–-]?\s*$", f[max(0, m.start() - 30):m.start()]):
            continue                                # "za ďalšie podlažie 0,10 €"
        r = _rate(m.group(1))
        if r is not None and ("," in m.group(1) or "." in m.group(1)):
            found.append((m.start(), m.end(), [r]))
    for m in _FLAT_SENTENCE.finditer(f):
        if _OTHER_OBJECT.search(m.group("gap")):
            continue
        r = _rate(m.group(2))
        if r is not None:
            found.append((m.start(), m.end(), [r]))
    for m in _FLAT_THEN_RATES.finditer(f):
        run = m.group("run")
        nums = re.findall(rf"(\d{{1,2}}(?:[,.]\d{{1,4}})?)(\s*{_CUR})?", run)
        # A bare number counts only as a decimal with a currency in sight:
        # in the run, or in the table's header or unit just around it.
        near = f[max(0, m.start() - 250):m.end() + 60]
        if len(nums) > 1 and _YEAR_HEADER.search(f[max(0, m.start() - 200):m.start()]):
            continue
        priced = any(c for _, c in nums) or re.search(_CUR, near)
        rates = [_rate(n) for n, c in nums if ("," in n or "." in n) or c]
        if not priced or not rates or any(r is None for r in rates):
            continue
        found.append((m.start(), m.end(), rates))
    found.sort()
    # One statement can match two patterns ("za byt je 0,710 € za každý …
    # bytu"): keep the first of overlapping matches.
    kept: list[tuple[int, int, list[float]]] = []
    for s, e, r in found:
        if kept and s < kept[-1][1]:
            continue
        kept.append((s, e, r))
    return kept


def _area_rates(f: str, areas: tuple[str, ...]) -> tuple[dict[str, float], int]:
    """A zoned ordinance's flat-tax table, one row per cadastral area with the
    flat rate in its first column: "banova 1,100 1,800 6,400". Returns
    ({area: rate}, where the first row starts)."""
    out: dict[str, float] = {}
    first = -1
    for sec in _FLAT_SECTION.finditer(f):
        start = sec.end()
        body = f[start:start + 4000]
        if "sadzb" not in body[:600]:
            continue
        end = _SECTION_END.search(body)
        body = body[:end.start()] if end else body
        for area in sorted(areas, key=len, reverse=True):
            m = re.search(rf"(?<![a-z]){re.escape(area)}(?![a-z])\s+(\d{{1,2}}[,.]\d{{1,4}})", body)
            if m and area not in out:
                r = _rate(m.group(1))
                if r is not None:
                    out[area] = r
                    first = start + m.start() if first < 0 else min(first, start + m.start())
        if out:
            break
    return out, first


def _tax_year(f: str, near: tuple[int, int] | None, document: bool) -> int | None:
    """The first tax year a document's rates apply to. An ordinance's own
    effective dates (the latest of them: a consolidated text lists every
    amendment's) count anywhere in a document; on a web page, where news and
    other taxes sit beside the rates, only a "na rok 2026" next to them does.
    Taxes on property follow the state on 1 January, so a rate in force from
    any later day of a year is first charged the next year."""
    years: list[int] = []
    if document:
        for m in _EFFECTIVE.finditer(f):
            d, mo, y = ((m.group(1), m.group(2), m.group(3)) if m.group(3)
                        else (m.group(4), _MONTHS[m.group(5)], m.group(6)))
            try:
                when = date(int(y), int(mo), int(d))
            except ValueError:
                continue
            years.append(when.year if (when.month, when.day) == (1, 1) else when.year + 1)
    lo, hi = (max(0, near[0] - 1500), near[1] + 1500) if near else (0, len(f))
    years += [int(y) for y in _YEAR_PHRASE.findall(f[lo:hi])]
    return max(years) if years else None


def read_text(text: str, url: str = "", title: str = "", document: bool = True,
              areas: tuple[str, ...] = ()) -> Reading | None:
    """The flat rate(s) a text states, or None when it states none.
    `document`: an ordinance or rate sheet (True) or a web page (False)."""
    kind = "page" if not document else (
        "sheet" if re.search(r"sadzb", fold(title + " " + url)) else "ordinance")
    f, disp = _normalize(text)
    matches = _flat_matches(f)
    area_rates, row = _area_rates(f, areas) if areas else ({}, -1)
    if not matches and not area_rates:
        return None
    rates: list[float] = []
    for r in [r for _, _, rs in matches for r in rs] + list(area_rates.values()):
        if r not in rates:
            rates.append(r)
    if matches:
        s, e = matches[0][0], matches[0][1]
    else:
        s, e = row, row + 40
    excerpt = disp[max(0, s - 110):e + 40].strip()
    year = _tax_year(f, (s, e), document)
    return Reading(url=url, title=title, rates=rates, excerpt=excerpt,
                   tax_year=year, dated=year is not None, kind=kind, areas=area_rates)


def mentions_flat_tax(text: str) -> bool:
    """A text about the flat tax at all: an amendment can change the rate in
    words this module doesn't read ("suma 0,60 € sa nahrádza sumou 0,70 €")."""
    f, _ = _normalize(text)
    return bool(re.search(r"dan\w* z bytov|za byty", f))


def is_draft(text: str, label: str = "") -> bool:
    """A draft (návrh) of an ordinance states rates that may never apply.
    An adopted one opens with its publication record — "Návrh VZN vyvesený …
    VZN schválené dňa 09.12.2024 uznesením č. 265/2024" — so a "návrh" at the
    top marks a draft only when no approval follows it."""
    if re.search(r"(?<![a-z])navrh", fold(label)):
        return True
    head, _ = _normalize((text or "")[:1500])
    if not re.search(r"(?<![a-z])n ?a ?v ?r ?h(?![a-z])", head[:400]):
        return False
    # "VZN schválené dňa 09.12.2024", "… schválené mestským zastupiteľstvom
    # v Šamoríne dňa 11.12.2025", "… pod č. 18/2024/V, 12.12.2024",
    # "uznesením č. 265/2024"
    return not re.search(r"schvalen\w*[^;]{0,100}?\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*20\d\d|"
                         r"uznesen\w*\s+(?:c\.|cislo)\s*\d", head)


# ── Documents ─────────────────────────────────────────────────────────────────
@dataclass
class Doc:
    url: str
    kind: str                       # html / pdf / docx / odt
    text: str
    html: str = ""
    problem: str = ""               # why it couldn't be read, if it couldn't
    title: str = ""                 # a web page's <title>


class Blocked(Exception):
    """The site refused an automated request."""


_BLOCK_MARKERS = re.compile(
    r"captcha|cf-chl|challenge-platform|access forbidden|access denied|request rejected|"
    r"are you a (?:human|robot)|ddos protection|bot protection|unusual traffic")


def _pdf_text(content: bytes) -> tuple[str, int]:
    """(text, pages) of a PDF."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)


def _zip_text(content: bytes) -> tuple[str, str] | None:
    """Text of a .docx or .odt file."""
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return None
    import html as _html
    for kind, member in (("docx", "word/document.xml"), ("odt", "content.xml")):
        if member in z.namelist():
            xml = z.read(member).decode("utf-8", "replace")
            xml = re.sub(r"</w:p>|</text:p>|</text:h>|<w:tab/>|<w:br/>", "\n", xml)
            return kind, _html.unescape(re.sub(r"<[^>]+>", " ", xml))
    return None


def doc_from_bytes(url: str, content: bytes, content_type: str = "") -> Doc:
    """Read a downloaded (or uploaded) file into text."""
    if content[:5] == b"%PDF-":
        try:
            text, pages = _pdf_text(content)
        except Exception as e:
            return Doc(url, "pdf", "", problem=f"the PDF could not be opened ({e})")
        # A scan has next to no text: a page number, a stamp. (Malacky's
        # 5 MB consolidated text gives 9 characters.)
        if len(re.sub(r"\s+", "", text)) < 50 * max(pages, 1):
            return Doc(url, "pdf", text, problem="a scanned PDF with no text layer — it can't be read")
        return Doc(url, "pdf", text)
    if content[:2] == b"PK":
        z = _zip_text(content)
        if z:
            return Doc(url, z[0], z[1])
        return Doc(url, "zip", "", problem="an archive, not a document")
    if content[:4] == b"\xd0\xcf\x11\xe0":
        return Doc(url, "doc", "", problem="an old Word (.doc) file — save it as PDF and upload it")
    raw = content.decode("utf-8", "replace") if "charset" not in content_type.lower() else None
    if raw is None:
        enc = content_type.lower().split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            raw = content.decode(enc, "replace")
        except LookupError:
            raw = content.decode("utf-8", "replace")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    text = soup.get_text("\n", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return Doc(url, "html", text, html=raw, title=re.sub(r"\s+", " ", title)[:150])


def _get(url: str, session=None, timeout: float = 45):
    """GET through ScraperAPI when it is configured, as the listing scrapers
    do; otherwise directly, with the browser headers but without "br" in
    Accept-Encoding. Brotli isn't installed, so requests can't unpack a
    Brotli answer, and bratislava.sk, humenne.sk and spisskanovaves.eu send
    one whenever it is offered: the page came back as unreadable bytes."""
    import requests
    from config import SCRAPER_API_KEY
    from scraper._http import BROWSER_HEADERS, get
    if SCRAPER_API_KEY:
        return get(url, session=session, timeout=int(timeout))
    s = session or requests.Session()
    s.headers.update({**BROWSER_HEADERS, "Accept-Encoding": "gzip, deflate"})
    return s.get(url, timeout=timeout)


def fetch(url: str, session=None, timeout: float = 45, retry: bool = True) -> Doc:
    """GET a page or document. Raises Blocked when the site refuses the
    request. A village's site is read with a shorter `timeout` and no
    `retry`: one slow site mustn't hold up the hundreds behind it."""
    import requests
    try:
        try:
            resp = _get(url, session, timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if not retry:
                raise
            time.sleep(2)               # a dropped connection is often just that
            resp = _get(url, session, timeout)
    except requests.exceptions.SSLError as e:
        raise Blocked(f"secure connection failed ({type(e).__name__})") from None
    except requests.exceptions.ConnectionError:
        raise Blocked("the site refused or reset the connection") from None
    except requests.exceptions.Timeout:
        raise Blocked("the site did not answer in time") from None
    if resp.status_code in (401, 403, 405, 429):
        raise Blocked(f"the site answered {resp.status_code} "
                      f"({'Access Forbidden' if resp.status_code == 403 else resp.reason})")
    if resp.status_code >= 400:
        raise Blocked(f"the site answered {resp.status_code} ({resp.reason})")
    doc = doc_from_bytes(resp.url or url, resp.content, resp.headers.get("content-type", ""))
    if doc.kind == "html" and len(doc.text) < 3000 and _BLOCK_MARKERS.search(fold(doc.html[:20000])):
        raise Blocked("the site answered with a CAPTCHA or bot check instead of the page")
    low = doc.html.lower() if doc.kind == "html" else ""
    if low and len(doc.text) < 400 and "<a " not in low and "<script" in low:
        # hajske.sk, sisov.sk: 3 KB, no link — a bot check by script, or a
        # page built in the browser. Nothing here for a program to read.
        raise Blocked("the page is built by JavaScript or a bot check: nothing to read")
    return doc


# ── Following links ───────────────────────────────────────────────────────────
# A link worth following names the property-tax ordinance or a rate sheet …
_STRONG = re.compile(   # in words or in a URL ("o-miestnych-daniach")
    r"nehnutelnost|miestn\w*[\s_-]+dan|dan\w*[\s_-]+z[\s_-]+bytov|sadzb\w*[\s_-]+dan|sadzby|"
    r"dane?[\s_-]+a[\s_-]+poplatky")
# … and is not a form, a draft or something else …
_SKIP = re.compile(
    r"navrh|priznani|tlaciv|poucen|potvrden|ziadost|registracn|oznamen|sharer|tweet|mailto:|"
    r"facebook|twitter|instagram|youtube|linkedin|zakonypreludi|slov-lex|\.jpg|\.png|\.zip|"
    r"zrusen|neplatn|archiv|"
    r"ulav|znizeni|oslobodeni|elektronick|e-?sluzb|platit|zaplat|prevod|majet|kontrol")
# … or another tax or fee — unless it names the property tax too: Čadca's
# ordinance is "o dani z nehnuteľností, dani za psa, dani za ubytovanie, …".
_OTHER_TAX = re.compile(r"psa(?![a-z])|ubytovan|parkovan|verejneho priestranstva|rozvoj")
_PROPERTY_TAX = re.compile(r"nehnutelnost|miestn\w*[\s_-]+dan|dan\w*[\s_-]+z[\s_-]+bytov")
# From a home page, also its list of ordinances or documents — a menu item
# there ("VZN", "Dokumenty", "Zverejňovanie" on village sites).
_ORDINANCES = re.compile(r"vseobecne[\s_-]+zavazne[\s_-]+nariadeni|(?<![a-z])vzn(?![a-z])|"
                         r"(?<![a-z])dokument|zverejnovani|legislativ|(?<![a-z])predpisy")
# A link to a file rather than a page.
_FILE = re.compile(r"\.pdf|\.docx?(?![a-z])|\.odt|download|/file|\.dat\b|/uploads?/|/storage/|"
                   r"stiahnut|subor|\bpdf\b")
MAX_FETCHES = 24        # per town
MAX_LINKS_PER_PAGE = 8
MAX_DEPTH = 2


def _site(host: str) -> str:
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:])


def _context(a) -> tuple[str, str]:
    """(tag, text) of the row or item a link sits in — its title is often
    there, not in a "stiahnuť" link — kept short so a menu's text doesn't
    leak in."""
    node = a
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        if node.name in ("tr", "li", "article", "p", "dd", "dt"):
            text = node.get_text(" ", strip=True)
            return (node.name, text) if len(text) < 500 else ("", "")
    return "", ""


def _in_menu(a) -> bool:
    """In the site's navigation, header or footer: the same links on every page."""
    for node in a.parents:
        if node.name in ("body", "html", "main", "[document]"):
            break                   # Šamorín's <body class="… menu203 …">
        if node.name in ("nav", "header", "footer"):
            return True
        marks = " ".join(node.get("class") or []) + " " + (node.get("id") or "")
        if re.search(r"menu|navig|navbar|footer|header|breadcrumb", marks.lower()):
            return True
    return False


def _links(doc: Doc, site: str, about_tax: bool = False,
           home: bool = False) -> list[tuple[int, str, str]]:
    """(rank, url, label) of the links on a page worth following, best first:
    files named as the tax ordinance or a rate sheet, then such pages, then
    files whose row names it ("stiahnuť" in a table of ordinances), then
    pages whose row does; within each, the newest year first. On a page
    that is itself about the tax ordinance (`about_tax`) its files count
    whatever their label: there the PDF is just "Stiahnuť" or
    "VZN_17_2023.pdf". From a `home` page its list of ordinances counts
    too, last."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(doc.html, "lxml")
    base = soup.find("base", href=True)    # poprad.sk: <base href="//www.poprad.sk/">
    base_url = urljoin(doc.url, base["href"]) if base else doc.url
    here = urlparse(doc.url)
    seen: set[str] = set()
    out = []
    for i, a in enumerate(soup.find_all("a", href=True)):
        href = urljoin(base_url, a["href"]).split("#")[0]
        there = urlparse(href)
        if (there.netloc, there.path) == (here.netloc, here.path):
            continue                # the same page again ("?mapa-webu=1", "?rss=200")
        if not href.startswith("http") or href in seen or href == doc.url.split("#")[0]:
            continue
        if _site(urlparse(href).hostname or "") != site:
            continue
        text, hint = a.get_text(" ", strip=True), (a.get("title") or "").strip()
        label = re.sub(r"\s+", " ", text if hint in text else f"{text} {hint}").strip()
        own = fold(label + " " + href)
        tag, ctx_text = _context(a)
        ctx = fold(ctx_text)
        if _SKIP.search(own) or (_OTHER_TAX.search(own) and not _PROPERTY_TAX.search(own)):
            continue
        # A table row or list item is the link's own entry: its status
        # ("Zrušené, neplatné") applies to it.
        if tag in ("tr", "li", "dd", "dt") and re.search(r"zrusen|neplatn", ctx):
            continue
        strong_own = bool(_STRONG.search(own))
        is_file = bool(_FILE.search(own))
        listing = home and bool(_ORDINANCES.search(own))
        if not strong_own and not listing and (_in_menu(a) or not (
                _STRONG.search(ctx) or (about_tax and is_file))):
            continue
        seen.add(href)
        tier = {(True, True): 3, (True, False): 2, (False, True): 1, (False, False): 0}[
            (strong_own, is_file)]
        years = [int(y) for y in re.findall(r"(?<!\d)(20[0-4]\d)(?!\d)", own + " " + ctx)]
        if listing and not strong_own:
            # An ordinance list before a generic "Dokumenty"/"Zverejňovanie"
            # page, which leads to election minutes and contracts first.
            tier = -1 if re.search(r"vseobecne|vzn|nariaden", own) else -2
        rank = tier * 100_000 + (max(years) if years else 2000) * 10 - min(i, 9)
        out.append((rank, href, label if strong_own or not ctx_text else ctx_text[:160]))
    out.sort(key=lambda t: -t[0])
    return out[:MAX_LINKS_PER_PAGE]


# ── CUET, the central official notice board ───────────────────────────────────
CUET = "https://cuet.slovensko.sk"
CUET_YEARS = 3          # how far back its documents are searched
CUET_DOCUMENTS = 6      # document pages opened, the newest first


def cuet_search_url(publisher: str, since: date) -> str:
    """CUET's search for `publisher`'s documents about local taxes published
    since `since`. By the annotation, not the title: CUET cuts titles at 50
    characters ("Novelizácia č. 2 VZN Mesta Zvolen č.230 o miestnyy")."""
    from urllib.parse import urlencode
    return f"{CUET}/sk?" + urlencode({
        "PublisherName": publisher, "DocumentAbstract": "miestnych daniach",
        "DocumentPublishedFrom": since.strftime("%d.%m.%Y")})


def cuet_documents(doc: Doc) -> list[tuple[str, str, date | None]]:
    """(url, title and annotation, published) of each document in a CUET
    search result about the property tax, drafts left out, newest first."""
    from bs4 import BeautifulSoup
    out = []
    for item in BeautifulSoup(doc.html, "lxml").select("div.resultItem"):
        a = item.find("a", href=re.compile(r"/dokument/"))
        if a is None:
            continue
        fields = {}
        for box in item.find_all("div", class_=re.compile(r"^item")):
            name = box.find("div", class_="metadataDocumentName")
            if name:
                key = name.get_text(" ", strip=True).rstrip(":")
                fields[key] = box.get_text(" ", strip=True)[len(name.get_text(" ", strip=True)):].strip()
        label = " — ".join(v for v in (fields.get("Názov dokumentu"),
                                        fields.get("Anotácia dokumentu")) if v)
        own = fold(label)
        if not _PROPERTY_TAX.search(own) or re.search(r"(?<![a-z])navrh", own):
            continue
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", fields.get("Zverejnené od", ""))
        published = None
        if m:
            try:
                published = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        out.append((urljoin(doc.url, a["href"]), label, published))
    out.sort(key=lambda t: t[2] or date.min, reverse=True)
    return out


def cuet_files(doc: Doc) -> list[str]:
    """The attached files of a CUET document page."""
    from bs4 import BeautifulSoup
    seen: list[str] = []
    for a in BeautifulSoup(doc.html, "lxml").find_all("a", href=re.compile(r"/priloha/zobraz/")):
        href = urljoin(doc.url, a["href"])
        if href not in seen:
            seen.append(href)
    return seen


# ── A town ────────────────────────────────────────────────────────────────────
@dataclass
class TownResult:
    town: str
    readings: list[Reading] = field(default_factory=list)
    current: Reading | None = None      # in force for the tax year asked for
    upcoming: Reading | None = None     # a later tax year's, already published
    conflict: list[Reading] = field(default_factory=list)   # same year, other rates
    unread_newer: list[str] = field(default_factory=list)   # newer, about flats, no rate read
    problems: list[str] = field(default_factory=list)       # what couldn't be read, and why
    blocked: str = ""                   # the start page itself was refused
    fetched: int = 0
    visited: list[tuple[str, str]] = field(default_factory=list)   # (url, what it gave)

    @property
    def found(self) -> bool:
        return self.current is not None or self.upcoming is not None


def pick(readings: list[Reading], year: int, today: int | None = None
         ) -> tuple[Reading | None, Reading | None, list[Reading]]:
    """(current, upcoming, conflicting) among a town's readings for tax year
    `year`. A web page or rate sheet with no year of its own is taken as this
    year's: a page kept up now states the rates now in force. An ordinance
    with no readable date is not — a repealed one stays on a site for years
    (Poprad's 2019 VZN, 0.35 €/m², beside the 1.00 in force) — so it counts
    only when nothing dated was read. The current one is the latest in force
    by `year`, a dated one before an undated one; the upcoming one is a dated
    reading for a later year."""
    today = today or date.today().year

    def yr(r: Reading) -> int:
        if r.tax_year is not None:
            return r.tax_year
        return today if r.kind in ("page", "sheet") else 0

    now = [r for r in readings if yr(r) <= year]
    later = [r for r in readings if r.dated and yr(r) > year]
    current = max(now, key=lambda r: (yr(r), r.dated), default=None)
    upcoming = max(later, key=yr, default=None)
    conflict = []
    if current:
        conflict = [r for r in now if yr(r) == yr(current) and r.dated == current.dated
                    and sorted(set(r.rates)) != sorted(set(current.rates))]
    return current, upcoming, conflict


def _from_cuet(town: Town, year: int, session, fetcher, res: TownResult, budget: int,
               delay: float) -> list[tuple[str, str]]:
    """(file url, label) of each file attached to `town`'s documents about
    local taxes on CUET, the newest document first. The search and the
    document pages count against `budget`, like any page read."""
    def get(url: str) -> Doc | None:
        if res.fetched >= budget:
            return None
        time.sleep(delay)
        res.fetched += 1
        try:
            doc = fetcher(url, session)
        except Exception as e:
            res.problems.append(f"CUET: {url}: {e}")
            res.visited.append((url, f"CUET failed: {e}"))
            return None
        return doc

    search = cuet_search_url(town.cuet, date(year - CUET_YEARS, 1, 1))
    found = get(search)
    if found is None:
        return []
    docs = cuet_documents(found)
    res.visited.append((search, f"CUET: {len(docs)} documents about local taxes"))
    out: list[tuple[str, str]] = []
    for url, label, _ in docs[:CUET_DOCUMENTS]:
        page = get(url)
        if page is None:
            continue
        files = cuet_files(page)
        res.visited.append((url, f"CUET: {len(files)} file(s) — {label[:80]}"))
        out += [(f, label) for f in files]
    return out


def check_town(town: Town, year: int, session=None, delay: float = 0.4,
               fetcher=None, budget: int = MAX_FETCHES, stop_when_found: bool = False
               ) -> TownResult:
    """Read `town`'s flat rate for tax year `year` from its own site, in at
    most `budget` pages and documents, the most promising link first (the
    property-tax ordinance, then a list of ordinances, then a generic page
    of documents). `stop_when_found`: stop at the first ordinance that
    dates a rate for `year` or later (a village's site, read once a month).
    When the town's own site refuses and the town publishes on CUET
    (Town.cuet), its documents about local taxes there are read instead."""
    import heapq
    fetcher = fetcher or fetch
    res = TownResult(town.name)
    queue: list[tuple[int, int, str, int, str]] = [(-10**9, i, u, 0, "")
                                                   for i, u in enumerate(town.start)]
    heapq.heapify(queue)
    order = len(queue)
    seen: set[str] = set()
    newer_mentions: list[tuple[int, str]] = []
    cuet_read = False
    while queue and res.fetched < budget:
        _, _, url, depth, label = heapq.heappop(queue)
        if url in seen:
            continue
        seen.add(url)
        if res.fetched:
            time.sleep(delay)
        res.fetched += 1
        try:
            doc = fetcher(url, session)
        except Blocked as b:
            if depth == 0:
                res.blocked = str(b)
            res.problems.append(f"{label or url}: {b}")
            res.visited.append((url, f"refused: {b}"))
            if depth == 0 and town.cuet and not cuet_read:
                cuet_read = True
                for href, lab in _from_cuet(town, year, session, fetcher, res, budget, delay):
                    order += 1
                    # The newest first; files only, so nothing is followed from them.
                    heapq.heappush(queue, (-10**8 + order, order, href, MAX_DEPTH + 1, lab))
            continue
        except Exception as e:                    # a broken link, a bad file
            log.warning(f"Tax rate {town.name}: {url} failed: {e}")
            res.problems.append(f"{label or url}: {type(e).__name__}: {e}")
            res.visited.append((url, f"failed: {type(e).__name__}"))
            continue
        if doc.problem:
            res.problems.append(f"{label or url}: {doc.problem}")
            res.visited.append((url, doc.problem))
            continue
        title = label or doc.title or url
        if doc.kind != "html" and is_draft(doc.text, label):
            res.visited.append((url, "a draft — skipped"))
            continue
        reading = read_text(doc.text, url=doc.url, title=title,
                            document=doc.kind != "html", areas=town.areas)
        if reading and reading.tax_year is None:
            # "Prehľad sadzieb dane z nehnuteľností v roku 2026": the year
            # is in the link, not the sheet.
            y = _YEAR_PHRASE.findall(_normalize(label)[0])
            if y:
                reading.tax_year, reading.dated = max(int(v) for v in y), True
        if reading:
            res.readings.append(reading)
            res.visited.append((url, f"{doc.kind}: flat rate {reading.rates}"
                                     f" for {reading.tax_year or 'an unstated year'}"))
            if stop_when_found and reading.dated and (reading.tax_year or 0) >= year:
                break
        else:
            res.visited.append((url, f"{doc.kind}: no flat rate"))
            if doc.kind != "html" and mentions_flat_tax(doc.text):
                f, _ = _normalize(doc.text)
                y = _tax_year(f, None, True)
                if y:
                    newer_mentions.append((y, title))
        about = depth > 0 and bool(_STRONG.search(fold(label + " " + url)))
        if doc.kind == "html" and (depth < MAX_DEPTH or about):
            site = _site(urlparse(doc.url).hostname or "")
            home = depth == 0 and urlparse(doc.url).path in ("", "/")
            for rank, href, lab in _links(doc, site, about_tax=about, home=home):
                # Past the last level, only an ordinance page's own files.
                if href not in seen and (depth < MAX_DEPTH or _FILE.search(fold(lab + " " + href))):
                    order += 1
                    heapq.heappush(queue, (-rank, order, href, depth + 1, lab))
    res.current, res.upcoming, res.conflict = pick(res.readings, year)
    base = res.current.tax_year if res.current and res.current.tax_year else None
    if base:
        res.unread_newer = [t for y, t in newer_mentions if y > base]
    return res


# ── Every Slovak municipality ─────────────────────────────────────────────────
WIKIDATA = "https://query.wikidata.org/sparql"
# Q6784672 "municipality of Slovakia": its Slovak name, okres and official
# website (P856), as Wikidata has them — 2,886 municipalities, 2,806 with a
# website, in November 2026.
_MUNICIPALITIES_QUERY = """
SELECT ?item ?name ?okres ?web ?pop WHERE {
  ?item wdt:P31 wd:Q6784672 .
  ?item rdfs:label ?name . FILTER(LANG(?name)="sk")
  OPTIONAL { ?item wdt:P856 ?web }
  OPTIONAL { ?item wdt:P131 ?o . ?o rdfs:label ?okres . FILTER(LANG(?okres)="sk") }
  OPTIONAL { ?item wdt:P1082 ?pop }
}"""


@dataclass
class Municipality:
    name: str
    okres: str                      # "Senec" (the district, without "okres")
    web: str
    population: int | None = None

    @property
    def key(self) -> str:
        """Its name, or name and district where several share the name."""
        return self.name


def municipalities(session=None) -> list[Municipality]:
    """Every Slovak municipality with its district and official website."""
    import requests
    s = session or requests.Session()
    r = s.get(WIKIDATA, params={"query": _MUNICIPALITIES_QUERY},
              headers={"Accept": "text/csv",
                       "User-Agent": "SovereignPropertyTax/1.0 (municipal tax rates)"},
              timeout=180)
    r.raise_for_status()
    import csv as _csv
    items: dict[str, dict] = {}
    for row in _csv.DictReader(io.StringIO(r.content.decode("utf-8"))):
        it = items.setdefault(row["item"], {"name": row["name"], "okres": set(), "web": [],
                                            "pop": row.get("pop")})
        if row.get("okres"):
            it["okres"].add(re.sub(r"^okres\s+", "", row["okres"]))
        if row.get("web") and row["web"] not in it["web"]:
            it["web"].append(row["web"])
    out = []
    for it in items.values():
        try:
            pop = int(float(it["pop"])) if it["pop"] else None
        except ValueError:
            pop = None
        out.append(Municipality(it["name"], ", ".join(sorted(it["okres"])),
                                (sorted(it["web"], key=lambda u: (not u.startswith("https"), len(u)))
                                 or [""])[0], pop))
    return out


def read_upload(name: str, content: bytes, town: Town | None = None,
                year: int | None = None) -> tuple[Reading | None, str]:
    """A document the user saved in the browser and uploaded: (reading, why
    not) — for a site that refuses automated requests."""
    doc = doc_from_bytes(name, content)
    if doc.problem:
        return None, doc.problem
    if is_draft(doc.text, name):
        return None, "this is a draft (návrh) of the ordinance, not the adopted text"
    r = read_text(doc.text, url=f"upload: {name}", title=name, document=doc.kind != "html",
                  areas=town.areas if town else ())
    if r is None:
        return None, "no flat rate (€ per m² for flats, 'za byty') found in it"
    return r, ""


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Read towns' flat rates from their sites.")
    ap.add_argument("towns", nargs="*", help="town names (default: all)")
    ap.add_argument("--year", type=int, default=date.today().year)
    ap.add_argument("-v", action="store_true", help="list every page and document read")
    args = ap.parse_args()
    import requests
    s = requests.Session()
    for name in args.towns or TOWNS:
        r = check_town(TOWNS[name], args.year, session=s)
        cur = r.current
        print(f"\n== {name}: fetched {r.fetched}"
              + (f" · BLOCKED: {r.blocked}" if r.blocked else ""))
        for rd in r.readings:
            print(f"   {rd.rates} year={rd.tax_year}{'' if rd.dated else '?'} {rd.title[:70]} | {rd.url}")
        print(f"   → current: {cur.rates if cur else None} ({cur.tax_year if cur else ''})"
              f"  upcoming: {r.upcoming.rates if r.upcoming else None}"
              f"  conflict: {[c.rates for c in r.conflict]}  unread newer: {r.unread_newer}")
        for p in r.problems[:6]:
            print(f"   ! {p[:160]}")
        if args.v:
            for u, what in r.visited:
                print(f"     · {what[:60]:60} {u[:140]}")
