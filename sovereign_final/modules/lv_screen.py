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
  - Distress entries (exekúcia, konkurz, súdny spor / žaloba) are never cleared
    by anything, whoever the creditor is.
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


# kind:
#   lien         — a security right; ordinary when the creditor is a bank
#   encumbrance  — burdens the property whoever holds it
#   distress     — enforcement, insolvency or litigation; never cleared, not
#                  even by the Claude read in modules/debt_bot._decide_lv
_RULES = (
    ("exekúcia",       "distress",    r"exeku"),           # exekúcia, exekučný príkaz, exekútor
    ("konkurz",        "distress",    r"konkurz"),
    ("súdny spor",     "distress",    r"sudn\w*\s+(?:spor|konan)\w*|(?<!\w)zalob\w*"),
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
# contain it (VÚB, ČSOB, Oberbank, mBank, …).
_BANK_RE = re.compile(
    r"(?<!\w)bank(?:a|y|e|u|ou|ovi|ami)?(?!\w)|sporiteln|"
    + "|".join(re.escape(fold(b)) for b in LV_BANK_NAMES)
)

_CREDITOR_SPAN = 60    # longest creditor name read after the marker
_MARKER_SPAN   = 120   # how far after a lien phrase its creditor may start
_ENTRY_SPAN    = 400   # a back-reference must sit this close to its lien

# ── Tiers for vecné bremeno / predkupné právo (folded text) ──────────────────
# A right for someone to use or live in the flat for life: whoever buys it,
# buys a sitting occupant. Always a hard stop, even beside a technical word.
_PERSONAL_USE_RE = re.compile(
    r"doziv|dozit|byvan|uzivan\w*\s+(?:bytu|bytom|nehnutel|stavb|domu|miestnost)")
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


def _tier(label: str, entry_text: str, holder: str) -> tuple[str, str]:
    """("hard" | "soft", why) for an easement or a pre-emption right, from its
    own entry's text (folded) and the holder's name."""
    if label == "vecné bremeno":
        if _PERSONAL_USE_RE.search(entry_text):
            return "hard", "lifetime right to use or live in it"
        if _TECHNICAL_RE.search(entry_text):
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


def _creditor_name(span: str) -> str:
    cut = _NAME_END.search(fold(span))
    name = span[:cut.start()] if cut else span
    return re.sub(r"\s+", " ", name).strip(" :.-")


def is_bank(creditor: str) -> bool:
    return bool(_BANK_RE.search(fold(creditor)))


def _excerpt(text: str, start: int, length: int = 160) -> str:
    return re.sub(r"\s+", " ", text[start:start + length]).strip()


def screen_lv(lv_text) -> list[dict]:
    """Every encumbrance in the LV text, in document order.

    Each entry: {flag, kind, blocking, creditor, excerpt}. `blocking` is False
    only for a lien whose own creditor is a bank; `creditor` is the text read
    after the creditor marker (None when no lien creditor applies).
    """
    text = str(lv_text or "")
    low = fold(text)

    hits = sorted(
        (m.start(), m.end(), label, kind)
        for label, kind, rx in _COMPILED
        for m in rx.finditer(low)
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
                        and not _ENTRY_NO_RE.search(low, last_seen[label], start)):
                    continue
            last_seen[label] = start
            entry = {"flag": label, "kind": kind, "blocking": True, "tier": "hard",
                     "creditor": None, "note": None, "excerpt": _excerpt(text, start)}
            if kind == "encumbrance":
                # The entry runs to the next entry's number or another kind
                # of hit, so another entry's wording can't soften this one.
                nxt = next((h[0] for h in hits[i + 1:] if h[2] != label), len(low))
                entry_end = min(nxt, end + _ENTRY_SPAN)
                nxt_entry = _ENTRY_NO_RE.search(low, end, entry_end)
                if nxt_entry:
                    entry_end = nxt_entry.start()
                holder = _holder(text, low, end, entry_end)
                entry["tier"], entry["note"] = _tier(label, low[start:entry_end], holder)
                entry["creditor"] = holder or None
                entry["blocking"] = entry["tier"] == "hard" or LV_SOFT_FLAGS_REJECT
            entries.append(entry)
            continue
        # "exekučné záložné právo" is the exekúcia's own lien — the distress
        # hit right before it already blocks.
        if "exeku" in low[max(0, start - 25):start]:
            continue
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(low)
        window_end = min(nxt, end + _MARKER_SPAN)
        window = low[end:window_end]
        is_reference = bool(_REFERENCE_BEFORE.search(low[max(0, start - 40):start]))
        markers = _CREDITOR_MARKERS[:1] if is_reference else _CREDITOR_MARKERS
        marker = None
        for rx in markers:
            marker = rx.search(window)
            if marker:
                break
        if marker is None and is_reference and last_lien_at is not None \
                and start - last_lien_at <= _ENTRY_SPAN:
            continue
        if marker is not None:
            c_start = end + marker.end()
            creditor = text[c_start:min(nxt, c_start + _CREDITOR_SPAN)]
        else:
            # No marker: the name may simply follow ("Záložné právo: Tatra
            # banka, a.s."). Anything else is a lien we can't attribute.
            creditor = text[end:window_end]
        creditor = _creditor_name(creditor)
        last_lien_at = start
        entries.append({"flag": label, "kind": kind,
                         "blocking": not is_bank(creditor),
                         "tier": "hard" if not is_bank(creditor) else None,
                         "creditor": creditor or None, "note": None,
                         "excerpt": _excerpt(text, start)})
    return entries


def _holder(text: str, low: str, end: int, entry_end: int) -> str:
    """Whom an easement or a pre-emption right is in favour of, read like a
    lien's creditor: the name after "v prospech" in the same entry."""
    m = _CREDITOR_MARKERS[0].search(low[end:entry_end])
    if not m:
        return ""
    start = end + m.end()
    return _creditor_name(text[start:min(entry_end, start + _CREDITOR_SPAN)])


# Where part C (ťarchy — the encumbrances) starts in the report's text:
# "ČASŤ C: ŤARCHY", "Časť C - Ťarchy", "C. ŤARCHY".
_PART_C_RE = re.compile(r"cast\s*c\s*[:.\-–]?\s*tarch|(?<!\w)c\s*[.:]\s*tarch")


def part_c_start(lv_text) -> int | None:
    """Index of part C's heading in an LV text, or None when there is none to
    recognise. Part C runs to the end of the report (notes and "Iné údaje"
    follow the ťarchy), so everything from here on is what can block."""
    m = _PART_C_RE.search(fold(str(lv_text or "")))
    return m.start() if m else None


def describe(entry: dict) -> str:
    """One line for a dashboard detail / log: what was found and in whose favour."""
    if entry["kind"] == "lien":
        who = entry.get("creditor") or "unreadable creditor"
        state = "bank" if not entry["blocking"] else "NOT a bank"
        return f"{entry['flag']} in favour of {who[:60]} ({state})"
    if entry.get("note"):
        return f"{entry['flag']} — {entry['note']}: {entry['excerpt'][:90]}"
    return f"{entry['flag']}: {entry['excerpt'][:90]}"
