"""
modules/lv_screen_cz.py — the encumbrances in a Czech výpis z listu
vlastnictví (LV), read entry by entry with the Slovak screen's own logic
(modules/lv_screen.screen_lv) and the Czech register's words.

What counts, on diacritic-folded text with word stems (so "exekuce",
"exekuční příkaz", "exekutorské zástavní právo" are one stem):

  distress     exekuce · insolvence / úpadek / konkurs · výkon rozhodnutí ·
               soudní spor (poznámka spornosti zápisu, žaloba) · a judicial,
               enforcement or administrative zástavní právo — never cleared
  lien         zástavní právo · zajišťovací převod práva · zákaz zcizení nebo
               zatížení — cleared only when ITS OWN beneficiary ("Oprávnění
               pro" / "ve prospěch") is a bank
  encumbrance  věcné břemeno / služebnost — hard when it gives someone a
               lifetime right to use or live in the flat (doživotní užívání,
               bydlení, požívání, výměnek) or its kind can't be read, soft for
               lines, pipes and access · předkupní právo — soft when the state,
               a kraj or a municipality holds it, hard otherwise · doživotní
               užívání · výhrada zpětné koupě (hard) · poznámka and a plomba
               (a change of rights pending in the cadastre) — soft: shown, not
               rejected on their own

A Czech LV is laid out in parts: A owners, B the property, B1 rights the
property ENJOYS over others (an easement there benefits this flat), C the
rights that burden it, D notes, E acquisition titles, F soil classes. Only C
and D can block, so when the text has recognisable part headings the screen
reads from C's heading to E's (a plomba is looked for everywhere). The
headings and the "Oprávnění pro" / "Povinnost k" wording follow the výpis
layout as published since 2014; no live výpis could be checked while writing
this (UNVERIFIED), so without a recognisable heading the whole text is read —
the conservative way.

A synthetic example, the shape the tests use:

  C Věcná práva zatěžující nemovitosti v části B včetně souvisejících údajů
  Typ vztahu
  o Zástavní právo smluvní
      k zajištění pohledávky ve výši 2 400 000 Kč
      Oprávnění pro Komerční banka, a.s., Na Příkopě 33, Praha 1, RČ/IČO: 00000000
      Povinnost k Jednotka: č. 101/5
      Listina Smlouva o zřízení zástavního práva ... V-1234/2020-101
"""

from __future__ import annotations

import re

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules.lv_screen import Vocabulary, fold, screen_lv, _ENTRY_NO_RE


def _bank_names() -> tuple:
    import markets
    return markets.CZ.lv_bank_names


_RULES = (
    ("exekuce",            "distress",    r"exeku"),
    ("insolvence",         "distress",    r"insolven|(?<!\w)upad(?:ek|ku|kem)(?!\w)|(?<!\w)konkurs"),
    ("výkon rozhodnutí",   "distress",    r"vykon\w*\s+rozhodnut\w*"),
    ("soudní spor",        "distress",    r"spornost\w*|(?<!\w)zalob\w*|soudn\w*\s+spor\w*"),
    ("zástavní právo z rozhodnutí", "distress",
     r"zastavn\w*\s+prav\w*\s+(?:soudcovsk|z\s+rozhodnut)|soudcovsk\w*\s+zastavn"),
    ("věcné břemeno",      "encumbrance", r"vecn\w*\s+bremen\w*|(?<!\w)sluzebnost\w*"),
    ("předkupní právo",    "encumbrance", r"predkupn\w*\s+prav\w*"),
    ("doživotní užívání",  "encumbrance",
     r"(?<!bremeno )(?<!bremeno - )(?<!sluzebnost )(?<!bremene )"
     r"dozivotn\w*\s+(?:uzivan|bydlen|pozivan|prav)\w*|(?<!\w)vymen(?:ek|ku|kem)(?!\w)"),
    ("výhrada zpětné koupě", "encumbrance", r"vyhrad\w*\s+zpetn\w*\s+(?:koup|prodej)\w*"),
    ("poznámka",           "encumbrance", r"(?<!\w)poznamk\w*"),
    ("plomba",             "encumbrance", r"(?<!\w)plomb\w*|dotcen\w*\s+zmenou\s+prav\w*"),
    ("zajišťovací převod práva", "lien", r"zajistovac\w*\s+prevod\w*\s+prav\w*"),
    ("zákaz zcizení",      "lien",        r"zakaz\w*\s+(?:zciz|zatiz)\w*"),
    ("zástavní právo",     "lien",        r"zastavn\w*\s+prav\w*"),
)

_CREDITOR_MARKERS = (
    re.compile(r"opravnen\w*\s+pro\s*:?\s*"),
    re.compile(r"ve\s+prospech\w*\s*:?\s*"),
    re.compile(r"(?<!\w)veritel\w*\s*:?\s*"),
    re.compile(r"(?<!\w)pro\s+"),
)
_REFERENCE_BEFORE = re.compile(r"smlouv|zrizen|zanik|vymaz|zrus|listin")
# "banka" / "spořitelna" in the name, any case form, or a name on the list
# (markets.CZ.lv_bank_names — names without either word: ČSOB, Raiffeisen,
# UniCredit, MONETA, mBank, the state housing funds, …).
_BANK_RE = re.compile(
    r"(?<!\w)bank(?:a|y|u|ou)?(?!\w)|(?<!\w)bance(?!\w)|sporiteln|"
    + "|".join(re.escape(fold(b)) for b in _bank_names())
)
_NAME_END = re.compile(
    r"[,;(]|\s[-–]\s|(?<!\w)ico(?!\w)|(?<!\w)rc(?!\w)|(?<!\w)nar\.|(?<!\w)povinnost|"
    r"(?<=\w{3})(?<!ing)(?<!mgr)(?<!dr)\.(?:\s|$)|"
    r"(?<!\w)na\s+(?:byt|jednotk|nebyt|nemovit|parc|pozem|stavb|podil)"
)

_PERSONAL_USE_RE = re.compile(
    r"doziv|bydlen|(?<!\w)pozivan|(?<!\w)vymen(?:ek|ku|kem)(?!\w)|"
    r"uzivan\w*\s+(?:bytu|byt|jednotk|nemovit|stavb|domu|mistnost)")
_TECHNICAL_RE = re.compile(
    r"inzenyr|(?<!\w)sit(?:e|i|emi)?(?!\w)|vedeni|elektr|plyn|vodovod|vodn\w*\s+dil|"
    r"kanaliz|rozvod|energet|distribuc|telekom|trafostanic|teplovod|potrub|pripojk|"
    r"kabel|ochrann\w*\s+pasm|chuze|jizd|pruchod|prujezd|pristup|(?<!\w)cest[aiyu]?(?!\w)|udrzb")
_PUBLIC_HOLDER_RE = re.compile(
    r"(?<!\w)(?:obec|obce|obci|mesto|mesta|mestsk\w*\s+cast\w*|cesk\w*\s+republik\w*|"
    r"stat|statn\w*|kraj|kraje|krajsk\w*|hlavn\w*\s+mest\w*|statutarn\w*\s+mest\w*)(?!\w)")


def _tier(label: str, entry_text: str, holder: str) -> tuple[str, str]:
    """("hard" | "soft", why) for an encumbrance, from its own entry's text
    (folded) and its holder's name."""
    if label == "věcné břemeno":
        if _PERSONAL_USE_RE.search(entry_text):
            return "hard", "lifetime right to use or live in it"
        if _TECHNICAL_RE.search(entry_text):
            return "soft", "utility / access easement"
        return "hard", "kind of easement not recognised"
    if label == "předkupní právo":
        if _PUBLIC_HOLDER_RE.search(fold(holder)):
            return "soft", "pre-emption right of the state, a kraj or a municipality"
        return "hard", "pre-emption right of a person or company"
    if label == "poznámka":
        return "soft", "a note on the LV — read what it says"
    if label == "plomba":
        return "soft", "a change of rights is pending in the cadastre"
    if label == "doživotní užívání":
        return "hard", "lifetime right to use or live in it"
    return "hard", label


VOCABULARY = Vocabulary(
    rules=tuple((label, kind, re.compile(pat)) for label, kind, pat in _RULES),
    creditor_markers=_CREDITOR_MARKERS, holder_markers=_CREDITOR_MARKERS[:2],
    reference_before=_REFERENCE_BEFORE, bank_re=_BANK_RE, name_end=_NAME_END,
    tier=_tier, entry_no_re=_ENTRY_NO_RE, distress_lien_prefix="exeku",
)
_PLOMBA_ONLY = Vocabulary(
    rules=tuple((label, kind, re.compile(pat)) for label, kind, pat in _RULES
                if label == "plomba"),
    creditor_markers=_CREDITOR_MARKERS, holder_markers=_CREDITOR_MARKERS[:2],
    reference_before=_REFERENCE_BEFORE, bank_re=_BANK_RE, name_end=_NAME_END,
    tier=_tier, entry_no_re=_ENTRY_NO_RE, distress_lien_prefix="exeku",
)

# Part headings, folded: "C Věcná práva zatěžující nemovitosti …" (and the
# older "C Omezení vlastnického práva"), "D Poznámky a další obdobné údaje"
# (older "D Jiné zápisy"), "E Nabývací tituly a jiné podklady zápisu".
_PART_C_RE = re.compile(
    r"(?<!\w)c\s*[-–:.]?\s*(?:omezeni\s+vlastnick\w*\s+prav\w*|"
    r"vecn\w*\s+prav\w*\s+zatezujic\w*[^\n]*)")
_PART_D_RE = re.compile(
    r"(?<!\w)d\s*[-–:.]?\s*(?:poznamk\w*\s+a\s+dals\w*\s+obdobn\w*\s+udaj\w*|jine\s+zapis\w*)")
_PART_E_RE = re.compile(r"(?<!\w)e\s*[-–:.]?\s*nabyvac\w*\s+titul\w*")


def part_c_start(lv_text) -> int | None:
    """Index of part C's heading, or None when there is none to recognise."""
    m = _PART_C_RE.search(fold(str(lv_text or "")))
    return m.start() if m else None


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def screen_lv_cz(lv_text) -> list[dict]:
    """Every encumbrance in a Czech LV text, in document order — entries
    shaped as modules/lv_screen.screen_lv's."""
    text = str(lv_text or "")
    low = fold(text)
    region = text
    c = _PART_C_RE.search(low)
    if c:
        e = _PART_E_RE.search(low, c.end())
        end = e.start() if e else len(text)
        region = _blank(_blank(region, end, len(text)), 0, c.end())
        d = _PART_D_RE.search(low, c.end(), end)
        if d:
            region = _blank(region, d.start(), d.end())
    entries = screen_lv(region, VOCABULARY)
    if c:
        # A plomba may be printed outside parts C–D.
        outside = _blank(text, c.end(), e.start() if e else len(text))
        entries += screen_lv(outside, _PLOMBA_ONLY)
    return entries


_LV_NO_RE = re.compile(r"list\w*\s+vlastnictvi\s*(?:c\.|cislo|:)?\s*:?\s*(\d{1,6})")
_UNIT_RE = re.compile(r"jednotk\w*\s*:?\s*(?:c\.|cislo)?\s*:?\s*(\d{1,5}/\d{1,5})")


def lv_number_in(lv_text) -> str | None:
    """The LV number a výpis states ("LIST VLASTNICTVÍ: 1234"), or None."""
    m = _LV_NO_RE.search(fold(str(lv_text or "")))
    return m.group(1) if m else None


def unit_numbers(lv_text) -> set:
    """The units ("Jednotka č. 101/5") a výpis lists. More than one means its
    encumbrances may be another unit's."""
    return set(_UNIT_RE.findall(fold(str(lv_text or ""))))
