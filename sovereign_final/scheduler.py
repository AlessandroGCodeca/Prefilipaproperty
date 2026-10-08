"""
scheduler.py — Sovereign Investor Dashboard
Runs the full pipeline every day at 06:00 CET.
On launch it runs only to catch up: when no run has succeeded since the last
06:00 (first start, the machine was off at 06:00, or the run failed).
Restarting the container, Docker Desktop or the PC does not re-run a pipeline
that already ran today.
A run succeeds when at least one portal was read. A failed run (every scraper
blocked, say) is retried hourly, up to three times; each attempt's outcome is
written to data/pipeline_status.json, which the dashboard shows.
Keep this running alongside the dashboard.
"""

import logging, sys, os
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


def read_last_run() -> datetime | None:
    try:
        with open(LAST_RUN_FILE, encoding="utf-8") as f:
            when = datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None
    return when if when.tzinfo else None


def record_run(when: datetime) -> None:
    os.makedirs(os.path.dirname(LAST_RUN_FILE), exist_ok=True)
    with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
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

SCRAPERS = (("Nehnutelnosti.sk", "scraper.nehnutelnosti"),
            ("Bazos.sk",         "scraper.bazos"),
            ("Topreality.sk",    "scraper.topreality"))
STEP_COUNT = 13


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


def _step(steps: list, n: int, name: str, fn):
    """Run one pipeline step: log it, record its outcome in `steps`, and
    never let it stop the run. fn returns (result, message); the result is
    returned, or None when the step raised."""
    log.info(f"Step {n}/{STEP_COUNT} — {name}")
    try:
        result, message = fn()
    except Exception as e:
        log.error(f"   ❌ {e}")
        steps.append({"step": name, "ok": False, "detail": str(e)[:300]})
        return None
    log.info(f"   ✅ {message}")
    steps.append({"step": name, "ok": True, "detail": message})
    return result


def _scrape(module: str):
    def run():
        import importlib
        n = importlib.import_module(module).run(max_pages=10)
        return n, f"{n} listings"
    return run


def _run_steps(steps: list) -> tuple[bool, str]:
    """The pipeline proper. Returns (ok, why not): a run is a success when at
    least one portal was read — the rest of the pipeline works on what the
    scrapers bring in, so a day with none of them has to be tried again."""
    from modules.backup import run_backup
    _step(steps, 1, "Backup", lambda: (None, run_backup()))

    scraped = 0
    for i, (name, module) in enumerate(SCRAPERS, start=2):
        if _step(steps, i, name, _scrape(module)) is not None:
            scraped += 1

    # Rent comps. Rentals (prenájom) feed the live €/m² rents; the rebuild
    # drops the scores of listings whose district rate moved, so the scoring
    # step below re-scores them on the new rent.
    def rent():
        from scraper.rentals import run as rentals
        summary = rentals(max_pages=5)
        return None, (f"{summary.get('rentals', 0)} rentals | "
                      f"{summary.get('keys', 0)} districts | "
                      f"{summary.get('rescored', 0)} queued for re-scoring")
    _step(steps, 5, "Rent comps (prenájom)", rent)

    # Housekeeping: stale-listing deactivation + dev-project flagging. With no
    # portal read today, "not seen for 21 days" says nothing about a listing,
    # so a few blocked days in a row must not retire everything.
    def housekeeping():
        from database import deactivate_stale_listings, backfill_dev_project_flags
        dev = backfill_dev_project_flags()
        if not scraped:
            return None, f"flagged {dev} dev projects | stale check skipped (no portal read)"
        stale = deactivate_stale_listings(days=21)
        return None, f"Deactivated {stale} stale | flagged {dev} dev projects"
    _step(steps, 6, "Housekeeping", housekeeping)

    def lv():
        from modules.debt_bot import run_debt_filter
        p, r, u = run_debt_filter()
        return None, f"Clean: {p} | Rejected: {r} | Unverified: {u}"
    _step(steps, 7, "LV Debt Filter", lv)

    # Optional; needs ANTHROPIC_API_KEY (no-op without). Before scoring, so
    # blank districts resolve to a real rent rate instead of the €6.50/m²
    # default.
    def addresses():
        from modules.address_enrichment import run_address_enrichment
        return None, f"{run_address_enrichment()} districts resolved"
    _step(steps, 8, "Address Normalization", addresses)

    # Optional; needs ANTHROPIC_API_KEY. Before scoring, so parking/furnished
    # rent premiums are available to the cashflow engine.
    def descriptions():
        from modules.description_enrichment import run_description_enrichment
        return None, f"{run_description_enrichment()} descriptions parsed"
    _step(steps, 9, "Description Enrichment", descriptions)

    def scoring():
        from modules.cashflow_runner import run_scoring
        return None, f"{run_scoring()} scored"
    _step(steps, 10, "Cash-Flow Scoring", scoring)

    def location():
        from modules.location_iq import run_location_scoring
        return None, f"{run_location_scoring(limit=200)} scored"
    _step(steps, 11, "Location IQ", location)

    # Noise / flood / construction for listings located before the real risk
    # data existed (bounded per run).
    def risk():
        from modules.location_iq import run_risk_backfill
        return None, f"{run_risk_backfill(limit=100)} listings"
    _step(steps, 12, "Risk backfill", risk)

    # Last, so it sees today's prices and LV verdicts.
    def merge():
        from database import mark_duplicates
        return None, f"{mark_duplicates()} listings in multi-portal groups"
    _step(steps, 13, "Merge portal copies", merge)

    if not scraped:
        return False, f"all {len(SCRAPERS)} scrapers failed"
    return True, ""


def run_pipeline(trigger: str = "06:00") -> bool:
    """One attempt at the daily pipeline. Records the attempt in
    pipeline_state's status file either way, and the finish time (which
    stops catch-ups and retries) only when it succeeded. Returns success."""
    from modules import pipeline_state

    start = datetime.now(TZ)
    slot = last_slot(start).isoformat()
    prev = pipeline_state.read_status() or {}
    attempt = prev.get("attempt", 0) + 1 if prev.get("slot") == slot else 1
    status = {"slot": slot, "attempt": attempt, "trigger": trigger,
              "state": "running", "started_at": start.isoformat(), "steps": []}
    try:
        pipeline_state.write_status(status)
    except OSError as e:
        log.error(f"Couldn't write the run status: {e}")

    log.info("=" * 60)
    log.info(f"🚀 PIPELINE START — {start.strftime('%Y-%m-%d %H:%M CET')} "
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
        try:
            with pipeline_state.PipelineLock("scheduler", wait_s=LOCK_WAIT_S):
                ok, error = _run_steps(status["steps"])
        except pipeline_state.PipelineBusy as busy:
            error = f"{busy} — still busy after {LOCK_WAIT_S // 60} min"
            log.error(f"❌ {error}")

    end = datetime.now(TZ)
    summary = ""
    if status["steps"]:                 # the database opened
        try:
            from database import get_stats
            s = get_stats()
            summary = (f"🟢{s['green']} 🟡{s['yellow']} ⚪{s['white']} "
                       f"❌{s['rejected']} ⏳{s['pending']}")
        except Exception as e:
            log.error(f"Stats: {e}")
    elapsed = (end - start).seconds // 60
    failed = [st["step"] for st in status["steps"] if not st["ok"]]
    log.info("=" * 60)
    if ok:
        log.info(f"📊 Done in ~{elapsed} min | {summary}"
                 + (f" | ⚠ failed: {', '.join(failed)}" if failed else ""))
    else:
        retry = end + RETRY_AFTER if attempt < MAX_ATTEMPTS else None
        log.error(f"❌ PIPELINE FAILED after ~{elapsed} min: {error}. "
                  + (f"Retrying at {retry:%H:%M}." if retry else
                     f"No more retries today ({attempt} attempts)."))
        status["next_retry_at"] = retry.isoformat() if retry else None
    log.info("=" * 60)

    status.update(state="ok" if ok else "failed", finished_at=end.isoformat(),
                  error=error, summary=summary)
    try:
        pipeline_state.write_status(status)
    except OSError as e:
        log.error(f"Couldn't write the run status: {e}")
    if ok:
        try:
            record_run(end)
        except OSError as e:
            log.error(f"Couldn't record the run: {e}")
    return ok


def retry_failed_run() -> None:
    from modules import pipeline_state
    if retry_due(datetime.now(TZ), read_last_run(), pipeline_state.read_status()):
        run_pipeline(trigger="retry")


if __name__ == "__main__":
    _setup_logging()
    log.info("⏰ Sovereign Scheduler — 06:00 CET daily")
    now, last = datetime.now(TZ), read_last_run()
    if catch_up_due(now, last):
        log.info("   No run since the last 06:00 — running the pipeline now...")
        run_pipeline(trigger="catch-up")
    else:
        log.info(f"   Last run finished {last.astimezone(TZ):%Y-%m-%d %H:%M} — "
                 f"not re-running on startup.")

    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(hour=RUN_HOUR, minute=0, timezone=TZ),
        id="daily_pipeline",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        retry_failed_run,
        trigger=IntervalTrigger(minutes=10, timezone=TZ),
        id="retry_failed_run",
        coalesce=True,
    )
    log.info("✅ Scheduler armed. Next run: 06:00 CET (a failed run is retried hourly, "
             f"{MAX_ATTEMPTS - 1}× a day).")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Stopped.")
