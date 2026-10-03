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

The text is the plain text of the portal's LV report (kataster_scraper
fetch_lv_text). Its entry layout could not be checked against live reports
while writing this, so the rules lean conservative: a lien whose creditor
cannot be read counts as blocking.
"""

import re
import unicodedata

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import LV_BANK_NAMES


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
            # not two exekúcie.
            if label in last_seen and start - last_seen[label] <= 120:
                continue
            last_seen[label] = start
            entries.append({"flag": label, "kind": kind, "blocking": True,
                            "creditor": None, "excerpt": _excerpt(text, start)})
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
                         "creditor": creditor or None,
                         "excerpt": _excerpt(text, start)})
    return entries


def describe(entry: dict) -> str:
    """One line for a dashboard detail / log: what was found and in whose favour."""
    if entry["kind"] == "lien":
        who = entry.get("creditor") or "unreadable creditor"
        state = "bank" if not entry["blocking"] else "NOT a bank"
        return f"{entry['flag']} in favour of {who[:60]} ({state})"
    return f"{entry['flag']}: {entry['excerpt'][:90]}"
