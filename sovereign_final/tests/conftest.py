"""Shared fixtures.

full_db: an isolated SQLite file with the real schema (database.SQLITE_SCHEMA
plus every column migration init_db runs), with database.get_conn patched to
open it. For tests that exercise several tables together; the older tests
build only the tables they need.
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def full_db(monkeypatch):
    import database as db

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    conn = _conn()
    conn.executescript(db.SQLITE_SCHEMA)
    db._ensure_dev_project_column(conn)
    db._ensure_cashflow_columns(conn)
    db._ensure_enrichment_columns(conn)
    db._ensure_location_columns(conn)
    db._ensure_rent_comps_columns(conn)
    conn.close()
    monkeypatch.setattr(db, "get_conn", _conn)
    yield _conn
    os.unlink(path)


def make_listing(lid: str, **over) -> dict:
    """A listing dict shaped like the scrapers' output."""
    now = over.pop("now", "2026-09-01T08:00:00+00:00")
    row = {
        "id": lid, "source": "bazos", "url": f"https://example.sk/{lid}",
        "url_hash": lid, "title": f"2-izbový byt {lid}", "description": "",
        "price_eur": 100_000.0, "size_m2": 55.0, "rooms": 2, "floor": None,
        "year_built": None, "energy_class": "UNKNOWN", "address_raw": "Žilina",
        "district": "Žilina", "city": "", "primary_image_url": "",
        "image_urls": "", "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
    }
    row.update(over)
    return row
