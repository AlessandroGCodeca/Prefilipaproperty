"""scheduler.py used to run the whole pipeline on every container start, so a
Docker Desktop restart (or a PC reboot) re-scraped every portal and re-ran
every LV check. At startup it now only catches up a missed 06:00 run.

It also stamped a run done when every step had failed (audit O4). A run now
counts only when a portal was read; a failed one is retried hourly, and
every attempt is written to the status file the dashboard shows."""

import os
from datetime import datetime

import pytest

import config
import scheduler
from scheduler import TZ, catch_up_due, last_slot


def at(y, mo, d, h, mi=0):
    return TZ.localize(datetime(y, mo, d, h, mi))


class TestLastSlot:
    def test_after_six_is_today(self):
        assert last_slot(at(2026, 10, 4, 9, 30)) == at(2026, 10, 4, 6)

    def test_before_six_is_yesterday(self):
        assert last_slot(at(2026, 10, 4, 5, 59)) == at(2026, 10, 3, 6)

    def test_six_sharp_is_today(self):
        assert last_slot(at(2026, 10, 4, 6)) == at(2026, 10, 4, 6)

    def test_stays_six_across_dst(self):
        # 25 Oct 2026: clocks go back. Yesterday's slot is still 06:00 local.
        slot = last_slot(at(2026, 10, 26, 5))
        assert slot == at(2026, 10, 25, 6)
        assert slot.astimezone(TZ).hour == 6


class TestCatchUpDue:
    def test_first_start_runs(self):
        assert catch_up_due(at(2026, 10, 4, 9), None)

    def test_restart_after_todays_run_does_not_rerun(self):
        assert not catch_up_due(at(2026, 10, 4, 11), at(2026, 10, 4, 6, 40))

    def test_restart_before_six_after_yesterdays_run_does_not_rerun(self):
        assert not catch_up_due(at(2026, 10, 4, 2), at(2026, 10, 3, 6, 40))

    def test_missed_six_oclock_catches_up(self):
        # The PC was off at 06:00; it boots at 09:00 with yesterday's run last.
        assert catch_up_due(at(2026, 10, 4, 9), at(2026, 10, 3, 6, 40))


_STEP_MODULES = ("scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality",
                 "enrich_pending", "scraper.rentals", "modules.debt_bot",
                 "modules.address_enrichment", "modules.description_enrichment",
                 "modules.cashflow_runner", "modules.location_iq")


@pytest.fixture
def run_file(tmp_path, monkeypatch):
    """Every file a run writes — the success record, the status file and the
    backups — in tmp_path instead of the real data/ and backups/."""
    from modules import backup, pipeline_state
    path = str(tmp_path / "data" / "last_pipeline_run")
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", path)
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "data" / "status.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return path


@pytest.fixture
def steps_fail(monkeypatch):
    """Every step after the backup fails to import, until a test swaps a
    working module in with `steps_fail(name, module)`."""
    import sys
    import types
    for name in _STEP_MODULES:
        monkeypatch.setitem(sys.modules, name, None)

    def works(name, n=7):
        monkeypatch.setitem(sys.modules, name,
                            types.SimpleNamespace(run=lambda max_pages=10: n))
    return works


def _status():
    from modules import pipeline_state
    return pipeline_state.read_status()


class TestRunRecord:
    def test_missing_record_reads_as_never(self, run_file):
        assert scheduler.read_last_run() is None

    def test_round_trip(self, run_file):
        when = at(2026, 10, 4, 6, 42)
        scheduler.record_run(when)
        assert scheduler.read_last_run() == when

    def test_garbage_reads_as_never(self, run_file):
        os.makedirs(os.path.dirname(run_file))
        with open(run_file, "w") as f:
            f.write("not a date")
        assert scheduler.read_last_run() is None

    def test_a_run_whose_every_scraper_failed_is_not_recorded(self, run_file, full_db,
                                                                steps_fail):
        # Audit O4: each step caught its own error and the run was stamped
        # done anyway, so a blocked 06:00 run was never retried.
        assert scheduler.run_pipeline() is False
        assert scheduler.read_last_run() is None
        st = _status()
        assert st["state"] == "failed" and st["attempt"] == 1
        assert "scrapers failed" in st["error"]
        assert st["next_retry_at"]
        # With no portal read, "unseen for 21 days" means nothing.
        house = next(s for s in st["steps"] if s["step"] == "Housekeeping")
        assert "stale check skipped" in house["detail"]

    def test_one_portal_read_is_a_success_and_failed_steps_are_listed(
            self, run_file, full_db, steps_fail):
        steps_fail("scraper.bazos", 12)
        assert scheduler.run_pipeline() is True
        assert scheduler.read_last_run() is not None
        st = _status()
        assert st["state"] == "ok" and st["error"] == ""
        ok = {s["step"]: s["ok"] for s in st["steps"]}
        assert ok["Bazos.sk"] and ok["Backup"]
        assert not ok["Nehnutelnosti.sk"] and not ok["LV Debt Filter"]

    def test_attempts_are_counted_and_stop_retrying(self, run_file, full_db,
                                                    steps_fail):
        for n in range(1, scheduler.MAX_ATTEMPTS + 1):
            scheduler.run_pipeline(trigger="retry")
            assert _status()["attempt"] == n
        assert _status()["next_retry_at"] is None

    def test_a_pipeline_that_cannot_open_the_db_is_not_recorded(self, run_file,
                                                                monkeypatch):
        import database

        def boom():
            raise RuntimeError("disk full")
        monkeypatch.setattr(database, "init_db", boom)
        assert scheduler.run_pipeline() is False
        assert scheduler.read_last_run() is None
        assert _status()["error"] == "database: disk full"

    def test_a_dashboard_job_holding_the_lock_fails_the_attempt(
            self, run_file, full_db, steps_fail, monkeypatch):
        from modules import pipeline_state
        steps_fail("scraper.bazos")
        monkeypatch.setattr(scheduler, "LOCK_WAIT_S", 0)
        with pipeline_state.PipelineLock("dashboard: BAZOS"):
            assert scheduler.run_pipeline() is False
        assert "dashboard: BAZOS is running" in _status()["error"]
        assert scheduler.read_last_run() is None

    def test_the_backup_step_writes_a_copy_and_an_export(self, run_file, full_db,
                                                         steps_fail, tmp_path):
        scheduler.run_pipeline()
        names = sorted(os.listdir(tmp_path / "backups"))
        assert [n.split("-")[0] for n in names] == ["sovereign", "your"]


def _fake_call(calls, fill=None):
    """A run_pipeline `call` that records what it was asked to run."""
    def call(module, func, **kwargs):
        calls.append((module, func, kwargs))
        if module == "enrich_pending":
            return fill or {"checked": 4, "price": 1, "size": 2, "district": 0, "gone": 1}
        return 5
    return call


class TestDashboardRun:
    """The dashboard's ▶ RUN EVERYTHING runs run_pipeline: it already holds
    the pipeline lock, reports progress, and runs the browser-driven steps
    its own way."""

    HOLDER = "dashboard: RUN EVERYTHING"

    def test_progress_hears_every_step_in_order(self, run_file, full_db, steps_fail):
        heard = []
        scheduler.run_pipeline(call=_fake_call([]),
                               progress=lambda i, n, note: heard.append((i, n, note)))
        assert [i for i, _, _ in heard] == list(range(1, scheduler.STEP_COUNT + 1))
        assert {n for _, n, _ in heard} == {scheduler.STEP_COUNT}
        assert heard[0][2] == "Backup" and heard[-1][2] == "Merge portal copies"
        # Every step on the status file was announced, and none twice.
        assert [note for _, _, note in heard] == [s["step"] for s in _status()["steps"]]

    def test_call_runs_the_scrapers_and_the_missing_details(self, run_file, full_db,
                                                            steps_fail):
        calls = []
        assert scheduler.run_pipeline(call=_fake_call(calls)) is True
        assert calls == [
            ("scraper.nehnutelnosti", "run", {"max_pages": 10}),
            ("scraper.bazos", "run", {"max_pages": 10}),
            ("scraper.topreality", "run", {"max_pages": 10}),
            ("enrich_pending", "run", {"limit": scheduler.FILL_DETAILS_LIMIT}),
        ]
        fill = next(s for s in _status()["steps"] if s["step"] == "Fill missing details")
        assert fill["ok"] and "4 re-read" in fill["detail"] and "+size 2" in fill["detail"]

    def test_no_fill_when_nehnutelnosti_could_not_be_read(self, run_file, full_db,
                                                          steps_fail):
        # A portal that just blocked the scrape would make each of up to
        # FILL_DETAILS_LIMIT page reads wait out its timeout, on every retry.
        calls = []

        def call(module, func, **kwargs):
            calls.append(module)
            if module == "scraper.nehnutelnosti":
                raise RuntimeError("blocked")
            return 5
        assert scheduler.run_pipeline(call=call) is True
        assert "enrich_pending" not in calls
        fill = next(s for s in _status()["steps"] if s["step"] == "Fill missing details")
        assert fill["ok"] and "skipped" in fill["detail"]

    def test_a_failed_fill_does_not_fail_the_run(self, run_file, full_db, steps_fail):
        def call(module, func, **kwargs):
            if module == "enrich_pending":
                raise RuntimeError("no browser")
            return 5
        assert scheduler.run_pipeline(call=call) is True
        fill = next(s for s in _status()["steps"] if s["step"] == "Fill missing details")
        assert not fill["ok"] and "no browser" in fill["detail"]

    def test_the_holder_runs_under_its_own_lock(self, run_file, full_db, steps_fail,
                                                monkeypatch):
        # The scheduler would wait for this lock and then fail the attempt
        # (test_a_dashboard_job_holding_the_lock_fails_the_attempt).
        from modules import pipeline_state
        monkeypatch.setattr(scheduler, "LOCK_WAIT_S", 0)
        with pipeline_state.PipelineLock(self.HOLDER):
            assert scheduler.run_pipeline(trigger="dashboard", holder=self.HOLDER,
                                          call=_fake_call([])) is True
        st = _status()
        assert st["state"] == "ok" and st["trigger"] == "dashboard"
        assert st["holder"] == self.HOLDER
        assert scheduler.read_last_run() is not None

    def test_the_scheduler_records_itself_as_the_holder(self, run_file, full_db,
                                                        steps_fail):
        scheduler.run_pipeline(call=_fake_call([]))
        assert _status()["holder"] == "scheduler"


class TestRetryDue:
    def status(self, state="failed", slot=at(2026, 10, 4, 6), retry=at(2026, 10, 4, 7, 5)):
        return {"state": state, "slot": slot.isoformat(),
                "next_retry_at": retry.isoformat() if retry else None}

    def test_failed_run_is_retried_once_its_time_comes(self):
        assert not scheduler.retry_due(at(2026, 10, 4, 7), None, self.status())
        assert scheduler.retry_due(at(2026, 10, 4, 7, 10), None, self.status())

    def test_no_retry_once_the_attempts_are_used_up(self):
        assert not scheduler.retry_due(at(2026, 10, 4, 9), None, self.status(retry=None))

    def test_no_retry_after_a_success(self):
        assert not scheduler.retry_due(at(2026, 10, 4, 9), at(2026, 10, 4, 8),
                                       self.status())

    def test_no_retry_of_yesterdays_failure(self):
        # Yesterday's attempts are over; today's 06:00 run is the next try.
        assert not scheduler.retry_due(at(2026, 10, 5, 7), None, self.status())

    def test_no_retry_while_a_run_is_going(self):
        assert not scheduler.retry_due(at(2026, 10, 4, 9), None, self.status("running"))


def test_record_lives_beside_the_database():
    assert os.path.dirname(scheduler.LAST_RUN_FILE) == os.path.dirname(config.SQLITE_PATH)


def test_paths_do_not_depend_on_the_working_directory():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (config.SQLITE_PATH, config.DATA_DIR, config.LOGS_DIR,
                 config.BACKUP_DIR):
        assert os.path.isabs(path)
        assert os.path.commonpath([path, here]) == here
