"""The pipeline runs per market (scheduler.run_all_markets): each market has
its own portals, steps, status file, success record and retries, under the
one shared lock — and a market that fails, or crashes, never stops the other.
No network: every step module is stubbed."""

import sys
import types

import pytest

import scheduler
from modules import pipeline_state

# Every module a step imports, in either market's pipeline.
_STEP_MODULES = ("scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality",
                 "enrich_pending", "scraper.rentals", "scraper.rentals_cz",
                 "modules.debt_bot", "modules.address_enrichment",
                 "modules.description_enrichment", "modules.cashflow_runner",
                 "modules.location_iq", "scraper.fake_cz_portal")


@pytest.fixture
def files(tmp_path, monkeypatch):
    from modules import backup
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", str(tmp_path / "data" / "last_run"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "data" / "status.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def stubbed(monkeypatch):
    """Every step module fails to import; Czechia gets one fake portal."""
    for name in _STEP_MODULES:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(scheduler.SCRAPERS, "cz", (("Fake.cz", "scraper.fake_cz_portal"),))

    def works(name, n=5):
        monkeypatch.setitem(sys.modules, name,
                            types.SimpleNamespace(run=lambda max_pages=10: n))
    return works


def test_status_and_success_files_are_per_market(files):
    assert pipeline_state.status_file() == pipeline_state.STATUS_FILE
    assert pipeline_state.status_file("cz").endswith("status_cz.json")
    assert scheduler.last_run_file() == scheduler.LAST_RUN_FILE
    assert scheduler.last_run_file("cz") == scheduler.LAST_RUN_FILE + "_cz"


def test_scrapers_are_listed_per_market():
    assert [m for _, m in scheduler.SCRAPERS["sk"]] == [
        "scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality"]
    assert "cz" in scheduler.SCRAPERS
    assert scheduler.step_count("sk") == scheduler.STEP_COUNT == 14


def test_a_market_with_no_portals_is_not_run(monkeypatch):
    monkeypatch.setitem(scheduler.SCRAPERS, "cz", ())
    assert scheduler.active_markets() == ["sk"]


def test_czech_failure_does_not_stop_the_slovak_run(files, full_db, stubbed):
    stubbed("scraper.bazos")                       # Slovakia reads one portal
    results = scheduler.run_all_markets()
    assert results == {"sk": True, "cz": False}
    assert scheduler.read_last_run("sk") is not None
    assert scheduler.read_last_run("cz") is None
    sk, cz = pipeline_state.read_status("sk"), pipeline_state.read_status("cz")
    assert sk["state"] == "ok" and cz["state"] == "failed"
    assert "1 scrapers failed" in cz["error"] and cz["next_retry_at"]
    # Czechia's run did its own steps on its own listings.
    assert [s["step"] for s in cz["steps"]][:3] == ["Backup", "Fake.cz", "Rent comps"]
    assert len(cz["steps"]) == scheduler.step_count("cz")


def test_slovak_failure_does_not_stop_the_czech_run(files, full_db, stubbed):
    stubbed("scraper.fake_cz_portal")
    results = scheduler.run_all_markets()
    assert results == {"sk": False, "cz": True}
    assert pipeline_state.read_status("cz")["state"] == "ok"
    assert pipeline_state.read_status("sk")["state"] == "failed"


def test_a_market_that_crashes_is_recorded_and_the_next_runs(files, full_db, stubbed,
                                                             monkeypatch):
    stubbed("scraper.fake_cz_portal")
    real = scheduler.run_pipeline

    def crash_in_slovakia(**kw):
        if kw.get("market", "sk") == "sk":
            raise RuntimeError("disk on fire")
        return real(**kw)
    monkeypatch.setattr(scheduler, "run_pipeline", crash_in_slovakia)
    results = scheduler.run_all_markets()
    assert results == {"sk": False, "cz": True}
    sk = pipeline_state.read_status("sk")
    assert sk["state"] == "failed" and "disk on fire" in sk["error"]
    assert sk["attempt"] == 1 and sk["next_retry_at"]      # retried like any failure


def test_one_lock_for_both_markets(files, full_db, stubbed, monkeypatch):
    held = []
    real = scheduler.run_pipeline

    def spy(**kw):
        from database import get_pipeline_lock
        held.append((kw.get("market", "sk"), get_pipeline_lock()["holder"], kw["holder"]))
        return real(**kw)
    monkeypatch.setattr(scheduler, "run_pipeline", spy)
    scheduler.run_all_markets()
    assert held == [("sk", "scheduler", "scheduler"), ("cz", "scheduler", "scheduler")]


def test_a_busy_lock_fails_every_market_with_a_retry(files, full_db, stubbed, monkeypatch):
    monkeypatch.setattr(scheduler, "LOCK_WAIT_S", 0)
    with pipeline_state.PipelineLock("dashboard: BAZOS"):
        assert scheduler.run_all_markets() == {"sk": False, "cz": False}
    for m in ("sk", "cz"):
        st = pipeline_state.read_status(m)
        assert "dashboard: BAZOS is running" in st["error"] and st["next_retry_at"]


def test_progress_runs_through_both_markets(files, full_db, stubbed):
    heard = []
    scheduler.run_all_markets(progress=lambda i, n, note: heard.append((i, n, note)))
    total = scheduler.step_count("sk") + scheduler.step_count("cz")
    assert [i for i, _, _ in heard] == list(range(1, total + 1))
    assert {n for _, n, _ in heard} == {total}
    assert heard[0][2] == "SK · Backup" and heard[-1][2] == "CZ · Merge portal copies"


def test_catch_up_and_retry_are_per_market(files, full_db, stubbed, monkeypatch):
    from datetime import datetime

    # A fixed clock after 06:00: a run ending 05:00–06:00 would owe its retry
    # to the next slot, and the test would fail an hour a day.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return scheduler.TZ.localize(datetime(2026, 10, 16, 7, 0))
    monkeypatch.setattr(scheduler, "datetime", Clock)
    stubbed("scraper.bazos")
    now = Clock.now(scheduler.TZ)
    assert scheduler.due_markets(now) == ["sk", "cz"]
    scheduler.run_all_markets()
    # Slovakia succeeded; Czechia failed and owes a retry once its time comes.
    assert scheduler.due_markets(now) == ["cz"]
    retry_at = datetime.fromisoformat(pipeline_state.read_status("cz")["next_retry_at"])
    assert scheduler.due_markets(retry_at, "retry") == ["cz"]
