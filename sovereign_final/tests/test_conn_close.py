"""Every helper that opens a connection closes it, even when a query fails.

These used to close only on the success path: a "database is locked" from the
other process (dashboard vs scheduler share the file) left the connection —
and, mid-write, its lock — open until garbage collection got round to it.
"""

import importlib
import sqlite3

import pytest


class _FailingConn:
    def __init__(self):
        self.closed = False

    def execute(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")

    executescript = executemany = execute

    def commit(self):
        pass

    def close(self):
        self.closed = True


HELPERS = [
    ("database", "init_db", ()),
    ("database", "get_all_active", ()),
    ("database", "get_stats", ()),
    ("database", "get_active_sources", ()),
    ("database", "get_unscored_cashflow", ()),
    ("database", "requeue_scores_without_benchmark", ()),
    ("database", "upsert_cashflow", ({"listing_id": "x", "classification": "WHITE"},)),
    ("database", "upsert_location", ({"listing_id": "x"},)),
    ("database", "set_lv_status", ("x", "PASS")),
    ("engine.regional_prices", "zero_below_regional_floor", ("bazos",)),
    ("engine.regional_prices", "zero_above_regional_ceiling", ("bazos",)),
    ("scraper.bazos", "_backfill_blank_districts", ()),
    ("scraper.bazos", "_zero_bogus_prices", ()),
    ("scraper.nehnutelnosti", "_deactivate_non_apartments", ()),
    ("scraper.nehnutelnosti", "_zero_bogus_prices", ()),
    ("scraper.nehnutelnosti", "_dedupe_canonical_urls", ()),
    ("scraper.nehnutelnosti", "_backfill_blank_districts", ()),
    ("scraper.topreality", "_deactivate_category_pages", ()),
    ("scraper.topreality", "_backfill_blank_districts", ()),
    ("scraper.topreality", "_deactivate_non_apartments", ()),
    ("scraper.topreality", "_zero_bogus_prices", ()),
    ("enrich_pending", "fetch_pending", ()),
]


@pytest.mark.parametrize("module,name,args", HELPERS,
                         ids=[f"{m}.{n}" for m, n, _ in HELPERS])
def test_connection_closed_when_a_query_fails(module, name, args, monkeypatch):
    import database
    mod = importlib.import_module(module)
    conns = []

    def fake_get_conn():
        conns.append(_FailingConn())
        return conns[-1]

    monkeypatch.setattr(database, "get_conn", fake_get_conn)
    if hasattr(mod, "get_conn"):          # bound by `from database import get_conn`
        monkeypatch.setattr(mod, "get_conn", fake_get_conn)

    with pytest.raises(sqlite3.OperationalError):
        getattr(mod, name)(*args)
    assert conns and all(c.closed for c in conns)


def test_get_conn_closes_when_wal_cannot_be_set(tmp_path, monkeypatch):
    import database
    opened = []

    class _Conn:
        row_factory = None

        def execute(self, sql, *a):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            opened.append("closed")

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(database.sqlite3, "connect", lambda *a, **k: _Conn())
    with pytest.raises(sqlite3.OperationalError):
        database.get_conn()
    assert opened == ["closed"]
