"""Audit 5: the scheduler and Location IQ defects a regression hunt found.

- A retry that runs past 06:00 holds _RUN_GUARD; the 06:00 job, run after it,
  must not run again a market that retry already ran for the new slot (its
  failure would say "Retrying at …" with no retry owed).
- A listing that failed to geocode once, then gets a map pin (or its pin
  moves), goes back to the front of Location IQ's queue: a pin needs no
  geocode.
"""
import sys
import types
from datetime import datetime

import pytest

import database as db
import modules.location_iq as liq
import scheduler
from modules import pipeline_state
from scheduler import TZ
from tests.conftest import make_listing


def at(d, h, mi=0):
    return TZ.localize(datetime(2026, 10, d, h, mi))


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
    now = [at(19, 5, 50)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0] if tz is None else now[0].astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    return now


def test_a_retry_past_six_is_not_run_again_at_six(env, monkeypatch):
    clock = env
    sun = scheduler.last_slot(at(18, 12))
    # CZ ran fine on Sunday; SK's Sunday attempts failed, next retry Mon 05:50.
    scheduler.record_run(at(18, 7), "cz")
    scheduler.record_run(at(17, 7), "sk")
    pipeline_state.write_status({"slot": sun.isoformat(), "attempt": 3, "trigger": "retry",
                                 "holder": "scheduler", "state": "failed",
                                 "started_at": at(19, 4, 40).isoformat(),
                                 "finished_at": at(19, 4, 50).isoformat(),
                                 "error": "all 3 scrapers failed",
                                 "next_retry_at": at(19, 5, 50).isoformat(),
                                 "steps": [], "summary": ""}, "sk")
    runs = []
    plan = {"sk": [(at(19, 6, 20), True), (at(19, 6, 40), False)],
            "cz": [(at(19, 7, 0), True)]}

    def portal(m):
        def run(max_pages=10):
            end, ok = plan[m].pop(0)
            runs.append((m, clock[0].strftime("%H:%M"), end.strftime("%H:%M"), ok))
            clock[0] = end
            if not ok:
                raise RuntimeError("HTTP 403")
            return 3
        return run
    monkeypatch.setitem(sys.modules, "scraper.topreality", types.SimpleNamespace(run=portal("sk")))
    monkeypatch.setitem(sys.modules, "scraper.fake_cz_portal", types.SimpleNamespace(run=portal("cz")))

    scheduler.retry_failed_run()          # 05:50: SK's retry, runs to 06:20, succeeds
    # The 06:00 fire waited on _RUN_GUARD (another job thread); it runs now.
    scheduler.run_daily()
    # SK ran once for Monday's slot (its retry); the 06:00 job ran only CZ.
    assert [r[:2] for r in runs] == [("sk", "05:50"), ("cz", "06:20")]
    st = pipeline_state.read_status("sk")
    assert st["state"] != "failed" and not st.get("next_retry_at")
    assert pipeline_state.summarize(st, None, now=at(19, 9, 0))[0] != "error"


# ── Location IQ queue ──────────────────────────────────────────────────────
NO_PLACE = "Predám 2-izbový byt"


@pytest.fixture
def geo(monkeypatch):
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


def located(full_db):
    c = full_db()
    try:
        return {r[0] for r in c.execute("SELECT listing_id FROM location_scores")}
    finally:
        c.close()


def test_a_listing_pinned_after_a_failed_geocode_goes_first(full_db, geo):
    # X: an old listing whose ad gave only its title as the address.
    db.upsert_listing(make_listing("X", lv_status="UNVERIFIED", address_raw=NO_PLACE, district=""))
    liq.run_location_scoring(limit=200)            # day 1: X can't be geocoded
    assert "X" not in located(full_db)
    # Day 2: 250 new listings scraped; X's portal now shows its map pin.
    for i in range(250):
        db.upsert_listing(make_listing(f"n{i:03d}", lv_status="UNVERIFIED",
                                       address_raw=f"Hlavná {i}, Žilina"))
    db.upsert_listing(make_listing("X", lv_status="UNVERIFIED", address_raw=NO_PLACE,
                                   district="", lat=49.21, lng=18.74))
    # The pin sent X's LV check back to PENDING; the day's LV step (before
    # Location IQ in the pipeline) finds no flat LV again: UNVERIFIED.
    c = full_db()
    c.execute("UPDATE listings SET lv_status='UNVERIFIED' WHERE id='X'")
    c.commit()
    c.close()
    queue = [r["id"] for r in db.get_unscored_location()]
    assert queue[0] == "X"                          # a pin needs no geocode: first
    liq.run_location_scoring(limit=200)             # day 2's Location IQ step (limit 200)
    assert "X" in located(full_db)


def test_a_moved_pin_goes_first_again(full_db, geo):
    # Y failed once (title-only address), was later located at its first pin,
    # then the agency moved the pin: the location row is dropped for
    # re-scoring at the new pin (upsert_listing -> _drop_location_score).
    db.upsert_listing(make_listing("Y", lv_status="UNVERIFIED", address_raw=NO_PLACE, district=""))
    liq.run_location_scoring(limit=200)
    db.upsert_listing(make_listing("Y", lv_status="UNVERIFIED", address_raw=NO_PLACE,
                                   district="", lat=49.21, lng=18.74))
    c = full_db()
    c.execute("UPDATE listings SET lv_status='UNVERIFIED' WHERE id='Y'")
    c.commit()
    c.close()
    liq.run_location_scoring(limit=200)
    assert "Y" in located(full_db)
    for i in range(250):
        db.upsert_listing(make_listing(f"m{i:03d}", lv_status="UNVERIFIED",
                                       address_raw=f"Hlavná {i}, Žilina"))
    db.upsert_listing(make_listing("Y", lv_status="UNVERIFIED", address_raw=NO_PLACE,
                                   district="", lat=49.30, lng=18.80))      # pin moved
    c = full_db()
    c.execute("UPDATE listings SET lv_status='UNVERIFIED' WHERE id='Y'")
    c.commit()
    c.close()
    queue = [r["id"] for r in db.get_unscored_location()]
    assert queue[0] == "Y"
    liq.run_location_scoring(limit=200)
    c = full_db()
    lat = c.execute("SELECT lat FROM location_scores WHERE listing_id='Y'").fetchone()
    c.close()
    assert lat is not None and abs(lat[0] - 49.30) < 1e-9
