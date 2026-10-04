"""
scheduler.py — Sovereign Investor Dashboard
Runs the full pipeline every day at 06:00 CET.
On launch it runs only to catch up: when no run has finished since the last
06:00 (first start, or the machine was off at 06:00). Restarting the
container, Docker Desktop or the PC does not re-run a pipeline that already ran
today.
Keep this running alongside the dashboard.
"""

import logging, sys, os
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATA_DIR, LOGS_DIR

log = logging.getLogger("sovereign")
TZ  = pytz.timezone("Europe/Bratislava")
RUN_HOUR = 6

# When the last pipeline run finished — beside the database, on the
# sovereign_data volume in Docker, so it outlives the container.
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
    """Whether a run is owed at startup: none has finished since the last
    06:00. A run interrupted before it finished (the PC shut down mid-run)
    left no record, so it is owed too."""
    return last_run is None or last_run < last_slot(now)


def run_pipeline():
    start = datetime.now(TZ)
    log.info("=" * 60)
    log.info(f"🚀 PIPELINE START — {start.strftime('%Y-%m-%d %H:%M CET')}")
    log.info("=" * 60)

    # DB init
    try:
        from database import init_db
        init_db()
        log.info("✅ DB ready")
    except Exception as e:
        log.error(f"❌ DB: {e}"); return

    # Step 1 — Nehnutelnosti
    try:
        log.info("Step 1/12 — Nehnutelnosti.sk")
        from scraper.nehnutelnosti import run as s1
        n = s1(max_pages=10)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 2 — Bazos
    try:
        log.info("Step 2/12 — Bazos.sk")
        from scraper.bazos import run as s2
        n = s2(max_pages=10)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 3 — Topreality
    try:
        log.info("Step 3/12 — Topreality.sk")
        from scraper.topreality import run as s3
        n = s3(max_pages=10)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 4 — Rent comps. Rentals (prenájom) feed the live €/m² rents; the
    # rebuild drops the scores of listings whose district rate moved, so the
    # scoring step below re-scores them on the new rent.
    try:
        log.info("Step 4/12 — Rent comps (prenájom)")
        from scraper.rentals import run as rentals
        summary = rentals(max_pages=5)
        log.info(f"   ✅ {summary.get('rentals', 0)} rentals | "
                 f"{summary.get('keys', 0)} districts | "
                 f"{summary.get('rescored', 0)} queued for re-scoring")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 5 — Housekeeping (stale-listing deactivation + dev-project flagging)
    try:
        log.info("Step 5/12 — Housekeeping")
        from database import deactivate_stale_listings, backfill_dev_project_flags
        stale = deactivate_stale_listings(days=21)
        dev   = backfill_dev_project_flags()
        log.info(f"   ✅ Deactivated {stale} stale | flagged {dev} dev projects")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 6 — LV Debt Filter
    try:
        log.info("Step 6/12 — LV Debt Filter")
        from modules.debt_bot import run_debt_filter
        p, r, u = run_debt_filter()
        log.info(f"   ✅ Clean: {p} | Rejected: {r} | Unverified: {u}")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 7 — Address Normalization (optional; needs ANTHROPIC_API_KEY).
    # No-op when no key is set. Runs before scoring so blank districts resolve
    # to a real rent rate instead of the €6.50/m² default.
    try:
        log.info("Step 7/12 — Address Normalization")
        from modules.address_enrichment import run_address_enrichment
        n = run_address_enrichment()
        log.info(f"   ✅ {n} districts resolved")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 8 — Description Enrichment (optional; needs ANTHROPIC_API_KEY).
    # No-op when no key is set. Runs before scoring so parking/furnished
    # rent premiums are available to the cashflow engine.
    try:
        log.info("Step 8/12 — Description Enrichment")
        from modules.description_enrichment import run_description_enrichment
        n = run_description_enrichment()
        log.info(f"   ✅ {n} descriptions parsed")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 9 — Cash-Flow Scoring
    try:
        log.info("Step 9/12 — Cash-Flow Scoring")
        from modules.cashflow_runner import run_scoring
        n = run_scoring()
        log.info(f"   ✅ {n} scored")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 10 — Location IQ
    try:
        log.info("Step 10/12 — Location IQ")
        from modules.location_iq import run_location_scoring
        n = run_location_scoring(limit=200)
        log.info(f"   ✅ {n} scored")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 11 — Risk backfill: noise / flood / construction for listings
    # located before the real risk data existed (bounded per run).
    try:
        log.info("Step 11/12 — Risk backfill")
        from modules.location_iq import run_risk_backfill
        n = run_risk_backfill(limit=100)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 12 — Merge the same flat listed on several portals. Last, so it
    # sees today's prices and LV verdicts.
    try:
        log.info("Step 12/12 — Merge portal copies")
        from database import mark_duplicates
        n = mark_duplicates()
        log.info(f"   ✅ {n} listings in multi-portal groups")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Summary
    try:
        from database import get_stats
        s = get_stats()
        elapsed = (datetime.now(TZ) - start).seconds // 60
        log.info("=" * 60)
        log.info(f"📊 Done in ~{elapsed} min | "
                 f"🟢{s['green']} 🟡{s['yellow']} ⚪{s['white']} ❌{s['rejected']} ⏳{s['pending']}")
        log.info("=" * 60)
    except Exception as e:
        log.error(f"Stats: {e}")

    try:
        record_run(datetime.now(TZ))
    except OSError as e:
        log.error(f"Couldn't record the run: {e}")


if __name__ == "__main__":
    _setup_logging()
    log.info("⏰ Sovereign Scheduler — 06:00 CET daily")
    now, last = datetime.now(TZ), read_last_run()
    if catch_up_due(now, last):
        log.info("   No run since the last 06:00 — running the pipeline now...")
        run_pipeline()
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
    log.info("✅ Scheduler armed. Next run: 06:00 CET.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Stopped.")
