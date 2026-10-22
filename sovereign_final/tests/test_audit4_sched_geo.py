"""Audit 4, scheduler / Location IQ area (C15–C17). Synthetic data only; no
network and no real waiting: every pipeline step module is stubbed, the
scheduler's clock is fixed and moved by the stubs, and APScheduler's job
processing is driven by hand on that clock.

C15  A missed 06:00 caught up just before the next 06:00 ran past it, so
     APScheduler skipped that 06:00 (one instance at a time): a market that
     failed before 06:00 kept the old slot and got no run or retry all day.
C16  A startup catch-up that ran past 06:00 left a market that finished
     before 06:00 with no run or retry for the new day (the scheduler is
     armed after the catch-up, so that 06:00 never fires).
C17  Listings that never geocode came first on every Location IQ run and
     filled its per-run limit, so the listings behind them were never
     located."""

import ast
import sqlite3
import sys
import threading
import types
from datetime import datetime, timedelta, timezone

import pytest

import database as db
import modules.location_iq as liq
import scheduler
from modules import pipeline_state
from scheduler import TZ
from tests.conftest import make_listing


def at(d, h, mi=0):
    """October 2026, Bratislava time: Sat 17, Sun 18, Mon 19, Tue 20."""
    return TZ.localize(datetime(2026, 10, d, h, mi))


SATURDAY_RUN = at(17, 6, 40)
SUNDAY_SLOT, MONDAY_SLOT = at(18, 6), at(19, 6)


# ── fixtures ──────────────────────────────────────────────────────────────────
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
    """scheduler's clock, fixed at clock[0] (Bratislava time) until a test or
    a stubbed portal moves it."""
    now = [at(19, 5, 30)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0] if tz is None else now[0].astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    return now


@pytest.fixture
def runs(monkeypatch, clock):
    """Every run_all_markets call: (clock when called, trigger, which)."""
    calls = []
    real = scheduler.run_all_markets

    def spy(*a, **kw):
        calls.append((clock[0], kw.get("trigger"), kw.get("which")))
        return real(*a, **kw)
    monkeypatch.setattr(scheduler, "run_all_markets", spy)
    return calls


def _saturday_ok():
    """Both markets last succeeded on Saturday morning."""
    for m in ("sk", "cz"):
        scheduler.record_run(SATURDAY_RUN, m)
        pipeline_state.write_status({
            "slot": scheduler.last_slot(SATURDAY_RUN).isoformat(), "attempt": 1,
            "trigger": "06:00", "holder": "scheduler", "state": "ok",
            "started_at": SATURDAY_RUN.isoformat(), "finished_at": SATURDAY_RUN.isoformat(),
            "error": "", "summary": "", "steps": []}, m)


def _portal(monkeypatch, clock, module, ends_at, works):
    """A portal that takes until `ends_at` (when the clock is earlier), then
    reads 3 listings when works[0], else is blocked."""
    def run(max_pages=10):
        if clock[0] < ends_at:
            clock[0] = ends_at
        if not works[0]:
            raise RuntimeError("HTTP 403")
        return 3
    monkeypatch.setitem(sys.modules, module, types.SimpleNamespace(run=run))


def _sk(monkeypatch, clock, ends_at, works):
    # Slovakia's last portal; the other two fail to import (stubbed).
    _portal(monkeypatch, clock, "scraper.topreality", ends_at, works)


def _cz(monkeypatch, clock, ends_at, works):
    _portal(monkeypatch, clock, "scraper.fake_cz_portal", ends_at, works)


def _status(market):
    return pipeline_state.read_status(market)


# ── C15 a wake run past 06:00 runs what that skipped 06:00 owed ──────────────
class TestWakeRunPastSix:
    def test_a_market_that_failed_before_six_is_run_for_the_new_day(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        # The PC slept through Sunday 06:00 and woke on Monday at 05:30: the
        # missed run started then. Slovakia's portals gave up at 05:45,
        # Czechia ran to 06:15, so Monday's 06:00 fire was skipped.
        _saturday_ok()
        sk_works = [False]
        _sk(monkeypatch, clock, at(19, 5, 45), sk_works)
        _cz(monkeypatch, clock, at(19, 6, 15), [True])
        scheduler.run_daily()
        assert runs == [(at(19, 5, 30), "06:00", None),
                        (at(19, 6, 15), "catch-up", ["sk"])]
        sk = _status("sk")
        assert sk["state"] == "failed" and sk["slot"] == MONDAY_SLOT.isoformat()
        assert sk["attempt"] == 1 and sk["next_retry_at"] == at(19, 7, 15).isoformat()
        # The ticker retries it, and Slovakia gets Monday's data.
        assert scheduler.due_markets(at(19, 7, 20), "retry") == ["sk"]
        sk_works[0] = True
        clock[0] = at(19, 7, 20)
        scheduler.retry_failed_run()
        assert scheduler.read_last_run("sk") == at(19, 7, 20)
        assert scheduler.due_markets(at(19, 23, 50)) == []

    def test_the_dashboard_no_longer_promises_a_retry_that_never_comes(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 45), [False])
        _cz(monkeypatch, clock, at(19, 6, 15), [True])
        scheduler.run_daily()
        level, text = pipeline_state.summarize(_status("sk"), None, now=at(19, 9, 0))
        assert level == "error" and "Retrying at about 07:15" in text
        assert "05:45" not in text

    def test_a_market_that_succeeded_before_six_runs_again(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        # Its 05:45 success is Sunday's: Monday's 06:00 still owes it.
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 45), [True])
        _cz(monkeypatch, clock, at(19, 6, 15), [True])
        scheduler.run_daily()
        assert [r[2] for r in runs] == [None, ["sk"]]
        assert scheduler.read_last_run("sk") == at(19, 6, 15)
        assert scheduler.due_markets(at(19, 6, 20)) == []

    def test_a_market_failing_after_six_keeps_its_retries(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        # Slovakia's own attempt ran past 06:00: audit 3 (#21) moved it to
        # Monday's slot, so it is retried hourly and not run again at once.
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 6, 10), [False])
        _cz(monkeypatch, clock, at(19, 6, 20), [True])
        scheduler.run_daily()
        assert len(runs) == 1
        sk = _status("sk")
        assert sk["slot"] == MONDAY_SLOT.isoformat() and sk["attempt"] == 1
        assert sk["next_retry_at"] == at(19, 7, 10).isoformat()

    def test_a_lock_wait_failure_past_six_is_not_run_again(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        # RUN EVERYTHING held the lock until the scheduler gave up at 06:30:
        # both markets are recorded failed in Monday's slot (audit 3 #22) and
        # wait for their retry instead of queueing on the lock again.
        _saturday_ok()

        class BusyUntilHalfPast:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                clock[0] = at(19, 6, 30)
                raise pipeline_state.PipelineBusy({"holder": "dashboard: RUN EVERYTHING"})

            def __exit__(self, *exc):
                return False
        monkeypatch.setattr(pipeline_state, "PipelineLock", BusyUntilHalfPast)
        scheduler.run_daily()
        assert len(runs) == 1
        for m in ("sk", "cz"):
            st = _status(m)
            assert st["state"] == "failed" and st["slot"] == MONDAY_SLOT.isoformat()
            assert st["next_retry_at"] == at(19, 7, 30).isoformat()

    def test_a_wake_run_ending_before_six_leaves_six_to_the_scheduler(
            self, files, full_db, stubbed, clock, runs, monkeypatch):
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 40), [False])
        _cz(monkeypatch, clock, at(19, 5, 50), [True])
        scheduler.run_daily()
        assert len(runs) == 1
        assert scheduler.due_markets(at(19, 6, 0)) == ["sk", "cz"]   # the 06:00 job runs them

    def test_a_six_oclock_run_is_unchanged(self, files, full_db, stubbed, clock, runs,
                                           monkeypatch):
        _saturday_ok()
        clock[0] = at(19, 6, 0)
        _sk(monkeypatch, clock, at(19, 6, 20), [False])
        _cz(monkeypatch, clock, at(19, 6, 40), [True])
        scheduler.run_daily()
        assert runs == [(at(19, 6, 0), "06:00", None)]
        assert _status("sk")["next_retry_at"] == at(19, 7, 20).isoformat()


class TestWakeRunWithAPScheduler:
    def test_the_skipped_six_oclock_fire_is_made_up(self, files, full_db, stubbed, clock,
                                                    runs, monkeypatch):
        # APScheduler's own job processing on the fake clock, called by hand:
        # armed on Saturday night, asleep through Sunday 06:00, awake on
        # Monday at 05:30. Monday's 06:00 comes due while the woken run is
        # still on Czechia, and APScheduler skips it.
        import apscheduler.schedulers.base as aps_base
        from apscheduler.events import (EVENT_JOB_ERROR, EVENT_JOB_EXECUTED,
                                        EVENT_JOB_MAX_INSTANCES)
        from apscheduler.schedulers.base import BaseScheduler

        monkeypatch.setattr(aps_base, "datetime", scheduler.datetime)
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 45), [False])
        at_six, go_on, done = threading.Event(), threading.Event(), threading.Event()

        def cz_portal(max_pages=10):
            if clock[0] < at(19, 6, 0):
                clock[0] = at(19, 6, 0)
                at_six.set()
                go_on.wait(60)
                clock[0] = at(19, 6, 15)
            return 3
        monkeypatch.setitem(sys.modules, "scraper.fake_cz_portal",
                            types.SimpleNamespace(run=cz_portal))

        class ByHand(BaseScheduler):
            def wakeup(self):
                pass

            def shutdown(self, wait=True):
                super().shutdown(wait)

        events = []

        def listen(e):
            events.append((e.code, e.job_id, clock[0]))
            if e.job_id == "daily_pipeline" and e.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
                done.set()

        s = ByHand(timezone=TZ)
        s.add_listener(listen, EVENT_JOB_MAX_INSTANCES | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        scheduler.arm(s)
        s.remove_job("retry_failed_run")        # driven by hand below
        clock[0] = at(17, 22, 0)
        s.start()
        try:
            assert s.get_job("daily_pipeline").next_run_time == SUNDAY_SLOT
            clock[0] = at(19, 5, 30)
            s._process_jobs()                    # the missed Sunday 06:00 runs now
            assert at_six.wait(60)
            s._process_jobs()                    # Monday 06:00, while it still runs
            go_on.set()
            assert done.wait(60)
            next_fire = s.get_job("daily_pipeline").next_run_time
        finally:
            go_on.set()
            s.shutdown(wait=True)

        assert (EVENT_JOB_MAX_INSTANCES, "daily_pipeline", at(19, 6, 0)) in events
        assert (EVENT_JOB_EXECUTED, "daily_pipeline", at(19, 6, 15)) in events
        assert next_fire == at(20, 6, 0)
        assert runs == [(at(19, 5, 30), "06:00", None), (at(19, 6, 15), "catch-up", ["sk"])]
        sk = _status("sk")
        assert sk["slot"] == MONDAY_SLOT.isoformat()
        assert scheduler.due_markets(at(19, 7, 20), "retry") == ["sk"]


# ── C16 a startup catch-up past 06:00 runs what that 06:00 owed ──────────────
def _main_block():
    """scheduler.py's own `if __name__ == "__main__":` body, compiled."""
    with open(scheduler.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    main = next(n for n in tree.body if isinstance(n, ast.If)
                and ast.unparse(n.test) == "__name__ == '__main__'")
    return compile(ast.Module(body=main.body, type_ignores=[]), scheduler.__file__, "exec")


_MAIN = _main_block()


@pytest.fixture
def startup(monkeypatch, clock):
    """Run the scheduler's startup on the fake clock. BlockingScheduler is a
    stand-in that keeps the jobs and the time it was started, and returns."""
    armed = []

    class Armed:
        def __init__(self, timezone=None):
            self.jobs, self.started_at = {}, None
            armed.append(self)

        def add_job(self, func, trigger=None, id=None, **kw):
            self.jobs[id] = trigger

        def start(self):
            self.started_at = clock[0]

        def first_six_oclock(self):
            return self.jobs["daily_pipeline"].get_next_fire_time(None, self.started_at)

    monkeypatch.setattr(scheduler, "BlockingScheduler", Armed)
    monkeypatch.setattr(scheduler, "_setup_logging", lambda: None)

    def run():
        exec(_MAIN, dict(vars(scheduler)))     # a copy: the module keeps its globals
        return armed[-1]
    return run


class TestStartupPastSix:
    def test_a_market_that_failed_before_six_is_run_for_the_new_day(
            self, files, full_db, stubbed, clock, runs, startup, monkeypatch):
        # Started on Monday at 05:30 with both markets owed. Slovakia failed at
        # 05:45, Czechia ran to 06:15; armed at 06:15, the first 06:00 the
        # scheduler fires is Tuesday's.
        _saturday_ok()
        sk_works = [False]
        _sk(monkeypatch, clock, at(19, 5, 45), sk_works)
        _cz(monkeypatch, clock, at(19, 6, 15), [True])
        armed = startup()
        assert runs == [(at(19, 5, 30), "catch-up", ["sk", "cz"]),
                        (at(19, 6, 15), "catch-up", ["sk"])]
        assert armed.first_six_oclock() == at(20, 6, 0)
        sk = _status("sk")
        assert sk["slot"] == MONDAY_SLOT.isoformat() and sk["attempt"] == 1
        assert sk["next_retry_at"] == at(19, 7, 15).isoformat()
        assert scheduler.due_markets(at(19, 7, 20), "retry") == ["sk"]
        sk_works[0] = True
        clock[0] = at(19, 7, 20)
        scheduler.retry_failed_run()
        assert scheduler.due_markets(at(19, 12, 0)) == []

    def test_a_market_that_succeeded_before_six_runs_again(
            self, files, full_db, stubbed, clock, runs, startup, monkeypatch):
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 45), [True])
        _cz(monkeypatch, clock, at(19, 6, 15), [True])
        startup()
        assert [r[2] for r in runs] == [["sk", "cz"], ["sk"]]
        assert scheduler.read_last_run("sk") == at(19, 6, 15)
        assert scheduler.due_markets(at(19, 6, 20)) == []

    def test_a_market_the_catch_up_did_not_cover_is_run_too(
            self, files, full_db, stubbed, clock, runs, startup, monkeypatch):
        # Czechia ran on Sunday, so only Slovakia was owed at 05:30; by the
        # time its catch-up ends at 06:10, Monday's 06:00 owes Czechia too.
        _saturday_ok()
        scheduler.record_run(at(18, 7, 0), "cz")
        _sk(monkeypatch, clock, at(19, 6, 10), [True])
        _cz(monkeypatch, clock, at(19, 6, 30), [True])
        startup()
        assert [r[2] for r in runs] == [["sk"], ["cz"]]
        assert scheduler.read_last_run("cz") == at(19, 6, 30)
        assert scheduler.due_markets(at(19, 6, 40)) == []

    def test_a_market_failing_after_six_keeps_its_retries(
            self, files, full_db, stubbed, clock, runs, startup, monkeypatch):
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 45), [True])
        _cz(monkeypatch, clock, at(19, 6, 15), [False])
        startup()
        assert [r[2] for r in runs] == [["sk", "cz"], ["sk"]]      # not Czechia
        cz = _status("cz")
        assert cz["slot"] == MONDAY_SLOT.isoformat() and cz["attempt"] == 1
        assert cz["next_retry_at"] == at(19, 7, 15).isoformat()

    def test_a_catch_up_ending_before_six_is_unchanged(
            self, files, full_db, stubbed, clock, runs, startup, monkeypatch):
        _saturday_ok()
        _sk(monkeypatch, clock, at(19, 5, 40), [False])
        _cz(monkeypatch, clock, at(19, 5, 50), [True])
        armed = startup()
        assert len(runs) == 1
        assert armed.first_six_oclock() == at(19, 6, 0)

    def test_nothing_owed_at_startup_runs_nothing(
            self, files, full_db, stubbed, clock, runs, startup):
        for m in ("sk", "cz"):
            scheduler.record_run(at(18, 7, 0), m)
        armed = startup()
        assert runs == [] and armed.first_six_oclock() == at(19, 6, 0)


# ── C17 listings that never geocode do not hold up the rest ──────────────────
NO_PLACE = "Predám 2-izbový byt"                  # an ad title, not an address


@pytest.fixture
def geo(monkeypatch):
    """Nominatim and the risk lookups stubbed: an address with "byt" in it is
    not found. Returns the addresses geocoded, in order."""
    asked = []

    def nominatim(address, market="sk"):
        asked.append(address)
        return (None, None, "") if "byt" in address else (49.2231, 18.7394, "address")
    monkeypatch.setattr(liq, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(liq, "SCRAPE_DELAY_SEC", 0)
    monkeypatch.setattr(liq.risk_data, "geocode_nominatim", nominatim)
    monkeypatch.setattr(liq.risk_data, "assess", lambda lat, lng, precision, market="sk": {
        "nearest_transit_m": 120.0, "grocery_count": 1, "pharmacy_count": 1,
        "school_count": 1, "construction": None, "construction_detail": "",
        "noise": None, "noise_detail": "", "flood": None, "flood_detail": ""})
    return asked


@pytest.fixture
def ticking(monkeypatch):
    """database's clock moves on a second at every reading."""
    t = [datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)]

    class Tick(datetime):
        @classmethod
        def now(cls, tz=None):
            t[0] += timedelta(seconds=1)
            return t[0] if tz is None else t[0].astimezone(tz)
    monkeypatch.setattr(db, "datetime", Tick)


def _unlocated(lid, address=NO_PLACE, **over):
    db.upsert_listing(make_listing(lid, lv_status="UNVERIFIED", address_raw=address,
                                   district="", **over))


def _queue():
    return [r["id"] for r in db.get_unscored_location()]


def _located(full_db):
    conn = full_db()
    try:
        return [r[0] for r in conn.execute("SELECT listing_id FROM location_scores")]
    finally:
        conn.close()


class TestLocationQueue:
    def test_the_scheduler_step_reaches_the_listing_behind_200_failures(
            self, full_db, geo):
        # The scheduler's own step (limit 200). 200 older listings whose only
        # address is their ad title, then one at a real address: before the
        # fix every run spent its 200 geocodes on the same 200 failures.
        for i in range(200):
            _unlocated(f"bad{i:03d}", f"{NO_PLACE} {i}")
        _unlocated("good", "Hlavná 1, Žilina")
        step = dict(scheduler._market_steps("sk", {"scraper.bazos"}))["Location IQ"]
        assert step() == (None, "0 scored")
        assert len(geo) == 200 and "Hlavná 1, Žilina" not in geo
        geo.clear()
        assert step() == (None, "1 scored")
        assert geo[0] == "Hlavná 1, Žilina" and len(geo) == 200
        assert _located(full_db) == ["good"]

    def test_a_failed_geocode_goes_to_the_back_of_the_queue(self, full_db, geo, ticking):
        for lid in ("a", "b", "c"):
            _unlocated(lid, f"{NO_PLACE} {lid}")
        _unlocated("d", "Hlavná 1, Žilina")
        assert liq.run_location_scoring(limit=2) == 0
        assert _queue() == ["c", "d", "a", "b"]
        assert liq.run_location_scoring(limit=2) == 1
        assert _located(full_db) == ["d"]
        assert _queue() == ["a", "b", "c"]

    def test_failed_listings_take_turns(self, full_db, geo, ticking):
        # Nothing is given up on: every failure is tried again, least
        # recently tried first.
        for lid in ("a", "b", "c"):
            _unlocated(lid, f"{NO_PLACE} {lid}")
        for _ in range(3):
            liq.run_location_scoring(limit=2)
        assert geo == [f"{NO_PLACE} {x}" for x in ("a", "b", "c", "a", "b", "c")]

    def test_listings_never_tried_keep_their_order(self, full_db, ticking):
        for lid in ("a", "b", "c", "d"):
            _unlocated(lid)
        assert _queue() == ["a", "b", "c", "d"]
        db.mark_location_tried("b")
        db.mark_location_tried("a")
        assert _queue() == ["c", "d", "b", "a"]
        db.mark_location_tried("b")
        assert _queue() == ["c", "d", "a", "b"]

    def test_a_failure_writes_no_location_row(self, full_db, geo):
        # A row with no coordinates would reach the map, the risk backfill
        # and the deal grade; the attempt is kept on the listing instead.
        _unlocated("a")
        liq.run_location_scoring()
        assert _located(full_db) == []
        conn = full_db()
        try:
            tried = conn.execute("SELECT location_tried_at FROM listings "
                                 "WHERE id='a'").fetchone()[0]
        finally:
            conn.close()
        assert tried and datetime.fromisoformat(tried).tzinfo is not None
        assert _queue() == ["a"]                  # still queued, tried again

    def test_a_czech_listing_takes_its_turn_too(self, full_db, geo, ticking):
        for lid in ("c1", "c2"):
            _unlocated(lid, f"{NO_PLACE} {lid}", market="cz", currency="CZK",
                       source="bezrealitky", url=f"https://example.cz/{lid}")
        _unlocated("c3", "Vinohradská 1, Praha", market="cz", currency="CZK",
                   source="bezrealitky", url="https://example.cz/c3")
        assert liq.run_location_scoring(limit=2, market="cz") == 0
        assert liq.run_location_scoring(limit=2, market="cz") == 1
        assert _located(full_db) == ["c3"]

    def test_an_older_database_gains_the_column(self, tmp_path, monkeypatch):
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(db.SQLITE_SCHEMA)
        conn.close()

        def _conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        monkeypatch.setattr(db, "get_conn", _conn)

        def cols():
            c = _conn()
            try:
                return [r[1] for r in c.execute("PRAGMA table_info(listings)")]
            finally:
                c.close()
        assert "location_tried_at" not in cols()
        assert db.get_unscored_location() == []
        assert db.get_unscored_location() == []            # idempotent
        assert cols().count("location_tried_at") == 1
