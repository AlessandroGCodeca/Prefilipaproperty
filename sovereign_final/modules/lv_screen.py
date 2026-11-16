"""
modules/lv_screen.py — find the encumbrances in an LV (list vlastníctva) text.

The old screen asked two document-wide questions: does any reject keyword
appear, and does any bank name appear. A bank name anywhere then cleared every
keyword, so a private lien next to a bank mortgage passed, an exekúcia next to
a bank mortgage passed, and inflected forms ("začatie exekúcie", "exekučný
príkaz", "záložným právom") were never seen at all.

This screen reads each encumbrance on its own:

  - Matching runs on diacritic-folded, lower-cased text with Slovak word stems,
    so every case form of a term is caught ("exekúcia", "exekúcie",
    "exekučný", "Exekucia" typed without diacritics, …).
  - A lien (záložné právo) is cleared only by ITS OWN creditor — the name after
    "v prospech" (or "oprávnený" / "veriteľ" / "pre") in the same entry. A bank
    named in some other entry clears nothing.
  - Distress entries (exekúcia, konkurz, súdny spor / žaloba, výkon záložného
    práva, dražba, predbežné opatrenie, zaistenie) are never cleared by
    anything, whoever the creditor is.
  - Easements and pre-emption rights are tiered. A lifetime right to use or
    live in the flat, a pre-emption right held by a person or a company, and
    any easement whose kind can't be read are hard stops. A technical easement
    (utility lines, access, right of way) and a pre-emption right held by the
    state or a municipality are soft flags: recorded and shown, not rejected
    — unless config.LV_SOFT_FLAGS_REJECT says otherwise. Which is which is a
    judgement call for you or your lawyer.

The text is the plain text of the portal's LV report (kataster_scraper
fetch_lv_text). Its entry layout could not be checked against live reports
while writing this, so the rules lean conservative: a lien whose creditor
cannot be read counts as blocking.
"""

import re
import unicodedata
from dataclasses import dataclass

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import LV_BANK_NAMES, LV_SOFT_FLAGS_REJECT


def fold(text: str) -> str:
    """Lower-case and strip diacritics, keeping every character's position, so
    a match on the folded text indexes straight back into the original."""
    out = []
    for c in text or "":
        base = unicodedata.normalize("NFD", c)[0].lower()
        out.append(base[0] if base else c)
    return "".join(out)


# The determination of who owns the flat. In part B it may be how the owner
# acquired it ("Titul nadobudnutia: Rozsudok … o určení vlastníckeho práva"),
# which burdens nothing: on its own it counts from part C on, like an auction
# (SK_VOCABULARY.part_c_only holds this very pattern). Proceedings for it
# ("začatie konania o určenie vlastníckeho práva") block wherever they are
# noted.
_OWNERSHIP_RULING_RE = re.compile(r"urcen\w*\s+vlastnick\w*\s+prav\w*")

# kind:
#   lien         — a security right; ordinary when the creditor is a bank
#   encumbrance  — burdens the property whoever holds it
#   distress     — enforcement, insolvency or litigation; never cleared, not
#                  even by the Claude read in modules/debt_bot._decide_lv
_RULES = (
    ("exekúcia",       "distress",    r"exeku"),           # exekúcia, exekučný príkaz, exekútor
    ("konkurz",        "distress",    r"konkurz"),
    # A court case, a court's note that the owner's title is disputed
    # ("poznámka o spornosti"), or proceedings to determine who owns it.
    ("súdny spor",     "distress",    r"sudn\w*\s+(?:spor|konan)\w*|(?<!\w)zalob\w*|"
                                      r"(?<!\w)spornost\w*|"
                                      r"(?<!\w)(?:konan\w*|spor(?:u|y|e|om|ov|och)?(?!\w)|navrh\w*|zalob\w*)"
                                      r"\W+(?:\S+\s+){0,8}?"
                                      + _OWNERSHIP_RULING_RE.pattern + "|"
                                      + _OWNERSHIP_RULING_RE.pattern
                                      + r"\W+(?:\S+\s+){0,3}?konan\w*"),
    # The determination itself, from part C on (compiled already: re.compile
    # hands this same object to _COMPILED, which part_c_only names).
    ("súdny spor",     "distress",    _OWNERSHIP_RULING_RE),
    # A pledgee has started enforcing its lien: the bank's name on the note
    # clears nothing.
    ("výkon záložného práva", "distress", r"vykon\w*\s+zalozn\w*\s+prav\w*"),
    # An auction, a court's ban on disposing of the flat, a seizure in
    # criminal proceedings: a sale may be void, or the flat may go to someone
    # else. (An auction counts from part C on: SK_VOCABULARY.part_c_only.)
    ("dražba",         "distress",    r"(?<!\w)drazb\w*|(?<!\w)drazobn\w*"),
    ("predbežné opatrenie", "distress", r"predbezn\w*\s+opatren\w*|zakaz\w*\s+naklad\w*"),
    ("zaistenie",      "distress",
     r"zaisten\w*\s+(?:nehnutel\w*|majetk\w*|bytu)|trestn\w*\s+poriad\w*"),
    ("vecné bremeno",  "encumbrance", r"vecn\w*\s+bremen\w*"),
    # A ban on selling or encumbering the flat ("zákaz scudzenia / prevodu /
    # zaťaženia", "obmedzenie prevodu"): the flat can't pass to you without
    # its holder's consent. Tiered in _tier: a bank's goes with its mortgage.
    ("zákaz prevodu",  "encumbrance", r"zakaz\w*\s+(?:scudz|prevod|zatazen)\w*|"
                                      r"obmedzen\w*\s+(?:prevod|scudz)\w*"),
    ("predkupné právo", "encumbrance", r"predkupn\w*\s+prav\w*"),
    # ── Entries the screen used to pass as clean (audit of 12 Nov 2026) ──
    # A plomba: the cadastre has a proposal on file that will change the
    # rights to the flat (a sale to someone else, a new lien). It is printed
    # with the property, so it is read in every part. A pending "návrh na
    # vklad" / "prebieha konanie" says the same in words (part C on).
    ("plomba",         "encumbrance", r"(?<!\w)plomb\w*"),
    ("prebiehajúce konanie", "encumbrance",
     r"navrh\w*\s+na\s+vklad\w*|prebieha\w*\s+konan\w*|"
     r"konan\w*\s+o\s+(?:povolen\w*\s+)?vklad\w*"),
    # A right to live in or use the flat for life, written without the words
    # "vecné bremeno" ("Právo doživotného bývania a užívania bytu …").
    ("doživotné užívanie", "encumbrance",
     r"dozivotn\w*\s+(?:\w+\s+){0,2}?(?:byvan|uzivan|prav)\w*|prav\w*\s+dozivotn\w*"),
    ("právo spätnej kúpy", "encumbrance", r"spatn\w*\s+(?:kup|odkup)\w*"),
    ("nájomné právo",  "encumbrance",
     r"najomn\w*\s+(?:prav|zmluv|vztah)\w*|(?<!\w)najomc\w*"),
    ("zádržné právo",  "encumbrance", r"zadrzn\w*\s+prav\w*"),
    # The title itself is in doubt, or the owner can't dispose of the flat.
    ("duplicitné vlastníctvo", "distress", r"duplicit\w*\s+vlastn\w*"),
    ("spochybnená hodnovernosť", "distress",
     r"hodnovernost\w*[^.]{0,80}?spochybn\w*|spochybn\w*[^.]{0,80}?hodnovernost\w*"),
    ("obmedzenie nakladania", "distress",
     r"obmedzen\w*\s+(?:naklad|dispozic)\w*|obmedzen\w*\s+vlastnick\w*\s+prav\w*"),
    ("nútená správa",  "distress",    r"nuten\w*\s+sprav\w*"),
    ("vyvlastnenie",   "distress",    r"(?<!\w)vyvlast\w*"),
    # Restructuring, debt relief, protection from creditors: insolvency by
    # another name ("konkurz" has its own rule).
    ("reštrukturalizácia", "distress",
     r"restrukturaliz\w*|(?<!\w)oddlzen\w*|splatkov\w*\s+kalendar\w*|"
     r"ochran\w*\s+pred\s+veritel\w*"),
    ("zabezpečovacie prevodné právo", "lien",
     r"zabezpecovac\w*\s+prevodn\w*\s+prav\w*"),
    ("záložné právo",  "lien",        r"zalozn\w*\s+prav\w*"),
)
_COMPILED = [(label, kind, re.compile(pat)) for label, kind, pat in _RULES]

# Raised whenever a change to the rules could turn a stored PASS into a
# REJECT: init_db sends the Slovak PASS verdicts made under an older version
# back to the LV check (database.schema._rescreen_lv_passes).
# 2: transfer bans ("zákaz prevodu / scudzenia", "obmedzenie prevodu").
# 3: the owners' statutory lien (§ 15 of Act 182/1993) is a soft flag — this
#    one can turn a stored REJECT into a PASS, so lien rejections are checked
#    again too.
# 4: twelve more kinds of entry (plomba, lifetime use without "vecné bremeno",
#    restrictions on disposal, …), a part C entry no rule names no longer
#    passes (unrecognised_entries), and one-word bank names ("Privatbanka",
#    "SLSP") are banks: PASS verdicts and lien rejections are checked again.
RULES_VERSION = 4

# Who a lien is in favour of. "v prospech" is the register's standard wording;
# the others turn up in older entries.
_CREDITOR_MARKERS = (
    re.compile(r"v\s+prospech\s*:?\s*"),
    re.compile(r"opravnen\w*\s*:?\s*"),
    re.compile(r"(?<!\w)verite\w*\s*:?\s*"),
    re.compile(r"(?<!\w)pre\s+"),
)
# A lien phrase that only refers back to the lien its entry already named
# ("… podľa zmluvy o zriadení záložného práva č. …") is not a second lien.
_REFERENCE_BEFORE = re.compile(r"zmluv|zriaden|zanik|vymaz|zrus")

# Slovak law reserves the word "banka" for licensed banks, so the word itself
# identifies one; the config list adds names and abbreviations that don't
# contain it (VÚB, ČSOB, Oberbank, mBank, …) — as whole words. A non-bank
# company of a banking group (leasing, insurance, factoring, an investment
# firm) or a credit union is no bank, whatever its name shares with one.
# A bank is an akciová spoločnosť / akciová společnost by law (SK zákon
# 483/2001 § 2, CZ zákon 21/1992 § 1): a limited company is none, whatever
# its name says ("BANKA PLUS s.r.o.").
_LIMITED_COMPANY = r"(?<!\w)s\.?\s?r\.?\s?o(?!\w)|(?<!\w)spol\.?\s+s\s+r\.?\s?o"
_NON_BANK = r"leasing|poistov|fa[ck]toring|invest(?!ic)|druzstv|" + _LIMITED_COMPANY
_BANK_RE = re.compile(
    rf"^(?!.*(?:{_NON_BANK})).*?(?:"
    # "banka" / "bank" as a word or a word's ending: Privatbanka, and the
    # names old liens still carry (Istrobanka, Volksbank, Sberbank, Citibank).
    r"(?<!\w)\w*bank(?:a|y|e|u|ou|ovi|ami)?(?!\w)|sporiteln|"
    + "|".join(rf"(?<!\w){re.escape(fold(b))}(?!\w)" for b in LV_BANK_NAMES)
    + ")", re.S)

# The statutory lien of § 15 of Act 182/1993 (o vlastníctve bytov): it arises
# by law on every flat in a building, in favour of the owners' association
# (spoločenstvo vlastníkov) or, without one, the other owners, and secures
# what the flat owes the building (fond opráv, services). It is on a great
# many LVs and is no private debt — but it does follow the flat, so the card
# flags it: ask the správca for a potvrdenie o bezdlžnosti. Recognised by the
# act it cites, or by whom it is in favour of. Owners enforcing it ("výkon
# záložného práva") is distress and blocks as ever.
_STATUTORY_ACT_RE = re.compile(r"182\s*/\s*(?:19)?93(?!\d)")
_STATUTORY_PAR_RE = re.compile(r"§\s*15(?!\d)")
_OWNERS_RE = re.compile(r"(?<!\w)(?:ostatn\w*\s+)?vlastnik\w*\s+bytov|"
                        r"(?<!\w)spolocenstv\w*\s+vlastnik\w*")
STATUTORY_LIEN_NOTE = ("statutory lien of the building's owners (§ 15 of Act 182/1993) — "
                       "on most flats; ask the správca to confirm the flat owes nothing")


def _statutory_owners_lien(entry_text: str, creditor: str) -> bool:
    """The lien entry (folded text, from its phrase to the entry's end) is the
    owners' statutory one."""
    return bool((_STATUTORY_ACT_RE.search(entry_text) and _STATUTORY_PAR_RE.search(entry_text))
                or _OWNERS_RE.search(fold(creditor or "")))


_CREDITOR_SPAN = 60    # longest creditor name read after the marker
_MARKER_SPAN   = 120   # how far after a lien phrase its creditor may start
_ENTRY_SPAN    = 400   # a back-reference must sit this close to its lien

# ── Tiers for vecné bremeno / predkupné právo (folded text) ──────────────────
# A right for someone to use or live in the flat for life: whoever buys it,
# buys a sitting occupant. Always a hard stop, even beside a technical word.
# The noun ("doživotného užívania bytu", "bývania") or the verb ("právo
# užívať byt", "bývať v byte", "do smrti"). The flat or a room may come a
# word or two after it ("užívať celý byt", "užívania jednej izby", "užívania
# kuchyne v byte"); a building or a part of the land may not, as a utility's
# "užívania elektroenergetickej stavby" or "užívania časti nehnuteľnosti" is
# no one's home.
_PERSONAL_USE_RE = re.compile(
    r"doziv|dozit|byvan|(?<!\w)byvat(?!\w)|(?<!\w)do\s+smrti(?!\w)|"
    r"uzivan\w*\s+(?:bytu|bytom|nehnutel|stavb|domu|miestnost)|"
    r"(?<!\w)uzivat\s+(?:(?:byt|dom)(?:u|om|e)?(?!\w)|nehnutel|stavb|miestnost)|"
    r"(?<!\w)uziva(?:n\w*|t)\s+(?:\w+\s+){0,2}(?:byt(?:u|om|e|y)?(?!\w)|izb\w*)")
# Lines, pipes and access across the land: common, and no bar to letting.
_TECHNICAL_RE = re.compile(
    r"inzinier|siet|vedeni|elektr|plyn|vodovod|vodn\w*\s+stavb|kanaliz|rozvod|"
    r"energet|distribuc|telekom|trafostanic|teplovod|potrub|pripojk|kabel|"
    r"ochrann\w*\s+pasm|prechod|prejazd|pristup|chodz|udrzb")
# A pre-emption right of the state or a municipality (common on flats first
# sold off by the city) needs its waiver, not a different flat.
_PUBLIC_HOLDER_RE = re.compile(
    r"(?<!\w)(?:obec|obce|mesto|mesta|mestsk\w*\s+cast\w*|slovensk\w*\s+republik\w*|"
    r"statn\w*|samospravn\w*\s+kraj\w*|vyssi\w*\s+uzemn\w*)(?!\w)")


# An entry's register number opens the next entry: "V 512/2019", "Z 55/2021".
_ENTRY_NO_RE = re.compile(r"(?<!\w)[vzp]\s*-?\s*\d{1,6}/\d{2,4}")
# A new entry's heading: its ordinal, register number and dash ("2 V 200/2021
# - "). A register number inside an entry ("podľa V 100/2015 zmluvy", "byt č.
# 12 V …", "IČO … V …", a date before it) has no ordinal of its own.
_SK_ENTRY_HEAD_RE = re.compile(
    r"(?<![\w./])(?<!c\.\s)\d{1,3}\.?\s+[vzp]\s*-?\s*\d{1,6}/\d{2,4}\s*[-–]\s")
# Where a new Slovak entry starts: a register number, its heading's dash and
# a type line in capitals ("P 55/2022 - Poznámka …" — a contract's own
# "V 100/2015 - zmluva o …" is part of its entry), or a line opened by an
# ordinal and then a register number or a capital ("2 V 200/2021 Zmluva …",
# "2 Zmluva …"). A lien's creditor, or its back-reference, never reaches
# past one.
_SK_NEW_ENTRY_RE = re.compile(
    r"(?<!\w)(?<![Pp]odľa )(?<![Pp]odla )"     # "podľa V 2797/2013 - Zmluva …" cites
    r"[VZPvzp]\s*-?\s*\d{1,6}/\d{2,4}\s*[-–]\s*(?=[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ])")
_SK_LINE_ENTRY_RE = re.compile(
    r"^[ \t]*\d{1,3}\.?[ \t]+(?:[VZP][ \t]*-?[ \t]*\d{1,6}/\d{2,4}[ \t]*[-–]?[ \t]*)?"
    r"(?=[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ])", re.M)


_SK_INLINE_ENTRY_RE = re.compile(
    r"(?<![\w./])(?<!č\.\s)(?<!č\.)\d{1,3}\.?\s+(?:[VZP]\s*-?\s*\d{1,6}/\d{2,4}\s*[-–]?\s*)?"
    r"(?=(?:Z(?i:áložn|mluv|riaden|abezpečovac)|V(?i:ecn)|P(?i:redkupn|oznámk)|E(?i:xeku))\w*)")
# The ordinal right before a lien phrase (folded): "1 V 2797/2013 - ", "1 ".
_SK_ORDINAL_BEFORE_RE = re.compile(
    r"(?<![\w./])(\d{1,3})\.?\s+(?:[vzp]\s*-?\s*\d{1,6}/\d{2,4}\s*[-–]?\s*)?$")


def _sk_next_entry(text: str, low: str, pos: int, endpos: int,
                   next_no: str | None = None) -> int:
    """Where the next Slovak entry starts in [pos, endpos), else endpos. With
    `next_no` (the entry after this lien's own), an ordinal inside a line
    opens it only when it is that number: "vchod 1 Zmluva …", "Bratislava 1
    Zmluva …" are part of the entry."""
    inline = next((m for m in _SK_INLINE_ENTRY_RE.finditer(text, pos, endpos)
                   if next_no is None
                   or re.match(r"\s*(\d{1,3})", m.group()).group(1) == next_no), None)
    found = [m.start() for m in (_SK_NEW_ENTRY_RE.search(text, pos, endpos),
                                 _SK_LINE_ENTRY_RE.search(text, pos, endpos), inline) if m]
    return min(found, default=endpos)


# A contract's register number right after the lien phrase that names the
# contract ("zmluvy o zriadení záložného práva V 2797/2013"), not followed by
# an entry's dash.
_CONTRACT_NO_RE = re.compile(
    r"[\s,]*(?:c\.\s*)?[vzp]\s*-?\s*\d{1,6}/\d{2,4}(?!\d)(?!\s*[-–]\s)")


# The holder's name and address ("v prospech Jana Nováková, Plynárenská 7, …"),
# up to the right's own description ("- právo …", "spočívajúce v …", "podľa
# …", "v zmysle zák. …", "na uloženie …"): a street or a surname is no
# utility line.
_HOLDER_BLOCK_RE = re.compile(
    r"v\s+prospech[\s\S]*?(?=\s[-–—]\s|§|(?<!\w)(?:prav[oae]|spociva\w*|podla|v\s+rozsahu|"
    r"v\s+zmysle|zak(?:on\w*|\.)|na\s+(?:ulozen|umiestnen|zriaden|vedeni)\w*)(?!\w)|$)")
# A company's legal form, in the holder's own name or right after it
# ("Západoslovenská energetika, a.s.", "Slovak Telekom, a.s."): then that name
# says what the easement serves. A person's surname ("Kabelková") says
# nothing, nor does a form or an IČO further on in the holder's block — a
# co-holder's, an address's, a sole trader's IČO.
_LEGAL_FORM_RE = re.compile(r"(?<!\w)(?:a\.\s?s\.?|s\.\s?r\.\s?o|s\.\s?p\.|akciov\w*\s+spolocnost\w*|"
                            r"spolocnost\w*\s+s\s+rucen\w*\s+obmedzen\w*|statn\w*\s+podnik\w*)(?!\w)")


def _holder_is_company(entry_text: str) -> bool:
    """The holder's name (folded entry text, after "v prospech") carries a
    company's legal form, in it or directly after it."""
    m = _CREDITOR_MARKERS[0].search(entry_text)
    if not m:
        return False
    rest = entry_text[m.end():]
    cut = _NAME_END.search(rest)
    name = rest[:cut.start()] if cut else rest
    return bool(_LEGAL_FORM_RE.search(name)
                or _LEGAL_FORM_RE.match(rest[len(name):].lstrip(" \t\r\n,")))


# Kinds of entry whose tier doesn't depend on who holds them.
_FIXED_TIERS = {
    "doživotné užívanie": ("hard", "lifetime right to use or live in it"),
    "právo spätnej kúpy": ("hard", "someone holds a right to buy it back"),
    "nájomné právo":      ("hard", "a lease is registered on it — it binds a new owner"),
    "zádržné právo":      ("hard", "a creditor's right to retain it"),
    "plomba":             ("soft", "a change of rights is pending at the cadastre (plomba) — "
                                   "find out what it is before an offer"),
    "prebiehajúce konanie": ("soft", "proceedings on it are pending at the cadastre — "
                                     "find out what they are before an offer"),
}


def _tier(label: str, entry_text: str, holder: str) -> tuple[str, str]:
    """("hard" | "soft", why) for an easement or a pre-emption right, from its
    own entry's text (folded) and the holder's name."""
    if label == "vecné bremeno":
        if _PERSONAL_USE_RE.search(entry_text):
            return "hard", "lifetime right to use or live in it"
        if _TECHNICAL_RE.search(_HOLDER_BLOCK_RE.sub(" ", entry_text)) or (
                _holder_is_company(entry_text) and _TECHNICAL_RE.search(fold(holder))):
            return "soft", "utility / access easement"
        return "hard", "kind of easement not recognised"
    if label in _FIXED_TIERS:
        return _FIXED_TIERS[label]
    if label == "zákaz prevodu":
        # A bank registers one with its mortgage, and it is lifted when the
        # loan is repaid from the price. Anyone else's — a town's or ŠFRB's on
        # a subsidised flat, a person's — needs their consent to sell.
        h = fold(holder)
        if h and is_bank(holder) and not re.search(r"sfrb|statn\w*\s+fond", h):
            return "soft", "bank's ban that goes with its mortgage — lifted when it is repaid"
        return "hard", "ban on transfer: the holder must consent to the sale"
    if _PUBLIC_HOLDER_RE.search(fold(holder)):
        return "soft", "pre-emption right of the state or a municipality"
    return "hard", "pre-emption right of a person or company"


# Where a creditor's name ends: its address / IČO / "na byt č. …" follow a
# comma or a keyword, and a sentence ends at a period after a full word ("a.s."
# and initials don't end one). Only the name may clear a lien — read further
# and a bank mentioned in the next sentence would clear a private creditor's.
_NAME_END = re.compile(
    r"[,;(]|\s[-–]\s|(?<!\w)ico(?!\w)|(?<!\w)nar\.|"
    r"(?<=\w{3})(?<!ing)(?<!mgr)(?<!dr)\.(?:\s|$)|"
    r"(?<!\w)na\s+(?:byt|nebyt|nehnut|parc|pozem|stavb|podiel)"
)


def _creditor_name(span: str, name_end: re.Pattern = _NAME_END) -> str:
    cut = name_end.search(fold(span))
    name = span[:cut.start()] if cut else span
    return re.sub(r"\s+", " ", name).strip(" :.-")


def is_bank(creditor: str, bank_re: re.Pattern = _BANK_RE) -> bool:
    return bool(bank_re.search(fold(creditor)))


def _excerpt(text: str, start: int, length: int = 160) -> str:
    return re.sub(r"\s+", " ", text[start:start + length]).strip()


@dataclass(frozen=True)
class Vocabulary:
    """One register's words for the screen below: the Slovak one here, the
    Czech one in modules/lv_screen_cz. The reading is the same for both."""
    rules: tuple                 # (label, kind, compiled pattern) on folded text
    creditor_markers: tuple      # what precedes a lien's creditor, most usual first
    holder_markers: tuple        # what precedes an easement's / a right's holder
    reference_before: re.Pattern  # a lien phrase after this only refers back
    bank_re: re.Pattern
    name_end: re.Pattern
    tier: object                 # (label, folded entry text, holder) -> (tier, why)
    entry_no_re: re.Pattern
    distress_lien_prefix: str    # "exekučné záložné právo": the distress's own lien
    # A back-reference stays in its own entry: a lien phrase with an entry
    # separator (entry_no_re) since the last lien is a new lien (Czech).
    reference_needs_same_entry: bool = False
    # Rules read only from part C's heading on, when part_c_at finds one — by
    # label, or one compiled pattern of a label: their words may also name,
    # in part B, how the owner acquired the flat (bought at an auction,
    # awarded by a court's ruling on ownership), which burdens nothing.
    part_c_only: frozenset = frozenset()
    part_c_at: object = None     # (text) -> index of part C's heading, or None
    # (folded entry text, creditor) -> a non-bank lien that is flagged, not
    # blocking (Slovakia's § 15 owners' lien); None: every non-bank lien blocks.
    statutory_lien: object = None
    # {label: label}: a hit of the first is part of the second's entry when
    # that one came just before it ("Vecné bremeno - právo doživotného
    # užívania" is one easement, not an easement and a lifetime right).
    absorbed_by: tuple = ()


# Where part C (ťarchy — the encumbrances) starts in the report's text:
# "ČASŤ C: ŤARCHY", "Časť C - Ťarchy", "C. ŤARCHY".
_PART_C_RE = re.compile(r"cast\s*c\s*[:.\-–]?\s*tarch|(?<!\w)c\s*[.:]\s*tarch")


# Before part C, proceedings on who owns the flat named in the owner's title
# ("Titul nadobudnutia: Rozsudok … v spore o určenie vlastníckeho práva") are
# the case the owner won; after a note ("Poznámka", "Iné údaje") a pending one.
_TITLE_OR_NOTE_RE = re.compile(r"titul\w*\s+nadobud\w*|(?<!\w)poznamk\w*|ine\s+udaj\w*")


def _in_title_of_acquisition(low: str, at: int) -> bool:
    last = None
    for last in _TITLE_OR_NOTE_RE.finditer(low, 0, at):  # noqa: B007 (keeps the last match)
        pass
    return bool(last and last.group().startswith("titul"))


def part_c_start(lv_text) -> int | None:
    """Index of part C's heading in an LV text, or None when there is none to
    recognise. Part C runs to the end of the report (notes and "Iné údaje"
    follow the ťarchy), so everything from here on is what can block."""
    m = _PART_C_RE.search(fold(str(lv_text or "")))
    return m.start() if m else None


SK_VOCABULARY = Vocabulary(
    rules=tuple(_COMPILED), creditor_markers=_CREDITOR_MARKERS,
    holder_markers=_CREDITOR_MARKERS[:1], reference_before=_REFERENCE_BEFORE,
    bank_re=_BANK_RE, name_end=_NAME_END, tier=_tier, entry_no_re=_ENTRY_NO_RE,
    distress_lien_prefix="exeku",
    part_c_only=frozenset({"dražba", "prebiehajúce konanie", _OWNERSHIP_RULING_RE}),
    part_c_at=part_c_start,
    statutory_lien=_statutory_owners_lien,
    absorbed_by=(("doživotné užívanie", "vecné bremeno"),),
)


def screen_lv(lv_text, vocabulary: Vocabulary | None = None) -> list[dict]:
    """Every encumbrance in the LV text, in document order — read with the
    Slovak register's words unless `vocabulary` gives another's.

    Each entry: {flag, kind, blocking, creditor, excerpt}. `blocking` is False
    only for a lien whose own creditor is a bank; `creditor` is the text read
    after the creditor marker (None when no lien creditor applies).
    """
    v = vocabulary or SK_VOCABULARY
    text = str(lv_text or "")
    low = fold(text)

    c_at = v.part_c_at(text) if v.part_c_only and v.part_c_at else None
    hits = sorted(
        (m.start(), m.end(), label, kind)
        for label, kind, rx in v.rules
        for m in rx.finditer(low)
        if c_at is None or m.start() >= c_at
        or (label not in v.part_c_only and rx not in v.part_c_only
            and not (_OWNERSHIP_RULING_RE.search(m.group())
                     and _in_title_of_acquisition(low, m.start())))
    )
    entries: list[dict] = []
    last_lien_at = None
    last_seen: dict[str, int] = {}
    for i, (start, end, label, kind) in enumerate(hits):
        if kind != "lien":
            # "Exekúcia EX 55/2021, exekučné záložné právo …" is one entry,
            # not two exekúcie; "Vecné bremeno … podľa zmluvy o zriadení
            # vecného bremena" is one easement. Two easements are two
            # entries, each with its own number ("V 512/2019") in between.
            if label in last_seen:
                gap = start - last_seen[label]
                if (gap <= 120 if kind == "distress" else
                        gap <= _ENTRY_SPAN
                        and not v.entry_no_re.search(low, last_seen[label], start)):
                    continue
            absorber = dict(v.absorbed_by).get(label)
            if (absorber in last_seen and start - last_seen[absorber] <= _ENTRY_SPAN
                    and not v.entry_no_re.search(low, last_seen[absorber], start)):
                continue
            last_seen[label] = start
            entry = {"flag": label, "kind": kind, "blocking": True, "tier": "hard",
                     "creditor": None, "note": None, "excerpt": _excerpt(text, start),
                     "at": start}
            if kind == "encumbrance":
                # The entry runs to the next entry's number or another kind
                # of hit, so another entry's wording can't soften this one.
                nxt = next((h[0] for h in hits[i + 1:] if h[2] != label), len(low))
                entry_end = min(nxt, end + _ENTRY_SPAN)
                nxt_entry = v.entry_no_re.search(low, end, entry_end)
                if nxt_entry:
                    entry_end = nxt_entry.start()
                holder = _holder(text, low, end, entry_end, v)
                entry["tier"], entry["note"] = v.tier(label, low[start:entry_end], holder)
                entry["creditor"] = holder or None
                entry["blocking"] = entry["tier"] == "hard" or LV_SOFT_FLAGS_REJECT
            entries.append(entry)
            continue
        # "exekučné záložné právo" is the exekúcia's own lien — the distress
        # hit right before it already blocks.
        if v.distress_lien_prefix in low[max(0, start - 25):start]:
            continue
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(low)
        window_end = min(nxt, end + _MARKER_SPAN)
        own_no = _SK_ORDINAL_BEFORE_RE.search(low, max(0, start - 30), start)
        next_no = str(int(own_no.group(1)) + 1) if own_no else None
        if not v.reference_needs_same_entry:
            # Slovak: the next entry's "… v prospech Tatra banka" is not this
            # lien's creditor.
            window_end = _sk_next_entry(text, low, end, window_end, next_no)
        window = low[end:window_end]
        ref_from = max(0, start - 40)
        if not v.reference_needs_same_entry:
            # "… podľa zmluvy V 2797/2013  2 V 512/2019 - Záložné právo pre …":
            # a contract word before the next entry's register number belongs
            # to the entry before; it makes this entry's lien no reference.
            for sp in v.entry_no_re.finditer(low, ref_from, start):
                ref_from = sp.end()
        is_reference = bool(v.reference_before.search(low[ref_from:start]))
        # A reference reads only a creditor it names itself ("v prospech", or
        # in Slovak the older "oprávnený" / "veriteľ" — not a bare "pre",
        # as in "zmluvy … pre zabezpečenie").
        markers = (v.creditor_markers[:1 if v.reference_needs_same_entry else 3]
                   if is_reference else v.creditor_markers)
        marker = None
        entry_stop = None
        if v.reference_needs_same_entry and not is_reference:
            # A Czech entry names its creditor ("Oprávnění pro" / "ve
            # prospěch") anywhere before the next entry — after a long claim
            # line ("… a budoucí pohledávky do výše …") or a page break.
            sep = v.entry_no_re.search(low, end, nxt)
            entry_window = low[end:sep.start() if sep else nxt]
            for rx in v.creditor_markers[:2]:
                marker = rx.search(entry_window)
                if marker:
                    break
        for rx in ([] if marker else markers):
            marker = rx.search(window)
            if marker:
                break
        if marker is None and v.reference_needs_same_entry and not is_reference:
            # Czech, no creditor before the next hit: that hit may be the
            # entry's own claim line naming the lien again, in lower case
            # ("zástavní právo k zajištění pohledávky …"), so read on to the
            # entry's end — its register number or bullet, or a hit written
            # with a capital ("Zástavní právo smluvní"): the next entry's type
            # line, its bullet lost.
            sep = v.entry_no_re.search(low, end)
            entry_stop = sep.start() if sep else len(low)
            entry_stop = next((h[0] for h in hits[i + 1:]
                               if end <= h[0] < entry_stop and text[h[0]].isupper()),
                              entry_stop)
            for rx in v.creditor_markers[:2]:
                marker = rx.search(low[end:entry_stop])
                if marker:
                    break
        if marker is None and is_reference and last_lien_at is not None:
            if v.reference_needs_same_entry:
                # Czech: the same entry runs on to the next bullet. A register
                # number ends a "Listina" line, and another "Listina …
                # zástavního práva" (an amendment) may follow it in the same
                # entry: the reference word must come after the last number.
                seps = list(v.entry_no_re.finditer(low, last_lien_at, start))
                after = seps[-1].end() if seps else last_lien_at
                same = all(sp.group() != "•" for sp in seps) and bool(
                    v.reference_before.search(low[max(after, start - 40):start]))
            else:
                # Slovak: close to the lien, and no new entry's heading
                # ("2 V 200/2021 - Zmluva o zriadení záložného práva pre …")
                # in between — that is a lien of its own.
                own = {re.sub(r"\W", "", n.group()) for n in
                       v.entry_no_re.finditer(low, max(0, last_lien_at - 60), last_lien_at)}
                # The lien's own entry's ordinal ("1 V 2797/2013 - Záložné
                # právo"): the next entry's is the next number.
                o = _SK_ORDINAL_BEFORE_RE.search(low, max(0, last_lien_at - 30), last_lien_at)
                next_no = str(int(o.group(1)) + 1) if o else None

                def _opens(m, rx, own=own, next_no=next_no):
                    n = v.entry_no_re.search(low, m.start(), m.end())
                    if n and re.sub(r"\W", "", n.group()) not in own:
                        return True
                    k = re.match(r"\s*(\d{1,3})", low[m.start():m.end()])
                    if n:
                        # Its own contract cited ("… 25 V 2797/2013 - zmluva
                        # …"), unless the next ordinal opens it with a capital:
                        # a new entry under the same number.
                        return bool(k and k.group(1) == next_no
                                    and text[m.end():m.end() + 1].isupper())
                    # An ordinal alone ("2 Zmluva …") is the next entry's only
                    # when it is the next number: "Bratislava 1", "Hodžovo
                    # námestie 3", an IČO's "930" are an address.
                    return (rx is _SK_LINE_ENTRY_RE or next_no is None or not k
                            or k.group(1) == next_no)
                heads = [(m, rx) for rx, s in ((_SK_ENTRY_HEAD_RE, low), (_SK_NEW_ENTRY_RE, text),
                                               (_SK_LINE_ENTRY_RE, text), (_SK_INLINE_ENTRY_RE, text))
                         for m in rx.finditer(s, last_lien_at, start)]
                same = (start - last_lien_at <= _ENTRY_SPAN
                        and not any(_opens(m, rx) for m, rx in heads))
            if same:
                continue
        sk_stop = None
        if marker is None and not v.reference_needs_same_entry:
            # Slovak, no creditor within reach: a long claim line ("na
            # zabezpečenie pohľadávky … zo zmluvy o úvere …") or the contract
            # it names ("podľa zmluvy o zriadení záložného práva V 2797/2013")
            # may come before "v prospech". Read on for "v prospech" alone —
            # never a "pre" or "veriteľ" of the claim's history — past such
            # contract references and their numbers, to the entry's end: the
            # next other hit or register number, or a lien phrase written
            # with a capital (the next entry's type line, "Záložné právo"),
            # at most _ENTRY_SPAN on.
            stop, at = min(len(low), end + _ENTRY_SPAN), end
            for h in hits[i + 1:]:
                if h[0] >= stop or v.entry_no_re.search(low, at, h[0]):
                    break
                if not (h[3] == "lien" and not text[h[0]].isupper()
                        and v.reference_before.search(low[max(0, h[0] - 40):h[0]])):
                    stop = h[0]
                    break
                num = _CONTRACT_NO_RE.match(low, h[1])
                at = num.end() if num else h[1]
            sep = v.entry_no_re.search(low, at, stop)
            if sep:
                stop = sep.start()
            stop = _sk_next_entry(text, low, end, stop, next_no)
            marker = v.creditor_markers[0].search(low[end:stop])
            if marker is not None:
                sk_stop = stop
        if marker is not None:
            c_start = end + marker.end()
            c_stop = nxt if sk_stop is None else sk_stop
            if entry_stop is not None and c_start >= nxt:
                # Czech: the creditor follows another hit of its own entry —
                # read the name up to the next hit after it, in this entry.
                c_stop = min(entry_stop, next(
                    (h[0] for h in hits[i + 1:] if h[0] >= c_start), len(low)))
            creditor = text[c_start:min(c_stop, c_start + _CREDITOR_SPAN)]
        else:
            # No marker: the name may simply follow ("Záložné právo: Tatra
            # banka, a.s."). Anything else is a lien we can't attribute.
            creditor = text[end:window_end]
        creditor = _creditor_name(creditor, v.name_end)
        bank = is_bank(creditor, v.bank_re)
        last_lien_at = start
        entry = {"flag": label, "kind": kind, "blocking": not bank,
                 "tier": "hard" if not bank else None,
                 "creditor": creditor or None, "note": None,
                 "excerpt": _excerpt(text, start), "at": start}
        if not bank and v.statutory_lien is not None:
            # This entry only: to the next hit or register number.
            entry_end = min(nxt, end + _ENTRY_SPAN)
            sep = v.entry_no_re.search(low, end, entry_end)
            if sep:
                entry_end = sep.start()
            if v.statutory_lien(low[start:entry_end], creditor):
                entry.update(tier="soft", note=STATUTORY_LIEN_NOTE,
                             blocking=LV_SOFT_FLAGS_REJECT)
        entries.append(entry)
    return entries


def _holder(text: str, low: str, end: int, entry_end: int,
            vocabulary: Vocabulary | None = None) -> str:
    """Whom an easement or a pre-emption right is in favour of, read like a
    lien's creditor: the name after "v prospech" in the same entry."""
    v = vocabulary or SK_VOCABULARY
    m = None
    for rx in v.holder_markers:
        m = rx.search(low[end:entry_end])
        if m:
            break
    if not m:
        return ""
    start = end + m.end()
    return _creditor_name(text[start:min(entry_end, start + _CREDITOR_SPAN)], v.name_end)


# ── The safety net: an entry no rule names ───────────────────────────────────
# Words that announce a right, a restriction, a note or proceedings. In part C
# each of them should sit in an entry one of the rules names; one that doesn't
# belongs to a kind of entry this screen doesn't know, so the title can't be
# called clean on the screen's word alone (modules/debt_bot.check_flat_lv).
_GENERIC_BURDEN_RE = re.compile(
    r"(?<!\w)prav[oa](?!\w)|(?<!\w)zakaz\w*|(?<!\w)obmedzen\w*|(?<!\w)poznamk\w*|"
    r"(?<!\w)konan\w*|(?<!\w)spor(?:u|y|e|om|ov|och|n\w*)?(?!\w)|"
    r"(?<!\w)najom\w*|(?<!\w)bremen\w*")
# The ones that only label or describe an entry ("Poznámka: Exekučný príkaz …",
# "právo zodpovedajúce vecnému bremenu") may come just before the words a
# rule knows. A ban, a restriction, a lease, a dispute or proceedings must be
# named by a rule itself, or follow one in its entry.
_LABEL_WORD_RE = re.compile(r"prav[oa]|poznamk\w*|bremen\w*")
# "Poznámka: Bez zápisu", "Poznámky: žiadne" — the section is empty.
_NO_ENTRY_AFTER_RE = re.compile(
    r"\w*\s*[:\-–]?\s*(?:bez\s+(?:zapisu|zapisov|tiarch|poznam\w*|udajov)|ziadn\w*)")
# "… prevod vlastníckeho práva …" names the ownership itself, not a burden.
_OWNERSHIP_BEFORE_RE = re.compile(r"vlastnick\w*\s+$")
_EXPLAINED_BEFORE = 80     # a rule's entry may open this far before its words
_EXPLAINED_AFTER = 300     # … and run this far after them, or to the next entry
# Where the entry after a recognised one starts, when it has no register
# number of its own: the report's next section ("Iné údaje:", "Poznámka:"),
# or an ordinal and a capitalised word ("6 Právo stavby …").
_SECTION_RE = re.compile(r"(?<!\w)(?:ine\s+udaje|poznamk\w*)\s*:")
_ORDINAL_ENTRY_RE = re.compile(r"(?<![\w./,])\d{1,3}\.?\s+(?=[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ][a-záäčďéíĺľňóôŕšťúýž])")


def _unknown_at(text: str, low: str, v: Vocabulary) -> tuple[int | None, list[int]]:
    """(where part C's text starts, where each unrecognised entry's telling
    word is) — (None, []) without a part C heading."""
    heading = _PART_C_RE.search(low)
    if not heading:
        return None, []
    start = heading.end()
    # Where each recognised entry's own text may lie: from a little before
    # the rule's words (never past the entry number that opens it) to the
    # next entry's heading.
    zones, before = [], []
    for _label, _kind, rx in v.rules:
        for m in rx.finditer(low, start):
            a = max(start, m.start() - _EXPLAINED_BEFORE)
            for n in v.entry_no_re.finditer(low, a, m.start()):
                a = n.end()
            before.append((a, m.start()))
            a = m.start()
            b = min(len(low), m.end() + _EXPLAINED_AFTER)
            heads = [h.start() for h in (_SK_ENTRY_HEAD_RE.search(low, m.end(), b),
                                         _SK_NEW_ENTRY_RE.search(text, m.end(), b),
                                         _SECTION_RE.search(low, m.end(), b),
                                         _ORDINAL_ENTRY_RE.search(text, m.end(), b)) if h]
            zones.append((a, min(heads, default=b)))
    out, reported_to = [], -1
    for g in _GENERIC_BURDEN_RE.finditer(low, start):
        at = g.start()
        if at < reported_to or any(a <= at < b for a, b in zones):
            continue
        if _LABEL_WORD_RE.fullmatch(g.group()) and any(a <= at < b for a, b in before):
            continue
        if _NO_ENTRY_AFTER_RE.match(low, g.end()) or _OWNERSHIP_BEFORE_RE.search(low[max(0, at - 16):at]):
            continue
        reported_to = at + _UNKNOWN_SPAN
        out.append(at)
    return start, out


_UNKNOWN_SPAN = 90      # how much of an unrecognised entry is quoted


def unrecognised_entries(lv_text, vocabulary: Vocabulary | None = None) -> list[str]:
    """Excerpts of part C that announce a right, a restriction, a note or
    proceedings which none of the rules names — a kind of entry this screen
    doesn't know. Empty when every such word sits in a recognised entry, and
    when the text has no part C heading to read from (check_flat_lv handles
    that case itself)."""
    text = str(lv_text or "")
    start, found = _unknown_at(text, fold(text), vocabulary or SK_VOCABULARY)
    return [re.sub(r"\s+", " ", text[max(start, at - 30):at + _UNKNOWN_SPAN]).strip(" .:-–")
            for at in found]


def part_c_marks(lv_text, vocabulary: Vocabulary | None = None) -> list[tuple[str, str]]:
    """Part C of an LV as (text, mark) pieces for the dashboard's "Read part
    C": mark is "hard" (blocks), "soft" (flagged), "bank" (an ordinary bank
    lien), "unknown" (an entry no rule names) or "" (plain text). [] when the
    text has no part C heading."""
    v = vocabulary or SK_VOCABULARY
    text = str(lv_text or "")
    low = fold(text)
    start = part_c_start(text)
    if start is None:
        return []
    spans = []
    for e in screen_lv(text, v):
        if e.get("at") is None or e["at"] < start:
            continue
        mark = ("hard" if e["blocking"] else "soft" if e.get("tier") == "soft" else "bank")
        spans.append((e["at"], e["at"] + 60, mark))
    spans += [(at, at + _UNKNOWN_SPAN, "unknown") for at in _unknown_at(text, low, v)[1]]
    spans.sort()
    pieces, pos = [], start
    for i, (a, b, mark) in enumerate(spans):
        if a < pos:
            continue
        # A mark never runs into the next entry's.
        b = min(b, len(text), *(n[0] for n in spans[i + 1:i + 2]))
        if a > pos:
            pieces.append((text[pos:a], ""))
        pieces.append((text[a:b], mark))
        pos = b
    if pos < len(text):
        pieces.append((text[pos:], ""))
    return pieces


def describe(entry: dict) -> str:
    """One line for a dashboard detail / log: what was found and in whose favour."""
    if entry["kind"] == "lien" and entry.get("tier") == "soft":
        return f"{entry['flag']} — {entry['note']}"
    if entry["kind"] == "lien":
        who = entry.get("creditor") or "unreadable creditor"
        state = "bank" if not entry["blocking"] else "NOT a bank"
        return f"{entry['flag']} in favour of {who[:60]} ({state})"
    if entry.get("note"):
        return f"{entry['flag']} — {entry['note']}: {entry['excerpt'][:90]}"
    return f"{entry['flag']}: {entry['excerpt'][:90]}"
