"""Tests for the location-data honesty fixes:

- upsert_location must mirror lat/lng onto the listing row (the dashboard's
  satellite view / MAPS buttons read l["lat"] via get_all_active's l.*, and
  location_scores' coordinates are not part of that select).
- _backfill_listing_coords repairs rows scored before that fix.
- run_location_scoring refuses to run without a Google key instead of
  fabricating coordinates (±2.5 km jitter) and random risk flags.
- check_construction / check_noise return False until real data sources are
  wired (they used to hash coordinates into random 15%/20% penalties).
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

import modules.location_iq as liq


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id TEXT PRIMARY KEY, source TEXT, url TEXT UNIQUE,
            lat REAL, lng REAL, is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE location_scores (
            listing_id TEXT PRIMARY KEY, lat REAL, lng REAL,
            nearest_transit_m REAL, amenity_count INTEGER, grocery_count INTEGER,
            pharmacy_count INTEGER, school_count INTEGER, construction_risk INTEGER,
            noise_flag INTEGER, flood_zone INTEGER, walkability_score INTEGER,
            industrial_zone INTEGER, industrial_zone_name TEXT,
            location_score INTEGER, location_tier TEXT, scored_at TEXT
        )
    """)
    conn.execute("INSERT INTO listings (id, source, url) VALUES ('l1','t','http://x/l1')")
    conn.commit()
    conn.close()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _conn)
    yield path
    os.unlink(path)


def _loc_row(lid, lat, lng):
    return {
        "listing_id": lid, "lat": lat, "lng": lng, "nearest_transit_m": 300.0,
        "amenity_count": 5, "grocery_count": 2, "pharmacy_count": 1,
        "school_count": 2, "construction_risk": 0, "noise_flag": 0,
        "flood_zone": 0, "walkability_score": 80, "industrial_zone": 0,
        "industrial_zone_name": "", "location_score": 80, "location_tier": "PRIME",
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


class TestCoordSync:
    def test_upsert_location_mirrors_coords_to_listing(self, temp_db):
        from database import upsert_location
        upsert_location(_loc_row("l1", 48.15, 17.11))
        conn = sqlite3.connect(temp_db)
        lat, lng = conn.execute("SELECT lat, lng FROM listings WHERE id='l1'").fetchone()
        conn.close()
        assert (lat, lng) == (48.15, 17.11)

    def test_none_coords_leave_listing_untouched(self, temp_db):
        from database import upsert_location
        upsert_location(_loc_row("l1", None, None))
        conn = sqlite3.connect(temp_db)
        lat, lng = conn.execute("SELECT lat, lng FROM listings WHERE id='l1'").fetchone()
        conn.close()
        assert lat is None and lng is None

    def test_backfill_repairs_pre_fix_rows(self, temp_db):
        import database as db
        # Simulate a pre-fix state: score row exists, listing coords NULL.
        conn = sqlite3.connect(temp_db)
        conn.execute(
            "INSERT INTO location_scores (listing_id, lat, lng) VALUES ('l1', 49.22, 18.74)")
        conn.commit()
        c2 = db.get_conn()
        db._backfill_listing_coords(c2)
        c2.close()
        lat, lng = conn.execute("SELECT lat, lng FROM listings WHERE id='l1'").fetchone()
        conn.close()
        assert (lat, lng) == (49.22, 18.74)


class TestLocationGate:
    def test_skips_without_google_key(self, monkeypatch):
        monkeypatch.setattr(liq, "GOOGLE_API_KEY", "")
        # Must return before ever querying the DB.
        monkeypatch.setattr(liq, "get_unscored_location",
                            lambda: (_ for _ in ()).throw(AssertionError("queried DB")))
        assert liq.run_location_scoring() == 0

    def test_no_fabricated_risk_flags(self):
        # Until real data sources exist, absence of evidence is not risk.
        for lat, lng in [(48.15, 17.11), (49.22, 18.74), (48.72, 21.26)]:
            assert liq.check_construction(lat, lng) is False
            assert liq.check_noise(lat, lng) is False
