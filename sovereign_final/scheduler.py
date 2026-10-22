"""
scheduler.py — Sovereign Investor Dashboard
Runs the full pipeline every day at 06:00 CET.
On launch it runs only to catch up: when no run has succeeded since the last
06:00 (first start, the machine was off at 06:00, or the run failed).
Restarting the container, Docker Desktop or the PC does not re-run a pipeline
that already ran today. A 06:00 the machine slept through (the process was
suspended, not restarted) runs once when it wakes.
A run succeeds when at least one portal was read. A failed run (every scraper
blocked, say) is retried hourly, up to three times; each attempt's outcome is
written to data/pipeline_status.json, which the dashboard shows.
Keep this running alongside the dashboard.

The dashboard's ▶ RUN EVERYTHING button runs the same pipeline through
run_all_markets(), for anyone who runs the dashboard without this scheduler.

Markets (markets.py): Slovakia and Czechia each have their own pipeline —
their own portals (SCRAPERS[market]), steps, success record, retries and
status file — run one after the other under the one shared pipeline lock. A
market whose run fails, or whose step raises, does not stop the other's.
run_pipeline() with no market is the Slovak pipeline, exactly as before.
"""

import contextlib
import importlib
import logging, sys, os
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATA_DIR, LOGS_DIR

log = logging.getLogger("sovereign")
TZ  = pytz.timezone("Europe/Bratislava")
RUN_HOUR = 6

# When the last successful pipeline run finished — beside the database, on
# the sovereign_data volume in Docker, so it outlives the container.
LAST_RUN_FILE = os.path.join(DATA_DIR, "last_pipeline_run")


def _setup_logging() -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(os.path.join(LOGS_DIR, "scheduler.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per Claude call


def last_slot(now: datetime) -> datetime:
    """The most recent scheduled run time (06:00 Bratislava) at or before
    `now`. Localised per day, so it stays 06:00 across a DST change."""
    day = now.astimezone(TZ).date()
    slot = TZ.localize(datetime(day.year, day.month, day.day, RUN_HOUR))
    if slot > now:
        day -= timedelta(days=1)
        slot = TZ.localize(datetime(day.year, day.month, day.day, RUN_HOUR))
    return slot


def last_run_file(market: str = "sk") -> str:
    """LAST_RUN_FILE for Slovakia; a sibling named for any other market."""
    return LAST_RUN_FILE if market == "sk" else f"{LAST_RUN_FILE}_{market}"


def read_last_run(market: str = "sk") -> datetime | None:
    try:
        with open(last_run_file(market), encoding="utf-8") as f:
            when = datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None
    return when if when.tzinfo else None


def record_run(when: datetime, market: str = "sk") -> None:
    path = last_run_file(market)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(when.isoformat())


def catch_up_due(now: datetime, last_run: datetime | None) -> bool:
    """Whether a run is owed at startup: none has succeeded since the last
    06:00. A run interrupted before it finished (the PC shut down mid-run) or
    one that failed left no record, so it is owed too."""
    return last_run is None or last_run < last_slot(now)


# A failed run is tried again RETRY_AFTER later, up to MAX_ATTEMPTS a day
# (06:00 plus three retries): a portal that blocked the 06:00 run is often
# back within the hour.
RETRY_AFTER  = timedelta(hours=1)
MAX_ATTEMPTS = 4
# How long a run waits for a dashboard button's job to finish.
LOCK_WAIT_S  = 3600

# Each market's portals, in the order its pipeline reads them.
SCRAPERS = {
    "sk": (("Nehnutelnosti.sk", "scraper.nehnutelnosti"),
           ("Bazos.sk",         "scraper.bazos"),
           ("Topreality.sk",    "scraper.topreality")),
    # Sreality.cz is the largest Czech portal, but its robots.txt disallows
    # the whole site (see BLOCKED), so it isn't read.
    "cz": (("Bezrealitky.cz",   "scraper.bezrealitky"),
           ("Reality.iDNES.cz", "scraper.idnes"),
           ("Bazos.cz",         "scraper.bazos_cz")),
}
# Portals left out of a market's run, and why. 🔗 TEST CZ SITES re-checks
# them live.
BLOCKED = {
    "cz": (("Sreality.cz", "scraper.sreality",
            "robots.txt disallows the whole site to crawlers other than the named "
            "search engines (User-agent: * / Disallow: /)"),),
}
STEP_COUNT = 14          # the Slovak pipeline's steps


def step_count(market: str = "sk") -> int:
    """How many steps a market's pipeline has."""
    return STEP_COUNT if market == "sk" else 1 + len(SCRAPERS[market]) + len(_CZ_STEPS)


def active_markets() -> list[str]:
    """The markets with at least one portal to read — the ones a run covers."""
    return [m for m in SCRAPERS if SCRAPERS[m]]
# Listings the "Fill missing details" step re-reads per run. Listings whose
# page never shows a size stay on its list, so a run re-reads at most this
# many of them instead of all of them every day.
FILL_DETAILS_LIMIT = 100


def retry_due(now: datetime, last_run: datetime | None, status: dict | None) -> bool:
    """Whether a failed run should be tried again now: no run has succeeded
    since the last 06:00, the latest attempt (this slot's) failed, and its
    retry time has come. The scheduler sets no retry time once a day's
    attempts are used up."""
    if not catch_up_due(now, last_run) or not status:
        return False
    if status.get("state") != "failed" or status.get("slot") != last_slot(now).isoformat():
        return False
    try:
        retry_at = datetime.fromisoformat(status.get("next_retry_at") or "")
    except ValueError:
        return False
    return now >= retry_at


def _step(steps: list, n: int, name: str, fn, total: int = STEP_COUNT):
    """Run one pipeline step: log it, record its outcome in `steps`, and
    never let it stop the run. fn returns (result, message); the result is
    returned, or None when the step raised."""
    log.info(f"Step {n}/{total} — {name}")
    try:
        result, message = fn()
    except Exception as e:
        log.error(f"   ❌ {e}")
        steps.append({"step": name, "ok": False, "detail": str(e)[:300]})
        return None
    log.info(f"   ✅ {message}")
    steps.append({"step": name, "ok": True, "detail": message})
    return result


def call_here(module: str, func: str, **kwargs):
    """Run module.func(**kwargs) in this process. The dashboard passes its own
    `call` to run_pipeline instead, which runs the browser-driven steps in a
    subprocess as its buttons do."""
    return getattr(importlib.import_module(module), func)(**kwargs)


def _scrape(module: str, call=call_here):
    def run():
        n = call(module, "run", max_pages=10)
        return n, f"{n} listings"
    return run


def _run_steps(steps: list, call=call_here, progress=None,
               market: str = "sk") -> tuple[bool, str]:
    """The pipeline proper. Returns (ok, why not): a run is a success when at
    least one portal was read — the rest of the pipeline works on what the
    scrapers bring in, so a day with none of them has to be tried again.
    `progress(i, n, note)`, when given, hears which step is starting.

    Every step works on `market`'s listings only."""
    if market != "sk":
        return _run_market_steps(steps, market, call, progress)

    def step(n, name, fn):
        if progress:
            progress(n, STEP_COUNT, name)
        return _step(steps, n, name, fn)

    from modules.backup import run_backup
    step(1, "Backup", lambda: (None, run_backup()))

    scraped = set()
    for i, (name, module) in enumerate(SCRAPERS["sk"], start=2):
        if step(i, name, _scrape(module, call)) is not None:
            scraped.add(module)

    # Listings the scrapers saved without a price, a size or a district: a
    # listing with no price or size is never scored, and the daily scrape
    # does not open its page again. Nehnutelnosti only (enrich_pending.py).
    def fill_details():
        # A portal that just blocked the scrape would make every one of these
        # page reads wait out its timeout (25 s each), on every retry.
        if "scraper.nehnutelnosti" not in scraped:
            return None, "skipped (Nehnutelnosti.sk couldn't be read this run)"
        c = call("enrich_pending", "run", limit=FILL_DETAILS_LIMIT)
        return None, (f"{c['checked']} re-read | +price {c['price']} | +size {c['size']} | "
                      f"+district {c['district']} | {c['gone']} gone")
    step(5, "Fill missing details", fill_details)

    # Rent comps. Rentals (prenájom) feed the live €/m² rents; the rebuild
    # drops the scores of listings whose district rate moved, so the scoring
    # step below re-scores them on the new rent.
    def rent():
        from scraper.rentals import run as rentals
        summary = rentals(max_pages=5)
        return None, (f"{summary.get('rentals', 0)} rentals | "
                      f"{summary.get('keys', 0)} districts | "
                      f"{summary.get('rescored', 0)} queued for re-scoring")
    step(6, "Rent comps (prenájom)", rent)

    # Housekeeping: stale-listing deactivation + dev-project flagging. With no
    # portal read today, "not seen for 21 days" says nothing about a listing,
    # so a few blocked days in a row must not retire everything.
    for i, (name, fn) in enumerate(_market_steps("sk", scraped), start=7):
        step(i, name, fn)

    if not scraped:
        return False, f"all {len(SCRAPERS['sk'])} scrapers failed"
    return True, ""


def _market_steps(market: str, scraped: set) -> list[tuple[str, object]]:
    """The steps after the scrapers (and, in Slovakia, the missing details
    and rent comps): housekeeping, the LV check, the optional Claude
    enrichment, scoring, location, risk and portal copies — each on
    `market`'s listings only. `scraped` holds the portals read this run."""
    def housekeeping():
        from database import deactivate_stale_listings, backfill_dev_project_flags
        dev = backfill_dev_project_flags()
        if not scraped:
            return None, f"flagged {dev} dev projects | stale check skipped (no portal read)"
        stale = deactivate_stale_listings(days=21, market=market)
        return None, f"Deactivated {stale} stale | flagged {dev} dev projects"

    def lv():
        from modules.debt_bot import run_debt_filter
        p, r, u = run_debt_filter(market=market)
        return None, f"Clean: {p} | Rejected: {r} | Unverified: {u}"

    # Optional; needs ANTHROPIC_API_KEY (no-op without). Before scoring, so
    # blank districts resolve to a real rent rate instead of the €6.50/m²
    # default.
    def addresses():
        from modules.address_enrichment import run_address_enrichment
        return None, f"{run_address_enrichment(market=market)} districts resolved"

    # Optional; needs ANTHROPIC_API_KEY. Before scoring, so parking/furnished
    # rent premiums are available to the cashflow engine.
    def descriptions():
        from modules.description_enrichment import run_description_enrichment
        return None, f"{run_description_enrichment(market=market)} descriptions parsed"

    def scoring():
        from modules.cashflow_runner import run_scoring
        return None, f"{run_scoring(market=market)} scored"

    def location():
        from modules.location_iq import run_location_scoring
        return None, f"{run_location_scoring(limit=200, market=market)} scored"

    # Noise / flood / construction for listings located before the real risk
    # data existed (bounded per run).
    def risk():
        from modules.location_iq import run_risk_backfill
        return None, f"{run_risk_backfill(limit=100, market=market)} listings"

    # Last, so it sees today's prices and LV verdicts.
    def merge():
        from database import mark_duplicates
        return None, f"{mark_duplicates(market=market)} listings in multi-portal groups"

    return [("Housekeeping", housekeeping), ("LV Debt Filter", lv),
            ("Address Normalization", addresses),
            ("Description Enrichment", descriptions), ("Cash-Flow Scoring", scoring),
            ("Location IQ", location), ("Risk backfill", risk),
            ("Merge portal copies", merge)]


# A market other than Slovakia: backup, its portals, its rent comps, then the
# shared steps above.
_CZ_STEPS = ("Rent comps",) + tuple(name for name, _ in _market_steps("cz", set()))


def _run_market_steps(steps: list, market: str, call=call_here,
                      progress=None) -> tuple[bool, str]:
    """A non-Slovak market's pipeline: its own portals and rent comps, then
    the steps every market shares (_market_steps), all on its listings."""
    total = step_count(market)

    def step(n, name, fn):
        if progress:
            progress(n, total, name)
        return _step(steps, n, name, fn, total)

    from modules.backup import run_backup
    step(1, "Backup", lambda: (None, run_backup()))

    scraped = set()
    for i, (name, module) in enumerate(SCRAPERS[market], start=2):
        if step(i, name, _scrape(module, call)) is not None:
            scraped.add(module)
    n = 2 + len(SCRAPERS[market])

    def rent():
        from importlib import import_module
        summary = import_module(f"scraper.rentals_{market}").run(max_pages=5)
        return None, (f"{summary.get('rentals', 0)} rentals | "
                      f"{summary.get('keys', 0)} districts | "
                      f"{summary.get('rescored', 0)} queued for re-scoring")
    step(n, "Rent comps", rent)
    for i, (name, fn) in enumerate(_market_steps(market, scraped), start=n + 1):
        step(i, name, fn)

    if not scraped:
        return False, f"all {len(SCRAPERS[market])} scrapers failed"
    return True, ""


def run_pipeline(trigger: str = "06:00", holder: str | None = None,
                 call=call_here, progress=None, market: str = "sk") -> bool:
    """One attempt at a market's daily pipeline (Slovakia's by default).
    Records the attempt in the market's status file either way, and the
    finish time (which stops catch-ups and retries) only when it succeeded.
    Returns success.

    The scheduler takes the pipeline lock itself. The dashboard's RUN
    EVERYTHING already holds it when it calls this: it passes the name it
    holds the lock under as `holder`, so the status can tell a run in
    progress from one that died. run_all_markets holds it the same way."""
    from modules import pipeline_state

    tag = "" if market == "sk" else f" [{market.upper()}]"
    start = datetime.now(TZ)
    slot = last_slot(start).isoformat()
    prev = pipeline_state.read_status(market) or {}
    attempt = prev.get("attempt", 0) + 1 if prev.get("slot") == slot else 1
    status = {"slot": slot, "attempt": attempt, "trigger": trigger,
              "holder": holder or "scheduler",
              "state": "running", "started_at": start.isoformat(), "steps": []}
    if market != "sk":
        status["market"] = market
    try:
        pipeline_state.write_status(status, market)
    except OSError as e:
        log.error(f"Couldn't write the run status: {e}")

    log.info("=" * 60)
    log.info(f"🚀 PIPELINE START{tag} — {start.strftime('%Y-%m-%d %H:%M CET')} "
             f"({trigger}, attempt {attempt})")
    log.info("=" * 60)

    ok, error = False, ""
    try:
        from database import init_db
        init_db()
        log.info("✅ DB ready")
    except Exception as e:
        log.error(f"❌ DB: {e}")
        error = f"database: {e}"
    else:
        lock = (contextlib.nullcontext() if holder else
                pipeline_state.PipelineLock("scheduler", wait_s=LOCK_WAIT_S))
        try:
            with lock:
                ok, error = _run_steps(status["steps"], call=call, progress=progress,
                                       market=market)
        except pipeline_state.PipelineBusy as busy:
            error = f"{busy} — still busy after {LOCK_WAIT_S // 60} min"
            log.error(f"❌ {error}")

    end = datetime.now(TZ)
    summary = ""
    if status["steps"]:                 # the database opened
        try:
            from database import get_stats
            s = get_stats(market=market)
            summary = (f"🟢{s['green']} 🟡{s['yellow']} ⚪{s['white']} "
                       f"❌{s['rejected']} ⏳{s['pending']}")
        except Exception as e:
            log.error(f"Stats: {e}")
    elapsed = (end - start).seconds // 60
    failed = [st["step"] for st in status["steps"] if not st["ok"]]
    log.info("=" * 60)
    if ok:
        log.info(f"📊{tag} Done in ~{elapsed} min | {summary}"
                 + (f" | ⚠ failed: {', '.join(failed)}" if failed else ""))
    else:
        # An attempt that began before a 06:00 and failed after it (a startup
        # catch-up at 05:45 whose portals took past 06:00 to give up) is that
        # 06:00's first failed attempt: under the slot it started in,
        # retry_due() — which only retries this slot's failure — would never
        # try it again, and the 06:00 run it ran across never fires.
        if last_slot(end).isoformat() != slot:
            slot, attempt = last_slot(end).isoformat(), 1
            status.update(slot=slot, attempt=attempt)
        retry = end + RETRY_AFTER if attempt < MAX_ATTEMPTS else None
        if holder and holder != "scheduler":   # ▶ RUN EVERYTHING: no scheduler may be running to retry
            then = "Click ▶ RUN EVERYTHING to try again."
        elif retry:
            then = f"Retrying at {retry:%H:%M}."
        else:
            then = f"No more retries today ({attempt} attempts)."
        log.error(f"❌{tag} PIPELINE FAILED after ~{elapsed} min: {error}. {then}")
        status["next_retry_at"] = retry.isoformat() if retry else None
    log.info("=" * 60)

    status.update(state="ok" if ok else "failed", finished_at=end.isoformat(),
                  error=error, summary=summary)
    try:
        pipeline_state.write_status(status, market)
    except OSError as e:
        log.error(f"Couldn't write the run status: {e}")
    if ok:
        try:
            record_run(end, market)
        except OSError as e:
            log.error(f"Couldn't record the run: {e}")
    return ok


def _record_failure(market: str, trigger: str, holder: str | None, error: str) -> None:
    """A market's attempt that raised, or never got the lock, recorded like a
    failed run_pipeline: counted against the day's attempts, with its retry
    time — so the dashboard says so and the scheduler tries it again."""
    from modules import pipeline_state
    now = datetime.now(TZ)
    slot = last_slot(now).isoformat()
    prev = pipeline_state.read_status(market) or {}
    crashed = prev.get("state") == "running" and prev.get("slot") == slot
    if crashed:
        attempt = prev.get("attempt", 1)          # the crashed run counted itself
    else:
        attempt = prev.get("attempt", 0) + 1 if prev.get("slot") == slot else 1
    retry = now + RETRY_AFTER if attempt < MAX_ATTEMPTS else None
    status = {"slot": slot, "attempt": attempt, "trigger": trigger,
              "holder": holder or "scheduler", "state": "failed",
              "started_at": prev.get("started_at") if crashed else now.isoformat(),
              "finished_at": now.isoformat(), "error": error,
              "next_retry_at": retry.isoformat() if retry else None,
              "steps": prev.get("steps", []) if crashed else [], "summary": ""}
    if market != "sk":
        status["market"] = market
    try:
        pipeline_state.write_status(status, market)
    except OSError as e:
        log.error(f"Couldn't write the run status: {e}")


def run_all_markets(trigger: str = "06:00", holder: str | None = None,
                    call=call_here, progress=None, which=None) -> dict[str, bool]:
    """Every market's pipeline, one after the other, under the one shared
    pipeline lock: {market: success}. A market whose run fails — or raises —
    is recorded as failed and the next market runs anyway. `which` (a list
    of market codes) defaults to every market with portals to read
    (active_markets()).

    `progress(i, n, note)` hears the steps of all of them as one run, each
    note prefixed with its market."""
    from modules import pipeline_state
    todo = list(which or active_markets())
    total = sum(step_count(m) for m in todo)
    results: dict[str, bool] = {}

    def run_them():
        offset = 0
        for m in todo:
            def market_progress(i, n, note="", _o=offset, _m=m):
                if progress:
                    progress(_o + i, total, f"{_m.upper()} · {note}" if note else _m.upper())
            kwargs = dict(trigger=trigger, holder=holder or "scheduler", call=call,
                          progress=market_progress if progress else None)
            try:
                # Slovakia is called exactly as run_pipeline always was.
                results[m] = (run_pipeline(**kwargs) if m == "sk"
                              else run_pipeline(**kwargs, market=m))
            except Exception as e:
                log.error(f"❌ [{m.upper()}] pipeline crashed: {e}")
                _record_failure(m, trigger, holder, f"{type(e).__name__}: {e}")
                results[m] = False
            offset += step_count(m)

    if holder:
        run_them()
    else:
        try:
            # The lock lives in the database: a first start must create the
            # tables before taking it.
            from database import init_db
            init_db()
            with pipeline_state.PipelineLock("scheduler", wait_s=LOCK_WAIT_S):
                run_them()
        except pipeline_state.PipelineBusy as busy:
            error = f"{busy} — still busy after {LOCK_WAIT_S // 60} min"
            log.error(f"❌ {error}")
            now = datetime.now(TZ)
            for m in todo:
                # The lock holder (▶ RUN EVERYTHING, say) may have run this
                # market since the last 06:00 while we waited: its fresh
                # success stands — a "failed" over it would never be retried
                # (nothing is owed) and would show FAILED all day.
                if not catch_up_due(now, read_last_run(m)):
                    log.info(f"   [{m.upper()}] already ran since the last 06:00 — "
                             f"not recorded as failed.")
                    results[m] = True
                    continue
                _record_failure(m, trigger, None, error)
                results[m] = False
        except Exception as e:
            error = f"pipeline could not start: {type(e).__name__}: {e}"
            log.error(f"❌ {error}")
            for m in todo:
                if m not in results:
                    _record_failure(m, trigger, None, error)
                    results[m] = False
    log.info("📊 Markets: " + " | ".join(
        f"{m.upper()} {'✅' if ok else '❌'}" for m, ok in results.items()))
    return results


def due_markets(now: datetime, kind: str = "catch_up") -> list[str]:
    """The active markets owed a run now: kind "catch_up" (no success since
    the last 06:00) or "retry" (a failed attempt whose retry time has come)."""
    from modules import pipeline_state
    out = []
    for m in active_markets():
        last = read_last_run(m)
        if kind == "retry":
            if retry_due(now, last, pipeline_state.read_status(m)):
                out.append(m)
        elif catch_up_due(now, last):
            out.append(m)
    return out


# This process's own runs, one at a time: a retry that comes due while the
# 06:00 run is still on its next market waits for it (the next 10-minute
# tick), instead of queueing on the database lock and losing an attempt.
_RUN_GUARD = threading.Lock()


def run_daily() -> None:
    with _RUN_GUARD:
        run_all_markets(trigger="06:00")


def retry_failed_run() -> None:
    if not _RUN_GUARD.acquire(blocking=False):
        return
    try:
        due = due_markets(datetime.now(TZ), "retry")
        if due:
            run_all_markets(trigger="retry", which=due)
    finally:
        _RUN_GUARD.release()


def arm(scheduler) -> None:
    """Add the daily 06:00 run and the 10-minute retry check to `scheduler`.

    The 06:00 run has no misfire grace: a process that was asleep at 06:00
    (the PC or Docker Desktop's VM suspended — neither restarts the
    container, so no startup catch-up runs) runs the missed 06:00 once when
    it wakes, at any hour, as a startup catch-up would. With a grace time
    APScheduler dropped it, and the retry check never ran it either (it
    retries failed runs only). coalesce: several missed 06:00s run once."""
    scheduler.add_job(
        run_daily,
        trigger=CronTrigger(hour=RUN_HOUR, minute=0, timezone=TZ),
        id="daily_pipeline",
        misfire_grace_time=None,
        coalesce=True,
    )
    scheduler.add_job(
        retry_failed_run,
        trigger=IntervalTrigger(minutes=10, timezone=TZ),
        id="retry_failed_run",
        coalesce=True,
    )


if __name__ == "__main__":
    _setup_logging()
    log.info(f"⏰ Sovereign Scheduler — 06:00 CET daily · markets: "
             f"{', '.join(m.upper() for m in active_markets())}")
    now = datetime.now(TZ)
    owed = due_markets(now)
    for m in active_markets():
        last = read_last_run(m)
        if m not in owed:
            log.info(f"   [{m.upper()}] last run finished "
                     f"{last.astimezone(TZ):%Y-%m-%d %H:%M} — not re-running on startup.")
    if owed:
        log.info(f"   No run since the last 06:00 for {', '.join(m.upper() for m in owed)} "
                 f"— running now...")
        with _RUN_GUARD:
            run_all_markets(trigger="catch-up", which=owed)

    scheduler = BlockingScheduler(timezone=TZ)
    arm(scheduler)
    log.info("✅ Scheduler armed. Next run: 06:00 CET (a failed run is retried hourly, "
             f"{MAX_ATTEMPTS - 1}× a day).")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Stopped.")
