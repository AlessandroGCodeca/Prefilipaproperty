"""scheduler.py used to run the whole pipeline on every container start, so a
Docker Desktop restart (or a PC reboot) re-scraped every portal and re-ran
every LV check. At startup it now only catches up a missed 06:00 run."""

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


class TestRunRecord:
    @pytest.fixture
    def run_file(self, tmp_path, monkeypatch):
        path = str(tmp_path / "data" / "last_pipeline_run")
        monkeypatch.setattr(scheduler, "LAST_RUN_FILE", path)
        return path

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

    def test_a_finished_pipeline_is_recorded(self, run_file, full_db, monkeypatch):
        import sys
        # Every step fails to import; run_pipeline logs each failure, carries
        # on, and still records that the run finished.
        for name in ("scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality",
                     "scraper.rentals", "modules.debt_bot",
                     "modules.address_enrichment", "modules.description_enrichment",
                     "modules.cashflow_runner", "modules.location_iq"):
            monkeypatch.setitem(sys.modules, name, None)
        scheduler.run_pipeline()
        assert scheduler.read_last_run() is not None

    def test_a_pipeline_that_cannot_open_the_db_is_not_recorded(self, run_file,
                                                                monkeypatch):
        import database

        def boom():
            raise RuntimeError("disk full")
        monkeypatch.setattr(database, "init_db", boom)
        scheduler.run_pipeline()
        assert scheduler.read_last_run() is None


def test_record_lives_beside_the_database():
    assert os.path.dirname(scheduler.LAST_RUN_FILE) == os.path.dirname(config.SQLITE_PATH)


def test_paths_do_not_depend_on_the_working_directory():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (config.SQLITE_PATH, config.DATA_DIR, config.LOGS_DIR,
                 config.CONTRACTS_DIR):
        assert os.path.isabs(path)
        assert os.path.commonpath([path, here]) == here
