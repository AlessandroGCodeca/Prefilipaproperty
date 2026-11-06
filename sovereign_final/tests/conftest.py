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


@pytest.fixture(autouse=True)
def _no_stored_tax_rates(monkeypatch):
    """The engine charges a town's property tax from its table plus the rates
    the dashboard's 🏛️ UPDATE TAX RATES stored (engine.property_tax_sk). A
    test sees the table alone, whatever a real data/sovereign.db holds; one
    about stored rates sets them itself."""
    from engine import property_tax_cz, property_tax_sk
    monkeypatch.setattr(property_tax_sk, "_stored", {})
    monkeypatch.setattr(property_tax_cz, "_stored", {})


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch, tmp_path):
    """No test opens the real data/sovereign.db. A test that reaches
    database.get_conn() without a database of its own (engine.property_tax_sk
    reads the municipality list through it) gets an empty file of its own;
    full_db, and a test that sets its own path, still replace this."""
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))


@pytest.fixture(autouse=True)
def _no_live_fx_rate(monkeypatch, tmp_path):
    """No test fetches the ČNB rate or reads or writes the real
    data/fx_rate.json; one about modules/fx_rate stubs _fetch itself."""
    from modules import fx_rate

    def _offline(timeout=15):
        raise fx_rate.FxError("no network in tests")
    monkeypatch.setattr(fx_rate, "_fetch", _offline)
    monkeypatch.setattr(fx_rate, "CACHE_PATH", str(tmp_path / "fx_rate.json"))


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
