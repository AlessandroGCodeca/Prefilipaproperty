"""The market registry (markets.py) and what it must not change.

Czechia runs beside Slovakia in the same app and database. Slovak behaviour
and existing data must not move: a database from before the market column
keeps every row (as Slovak), every Slovak engine figure is what it was, and
two markets never mix — a Czech flat is never a "copy" of a Slovak one.
"""

import json
import os
import sqlite3

import pytest

import config
import markets
from tests.conftest import make_listing

HERE = os.path.dirname(os.path.abspath(__file__))


# ── Registry ──────────────────────────────────────────────────────────────────
class TestRegistry:
    def test_two_markets(self):
        assert markets.MARKET_CODES == ("sk", "cz")
        assert markets.get("sk").currency == "EUR"
        assert markets.get("cz").currency == "CZK"
        assert markets.get("cz").country_code == "cz"

    def test_blank_or_unknown_is_slovak(self):
        # Every row from before the market column is Slovak.
        for code in (None, "", " ", "xx"):
            assert markets.normalize(code) == "sk"
        assert markets.normalize(" CZ ") == "cz"
        assert markets.of_row({}) == "sk"
        assert markets.of_row({"market": "cz"}) == "cz"

    def test_slovak_profile_is_config(self):
        sk = markets.SK
        assert sk.mortgage_rate_pa == config.MORTGAGE_RATE_PA
        assert sk.ltv_ratio == config.LTV_RATIO
        assert sk.ltv_ratio_investor == config.LTV_RATIO_INVESTOR
        assert sk.tax_year_rules is config.TAX_YEAR_RULES
        assert sk.rent_per_m2 is config.RENT_PER_M2
        assert sk.sale_price_min == config.SALE_PRICE_MIN_EUR
        assert markets.tax_rules(market="sk") == {**config.tax_rules(), "market": "sk"}

    def test_conversion_uses_the_one_dated_rate(self):
        assert markets.to_eur(100, "EUR") == 100
        assert markets.to_eur(config.CZK_PER_EUR * 1000, "CZK") == pytest.approx(1000)
        assert markets.to_eur(None, "CZK") is None
        assert config.FX_RATE_DATE in markets.fx_note()
        with pytest.raises(ValueError):
            markets.to_eur(1, "USD")

    def test_money_is_written_the_markets_way(self):
        assert markets.format_money(78000) == "€78,000"
        assert markets.format_money(-41, suffix="/mo") == "-€41/mo"
        assert markets.format_money(23, suffix="/mo") == "+€23/mo"
        assert markets.format_money(-0.2) == "€0"
        nb = " "
        assert markets.format_money(3_450_000, "CZK") == f"3{nb}450{nb}000{nb}Kč"
        assert markets.format_money(-1200, "CZK", suffix="/měs.") == f"-1{nb}200{nb}Kč/měs."
        assert markets.format_money(None, "CZK") == "—"


# ── Slovak figures are the ones the code produced before markets existed ─────
# (plus two corrections from the second review: the s.r.o.'s setup cost is
# paid in the IRR's year 0, and a Bratislava city part named alone —
# "Ružinov" — takes its own median, not the kraj's)
def _golden():
    with open(os.path.join(HERE, "fixtures", "sk_golden.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", _golden(), ids=lambda c: c["district"] or "blank")
def test_slovak_scores_are_unchanged(case):
    from engine import financial as fin
    from engine import regional_prices as rp
    r = fin.analyse(case["price"], case["size"], case["district"], rooms=case["rooms"])
    extras = fin.deal_extras(r)
    for key, want in case.items():
        if key in ("district", "price", "size", "rooms"):
            continue
        if key == "floor":
            got = rp.regional_price_floor(case["district"])
        elif key == "ceiling":
            got = rp.regional_price_ceiling(case["district"])
        elif key in extras:
            got = extras[key]
        else:
            got = getattr(r, key)
        assert got == want, key
    assert r.market == "sk" and r.currency == "EUR"


# ── Migration of a database from before the market column ────────────────────
# The three tables the migration touches, as they were created before it.
_PRE_MARKET_DDL = """
CREATE TABLE listings (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
    url_hash TEXT UNIQUE, title TEXT, description TEXT, price_eur REAL NOT NULL,
    size_m2 REAL, rooms REAL, floor INTEGER, year_built INTEGER,
    energy_class TEXT DEFAULT 'UNKNOWN', address_raw TEXT, district TEXT,
    city TEXT, cadastral_area TEXT, cadastral_number TEXT, lat REAL, lng REAL,
    primary_image_url TEXT, image_urls TEXT, classification TEXT DEFAULT 'PENDING',
    lv_status TEXT DEFAULT 'PENDING', llm_sentiment REAL, llm_risk_flags TEXT,
    scraped_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_active INTEGER DEFAULT 1,
    is_dev_project INTEGER DEFAULT 0, notes TEXT
);
CREATE TABLE rent_comps (
    id TEXT PRIMARY KEY, district TEXT NOT NULL, city TEXT, size_band TEXT NOT NULL,
    avg_rent_eur REAL, median_rent_eur REAL, sample_count INTEGER, source TEXT,
    updated_at TEXT, eur_per_m2 REAL, UNIQUE(district, size_band)
);
CREATE TABLE rental_listings (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE, title TEXT,
    rent_eur REAL NOT NULL, size_m2 REAL NOT NULL, rooms REAL, district TEXT,
    rent_key TEXT, energies_included INTEGER DEFAULT 0, furnished TEXT,
    scraped_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_active INTEGER DEFAULT 1
);
"""


@pytest.fixture
def pre_market_db(monkeypatch, tmp_path):
    import database
    path = str(tmp_path / "sovereign.db")
    conn = sqlite3.connect(path)
    conn.executescript(_PRE_MARKET_DDL)
    for i in range(30):
        conn.execute(
            "INSERT INTO listings (id, source, url, title, price_eur, size_m2, district, "
            "classification, scraped_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"l{i}", "bazos", f"https://x/{i}", f"Byt {i}", 100_000 + i, 50 + i,
             "Žilina", "GREEN", "2026-09-01", "2026-09-01"))
    conn.execute("INSERT INTO rent_comps VALUES ('live-žilina','žilina','','all',600,590,"
                 "12,'live_prenajom','2026-09-01',10.5)")
    conn.execute("INSERT INTO rental_listings (id, source, url, rent_eur, size_m2, "
                 "district, rent_key, scraped_at, last_seen_at) VALUES "
                 "('r1','bazos','https://x/r1',650,55,'Žilina','žilina','2026-09-01','2026-09-01')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "SQLITE_PATH", path)
    return database, path


class TestMigration:
    def test_every_row_is_kept_and_reads_as_slovak(self, pre_market_db):
        database, path = pre_market_db
        before = sqlite3.connect(path).execute(
            "SELECT id, price_eur, size_m2, district, classification FROM listings "
            "ORDER BY id").fetchall()
        database.init_db()
        conn = sqlite3.connect(path)
        after = conn.execute(
            "SELECT id, price_eur, size_m2, district, classification FROM listings "
            "ORDER BY id").fetchall()
        assert after == before and len(after) == 30
        assert set(conn.execute("SELECT market, currency FROM listings")) == {("sk", "EUR")}
        assert set(conn.execute("SELECT market, currency FROM rental_listings")) == {("sk", "EUR")}
        assert conn.execute("SELECT market, district, eur_per_m2 FROM rent_comps").fetchall() \
            == [("sk", "žilina", 10.5)]

    def test_rent_comps_are_unique_per_market(self, pre_market_db):
        database, path = pre_market_db
        database.init_db()
        conn = sqlite3.connect(path)
        # The same key in both markets is two rows now, not a conflict.
        conn.execute("INSERT INTO rent_comps (id, district, size_band, market) "
                     "VALUES ('live-cz-žilina', 'žilina', 'all', 'cz')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO rent_comps (id, district, size_band, market) "
                         "VALUES ('again', 'žilina', 'all', 'sk')")

    def test_running_it_again_changes_nothing(self, pre_market_db):
        database, path = pre_market_db
        database.init_db()
        snapshot = sqlite3.connect(path).execute("SELECT * FROM listings ORDER BY id").fetchall()
        database.init_db()
        assert sqlite3.connect(path).execute(
            "SELECT * FROM listings ORDER BY id").fetchall() == snapshot


# ── Markets never mix ─────────────────────────────────────────────────────────
def _add(db, lid, market="sk", **kw):
    row = make_listing(lid, **kw)
    if market != "sk":
        row["market"] = market
    db.upsert_listing(row)


class TestQueriesByMarket:
    def test_a_listing_keeps_its_market_and_currency(self, full_db):
        import database as db
        _add(db, "s1")
        _add(db, "c1", market="cz", district="Praha 2", price_eur=4_500_000)
        rows = {r["id"]: r for r in db.get_all_active()}
        assert (rows["s1"]["market"], rows["s1"]["currency"]) == ("sk", "EUR")
        assert (rows["c1"]["market"], rows["c1"]["currency"]) == ("cz", "CZK")
        assert rows["c1"]["price_eur"] == 4_500_000      # stored in Kč, as listed
        assert {r["id"] for r in db.get_all_active(market="cz")} == {"c1"}
        assert {r["id"] for r in db.get_all_active(market="sk")} == {"s1"}

    def test_stats_and_stale_cleanup_per_market(self, full_db):
        import database as db
        old = "2020-01-01T00:00:00+00:00"
        _add(db, "s1", last_seen_at=old)
        _add(db, "c1", market="cz", last_seen_at=old)
        assert db.get_stats(market="cz")["total"] == 1
        assert db.get_stats()["total"] == 2
        # A market whose portals weren't read skips its own check only.
        assert db.deactivate_stale_listings(days=21, market="sk") == 1
        assert db.get_stats(market="cz")["total"] == 1
        assert db.deactivate_stale_listings(days=21) == 1

    def test_pending_lv_rows_carry_their_market(self, full_db):
        import database as db
        _add(db, "s1")
        _add(db, "c1", market="cz")
        assert {r["id"]: r["market"] for r in db.get_pending_lv()} == {"s1": "sk", "c1": "cz"}
        assert [r["id"] for r in db.get_pending_lv(market="cz")] == ["c1"]

    def test_a_query_on_a_table_without_the_column_is_all_slovak(self, tmp_path, monkeypatch):
        import database as db
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE listings (id TEXT PRIMARY KEY, classification TEXT, "
                     "lv_status TEXT, is_active INTEGER DEFAULT 1, last_seen_at TEXT)")
        conn.execute("INSERT INTO listings VALUES ('a', 'GREEN', 'PASS', 1, '2026-01-01')")
        conn.commit()
        conn.close()

        def _conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        monkeypatch.setattr(db, "get_conn", _conn)
        assert db.get_stats(market="sk")["green"] == 1
        assert db.get_stats(market="cz")["total"] == 0


class TestDuplicatesWithinMarket:
    def test_identical_flats_in_two_markets_are_not_copies(self):
        from engine.duplicates import group_duplicates
        base = dict(district="Praha 2", size_m2=55.0, price_eur=100_000.0, rooms=2)
        rows = [{"id": "a", "url": "u1", **base},
                {"id": "b", "url": "u2", **base, "market": "cz"},
                {"id": "c", "url": "u3", **base, "market": "cz"}]
        assert group_duplicates(rows) == {"b": "b", "c": "b"}

    def test_slovak_grouping_is_as_before(self):
        from engine.duplicates import group_duplicates
        rows = [{"id": "a", "url": "u1", "district": "Petržalka", "size_m2": 55.0,
                 "price_eur": 100_000.0},
                {"id": "b", "url": "u2", "district": "Bratislava V", "size_m2": 55.4,
                 "price_eur": 101_000.0}]
        assert group_duplicates(rows) == {"a": "a", "b": "a"}

    def test_mark_duplicates_for_one_market_leaves_the_others_groups(self, full_db):
        import database as db
        for lid in ("s1", "s2"):
            _add(db, lid, district="Žilina", size_m2=55.0, price_eur=100_000.0)
        for lid in ("c1", "c2"):
            _add(db, lid, market="cz", district="Praha 2", size_m2=55.0,
                 price_eur=4_000_000.0)
        assert db.mark_duplicates() == 4
        assert db.mark_duplicates(market="cz") == 2
        groups = {r["id"]: r["dup_group"] for r in db.get_all_active()}
        assert groups["s1"] and groups["s1"] == groups["s2"]
        assert groups["c1"] and groups["c1"] == groups["c2"] != groups["s1"]
