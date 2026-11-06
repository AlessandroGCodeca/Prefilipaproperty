"""
dashboard/actions.py — what the sidebar's pipeline buttons run. Each step
runs on a worker thread (modules/jobs) under the lock the scheduler also
takes; the browser-driven ones (the scrapers, filling in missing details) in a
fresh subprocess.
"""

import logging
import os
import sys

import streamlit as st

from modules import jobs


# The project folder: the subprocess imports the scrapers from there.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Pipeline actions ──────────────────────────────────────────────────────────
# Each button's step runs on a worker thread (modules/jobs) under the lock the
# scheduler also takes. A step gets progress(i, n, note) and returns
# (level, message) for the sidebar.
# The step runs in the background, so it can take its time. Pages are stored
# as they are scraped: a run stopped at the limit keeps the pages it finished.
SCRAPER_TIMEOUT_S = 1800   # ten pages plus detail pages can pass 5 min cold


def _run_in_subprocess(module: str, func: str, kwargs: dict) -> tuple[object, str, bool]:
    """Run module.func(**kwargs) as a fresh subprocess — bypasses Python
    module cache, and a browser that hangs can be stopped. Returns (its
    result, error, stopped at SCRAPER_TIMEOUT_S)."""
    import subprocess, json as _json
    _dir = ROOT
    wrapper = f"""
import sys, os, json
sys.path.insert(0, {_dir!r})
try:
    import importlib
    mod = importlib.import_module({module!r})
    n = getattr(mod, {func!r})(**json.loads({_json.dumps(kwargs)!r}))
    print(json.dumps({{"ok": True, "n": n}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True, text=True, timeout=SCRAPER_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        # run() has killed the scraper; uncaught, this was a raw traceback.
        return None, "", True
    for line in (proc.stdout + proc.stderr).strip().splitlines():
        try:
            data = _json.loads(line)
            if data.get("ok"):
                return data["n"], "", False
            return None, data.get("error", "Unknown error"), False
        except Exception:
            continue
    stderr = proc.stderr.strip()
    return None, stderr or "Scraper produced no output", False


def _run_scraper_subprocess(script_name: str) -> tuple[int, str, bool]:
    """Run a scraper as a fresh subprocess. Returns (listings stored, error,
    stopped at SCRAPER_TIMEOUT_S)."""
    n, err, timed_out = _run_in_subprocess(f"scraper.{script_name}", "run", {"max_pages": 10})
    return n or 0, err, timed_out


def _call_in_subprocess(module: str, func: str, **kwargs):
    """scheduler.run_pipeline's `call` for ▶ RUN EVERYTHING: the browser-driven
    steps (the scrapers, filling in missing details) run in a subprocess, as
    their buttons run them. A failure raises, which fails that step only."""
    result, err, timed_out = _run_in_subprocess(module, func, kwargs)
    if err:
        raise RuntimeError(err)
    if timed_out:
        raise TimeoutError(f"stopped at the {SCRAPER_TIMEOUT_S // 60}-minute limit; "
                           f"what it finished is saved")
    return result


RUN_ALL = "RUN EVERYTHING"


def _run_outcome(ok: bool, status: dict) -> tuple[str, str]:
    """(level, message) for one market's full run."""
    if not ok:
        return "error", f"❌ Full run failed: {status.get('error') or 'unknown error'}."
    done = f"✅ Full run done: {status.get('summary') or 'see the tiles above'}."
    failed = [s["step"] for s in status.get("steps", []) if not s.get("ok")]
    if failed:
        return "warning", f"{done} ⚠ {len(failed)} step(s) failed — {', '.join(failed)}."
    return "success", done


def _all_step(progress):
    """The whole pipeline — the scheduler's run_all_markets, so a dashboard
    run and a 06:00 run do the same steps and record the same status. Each
    market runs on its own: one failing doesn't stop the other."""
    import scheduler
    from modules.pipeline_state import read_status
    # jobs.start() holds the pipeline lock as "dashboard: <label>" already.
    results = scheduler.run_all_markets(trigger="dashboard",
                                        holder=f"dashboard: {RUN_ALL}",
                                        call=_call_in_subprocess, progress=progress)
    outcomes = {m: _run_outcome(ok, read_status(m) or {}) for m, ok in results.items()}
    if list(outcomes) == ["sk"]:
        return outcomes["sk"]
    levels = {lvl for lvl, _ in outcomes.values()}
    level = ("success" if levels == {"success"} else
             "error" if levels == {"error"} else "warning")
    return level, " | ".join(f"{m.upper()} — {msg}" for m, (_, msg) in outcomes.items())


def _fill_step(progress):
    counts, err, timed_out = _run_in_subprocess("enrich_pending", "run", {"limit": 200})
    if err:
        return "error", f"❌ Fill missing details: {err}"
    # Stopped or not, each listing it re-read is saved: score what it filled.
    from modules.cashflow_runner import run_scoring
    scored = run_scoring()
    if timed_out:
        return "warning", (f"⏱ FILL MISSING DETAILS hit the {SCRAPER_TIMEOUT_S // 60}-minute "
                           f"limit and was stopped. The listings it finished are saved; "
                           f"scored {scored}. Click it again to carry on.")
    if not counts["checked"]:
        return "info", "ℹ️ No nehnutelnosti listing is missing a price, size or district."
    return "success", (f"✅ Re-read {counts['checked']}: +price {counts['price']}, "
                       f"+size {counts['size']}, +district {counts['district']}, "
                       f"{counts['gone']} taken down. Scored {scored}.")


# How old the Czech rentals may be before a Czech portal's button reads them
# again ahead of scoring. Under a day, so the 06:00 run's read counts for the
# day; a button clicked with none read since gets fresh comps first.
CZ_RENTALS_FRESH_H = 20


def _czech_rentals_if_stale() -> str:
    """Read the Czech rentals (scraper.rentals_cz) and rebuild their comps
    when none were read in the last CZ_RENTALS_FRESH_H hours — so a Czech
    town with no published rent figure can be scored from its live comps.
    Returns a note for the button's message ("" when they were fresh). A
    failure is only a note: scoring still runs on what is there."""
    from datetime import datetime, timedelta, timezone
    from engine.rent_comps_cz import last_rental_read
    last = last_rental_read()
    if last is not None and datetime.now(timezone.utc) - last < timedelta(hours=CZ_RENTALS_FRESH_H):
        return ""
    try:
        from scraper.rentals_cz import run as rentals_cz
        summary = rentals_cz(max_pages=5)
    except Exception as e:
        logging.getLogger("sovereign").exception("Czech rent comps failed")
        return f" Czech rent comps couldn't be read ({type(e).__name__}: {e})."
    return (f" Read {summary.get('rentals', 0)} Czech rentals first "
            f"({summary.get('keys', 0)} towns).")


def _scrape_step(module: str, name: str, button: str, market: str | None = None):
    """A portal's button. `market` (a Czech portal's "cz") keeps the
    follow-up steps to that market's listings; a Slovak button runs them as
    it always did. A Czech button reads the Czech rentals before it scores
    when they are stale, as the Czech pipeline does."""
    kw = {} if market is None else {"market": market}

    def step(progress):
        import scheduler
        from database.portal_runs import now_iso
        started = now_iso()
        n, err, timed_out = _run_scraper_subprocess(module)
        # What the portal returned, for the dashboard's quiet-portal flag.
        seen = scheduler._record_portal(
            market or "sk", f"scraper.{module}", started, n,
            err or (f"stopped at the {SCRAPER_TIMEOUT_S // 60}-minute limit" if timed_out else ""))
        if err:
            return "error", f"❌ {name}: {err}"
        if not seen and not timed_out:
            return "warning", (f"⚠ {name} ran but returned no listings — it may be blocked, "
                               f"or its page layout changed. 🔗 TEST SITES checks it.")
        # Stopped or not, what was stored gets the usual follow-up steps.
        from modules.address_enrichment import run_address_enrichment
        run_address_enrichment(**kw)
        from modules.description_enrichment import run_description_enrichment
        run_description_enrichment(**kw)
        rent_note = _czech_rentals_if_stale() if market == "cz" else ""
        from modules.cashflow_runner import run_scoring
        scored = run_scoring(**kw)
        from database import mark_duplicates
        mark_duplicates(**kw)
        if timed_out:
            from config import DETAIL_REFRESH_DAYS
            return "warning", (
                f"⏱ {name} hit the {SCRAPER_TIMEOUT_S // 60}-minute limit and was stopped. "
                f"The pages it finished are saved; scored {scored}. Click {button} again "
                f"to carry on — detail pages read in the last {DETAIL_REFRESH_DAYS} days "
                f"are not opened again, so each run gets further.{rent_note}")
        return "success", f"✅ {name}: scraped {n} listings, scored {scored}.{rent_note}"
    return step


def _lv_step(progress):
    from modules.debt_bot import run_debt_filter
    from database import mark_duplicates
    p, r, u = run_debt_filter(progress_callback=progress)
    mark_duplicates()           # a rejected copy flags the flat's other copies
    return "success", f"✅ LV done — Clean: {p}, Rejected: {r}, ⚠ Unverified: {u}"


def _cf_step(progress):
    from modules.cashflow_runner import run_scoring
    return "success", f"✅ Scored {run_scoring(progress_callback=progress)} listings"


def _desc_step(progress):
    from modules.description_enrichment import run_description_enrichment
    n = run_description_enrichment(progress_callback=progress)
    if n:
        return "success", f"✅ Parsed {n} descriptions. Re-score to apply rent premiums."
    return "info", ("ℹ️ Nothing parsed — set ANTHROPIC_API_KEY, or no new descriptions "
                    "to parse.")


def _addr_step(progress):
    from modules.address_enrichment import run_address_enrichment
    n = run_address_enrichment(progress_callback=progress)
    if n:
        return "success", f"✅ Resolved {n} blank districts. Re-score to apply rent rates."
    return "info", ("ℹ️ Nothing normalized — set ANTHROPIC_API_KEY, or no blank "
                    "districts with an address to resolve.")


def _rescore_step(progress):
    from database import clear_cashflow_scores
    from modules.cashflow_runner import run_scoring
    cleared = clear_cashflow_scores()
    n = run_scoring(progress_callback=progress)
    return "success", f"✅ Cleared {cleared} old scores, re-scored {n} listings"


def _loc_step(progress):
    from modules.location_iq import run_location_scoring
    return "success", f"✅ Location scored {run_location_scoring(progress_callback=progress)}"


def _reparse_step(progress):
    from database import requeue_descriptions_missing_extras
    from modules.description_enrichment import run_description_enrichment
    q = requeue_descriptions_missing_extras()
    n = run_description_enrichment(progress_callback=progress)
    return "success", f"✅ Re-queued {q}, parsed {n} descriptions."


def _risk_step(progress):
    from modules.location_iq import run_risk_backfill
    return "success", f"✅ Risk data added to {run_risk_backfill(progress_callback=progress)} listings"


def _rent_step(progress):
    """🏘️ RENT COMPS: the Slovak (prenájom) and Czech (pronájem) rentals,
    each on its own — one failing leaves the other's comps — then a scoring
    run on the new rates. Czech listings in a town with no published rent
    figure are scored only once its live comps exist."""
    from importlib import import_module
    from modules.cashflow_runner import run_scoring as _run_cf
    parts, failed = [], []
    for flag, label, module in (("🇸🇰", "districts", "scraper.rentals"),
                                ("🇨🇿", "towns", "scraper.rentals_cz")):
        try:
            summary = import_module(module).run(max_pages=5)
        except Exception as e:
            logging.getLogger("sovereign").exception(f"{flag} rent comps failed")
            failed.append(f"{flag} rent comps failed: {type(e).__name__}: {e}")
            continue
        parts.append(f"{flag} {summary.get('rentals', 0)} rentals across "
                     f"{summary.get('keys', 0)} {label} · "
                     f"{len(summary.get('changed', []))} rates moved")
    scored = _run_cf()
    text = " | ".join(parts + failed) + f" · re-scored {scored}."
    if not parts:
        return "error", "❌ " + text
    return ("warning", "⚠ " + text) if failed else ("success", "✅ " + text)


def _tax_step(progress):
    """🏛️ UPDATE TAX RATES: every Slovak town's rate from its site
    (modules/tax_rates) and every Czech municipality's coefficients from the
    official sources (modules/tax_rates_cz), then a scoring run for the
    listings whose tax it moved."""
    from modules import tax_rates, tax_rates_cz
    from modules.cashflow_runner import run_scoring
    sk = tax_rates.update(progress=progress)
    try:
        cz, cz_error = tax_rates_cz.update(progress=progress), ""
    except Exception as e:                     # Slovakia's result still stands
        logging.getLogger("sovereign").exception("Czech tax coefficients failed")
        cz, cz_error = None, f"{type(e).__name__}: {e}"
    if sk["requeued"] or (cz and cz["requeued"]):
        run_scoring()
    review = sk["counts"].get("review")
    level = "warning" if review or cz is None else "success"
    return level, ("🏛️ 🇸🇰 " + tax_rates.summary_text(sk)
                   + (" See the TAX RATES tab for the ones to review." if review else "")
                   + "  " + (tax_rates_cz.summary_text(cz) if cz else
                             f"🇨🇿 The Czech coefficients couldn't be updated: {cz_error}."))


def _dupes_step(progress):
    from database import mark_duplicates
    return "success", f"✅ {mark_duplicates()} listings are copies of a flat listed more than once."


def _stale_step(progress):
    """🧹 CLEAN STALE: every portal's listings not seen for 21 days — but not
    a quiet portal's (blocked or broken on its last runs), whose listings
    weren't seen because it couldn't be read."""
    import scheduler
    from database import deactivate_stale_listings, quiet_portals
    quiet = quiet_portals()
    n = deactivate_stale_listings(days=21, exclude_sources=[q["source"] for q in quiet])
    kept = (" Kept the listings of " + ", ".join(scheduler.portal_name(q["market"], q["source"])
                                                 for q in quiet)
            + ": no listings from it on its last runs, so not seeing them says nothing."
            if quiet else "")
    if n:
        return "success", f"✅ Deactivated {n} stale listings (last seen > 21 days ago).{kept}"
    return "info", f"ℹ️ No stale listings — all active rows seen within the last 21 days.{kept}"


def dispatch(sb) -> None:
    """Start the step of the sidebar button clicked on this run, as a job."""
    _cz_clicks = sb.cz_clicks
    do_addr = sb.do_addr
    do_all = sb.do_all
    do_bazos = sb.do_bazos
    do_cf = sb.do_cf
    do_desc = sb.do_desc
    do_dupes = sb.do_dupes
    do_fill = sb.do_fill
    do_loc = sb.do_loc
    do_lv = sb.do_lv
    do_nehnut = sb.do_nehnut
    do_rent = sb.do_rent
    do_reparse = sb.do_reparse
    do_rescore = sb.do_rescore
    do_risk = sb.do_risk
    do_stale = sb.do_stale
    do_tax = sb.do_tax
    do_topreal = sb.do_topreal
    for _clicked, _label, _step in (
        (do_all,     RUN_ALL,                  _all_step),
        (do_nehnut,  "NEHNUT",                 _scrape_step("nehnutelnosti", "Nehnutelnosti", "NEHNUT")),
        (do_bazos,   "BAZOS",                  _scrape_step("bazos", "Bazos", "BAZOS")),
        (do_topreal, "TOPREAL",                _scrape_step("topreality", "Topreality", "TOPREAL")),
        (do_fill,    "FILL MISSING DETAILS",   _fill_step),
        (do_lv,      "LV DEBT FILTER",         _lv_step),
        (do_cf,      "CASHFLOW SCORE",         _cf_step),
        (do_desc,    "PARSE DESC",             _desc_step),
        (do_addr,    "NORM ADDR",              _addr_step),
        (do_rescore, "RESCORE ALL",            _rescore_step),
        (do_loc,     "LOCATION IQ",            _loc_step),
        (do_reparse, "RE-PARSE",               _reparse_step),
        (do_risk,    "RISK BACKFILL",          _risk_step),
        (do_rent,    "RENT COMPS",             _rent_step),
        (do_tax,     "TAX RATES",              _tax_step),
        (do_dupes,   "MERGE PORTAL COPIES",    _dupes_step),
        (do_stale,   "CLEAN STALE",            _stale_step),
        *((_clicked_cz, _label_cz, _scrape_step(_module_cz.split(".", 1)[1], _name_cz,
                                                _label_cz, market="cz"))
          for _clicked_cz, _label_cz, _name_cz, _module_cz in _cz_clicks),
    ):
        if _clicked:
            _why = jobs.start(_label, _step)
            if _why:
                st.sidebar.warning(_why)
            else:
                # Watched from the start: a quick step can finish before the
                # page ever draws it running, and its result still gets the toast
                # and the redraw.
                st.session_state["_job_watch"] = jobs.current().id
                st.rerun()      # draw the sidebar with the job running
