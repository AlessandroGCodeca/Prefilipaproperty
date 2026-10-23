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
    ("predkupné právo", "encumbrance", r"predkupn\w*\s+prav\w*"),
    ("zabezpečovacie prevodné právo", "lien",
     r"zabezpecovac\w*\s+prevodn\w*\s+prav\w*"),
    ("záložné právo",  "lien",        r"zalozn\w*\s+prav\w*"),
)
_COMPILED = [(label, kind, re.compile(pat)) for label, kind, pat in _RULES]

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
_NON_BANK = r"leasing|poistov|fa[ck]toring|invest(?!ic)|druzstv"
_BANK_RE = re.compile(
    rf"^(?!.*(?:{_NON_BANK})).*?(?:"
    r"(?<!\w)bank(?:a|y|e|u|ou|ovi|ami)?(?!\w)|sporiteln|"
    + "|".join(rf"(?<!\w){re.escape(fold(b))}(?!\w)" for b in LV_BANK_NAMES)
    + ")", re.S)

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
    r"(?=(?:Záložn|Zmluv|Zriaden|Vecn|Predkupn|Poznámk|Exeku|Zabezpečovac)\w*)")


def _sk_next_entry(text: str, low: str, pos: int, endpos: int) -> int:
    """Where the next Slovak entry starts in [pos, endpos), else endpos."""
    found = [m.start() for m in (_SK_NEW_ENTRY_RE.search(text, pos, endpos),
                                 _SK_LINE_ENTRY_RE.search(text, pos, endpos),
                                 _SK_INLINE_ENTRY_RE.search(text, pos, endpos)) if m]
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


# Where part C (ťarchy — the encumbrances) starts in the report's text:
# "ČASŤ C: ŤARCHY", "Časť C - Ťarchy", "C. ŤARCHY".
_PART_C_RE = re.compile(r"cast\s*c\s*[:.\-–]?\s*tarch|(?<!\w)c\s*[.:]\s*tarch")


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
    part_c_only=frozenset({"dražba", _OWNERSHIP_RULING_RE}), part_c_at=part_c_start,
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
        or (label not in v.part_c_only and rx not in v.part_c_only)
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
            last_seen[label] = start
            entry = {"flag": label, "kind": kind, "blocking": True, "tier": "hard",
                     "creditor": None, "note": None, "excerpt": _excerpt(text, start)}
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
        if not v.reference_needs_same_entry:
            # Slovak: the next entry's "… v prospech Tatra banka" is not this
            # lien's creditor.
            window_end = _sk_next_entry(text, low, end, window_end)
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

                def _opens(m):
                    n = v.entry_no_re.search(low, m.start(), m.end())
                    return not (n and re.sub(r"\W", "", n.group()) in own)
                heads = [m for rx, s in ((_SK_ENTRY_HEAD_RE, low), (_SK_NEW_ENTRY_RE, text),
                                         (_SK_LINE_ENTRY_RE, text), (_SK_INLINE_ENTRY_RE, text))
                         for m in rx.finditer(s, last_lien_at, start)]
                same = (start - last_lien_at <= _ENTRY_SPAN
                        and not any(_opens(m) for m in heads))
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
            stop = _sk_next_entry(text, low, end, stop)
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
        entries.append({"flag": label, "kind": kind,
                         "blocking": not bank,
                         "tier": "hard" if not bank else None,
                         "creditor": creditor or None, "note": None,
                         "excerpt": _excerpt(text, start)})
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


def describe(entry: dict) -> str:
    """One line for a dashboard detail / log: what was found and in whose favour."""
    if entry["kind"] == "lien":
        who = entry.get("creditor") or "unreadable creditor"
        state = "bank" if not entry["blocking"] else "NOT a bank"
        return f"{entry['flag']} in favour of {who[:60]} ({state})"
    if entry.get("note"):
        return f"{entry['flag']} — {entry['note']}: {entry['excerpt'][:90]}"
    return f"{entry['flag']}: {entry['excerpt'][:90]}"
