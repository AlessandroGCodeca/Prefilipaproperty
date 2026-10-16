"""
modules/lv_cz.py — the title-deed (LV, list vlastnictví) check for a Czech
listing, under modules/debt_bot's three verdicts:

  PASS        the flat's own výpis z LV was read and nothing in it blocks.
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
_COOP_RE = re.compile(
    r"vlastnictvi\s*:?\s*druzstev|druzstevn\w*\s+(?:byt|vlastnictv|podil)|"
    r"prevod\w*\s+(?:druzstevn\w*\s+)?(?:clensk\w*\s+prav|podil\w*\s+v\s+druzstv)")


def _unverified(detail: str, **extra) -> dict:
    return {"status": "UNVERIFIED", "detail": detail, "raw": {}, "market": "cz", **extra}


def is_cooperative(description: str) -> bool:
    """True when the listing says the flat is held in a cooperative."""
    return bool(_COOP_RE.search(fold(description or "")))


def check_text(lv_text: str, lv_number=None) -> dict:
    """The verdict on a pasted výpis z LV — modules/debt_bot._parse_lv with
    the Czech screen."""
    from modules.debt_bot import _parse_lv
    from modules.lv_screen_cz import screen_lv_cz, lv_number_in, unit_numbers
    stated = lv_number_in(lv_text)
    wanted = str(lv_number or "").strip()
    if wanted and stated and stated != wanted:
        return _unverified(f"The pasted výpis is LV {stated}; the card says the flat is "
                           f"on LV {wanted}. {_HINT}")
    decision = _parse_lv(lv_text, screen=screen_lv_cz)
    units = unit_numbers(lv_text)
    label = f"LV {stated or wanted}" if (stated or wanted) else "The pasted LV"
    if decision["status"] == "REJECT" and len(units) > 1:
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
    doc = get_lv_document(row["id"])
    coop = is_cooperative(get_listing_description(row["id"]))
    if doc:
        result = check_text(doc, row.get("lv_number"))
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
