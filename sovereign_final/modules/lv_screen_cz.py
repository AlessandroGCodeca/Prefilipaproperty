"""
modules/lv_screen_cz.py — the encumbrances in a Czech výpis z listu
vlastnictví (LV), read entry by entry with the Slovak screen's own logic
(modules/lv_screen.screen_lv) and the Czech register's words.

What counts, on diacritic-folded text with word stems (so "exekuce",
"exekuční příkaz", "exekutorské zástavní právo" are one stem):

  distress     exekuce · insolvence / úpadek / konkurs / majetková podstata /
               oddlužení · výkon rozhodnutí · soudní spor (poznámka spornosti
               zápisu, žaloba) · předběžné opatření / zákaz nakládání ·
               zajištění v trestním řízení · dražba · a judicial, enforcement
               or administrative zástavní právo — never cleared
  lien         zástavní právo · zajišťovací převod práva · zákaz zcizení nebo
               zatížení — cleared only when ITS OWN beneficiary ("Oprávnění
               pro" / "ve prospěch") is a bank
  encumbrance  věcné břemeno / služebnost — hard when it gives someone a
               lifetime right to use or live in the flat (doživotní užívání,
               bydlení, požívání, výměnek) or its kind can't be read, soft for
               lines, pipes and access · předkupní právo — soft when the state,
               a kraj or a municipality holds it, hard otherwise · doživotní
               užívání · výhrada zpětné koupě, výhrada vlastnického práva /
               práva lepšího kupce, koupě na zkoušku, nájem / pacht, užívací
               právo (hard) · poznámka and a plomba (a change of rights
               pending in the cadastre) — soft: shown, not rejected on their own

An entry of parts C–D (its "o <Typ>" bullet) that none of these names is a
kind of burden the screen does not know: modules/lv_cz never calls such a
title clean (unrecognised_entries). A lien phrase is a back-reference to the
lien before it only on the same line as "Smlouva …" / "Listina …" and
within the same entry (no register number or bullet between).

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
import unicodedata

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules.lv_screen import Vocabulary, fold, screen_lv


def _bank_names() -> tuple:
    import markets
    return markets.CZ.lv_bank_names


_RULES = (
    ("exekuce",            "distress",    r"exeku"),
    ("insolvence",         "distress",
     r"insolven|(?<!\w)upad(?:ek|ku|kem)(?!\w)|(?<!\w)konkurs|"
     r"majetkov\w*\s+podstat\w*|(?<!\w)oddluzen\w*"),
    ("výkon rozhodnutí",   "distress",    r"vykon\w*\s+rozhodnut\w*"),
    ("soudní spor",        "distress",    r"spornost\w*|(?<!\w)zalob\w*|soudn\w*\s+spor\w*"),
    # A court's ban on disposing of it, a seizure in criminal proceedings, an
    # auction: a sale may be void, or the flat may go to someone else.
    ("předběžné opatření", "distress",
     r"predbezn\w*\s+opatren\w*|zakaz\w*\s+naklad\w*"),
    ("zajištění v trestním řízení", "distress",
     r"zajisten\w*\s+(?:nemovit\w*|majetk\w*)|trestn\w*\s+rizen\w*"),
    ("dražba",             "distress",    r"(?<!\w)drazb\w*|(?<!\w)drazebn\w*"),
    ("zástavní právo z rozhodnutí", "distress",
     r"zastavn\w*\s+prav\w*\s+(?:soudcovsk|z\s+rozhodnut)|soudcovsk\w*\s+zastavn"),
    ("věcné břemeno",      "encumbrance", r"vecn\w*\s+bremen\w*|(?<!\w)sluzebnost\w*"),
    ("předkupní právo",    "encumbrance", r"predkupn\w*\s+prav\w*"),
    ("doživotní užívání",  "encumbrance",
     r"(?<!bremeno )(?<!bremeno - )(?<!sluzebnost )(?<!bremene )"
     r"dozivotn\w*\s+(?:uzivan|bydlen|pozivan|prav)\w*|(?<!\w)vymen(?:ek|ku|kem)(?!\w)"),
    ("výhrada zpětné koupě", "encumbrance", r"vyhrad\w*\s+zpetn\w*\s+(?:koup|prodej)\w*"),
    ("výhrada vlastnického práva", "encumbrance",
     r"vyhrad\w*\s+(?:vlastnick\w*\s+prav\w*|prav\w*\s+lepsi\w*\s+kupce)"),
    ("koupě na zkoušku",   "encumbrance", r"koup\w*\s+na\s+zkousk\w*"),
    ("nájem",              "encumbrance", r"(?<!\w)naj(?:em|m)\w*|(?<!\w)pacht\w*"),
    ("užívací právo",      "encumbrance", r"uzivac\w*\s+prav\w*"),
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
# A lien phrase after one of these words ON THE SAME LINE, with no entry
# bullet ("o ") between, only refers back ("Listina Smlouva o zřízení
# zástavního práva"). Each entry ends with its "Listina …" line, so a word on
# an earlier line must not make the next entry's lien a reference.
_REFERENCE_BEFORE = re.compile(
    r"(?:smlouv|zrizen|zanik|vymaz|zrus|listin)[^\n•]*(?:\n[^\S\n]*)?$")
# A non-bank company of a banking group (leasing, insurance, car finance,
# factoring, an investment firm) or a credit union is no bank, whatever its
# name shares with one.
_NON_BANK = (r"leasing|pojistovn|(?<!\w)auto(?!\w)|fa[ck]toring|invest(?!ic)|"
             r"druzstv|(?<!\w)zalozn")
# "banka" / "spořitelna" in the name, any case form, or a whole name on the
# list (markets.CZ.lv_bank_names — names without either word: ČSOB,
# Raiffeisenbank, UniCredit, MONETA, mBank, the state housing funds, …).
_BANK_RE = re.compile(
    rf"^(?!.*(?:{_NON_BANK})).*?(?:"
    r"(?<!\w)bank(?:a|y|u|ou)?(?!\w)|(?<!\w)bance(?!\w)|sporiteln|"
    + "|".join(rf"(?<!\w){re.escape(fold(b))}(?!\w)" for b in _bank_names())
    + ")", re.S)
# A Czech creditor's name keeps its dashes ("Wüstenrot - stavební spořitelna",
# "Raiffeisen - Leasing"); its address follows a comma, and it never runs on
# to the next line, the entry's "Listina" or the next entry's bullet.
_NAME_END = re.compile(
    r"[,;(\n\v\u2028•]|(?<!\w)listin\w*|(?<!\w)ico(?!\w)|(?<!\w)rc(?!\w)|(?<!\w)nar\.|(?<!\w)povinnost|"
    r"(?<=\w{3})(?<!ing)(?<!mgr)(?<!dr)\.(?:\s|$)|"
    r"(?<!\w)na\s+(?:byt|jednotk|nebyt|nemovit|parc|pozem|stavb|podil)"
)

# "Služebnost bytu" / "Věcné břemeno bytu" is a right to live in it. The
# generic type "Věcné břemeno užívání" is not on its own: its entry says what
# is used (a flat — "užívání bytu" — or a strip of land for a cable).
_PERSONAL_USE_RE = re.compile(
    r"doziv|bydlen|(?<!\w)pozivan|(?<!\w)vymen(?:ek|ku|kem)(?!\w)|"
    r"uzivan\w*\s+(?:bytu|byt|jednotk|nemovit|stavb|domu|mistnost)|"
    r"(?:sluzebnost|bremen)\w*\s+bytu")
_TECHNICAL_RE = re.compile(
    r"inzenyr|(?<!\w)sit(?:e|i|emi)?(?!\w)|vedeni|elektr|plyn|vodovod|vodn\w*\s+dil|"
    r"kanaliz|rozvod|energet|distribuc|telekom|trafostanic|teplovod|potrub|pripojk|"
    r"kabel|ochrann\w*\s+pasm|chuze|jizd|pruchod|prujezd|pristup|(?<!\w)cest[aiyu]?(?!\w)|udrzb")
# The state, a kraj, a municipality — not a company that shares a word with
# one ("Krajská nemocnice, a.s." is a company).
_PUBLIC_HOLDER_RE = re.compile(
    r"(?<!\w)(?:obec|obce|obci|mesto|mesta|mestsk\w*\s+cast\w*|cesk\w*\s+republik\w*|"
    r"stat|statn\w*|kraj|kraje|hlavn\w*\s+mest\w*|statutarn\w*\s+mest\w*)(?!\w)")


# The holder's block ("Oprávnění pro Kabelková Marie, Plynární 12, …") up to
# "Povinnost k": a surname or a street is no utility line.
_HOLDER_BLOCK_RE = re.compile(
    r"(?:opravnen\w*\s+pro|ve\s+prospech\w*)[\s\S]*?(?=(?<!\w)povinnost\w*\s+k(?!\w)|$)")
_HOLDER_MARKER_RE = re.compile(r"(?:opravnen\w*\s+pro|ve\s+prospech\w*)\s*:?\s*")
# A company's legal form, in its name ("Testovací teplárna a.s.") or right
# after it (", a. s.", ", s.r.o.", ", spol. s r.o.") — folded text.
_COMPANY_FORM_RE = re.compile(r"(?<!\w)(?:a\.\s*s\.|s\.\s*r\.\s*o\.|spol\.\s*s\s*r\.\s*o\.)")


def _holder_evidence(block) -> str:
    """What of a holder's block may say what an easement is for: the name of a
    company ("ČEZ Distribuce, a. s." — a distribution company's easement is a
    line or a pipe, whatever the deed calls it), never a person's name nor
    anyone's address."""
    rest = block.group()[_HOLDER_MARKER_RE.match(block.group()).end():]
    cut = _NAME_END.search(rest)
    name = rest[:cut.start()] if cut else rest
    form = _COMPANY_FORM_RE.search(name)
    if form:                    # "… a.s. Plynární 5": the street is not the name
        return f" {name[:form.end()]} "
    if _COMPANY_FORM_RE.match(rest[len(name):].lstrip(" \t,")):
        return f" {name} "
    return " "


def _tier(label: str, entry_text: str, holder: str) -> tuple[str, str]:
    """("hard" | "soft", why) for an encumbrance, from its own entry's text
    (folded) and its holder's name."""
    if label == "věcné břemeno":
        if _PERSONAL_USE_RE.search(entry_text):
            return "hard", "lifetime right to use or live in it"
        if _TECHNICAL_RE.search(_HOLDER_BLOCK_RE.sub(_holder_evidence, entry_text)):
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


# Where one entry ends and the next starts: its register number ("V-1234/2020-101",
# "Z-1234567/2024-101", the older "POLVZ:12/1996" and "PV-12/1998"), or the
# bullet that opens each entry of parts C and D (read as "•", see _norm).
_ENTRY_NO_CZ_RE = re.compile(
    r"(?<!\w)(?:[vz]\d?\s*-?\s*\d{1,8}/\d{2,4}|polvz\s*:?\s*\d{1,8}/\d{2,4}|"
    r"pv\s*-?\s*\d{1,8}/\d{2,4})|•")

VOCABULARY = Vocabulary(
    rules=tuple((label, kind, re.compile(pat)) for label, kind, pat in _RULES),
    creditor_markers=_CREDITOR_MARKERS, holder_markers=_CREDITOR_MARKERS[:2],
    reference_before=_REFERENCE_BEFORE, bank_re=_BANK_RE, name_end=_NAME_END,
    tier=_tier, entry_no_re=_ENTRY_NO_CZ_RE, distress_lien_prefix="exeku",
    reference_needs_same_entry=True,
)
_PLOMBA_ONLY = Vocabulary(
    rules=tuple((label, kind, re.compile(pat)) for label, kind, pat in _RULES
                if label == "plomba"),
    creditor_markers=_CREDITOR_MARKERS, holder_markers=_CREDITOR_MARKERS[:2],
    reference_before=_REFERENCE_BEFORE, bank_re=_BANK_RE, name_end=_NAME_END,
    tier=_tier, entry_no_re=_ENTRY_NO_CZ_RE, distress_lien_prefix="exeku",
    reference_needs_same_entry=True,
)

# Part headings, folded: "C Věcná práva zatěžující nemovitosti v části B
# včetně souvisejících údajů" (and the older "C Omezení vlastnického práva"),
# "D Poznámky a další obdobné údaje" (older "D Jiné zápisy"), "E Nabývací
# tituly a jiné podklady zápisu". The C heading is matched word by word, never
# "to the end of the line": a výpis pasted as one line keeps its entries.
_PART_C_RE = re.compile(
    r"(?<!\w)c\s*[-–:.]?\s*(?:omezeni\s+vlastnick\w*\s+prav\w*|"
    r"vecn\w*\s+prav\w*\s+zatezujic\w*(?:\s+nemovitost\w*)?(?:\s+v\s+cast\w*\s+b)?"
    r"(?:\s+vcetne\s+souvisejic\w*\s+udaj\w*)?)")
_PART_D_RE = re.compile(
    r"(?<!\w)d\s*[-–:.]?\s*(?:poznamk\w*\s+a\s+dals\w*\s+obdobn\w*\s+udaj\w*|jine\s+zapis\w*)")
_PART_E_RE = re.compile(r"(?<!\w)e\s*[-–:.]?\s*nabyvac\w*\s+titul\w*")


# An entry's bullet: "o" (or "◦", "▪", "●") before the capitalised type —
# "o Zástavní právo smluvní". At a line's start, or after a space when the
# výpis was pasted as one line; "smlouva o zřízení" (lower case) is no bullet.
_BULLET_IN_RE = re.compile(
    r"(?:(?<=\s)|^)[o◦▪●•](?=[ \t]+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])", re.M)


def _norm(lv_text) -> str:
    """The text the screen reads: accents composed (NFC) and any stray
    combining mark dropped — a výpis copied from a PDF may carry "a" + "́"
    for "á", which the stems would not match — and each entry's bullet
    written "•"."""
    text = unicodedata.normalize("NFC", str(lv_text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return _BULLET_IN_RE.sub("•", text)


_AS_OF_RE = re.compile(r"stav\w*\s+evidovan\w*\s+k\s+datu\s*:?\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")


def vypis_date(lv_text):
    """The date whose register state a výpis certifies ("prokazující stav
    evidovaný k datu 15.10.2026 08:00:00"), or None."""
    from datetime import date
    m = _AS_OF_RE.search(fold(_norm(lv_text)))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def parts_c_d_whole(lv_text) -> bool:
    """True when the text runs from part C's heading on to part E's — a
    whole výpis prints "E Nabývací tituly…" even when C and D are "Bez
    zápisu"; page 1 of 2 stops before it."""
    low = fold(_norm(lv_text))
    c = _PART_C_RE.search(low)
    return bool(c and _PART_E_RE.search(low, c.end()))


def part_c_start(lv_text) -> int | None:
    """Index of part C's heading (in the NFC text), or None when there is
    none to recognise."""
    m = _PART_C_RE.search(fold(_norm(lv_text)))
    return m.start() if m else None


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _parts(text: str, low: str):
    """(region, c, e): the text with everything outside parts C–D blanked
    (and D's own heading) — or the whole text when there is no C heading, or
    nothing between it and E — with the C and E heading matches."""
    c = _PART_C_RE.search(low)
    if not c:
        return text, None, None
    e = _PART_E_RE.search(low, c.end())
    end = e.start() if e else len(text)
    region = _blank(_blank(text, end, len(text)), 0, c.end())
    d = _PART_D_RE.search(low, c.end(), end)
    if d:
        region = _blank(region, d.start(), d.end())
    if not region.strip():
        return text, c, e                 # nothing read between the headings
    return region, c, e


def screen_lv_cz(lv_text) -> list[dict]:
    """Every encumbrance in a Czech LV text, in document order — entries
    shaped as modules/lv_screen.screen_lv's."""
    text = _norm(lv_text)
    region, c, e = _parts(text, fold(text))
    entries = screen_lv(region, VOCABULARY)
    if c and region is not text:
        # A plomba may be printed outside parts C–D.
        outside = _blank(text, c.end(), e.start() if e else len(text))
        entries += screen_lv(outside, _PLOMBA_ONLY)
    return entries


_BULLET_RE = re.compile(r"•[ \t]*([^\s•][^\n•]*)")
_RULE_RES = tuple(rx for _, _, rx in VOCABULARY.rules)
# For finding entries only (the screen keeps _norm's bullets): a bullet in
# capitals ("O NAŘÍZENÍ …" — only at a line's start, so the "O" of "POZNÁMKA
# O UZAVŘENÍ SMLOUVY" is no bullet), copied as "○", followed by a
# non-breaking space, or left on a line of its own by a PDF copy.
_CAPS_BULLET_RE = re.compile(
    r"^([ \t\u00a0]*)O(?=(?:[ \t\u00a0]+|[ \t\u00a0]*\n[ \t\u00a0]*)[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])", re.M)
_BULLET_LOOSE_RE = re.compile(
    r"(?:(?<=\s)|^)[o◦○▪●•](?:[ \t\u00a0]+|[ \t\u00a0]*\n[ \t\u00a0]*)"
    r"(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ])", re.M)
# A line that only goes on with the entry before it: its holder, what it
# burdens, its deed ("Listina …") — after a register number the entry cited
# ("… dle V-3333/2026-101") or a deed of its own.
_CONTINUATION_RE = re.compile(
    r"\W*(?:povinnost\w*\s+k(?!\w)|opravnen\w*\s+pro|ve\s+prospech|listin)")
_NOT_A_TYPE_LINE_RE = re.compile(r"\W*(?:typ\s+vztahu|poradi)")


def _first_line(seg: str) -> str:
    """The first line of a (folded) segment that could name an entry: two
    letters or more, not the "Typ vztahu" header nor a "Pořadí k …" stamp."""
    return next((ln for ln in seg.splitlines()
                 if len(re.findall(r"[^\W\d_]", ln)) >= 2
                 and not _NOT_A_TYPE_LINE_RE.match(ln)), "")


def unrecognised_entries(lv_text) -> list[str]:
    """The entries of parts C–D ("o <Typ>" bullets) that no rule above names —
    a kind of burden this screen does not know, so it cannot call the title
    clean. Empty when the text has no recognisable part C."""
    text = _BULLET_LOOSE_RE.sub("•", _CAPS_BULLET_RE.sub(r"\1o", _norm(lv_text)))
    low = fold(text)
    region, c, _ = _parts(text, low)
    if not c:
        return []
    out = []
    flow = fold(region)
    for m in _BULLET_RE.finditer(flow):
        if not any(rx.search(m.group(1)) for rx in _RULE_RES):
            out.append(re.sub(r"\s+", " ", text[m.start(1):m.end(1)]).strip()[:80])
    # A bullet copied as another glyph, lost, or in capitals hides the entry
    # from the pass above: read every entry body ("Oprávnění pro" /
    # "Povinnost k") between register numbers and bullets too. A segment
    # after a register number that only goes on with the entry before it
    # (its "Povinnost k", another "Listina") is read as part of that entry.
    seps = sorted([(m.start(), m.end(), m.group() != "•")
                   for m in _ENTRY_NO_CZ_RE.finditer(flow)]
                  + [(m.start(), m.end(), False) for m in _PART_D_RE.finditer(low)])
    spans, pos, after_number = [], 0, False
    for s, e, number in seps + [(len(flow), len(flow), False)]:
        if spans and after_number and _CONTINUATION_RE.match(_first_line(flow[pos:s])):
            spans[-1][1] = s
        else:
            spans.append([pos, s])
        pos, after_number = e, number
    for start, end in spans:
        seg = flow[start:end]
        if not _ENTRY_BODY_RE.search(seg) or any(rx.search(seg) for rx in _RULE_RES):
            continue
        names = (re.sub(r"\s+", " ", re.sub(r"^\W*(?:[oO](?=\W|$))?\W*", "", ln)).strip()
                 for ln in region[start:end].splitlines()
                 if not re.match(r"\W*(?:typ\s+vztahu|poradi)", fold(ln)))
        name = next((n for n in names if len(re.findall(r"[^\W\d_]", n)) >= 2), "")[:80]
        if name and name not in out:
            out.append(name)
    return out


_ENTRY_BODY_RE = re.compile(r"opravnen\w*\s+pro|(?<!\w)povinnost\w*\s+k(?!\w)")


# Part A, the owners: "A Vlastník, jiný oprávněný" up to "B Nemovitosti".
_PART_A_RE = re.compile(r"(?<!\w)a\s*[-–:.]?\s*vlastnik\w*")
_PART_B_RE = re.compile(r"(?<!\w)b\s*[-–:.]?\s*nemovitost\w*")


def owner_is_cooperative(lv_text) -> bool:
    """True when part A names a cooperative (družstvo) as the owner — a
    cooperative flat, whatever its listing says."""
    low = fold(_norm(lv_text))
    a = _PART_A_RE.search(low)
    if not a:
        return False
    b = _PART_B_RE.search(low, a.end())
    # "Bytové družstvo Testov" — not the owner's street "U Družstva Ideál".
    return bool(re.search(r"(?<!\w)druzstvo(?!\w)",
                          low[a.end():b.start() if b else a.end() + 600]))


_LV_NO_RE = re.compile(r"list\w*\s+vlastnictvi\s*(?:c\.|cislo|:)?\s*:?\s*(\d{1,6})")
_UNIT_RE = re.compile(r"jednotk\w*\s*:?\s*(?:c\.|cislo)?\s*:?\s*(\d{1,5}/\d{1,5})")
# "Katastrální území: 727440 Žižkov" (or "Kat.území:"), the name running to a
# wide gap, the "List vlastnictví" beside it, or the line's end.
_KU_RE = re.compile(
    r"kat(?:astraln\w*)?\.?\s*uzemi\s*:?[ \t]*(\d{6})?[ \t]*(?:[-–,][ \t]*)?"
    r"([^\W\d][^\n]*?)?(?=[ \t]{2,}|[ \t]*list\w*\s+vlastnictvi|[ \t]*\n|[ \t]*$)")
_PART_B1_RE = re.compile(r"(?<!\w)b1(?!\w)")
# Part B as a table: a "Jednotky" heading or its "Č.p./Č.jednotky" ("Číslo
# jednotky") column, then a row per unit — its number and its use ("1567/12
# byt  6543/123456"). A share alone on its line ("6543/123456") is no row.
_UNIT_TABLE_RE = re.compile(
    r"(?<!\w)(?:c\.?\s*|cislo\s+)jednotk\w*|^[ \t]*jednotky[ \t]*$", re.M)
_UNIT_ROW_RE = re.compile(r"^[ \t]*(\d{1,5}/\d{1,5})(?=[ \t]+[^\W\d_])", re.M)


def lv_number_in(lv_text) -> str | None:
    """The LV number a výpis states ("LIST VLASTNICTVÍ: 1234"), or None."""
    m = _LV_NO_RE.search(fold(_norm(lv_text)))
    return m.group(1) if m else None


def ku_in(lv_text) -> tuple[str, str] | None:
    """(code, name) of the katastrální území a výpis names — either may be
    "" — or None when it names none."""
    # Every space but a line break read as a plain one (a non-breaking space
    # copied from a web page or a PDF), one for one.
    low = re.sub(r"[^\S\n]", " ", fold(_norm(lv_text)))
    for m in _KU_RE.finditer(low):
        # "V kat. území jsou pozemky vedeny v jedné číselné řadě" is the
        # standard line under the header, not a k.ú.
        if re.search(r"(?<!\w)v $", low[max(0, m.start() - 2):m.start()]):
            continue
        if not (m.group(1) or m.group(2)):
            return None
        return m.group(1) or "", (m.group(2) or "").strip()
    return None


def unit_numbers(lv_text) -> set:
    """The units ("Jednotka č. 101/5", or a row of the "Jednotky" table) part
    B of a výpis lists — the whole text when it has no part B heading. More
    than one means its encumbrances may be another unit's. A unit named in
    B1, C or E (an easement's beneficiary, a declaration's range) is not one
    of the LV's."""
    low = fold(_norm(lv_text))
    b = _PART_B_RE.search(low)
    if b:
        ends = [m.start() for m in (_PART_B1_RE.search(low, b.end()),
                                    _PART_C_RE.search(low, b.end())) if m]
        low = low[b.start():min(ends) if ends else len(low)]
    units = set(_UNIT_RE.findall(low))
    table = _UNIT_TABLE_RE.search(low)
    if table:
        units |= set(_UNIT_ROW_RE.findall(low, table.end()))
    return units
