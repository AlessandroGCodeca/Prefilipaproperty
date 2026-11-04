"""Audit 6: the scheduler defects a regression hunt found in audit 5.

- The 06:00 job reading the clock a few seconds early (a wall clock stepped
  back after APScheduler's due check) must still run that 06:00's markets.
- A market that ▶ RUN EVERYTHING ran while the 06:00 job (or a retry) waited
  for the pipeline lock is not run again.
- A success stamped in the future (the clock was ahead, then corrected) does
  not make a market's day be skipped.
"""
import sys
import types
from datetime import datetime, timedelta

import pytest

import scheduler
from modules import pipeline_state
from scheduler import TZ


def at(d, h, mi=0, s=0):
    return TZ.localize(datetime(2026, 10, d, h, mi, s))


@pytest.fixture
def env(tmp_path, monkeypatch, full_db):
    from modules import backup
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", str(tmp_path / "data" / "last_run"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "data" / "status.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    for name in ("scraper.nehnutelnosti", "scraper.bazos", "enrich_pending", "scraper.rentals",
                 "scraper.rentals_cz", "modules.debt_bot", "modules.address_enrichment",
                 "modules.description_enrichment", "modules.cashflow_runner",
                 "modules.location_iq"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(scheduler.SCRAPERS, "cz", (("Fake.cz", "scraper.fake_cz_portal"),))
    now = [None]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0] if tz is None else now[0].astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    # Yesterday (Sun 18 Oct): both markets ran fine.
    for m in ("sk", "cz"):
        scheduler.record_run(at(18, 7), m)
        pipeline_state.write_status({"slot": at(18, 6).isoformat(), "attempt": 1,
                                     "trigger": "06:00", "holder": "scheduler", "state": "ok",
                                     "started_at": at(18, 6).isoformat(),
                                     "finished_at": at(18, 7).isoformat(),
                                     "error": "", "summary": "", "steps": []}, m)
    return now


def portals(monkeypatch, clock, plan, runs, who):
    def portal(m):
        def run(max_pages=10):
            dur, ok = plan[m].pop(0)
            t0 = clock[0]
            clock[0] = t0 + timedelta(minutes=dur)
            runs.append((m, who[0], t0.strftime("%H:%M:%S"), clock[0].strftime("%H:%M"), ok))
            if not ok:
                raise RuntimeError("HTTP 403")
            return 3
        return run
    monkeypatch.setitem(sys.modules, "scraper.topreality", types.SimpleNamespace(run=portal("sk")))
    monkeypatch.setitem(sys.modules, "scraper.fake_cz_portal", types.SimpleNamespace(run=portal("cz")))


def ticks(clock, until):
    while clock[0] + timedelta(minutes=10) < until:
        clock[0] += timedelta(minutes=10)
        scheduler.retry_failed_run()


def nothing_owed(at_time):
    return (scheduler.due_markets(at_time) == []
            and scheduler.due_markets(at_time, "retry") == [])


def test_a_six_oclock_run_read_a_few_seconds_early_still_runs(env, monkeypatch):
    clock = env
    runs, who = [], ["sched"]
    portals(monkeypatch, clock, {"sk": [(25, True)] * 5, "cz": [(15, True)] * 5}, runs, who)
    clock[0] = at(19, 5, 59, 57)       # the 06:00 job; the clock reads 3 s early
    scheduler.run_daily()
    ticks(clock, at(19, 23, 55))       # the 10-minute retry check, all day
    # Still this 06:00's run: each market runs once, and nothing is owed.
    assert [(r[0], r[4]) for r in runs] == [("sk", True), ("cz", True)]
    assert nothing_owed(at(19, 23, 55))


def test_a_market_run_while_the_six_oclock_job_waited_is_not_rerun(env, monkeypatch):
    clock = env
    runs, who = [], ["sched"]
    portals(monkeypatch, clock, {"sk": [(20, True), (20, False), (20, False), (20, False)],
                                 "cz": [(10, True), (10, True)]}, runs, who)
    real_ram = scheduler.run_all_markets
    pending = [at(19, 5, 50)]
    RealLock = pipeline_state.PipelineLock

    class Lock(RealLock):
        # The dashboard's run (another process) holds the lock 05:50-06:20;
        # the scheduler's acquire returns once it is done.
        def __enter__(self):
            if pending and self.holder == "scheduler":
                c = clock[0]
                clock[0] = pending.pop()
                who[0] = "dashboard"
                real_ram(trigger="dashboard", holder="dashboard: RUN EVERYTHING")
                who[0] = "sched"
                clock[0] = max(c, clock[0])
            return super().__enter__()
    monkeypatch.setattr(pipeline_state, "PipelineLock", Lock)
    clock[0] = at(19, 6, 0, 0)         # the 06:00 job, on time
    scheduler.run_daily()
    ticks(clock, at(19, 23, 55))
    # ▶ RUN EVERYTHING ran both markets while the 06:00 job waited for the
    # lock: the job runs neither again, so no "FAILED, retrying" is left.
    assert [(r[0], r[1]) for r in runs] == [("sk", "dashboard"), ("cz", "dashboard")]
    st = pipeline_state.read_status("sk")
    assert st.get("state") != "failed"
    assert pipeline_state.summarize(st, None, now=at(19, 23, 55))[0] != "error"
    assert nothing_owed(at(19, 23, 55))


def test_a_success_stamped_in_the_future_does_not_skip_the_day(env, monkeypatch):
    clock = env
    runs, who = [], ["sched"]
    portals(monkeypatch, clock, {"sk": [(25, True)] * 5, "cz": [(15, True)] * 5}, runs, who)
    # Sunday's run finished at 07:00 while the clock read Monday 07:00.
    scheduler.record_run(at(19, 7), "sk")
    clock[0] = at(19, 6, 0, 1)            # Monday's 06:00, the clock now right
    scheduler.run_daily()
    ticks(clock, at(19, 23, 55))
    assert [r[0] for r in runs] == ["sk", "cz"]
    assert nothing_owed(at(19, 23, 55))
