"""Audit 3, database / scheduler area (#18–#24). Synthetic listings only; no
network: every pipeline step module is stubbed, and the clock is fixed where
a test depends on the time of day."""

import os
import runpy
import sys
import threading
import types
from datetime import datetime, timedelta, timezone

import pytest

import database as db
import scheduler
from modules import pipeline_state
from scheduler import TZ
from tests.conftest import make_listing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def at(y, mo, d, h, mi=0):
    return TZ.localize(datetime(y, mo, d, h, mi))


# ── shared fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def files(tmp_path, monkeypatch):
    """The success records, status files and backups in tmp_path."""
    from modules import backup
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", str(tmp_path / "data" / "last_run"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "data" / "status.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path


_STEP_MODULES = ("scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality",
                 "enrich_pending", "scraper.rentals", "scraper.rentals_cz",
                 "modules.debt_bot", "modules.address_enrichment",
                 "modules.description_enrichment", "modules.cashflow_runner",
                 "modules.location_iq", "scraper.fake_cz_portal")


@pytest.fixture
def stubbed(monkeypatch):
    """Every step module fails to import; Czechia gets one fake portal."""
    for name in _STEP_MODULES:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(scheduler.SCRAPERS, "cz", (("Fake.cz", "scraper.fake_cz_portal"),))


@pytest.fixture
def clock(monkeypatch):
    """scheduler's clock, fixed at clock[0] (Bratislava time) until a test
    moves it."""
    now = [at(2026, 10, 17, 9, 0)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0] if tz is None else now[0].astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    return now


# ── #18 a market-scoped scoring run drops only its own market's scores ────────
def _two_markets_scored():
    db.upsert_listing(make_listing("sk1", district="Žilina", price_eur=100_000.0, size_m2=55.0))
    db.upsert_listing(make_listing("cz1", district="Praha 2", price_eur=4_500_000.0,
                                   size_m2=55.0, source="bezrealitky", market="cz",
                                   currency="CZK", url="https://example.cz/cz1",
                                   title="Byt 2+kk"))
    from modules.cashflow_runner import run_scoring
    assert run_scoring() == 2


def _scores(full_db):
    conn = full_db()
    try:
        return {r["id"]: (r["lc"], r["cc"]) for r in conn.execute(
            "SELECT l.id, l.classification AS lc, c.classification AS cc FROM listings l "
            "LEFT JOIN cashflow_scores c ON c.listing_id = l.id")}
    finally:
        conn.close()


def _set_scores(full_db, sql):
    conn = full_db()
    conn.execute(sql)
    conn.commit()
    conn.close()


class TestScopedRequeue:
    def test_czech_scoring_keeps_the_slovak_scores(self, full_db):
        # A Czech portal button (run_scoring(market="cz")) after a model
        # update used to drop every Slovak score and re-score none of them.
        _two_markets_scored()
        before = _scores(full_db)
        assert before["sk1"][1] is not None and before["cz1"][1] is not None
        _set_scores(full_db, "UPDATE cashflow_scores SET model_version = 1")
        from modules.cashflow_runner import run_scoring
        assert run_scoring(market="cz") == 1
        after = _scores(full_db)
        assert after["sk1"] == before["sk1"]          # still scored, not PENDING
        assert after["cz1"] == before["cz1"]          # re-scored

    def test_slovak_scoring_keeps_the_czech_scores(self, full_db):
        _two_markets_scored()
        before = _scores(full_db)
        _set_scores(full_db, "UPDATE cashflow_scores SET model_version = 1")
        from modules.cashflow_runner import run_scoring
        assert run_scoring(market="sk") == 1
        assert _scores(full_db) == before

    def test_an_unscoped_run_still_requeues_every_market(self, full_db):
        _two_markets_scored()
        before = _scores(full_db)
        _set_scores(full_db, "UPDATE cashflow_scores SET model_version = 1")
        from modules.cashflow_runner import run_scoring
        assert run_scoring() == 2
        assert _scores(full_db) == before

    def test_older_model_requeue_takes_a_market(self, full_db):
        _two_markets_scored()
        _set_scores(full_db, "UPDATE cashflow_scores SET model_version = 1")
        assert db.requeue_scores_from_older_model(market="cz") == 1
        s = _scores(full_db)
        assert s["cz1"] == ("PENDING", None) and s["sk1"][1] is not None
        assert db.requeue_scores_from_older_model(market="sk") == 1
        assert _scores(full_db)["sk1"] == ("PENDING", None)

    def test_stale_class_requeue_takes_a_market(self, full_db):
        _two_markets_scored()
        _set_scores(full_db, "UPDATE cashflow_scores SET max_price_green = 1")
        assert db.requeue_scores_with_stale_class(market="cz") == 1
        assert _scores(full_db)["sk1"][1] is not None
        assert db.requeue_scores_with_stale_class(market="sk") == 1
        assert _scores(full_db)["sk1"] == ("PENDING", None)

    def test_benchmark_requeue_takes_a_market(self, full_db):
        _two_markets_scored()
        # The Slovak score as if worked out before Žilina had a median.
        _set_scores(full_db, "UPDATE cashflow_scores SET regional_median_m2 = NULL "
                             "WHERE listing_id = 'sk1'")
        assert db.requeue_scores_without_benchmark(market="cz") == 0
        assert _scores(full_db)["sk1"][1] is not None
        assert db.requeue_scores_without_benchmark(market="sk") == 1
        assert _scores(full_db)["sk1"] == ("PENDING", None)

    def test_requeues_default_to_every_market(self, full_db):
        _two_markets_scored()
        _set_scores(full_db, "UPDATE cashflow_scores SET model_version = 1")
        assert db.requeue_scores_from_older_model() == 2


# ── #19 a 06:00 the machine slept through runs on waking ─────────────────────
class TestMissedSixOClock:
    def test_the_daily_job_has_no_misfire_grace(self):
        from apscheduler.schedulers.background import BackgroundScheduler
        s = BackgroundScheduler(timezone=TZ)
        scheduler.arm(s)
        daily = s.get_job("daily_pipeline")
        assert daily.misfire_grace_time is None and daily.coalesce
        assert daily.func is scheduler.run_daily
        assert str(daily.trigger.fields[5]) == "6" and str(daily.trigger.fields[6]) == "0"
        retry = s.get_job("retry_failed_run")
        assert retry.func is scheduler.retry_failed_run and retry.coalesce

    def test_a_process_waking_after_six_runs_the_missed_run(self, monkeypatch):
        # The PC slept 05:30–07:30: on waking the 06:00 run was 90 min late.
        # With misfire_grace_time=3600 APScheduler skipped it, and the retry
        # ticker only retries failures, so no run happened that day.
        from apscheduler.schedulers.background import BackgroundScheduler
        ran = threading.Event()
        monkeypatch.setattr(scheduler, "run_daily", ran.set)
        monkeypatch.setattr(scheduler, "retry_failed_run", lambda: None)
        s = BackgroundScheduler(timezone=TZ)
        s.start(paused=True)
        try:
            scheduler.arm(s)
            s.get_job("daily_pipeline").modify(
                next_run_time=datetime.now(TZ) - timedelta(minutes=90))
            s.resume()
            assert ran.wait(10)
            # Once, then the next 06:00 as usual.
            nxt = s.get_job("daily_pipeline").next_run_time
            assert nxt > datetime.now(TZ) and nxt.astimezone(TZ).hour == 6
        finally:
            s.shutdown(wait=False)

    def test_starting_after_six_does_not_fire_at_once(self, monkeypatch):
        # Startup is unchanged: the startup catch-up decides; the job's first
        # fire is the next 06:00 after the start.
        from apscheduler.schedulers.background import BackgroundScheduler
        monkeypatch.setattr(scheduler, "run_daily", lambda: None)
        s = BackgroundScheduler(timezone=TZ)
        scheduler.arm(s)
        s.start(paused=True)
        try:
            nxt = s.get_job("daily_pipeline").next_run_time
            assert nxt > datetime.now(TZ) and nxt - datetime.now(TZ) <= timedelta(days=1)
            assert nxt.astimezone(TZ).hour == 6
        finally:
            s.shutdown(wait=False)


# ── #20 restart.sh serves this computer only ─────────────────────────────────
def test_restart_binds_the_dashboard_to_this_computer():
    with open(os.path.join(ROOT, "restart.sh"), encoding="utf-8") as f:
        code = [ln for ln in f.read().splitlines() if not ln.lstrip().startswith("#")]
    runs = [ln for ln in code if "streamlit run app.py" in ln]
    assert runs and all("--server.address 127.0.0.1" in ln for ln in runs)


def test_docker_still_listens_inside_its_container():
    # Docker publishes the port on 127.0.0.1 itself; inside the container
    # Streamlit must listen on 0.0.0.0 to be reachable at all.
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        assert "--server.address 0.0.0.0" in f.read()


# ── #21 a failed attempt that ran past 06:00 is that 06:00's, and retried ────
def _slow_blocked_portal(monkeypatch, clock, ends_at):
    def run(max_pages=10):
        clock[0] = ends_at                 # the portals take this long to give up
        raise RuntimeError("blocked")
    monkeypatch.setitem(sys.modules, "scraper.bazos", types.SimpleNamespace(run=run))


class TestAttemptAcrossSix:
    def test_a_catch_up_failing_after_six_is_retried_that_day(
            self, files, full_db, stubbed, clock, monkeypatch):
        # Startup catch-up at 05:45 (yesterday's slot); every portal blocked,
        # giving up at 06:15. It used to keep yesterday's slot, so the ticker
        # never retried it and today's 06:00 never ran.
        clock[0] = at(2026, 10, 17, 5, 45)
        _slow_blocked_portal(monkeypatch, clock, at(2026, 10, 17, 6, 15))
        assert scheduler.run_all_markets(trigger="catch-up", which=["sk"]) == {"sk": False}
        st = pipeline_state.read_status("sk")
        assert st["state"] == "failed"
        assert st["slot"] == at(2026, 10, 17, 6).isoformat()
        assert st["attempt"] == 1
        assert st["next_retry_at"] == at(2026, 10, 17, 7, 15).isoformat()
        assert scheduler.due_markets(at(2026, 10, 17, 7, 20), "retry") == ["sk"]

    def test_the_next_attempt_counts_on_from_it(self, files, full_db, stubbed, clock,
                                                monkeypatch):
        clock[0] = at(2026, 10, 17, 5, 45)
        _slow_blocked_portal(monkeypatch, clock, at(2026, 10, 17, 6, 15))
        scheduler.run_pipeline(trigger="catch-up", holder="scheduler")
        clock[0] = at(2026, 10, 17, 7, 20)
        _slow_blocked_portal(monkeypatch, clock, at(2026, 10, 17, 7, 30))
        scheduler.run_pipeline(trigger="retry", holder="scheduler")
        st = pipeline_state.read_status("sk")
        assert st["slot"] == at(2026, 10, 17, 6).isoformat() and st["attempt"] == 2

    def test_an_attempt_within_one_slot_is_unchanged(self, files, full_db, stubbed,
                                                     clock, monkeypatch):
        clock[0] = at(2026, 10, 17, 6, 0)
        _slow_blocked_portal(monkeypatch, clock, at(2026, 10, 17, 6, 40))
        scheduler.run_pipeline(holder="scheduler")
        st = pipeline_state.read_status("sk")
        assert st["slot"] == at(2026, 10, 17, 6).isoformat() and st["attempt"] == 1
        assert st["next_retry_at"] == at(2026, 10, 17, 7, 40).isoformat()

    def test_a_success_across_six_is_recorded_as_before(self, files, full_db, stubbed,
                                                        clock, monkeypatch):
        clock[0] = at(2026, 10, 17, 5, 45)

        def run(max_pages=10):
            clock[0] = at(2026, 10, 17, 6, 15)
            return 3
        monkeypatch.setitem(sys.modules, "scraper.bazos", types.SimpleNamespace(run=run))
        assert scheduler.run_pipeline(holder="scheduler") is True
        st = pipeline_state.read_status("sk")
        assert st["state"] == "ok" and st["slot"] == at(2026, 10, 16, 6).isoformat()
        assert scheduler.read_last_run("sk") == at(2026, 10, 17, 6, 15)
        assert scheduler.due_markets(at(2026, 10, 17, 7, 20)) == ["cz"]   # Slovakia is done


# ── #22 a lock-wait failure leaves a market the holder already ran alone ────
def _ok_status(market, finished):
    pipeline_state.write_status({
        "slot": scheduler.last_slot(finished).isoformat(), "attempt": 1,
        "trigger": "dashboard", "holder": "dashboard: RUN EVERYTHING", "state": "ok",
        "started_at": (finished - timedelta(minutes=40)).isoformat(),
        "finished_at": finished.isoformat(), "error": "", "summary": "🟢1",
        "steps": []}, market)


class TestLockWaitAfterHolderRan:
    def test_a_market_the_holder_finished_keeps_its_success(self, files, full_db,
                                                            clock, monkeypatch):
        # RUN EVERYTHING finished Slovakia at 08:55 and still holds the lock
        # for Czechia when the scheduler gives up waiting at 09:00.
        monkeypatch.setattr(scheduler, "LOCK_WAIT_S", 0)
        scheduler.record_run(at(2026, 10, 17, 8, 55), "sk")
        _ok_status("sk", at(2026, 10, 17, 8, 55))
        with pipeline_state.PipelineLock("dashboard: RUN EVERYTHING"):
            results = scheduler.run_all_markets(trigger="06:00", which=["sk", "cz"])
        assert results == {"sk": True, "cz": False}
        sk = pipeline_state.read_status("sk")
        assert sk["state"] == "ok" and "next_retry_at" not in sk
        level, _ = pipeline_state.summarize(sk, None, now=at(2026, 10, 17, 9, 5))
        assert level == "ok"
        cz = pipeline_state.read_status("cz")         # still owed: failed, retried
        assert cz["state"] == "failed" and cz["next_retry_at"]
        assert "RUN EVERYTHING is running" in cz["error"]
        assert scheduler.due_markets(at(2026, 10, 17, 10, 5), "retry") == ["cz"]

    def test_a_run_before_six_is_still_owed(self, files, full_db, clock, monkeypatch):
        # Finished at 05:50: the 06:00 run is still owed, so it fails and retries.
        monkeypatch.setattr(scheduler, "LOCK_WAIT_S", 0)
        scheduler.record_run(at(2026, 10, 17, 5, 50), "sk")
        _ok_status("sk", at(2026, 10, 17, 5, 50))
        with pipeline_state.PipelineLock("dashboard: RUN EVERYTHING"):
            assert scheduler.run_all_markets(which=["sk"]) == {"sk": False}
        sk = pipeline_state.read_status("sk")
        assert sk["state"] == "failed" and sk["next_retry_at"]


# ── #23 the lock's "running since" is Bratislava time ────────────────────────
class TestLockTimeIsLocal:
    def test_summer_time(self):
        lock = {"holder": "scheduler", "acquired_at": "2026-07-15T04:00:00+00:00"}
        now = at(2026, 7, 15, 6, 30)
        assert pipeline_state.describe_lock(lock, now) == "scheduler is running (since 06:00)"

    def test_winter_time(self):
        lock = {"holder": "scheduler", "acquired_at": "2026-01-15T05:00:00+00:00"}
        now = at(2026, 1, 15, 6, 30)
        assert pipeline_state.describe_lock(lock, now) == "scheduler is running (since 06:00)"

    def test_today_is_the_local_day(self):
        # 22:30 UTC on 14 Jul is 00:30 on 15 Jul in Bratislava: today.
        lock = {"holder": "dashboard: BAZOS", "acquired_at": "2026-07-14T22:30:00+00:00"}
        assert pipeline_state.describe_lock(lock, at(2026, 7, 15, 1, 0)) == \
            "dashboard: BAZOS is running (since 00:30)"
        assert pipeline_state.describe_lock(lock, at(2026, 7, 16, 1, 0)) == \
            "dashboard: BAZOS is running (since 15 Jul 00:30)"

    def test_no_time_on_the_row(self):
        assert pipeline_state.describe_lock({"holder": None, "acquired_at": None}) == \
            "Another run is running (since ?)"

    def test_a_button_pressed_during_a_run_names_the_local_time(self, full_db):
        from modules import jobs
        with pipeline_state.PipelineLock("scheduler"):
            row = db.get_pipeline_lock()
            local = datetime.fromisoformat(row["acquired_at"]).astimezone(TZ)
            msg = jobs.start("RUN EVERYTHING", lambda p: ("success", "x"))
        assert msg.startswith("scheduler is running (since ")
        assert f"{local:%H:%M}). Try again" in msg
        assert datetime.fromisoformat(row["acquired_at"]).tzinfo == timezone.utc


# ── #24 diagnose.py prints each listing's own currency, each market's samples ─
def test_diagnose_prices_each_market_in_its_own_currency(full_db, capsys):
    for i, price in enumerate((120_000.0, 95_000.0, 80_000.0, 70_000.0)):
        db.upsert_listing(make_listing(f"sk{i}", price_eur=price, size_m2=60.0,
                                       url=f"https://example.sk/sk{i}"))
    db.upsert_listing(make_listing("cz1", price_eur=4_500_000.0, size_m2=55.0,
                                   district="Praha 2", source="bezrealitky", market="cz",
                                   currency="CZK", url="https://example.cz/cz1"))
    runpy.run_path(os.path.join(ROOT, "diagnose.py"), run_name="__main__")
    out = capsys.readouterr().out
    samples = out.split("=== Sample listings by classification ===")[1]
    lines = [ln for ln in samples.splitlines() if ln.strip().startswith("[")]
    # Slovakia's own top 3 first, in euros; the Czech one after, in CZK.
    assert [ln.split()[-1] for ln in lines] == ["sk0", "sk1", "sk2", "cz1"]
    assert "€  120000" in lines[0]
    assert "CZK  4500000" in lines[3] and "€" not in lines[3]


def test_diagnose_slovak_samples_print_as_before(full_db, capsys):
    db.upsert_listing(make_listing("sk1", price_eur=120_000.0, size_m2=60.0))
    runpy.run_path(os.path.join(ROOT, "diagnose.py"), run_name="__main__")
    out = capsys.readouterr().out
    assert ("    [bazos       ] €  120000   60.0m²  Žilina                     "
            "2-izbový byt sk1") in out.splitlines()
