"""
modules/lv_cz.py — the title-deed (LV, list vlastnictví) check for a Czech
listing, under modules/debt_bot's three verdicts:

  PASS        the flat's own výpis z LV was read — its part C there, every
              entry of parts C–D one the screen knows — and nothing blocks.
  REJECTED    the flat's own výpis z LV carries a blocking encumbrance.
  UNVERIFIED  no výpis of this flat was read — the detail says how far the
              check got (the building under the map pin, its LV, pending
              proceedings).

Where an LV's contents come from: ČÚZK's free services tell a program which
LV a building or unit is on and whether a change of rights is pending (API KN,
modules/cuzk_cz), not what the LV carries. Nahlížení do katastru shows part C
one query at a time behind a CAPTCHA, and is not to be read by programs. The
výpis z LV itself is sold by CzechPOINT and ČÚZK's dálkový přístup. So a
Czech flat is verified by pasting its výpis on the dashboard card
(database.set_lv_document); the screen is modules/lv_screen_cz, Claude's read
(when enabled) the Czech prompt — the same decision path as a Slovak LV.

A cooperative flat (družstevní byt) has no LV of its own: the cooperative owns
the building and the buyer takes over a membership share. It is never PASS —
the cooperative's LV and the share-transfer terms are for a lawyer to read.
"""

from __future__ import annotations

import re

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules import cuzk_cz
from modules.lv_screen import fold

NAHLIZENI_URL = "https://nahlizenidokn.cuzk.gov.cz/"
_HINT = ("Paste the flat's výpis z LV (CzechPOINT or ČÚZK dálkový přístup) on its "
         "card to verify it.")
# "Vlastnictví: družstevní", "družstevní byt", "(družstevní)", "členský podíl /
# členská práva", "podíl v (bytovém) družstvu" — not "dříve družstevní", "z
# družstevního do osobního", "není družstevní", nor a building an "bytové
# družstvo" merely manages.
_COOP_RE = re.compile(
    r"vlastnictvi\s*:?\s*druzstev|"
    r"(?<!drive )(?<!puvodne )(?<!z )(?<!neni )(?<!\w)druzstevn\w*|"
    r"(?<!\w)clensk\w*\s+(?:prav|podil)\w*|podil\w*\s+v\s+(?:bytov\w*\s+)?druzstv")


def _unverified(detail: str, **extra) -> dict:
    return {"status": "UNVERIFIED", "detail": detail, "raw": {}, "market": "cz", **extra}


def is_cooperative(description: str) -> bool:
    """True when the listing says the flat is held in a cooperative."""
    return bool(_COOP_RE.search(fold(description or "")))


def _ku_differs(stated: tuple[str, str] | None, card: str) -> bool:
    """True when the výpis's k.ú. (code, folded name) is plainly not the
    card's k.ú. ("727440", "Žižkov" or "k.ú. Žižkov [727440]")."""
    if not stated or not (card or "").strip():
        return False
    code, name = stated
    card_code = re.search(r"(?<!\d)\d{6}(?!\d)", card)
    if code and card_code:
        return card_code.group() != code
    card_name = re.sub(r"\bk\.?\s*u\.?\s|\[?\d+\]?|katastraln\w*\s+uzemi", " ", fold(card))
    card_name = re.sub(r"\s+", " ", card_name).strip(" :.,")
    if not card_name or not name:
        return False
    return card_name not in name and name not in card_name


def check_text(lv_text: str, lv_number=None, cadastral_area: str = "") -> dict:
    """The verdict on a pasted výpis z LV — modules/debt_bot._parse_lv with
    the Czech screen. A clean result needs part C to have been read whole: a
    text with no part C heading (page 1 of 2, or not a výpis at all), or one
    whose parts C–D hold an entry the screen does not know, is UNVERIFIED —
    a blocking entry still REJECTs."""
    from modules.debt_bot import _parse_lv
    from modules.lv_screen_cz import (
        screen_lv_cz, lv_number_in, unit_numbers, part_c_start, unrecognised_entries,
        ku_in, _norm,
    )
    lv_text = _norm(lv_text)
    stated = lv_number_in(lv_text)
    wanted = str(lv_number or "").strip()
    if wanted and stated and stated != wanted:
        return _unverified(f"The pasted výpis is LV {stated}; the card says the flat is "
                           f"on LV {wanted}. {_HINT}")
    # LV numbers start again in every k.ú.: the same number in the next
    # k.ú. is another property.
    ku = ku_in(lv_text)
    if _ku_differs(ku, cadastral_area):
        return _unverified(f"The pasted výpis is for k.ú. {ku[1] or ku[0]}; the card says "
                           f"k.ú. {cadastral_area.strip()}. {_HINT}")
    decision = _parse_lv(lv_text, screen=screen_lv_cz)
    units = unit_numbers(lv_text)
    label = f"LV {stated or wanted}" if (stated or wanted) else "The pasted LV"
    if decision["status"] == "PASS":
        if part_c_start(lv_text) is None:
            return _unverified(
                f"{label}: the pasted text has no part C ('C Věcná práva zatěžující "
                f"nemovitosti…'), so its encumbrances weren't read — paste the whole "
                f"výpis, parts A to E. {_HINT}")
        unknown = unrecognised_entries(lv_text)
        if unknown:
            return _unverified(
                f"{label}: nothing blocking was recognised, but parts C–D hold "
                f"{len(unknown)} entr{'y' if len(unknown) == 1 else 'ies'} the screen "
                f"does not know ({'; '.join(unknown[:3])}) — read "
                f"{'it' if len(unknown) == 1 else 'them'} before relying on this title.")
    # Several units on one Czech LV are one owner's: a private lien may be
    # another unit's, but distress (exekuce, insolvence, a court's ban) binds
    # every unit the owner has.
    if decision["status"] == "REJECT" and decision.get("claude_may_clear") \
            and len(units) > 1:
        return _unverified(
            f"{label} lists {len(units)} units and "
            f"{decision['detail'].removeprefix('LV encumbrance: ')} — check part C "
            f"for this flat's unit before ruling it out.")
    decision["detail"] = f"{label}: {decision['detail']}"
    decision["market"] = "cz"
    return decision


def _place_matches(building: dict, district: str) -> bool:
    """The building found under the pin is in the listing's town."""
    words = {w for w in re.findall(r"[a-z]{4,}", fold(district or ""))
             if w not in ("okres", "mesto", "obec", "kraj")}
    if not words:
        return True
    place = fold(" ".join(str(building.get(k) or "") for k in
                          ("municipality", "part_of_town", "ku_name")))
    return any(w in place for w in words)


def check_building(row: dict) -> dict:
    """How far a listing gets without its výpis: the building under its map
    pin (RÚIAN → API KN), the building's LV and pending proceedings. Always
    UNVERIFIED; what was found is captured for the card and the LV to-do."""
    if row.get("lv_number"):
        ku = row.get("cadastral_area") or "k.ú. unknown"
        return _unverified(f"Flat LV {row['lv_number']} ({ku}) is set, but its contents "
                           f"weren't read. {_HINT}")
    if not cuzk_cz.enabled():
        return _unverified(f"No title deed read. {_HINT} With CZ_CUZK_API_KEY set (free, "
                           f"registrace.cuzk.gov.cz) the building and its LV are found "
                           f"from the map pin.")
    if row.get("coords_source") != "listing" or row.get("lat") is None:
        return _unverified("No title deed read — the listing has no map pin of its own "
                           f"to find its building by. {_HINT}")
    found = cuzk_cz.building_at_pin(row["lat"], row["lng"])
    if found["status"] != "OK":
        return _unverified(f"No title deed read — building lookup "
                           f"{found['status'].lower()}: {found['detail']}. {_HINT}")
    b = found["building"]
    if not _place_matches(b, row.get("district") or ""):
        return _unverified(f"No title deed read — the map pin is in "
                           f"{b.get('municipality') or b.get('ku_name')}, not "
                           f"{row.get('district')}. {_HINT}")
    captured = {"cadastral_area": b.get("ku_name") or "", "parcel_no": b.get("parcel_no"),
                "ku_code": b.get("ku_code"), "plot_lv": b.get("lv_no")}
    house = "/".join(b.get("house_numbers") or []) or "?"
    note = (f"Building č.p. {house} (k.ú. {b.get('ku_name') or '?'}), building LV "
            f"{b.get('lv_no') or '?'}, {len(b.get('units') or [])} unit(s)")
    if b.get("pending"):
        note += (f"; pending proceedings {', '.join(b['pending'][:3])} — a change of "
                 f"rights is under way")
    return _unverified(f"{note}. A flat's own LV is its unit's, and only the výpis shows "
                       f"what it carries. {_HINT}", parcel=captured)


def check_listing(row: dict) -> dict:
    """LV verdict for one Czech listing row (a get_pending_lv() row)."""
    from database import get_lv_document, get_listing_description
    from modules.lv_screen_cz import owner_is_cooperative
    doc = get_lv_document(row["id"])
    coop = is_cooperative(get_listing_description(row["id"])) or \
        bool(doc and owner_is_cooperative(doc))
    if doc:
        result = check_text(doc, row.get("lv_number"), row.get("cadastral_area") or "")
        if coop:
            return _unverified(
                "Cooperative flat (družstevní byt): no LV of its own — the pasted LV is "
                f"the cooperative's ({result['detail']}). The share transfer and the "
                "cooperative's debts are for a lawyer to check.")
        return result
    if coop:
        return _unverified("Cooperative flat (družstevní byt): no LV of its own — the "
                           "cooperative owns the building. Its LV, the share transfer and "
                           "the cooperative's debts are for a lawyer to check.")
    return check_building(row)


def lv_link(listing: dict) -> str:
    """Where to read the flat's LV by hand: ČÚZK's nahlížení do katastru."""
    return NAHLIZENI_URL


def quick_requests():
    return cuzk_cz.quick_requests()
