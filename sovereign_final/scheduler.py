"""
scheduler.py — Sovereign Investor Dashboard
Runs the full pipeline every day at 06:00 CET.
Starts immediately on launch, then repeats daily.
Keep this running alongside the dashboard.
"""

import logging, sys, os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("sovereign")
TZ  = pytz.timezone("Europe/Bratislava")


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
        log.info("Step 1/5 — Nehnutelnosti.sk")
        from scraper.nehnutelnosti import run as s1
        n = s1(max_pages=10)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 2 — Bazos
    try:
        log.info("Step 2/5 — Bazos.sk")
        from scraper.bazos import run as s2
        n = s2(max_pages=10)
        log.info(f"   ✅ {n} listings")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 3 — LV Debt Filter
    try:
        log.info("Step 3/5 — LV Debt Filter")
        from modules.debt_bot import run_debt_filter
        p, r = run_debt_filter()
        log.info(f"   ✅ Passed: {p} | Rejected: {r}")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 4 — Cash-Flow Scoring
    try:
        log.info("Step 4/5 — Cash-Flow Scoring")
        from modules.cashflow_runner import run_scoring
        n = run_scoring()
        log.info(f"   ✅ {n} scored")
    except Exception as e:
        log.error(f"   ❌ {e}")

    # Step 5 — Location IQ
    try:
        log.info("Step 5/5 — Location IQ")
        from modules.location_iq import run_location_scoring
        n = run_location_scoring()
        log.info(f"   ✅ {n} scored")
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


if __name__ == "__main__":
    log.info("⏰ Sovereign Scheduler — 06:00 CET daily")
    log.info("   Running initial pipeline now...")
    run_pipeline()

    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(
        run_pipeline,
        trigger=CronTrigger(hour=6, minute=0, timezone=TZ),
        id="daily_pipeline",
        misfire_grace_time=3600,
    )
    log.info("✅ Scheduler armed. Next run: tomorrow 06:00 CET.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Stopped.")
