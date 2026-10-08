"""
modules/debt_bot.py — Sovereign Investor Dashboard
Module D: LV (List Vlastníctva) Debt-Bot

Hard stop: any non-bank lien, execution, or lawsuit = instant REJECTED.

Three verdicts, and only one of them says the title is clean:
  PASS        the flat's OWN LV was read and nothing on it blocks.
  REJECTED    the flat's own LV carries a blocking encumbrance.
  UNVERIFIED  no LV of this flat was read. The detail says how far the check
              got — often to the building plot under the listing's map pin.

Why a plot is never enough: identify_parcels() resolves a map pin to the land
parcel, and that parcel's LV is the plot's. A flat in a bytový dom is
registered with its own entry, usually on a different LV, sometimes on one LV
shared by the whole building — so a clean plot LV says nothing about the flat,
and a lien on it may be a neighbour's. A flat is verified through its own LV
number (set on the dashboard card from the seller's papers or the agent).

Decision layers on an LV that IS the flat's (most reliable first):
  1. Claude analyze_lv() — schema-validated risk read when ANTHROPIC_API_KEY is
     set. It can reject what the screen missed and clear a lien the screen
     couldn't attribute, but never an exekúcia / konkurz / súdny spor hit.
  2. modules/lv_screen — the always-on, entry-by-entry screen.
"""

import logging
import re

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import LV_RECHECK_DAYS
from database import (
    get_pending_lv, get_lv_row, set_lv_status, set_lv_analysis,
    set_parcel_data, set_flat_lv, reset_demo_rejections, init_db,
)
from kataster_scraper import enrich_parcel, enrich_lv, parcel_at, fold
from modules.lv_screen import screen_lv, describe
from engine.regional_prices import kraj_for_district
from modules.llm_enrichment import (
    is_enabled as claude_enabled, analyze_lv as claude_analyze_lv,
    LV_ANALYSIS_MAX_CHARS,
)

log = logging.getLogger(__name__)

_VERIFY_HINT = "Enter the flat's own LV number on its card to verify it."


def _unverified(detail: str, **extra) -> dict:
    return {"status": "UNVERIFIED", "detail": detail, "raw": {}, **extra}


# ── The screen ────────────────────────────────────────────────────────────────
def _parse_lv(lv_text) -> dict:
    """Screen one LV text entry by entry (modules/lv_screen). REJECT when any
    entry blocks; `raw` carries the text through to _decide_lv for Claude."""
    entries = screen_lv(lv_text)
    blocking = [e for e in entries if e["blocking"]]
    if blocking:
        return {
            "status": "REJECT", "flag": blocking[0]["flag"],
            "detail": "LV encumbrance: " + "; ".join(describe(e) for e in blocking[:3]),
            "raw": lv_text, "entries": entries,
            # Claude may overrule a lien it can attribute to a bank, never
            # distress (exekúcia / konkurz / súdny spor).
            "claude_may_clear": all(e["kind"] != "distress" for e in blocking),
        }
    banks = [e for e in entries if e["kind"] == "lien"]
    detail = "Clean title — no non-bank encumbrances"
    if banks:
        detail += f" ({len(banks)} bank lien(s): " \
                  + "; ".join(e["creditor"] or "?" for e in banks[:3]) + ")"
    return {"status": "PASS", "detail": detail, "raw": lv_text, "entries": entries}


_FLAT_NO_RE = re.compile(r"(?<!\w)byt\w*\s+c\.?\s*(\d+)")


def _flat_numbers(lv_text) -> set:
    """Flat numbers ("byt č. 12") an LV lists. More than one means the LV is
    shared by several flats, and its encumbrances may be another flat's."""
    return set(_FLAT_NO_RE.findall(fold(str(lv_text or ""))))


# ── Cadastre lookups (unofficial scraper — no API/key exists) ────────────────
def check_flat_lv(area, lv_no) -> dict:
    """Screen the flat's OWN LV — the only check that can PASS or REJECT."""
    result = enrich_lv(str(area), str(lv_no))
    if result["status"] != "OK" or not result.get("lv_text"):
        return _unverified(f"LV {lv_no} lookup {result['status'].lower()}: "
                           f"{result['detail']}")
    text = result["lv_text"]
    decision = _parse_lv(text)
    flats = _flat_numbers(text)
    if decision["status"] == "REJECT" and len(flats) > 1:
        # A shared LV: a lien on it may sit on another flat's share.
        return _unverified(
            f"LV {lv_no} is shared by {len(flats)} flats and lists "
            f"{decision['detail'].removeprefix('LV encumbrance: ')} — check "
            f"part C for this flat's number before ruling it out.")
    decision["detail"] = f"LV {lv_no}: {decision['detail']}"
    return decision


def _pin_matches_listing(parcel: dict, district: str) -> bool:
    """A pin in the wrong town (a portal's default pin, a mistyped address)
    must not hand this listing another town's parcel. The listing's district
    words have to appear in the parcel's municipality or cadastral unit."""
    words = {w for w in re.findall(r"[a-z]{4,}", fold(district or ""))
             if w not in ("okres", "mesto", "nove", "stare", "okolie")}
    if not words:
        return True
    ku = parcel.get("cadastral_unit") or {}
    place = fold(f"{parcel.get('municipality') or ''} {ku.get('name') or ''}")
    if any(w in place for w in words):
        return True
    # "Bratislava" / "Košice II" with the pin in a city part whose cadastral
    # unit is named for the part alone ("Petržalka", "Západ").
    if words <= {"bratislava", "kosice"}:
        kraj = kraj_for_district(place)
        return kraj is None or kraj == kraj_for_district(" ".join(words))
    return False


def check_plot(row: dict) -> dict:
    """How far a listing without its flat's LV number gets: the building plot
    under its map pin, and that plot's LV. Always UNVERIFIED — see the module
    docstring — but the plot data is captured (`parcel`) and what the plot LV
    shows is spelled out, so the manual check starts from the right parcel."""
    area, parcel_no = row.get("cadastral_area"), row.get("cadastral_number")
    ku_code, plot_lv = row.get("cadastral_unit_code"), row.get("plot_lv_number")
    captured = None
    if not (area and parcel_no):
        if row.get("coords_source") != "listing" or row.get("lat") is None:
            return _unverified(
                "No title deed read — the listing has no map pin of its own "
                f"to find its building by. {_VERIFY_HINT}")
        found = parcel_at(row["lat"], row["lng"])
        if found["status"] != "OK":
            return _unverified(
                f"No title deed read — building lookup "
                f"{found['status'].lower()}: {found['detail']}. {_VERIFY_HINT}")
        parcel = found["parcel"]
        ku = parcel.get("cadastral_unit") or {}
        if not _pin_matches_listing(parcel, row.get("district") or ""):
            return _unverified(
                f"No title deed read — the map pin is in "
                f"{parcel.get('municipality') or ku.get('name')}, not "
                f"{row.get('district')}. {_VERIFY_HINT}")
        area, parcel_no = ku.get("name") or "", parcel["no"]
        ku_code, plot_lv = ku.get("code"), parcel.get("lv_no")
        captured = {"cadastral_area": area, "parcel_no": parcel_no,
                    "ku_code": ku_code, "plot_lv": plot_lv}

    where = f"parcel {parcel_no} (k.ú. {area})"
    plot = enrich_parcel(str(ku_code or area), parcel_no, register="C")
    if plot["status"] != "OK":
        return _unverified(f"Building plot {where}; its LV lookup "
                           f"{plot['status'].lower()}: {plot['detail']}. "
                           f"{_VERIFY_HINT}", parcel=captured)
    plot_lv = (plot.get("lv") or {}).get("no", plot_lv)
    if captured and plot_lv is not None:
        captured["plot_lv"] = plot_lv
    note = f"Building plot {where}, plot LV {plot_lv}"
    if plot.get("lv_text"):
        found = [e for e in screen_lv(plot["lv_text"]) if e["blocking"]]
        if found:
            note += (" lists " + "; ".join(describe(e) for e in found[:2])
                     + " — it may concern another flat or the land")
    return _unverified(f"{note}. A flat's own LV differs from its plot's. "
                       f"{_VERIFY_HINT}", parcel=captured)


def check_listing(row: dict) -> dict:
    """LV verdict for one listing row (a get_pending_lv() row)."""
    area = row.get("cadastral_unit_code") or row.get("cadastral_area")
    if row.get("lv_number"):
        if not area:
            return _unverified(f"Flat LV {row['lv_number']} is set but its "
                               f"katastrálne územie is unknown — add it on the card.")
        return check_flat_lv(area, row["lv_number"])
    return check_plot(row)


# ── Unified LV decision (Claude-authoritative, screen fallback) ──────────────
def _decide_lv(api_result: dict) -> dict:
    """Refine a screened LV result with Claude's structured LV analysis.

    Runs only on LV text that is the flat's own (`raw`); an UNVERIFIED result
    carries none. When Claude is enabled its read is authoritative in both
    directions — it can REJECT what the screen missed and PASS a lien the
    screen couldn't attribute to a bank — with two exceptions: a distress hit
    (exekúcia, konkurz, súdny spor) stays REJECTED whatever Claude says, and so
    does any hit on an LV longer than Claude was shown (see
    LV_ANALYSIS_MAX_CHARS). Claude can still REJECT in both cases.

    Degrades gracefully — returns the screen's decision untouched when Claude
    is disabled, there's no LV text, the call fails, or it returns an UNKNOWN
    risk level. So the hard-stop safety net is never weaker than the screen.
    """
    if not claude_enabled():
        return api_result
    raw = api_result.get("raw")
    if not raw or api_result.get("status") == "UNVERIFIED":
        return api_result

    analysis = claude_analyze_lv(str(raw))
    if not analysis or analysis.get("risk_level") == "UNKNOWN":
        return api_result  # fall back to the screen's decision

    # analyze_lv() truncates; on a longer LV Claude never saw the end, where the
    # encumbrances are, so its "safe" cannot overrule what the screen found.
    saw_whole_lv = len(str(raw)) <= LV_ANALYSIS_MAX_CHARS
    flags = analysis.get("flags") or []
    summary = (analysis.get("summary") or "").strip()
    level = analysis.get("risk_level")
    note = f"[Claude {level}] {summary}".strip()

    decided = {
        "raw": raw,
        "llm_risk_level": level,
        "llm_analysis": summary,
        "llm_flags": flags,
    }
    if not analysis.get("is_safe_to_proceed") or level == "HIGH":
        decided.update({
            "status": "REJECT",
            "flag": flags[0] if flags else "LV_RISK",
            "detail": note or api_result.get("detail", "LV risk flagged by Claude"),
        })
    elif (api_result.get("status") == "REJECT"
          and not (api_result.get("claude_may_clear", True) and saw_whole_lv)):
        why = ("exekúcia / konkurz / súdny spor still blocks"
               if not api_result.get("claude_may_clear", True) else
               f"it only read the first {LV_ANALYSIS_MAX_CHARS} characters of a "
               f"longer LV and the encumbrances are listed last")
        decided.update({
            "status": "REJECT",
            "flag": api_result.get("flag", "LV_RISK"),
            "detail": f"{api_result.get('detail', '')} (Claude read it as "
                      f"{level}; {why})",
        })
    else:
        decided.update({
            "status": "PASS",
            "detail": note or api_result.get("detail", "Clean title"),
        })
    return decided


# ── Main Runner ───────────────────────────────────────────────────────────────
_DB_STATUS = {"PASS": "PASS", "REJECT": "REJECTED", "UNVERIFIED": "UNVERIFIED"}


def _check_and_store(row: dict, module: str = "debt_bot") -> dict:
    result = check_listing(row)
    parcel = result.get("parcel")
    if parcel:
        set_parcel_data(row["id"], parcel["cadastral_area"], parcel["parcel_no"],
                        parcel["ku_code"], parcel["plot_lv"])
    # Claude-authoritative refinement (no-op when disabled / not the flat's LV).
    result = _decide_lv(result)
    if result.get("llm_risk_level"):
        set_lv_analysis(row["id"], result["llm_risk_level"], result.get("llm_analysis", ""))
    set_lv_status(row["id"], _DB_STATUS[result["status"]],
                  result.get("flag", "DEBT_FLAG"), result.get("detail", ""),
                  module=module)
    return result


def run_debt_filter(progress_callback=None) -> tuple[int, int, int]:
    """Check every pending listing. Returns (passed, rejected, unverified) —
    `passed` counts only flats whose own LV was read and found clean."""
    # Heal rows the old demo mode fabricated: "[DEMO]" rejections hid real
    # listings behind invented liens. Reset them to PENDING so they get an
    # honest re-check below. Idempotent — a clean DB is a no-op.
    healed = reset_demo_rejections()
    if healed:
        log.info(f"♻️  Reset {healed} fabricated [DEMO] rejections back to PENDING.")

    pending = get_pending_lv(recheck_days=LV_RECHECK_DAYS)
    if not pending:
        log.info("✅ No pending LV checks.")
        return 0, 0, 0

    log.info(f"🔒 Running LV debt filter on {len(pending)} listings...")
    passed = rejected = unverified = plots = 0

    for i, row in enumerate(pending):
        addr = (row.get("address_raw") or "")[:55]
        if progress_callback:
            progress_callback(i + 1, len(pending), addr)

        result = _check_and_store(row)
        if result["status"] == "REJECT":
            rejected += 1
            log.warning(f"  ❌ {addr} — {result['detail']}")
        elif result["status"] == "PASS":
            passed += 1
            log.info(f"  ✅ {addr} — {result['detail']}")
        else:
            unverified += 1
            if result.get("parcel"):
                plots += 1

        # No pause needed here — kataster_scraper throttles its own requests
        # (CADASTRAL_DELAY_SEC) and cache hits shouldn't wait at all.

    if unverified:
        log.warning(f"  ⚠️  {unverified} UNVERIFIED — no LV of the flat itself was read "
                    f"({plots} building plot(s) found from map pins). Enter a flat's "
                    f"LV number on its card to verify it.")
    log.info(f"✅ LV filter complete. Clean: {passed} | Rejected: {rejected} | "
             f"Unverified: {unverified}")
    return passed, rejected, unverified


def reverify(listing_id: str, lv_number: str | None = None,
             cadastral_area: str = "") -> dict:
    """Re-check one listing's LV now — before committing to a purchase, or
    after entering the flat's own LV number (and its katastrálne územie).
    lv_number=None keeps the stored one; "" clears it."""
    if lv_number is not None:
        set_flat_lv(listing_id, lv_number, cadastral_area)
    row = get_lv_row(listing_id)
    if not row:
        return {"status": "ERROR", "detail": "Not found"}
    return _check_and_store(row, module="debt_bot_reverify")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run_debt_filter()
