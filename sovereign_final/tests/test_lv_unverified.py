"""Tests for the LV debt filter's verdicts: PASS only for a flat whose own LV
was read and is clean, REJECTED only on the flat's own LV, and UNVERIFIED —
stored as such, shown as ⚠ — for everything else.

History: the old demo mode invented "[DEMO]" liens for every listing and one
run REJECTED them all. Its replacement then stored PASS for every listing it
could NOT check, which the dashboard showed as ✅ CLEAN. And where a parcel was
known, the parcel's LV was screened as if it were the flat's — but a parcel's
LV is the building plot's, and a flat has its own entry, usually on another LV.

All cadastre traffic is faked at the debt_bot boundary (enrich_parcel,
enrich_lv, parcel_at) — no network."""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import modules.debt_bot as debt_bot

CLEAN_LV = "Výpis z LV 4321. ČASŤ C: ŤARCHY: Bez zápisu."
BANK_LV = "ČASŤ C: Záložné právo v prospech Tatra banka, a.s. na byt č. 12"
PRIVATE_LV = ("ČASŤ C: 1 Záložné právo v prospech Tatra banka, a.s. na byt č. 12 "
              "2 Záložné právo v prospech Ján Novák, nar. 1970 na byt č. 12")
EXEKUCIA_LV = "ČASŤ C: Záložné právo v prospech VÚB, a.s. Exekúcia EX 55/2021"
SHARED_LV = ("ČASŤ B: 1 Novák Ján — Byt č. 3, 1/1 2 Malá Eva — Byt č. 7, 1/1 "
             "ČASŤ C: Záložné právo v prospech Peter Kováč na byt č. 7")
SHARED_CLEAN_LV = "ČASŤ B: Byt č. 3 … Byt č. 7 … ČASŤ C: ŤARCHY: Bez zápisu."


def _lookup(status="OK", detail="", lv_text=None, lv_no=4321):
    """Shape returned by kataster_scraper.enrich_parcel / enrich_lv."""
    return {
        "status": status, "detail": detail, "source": "live",
        "query": {}, "cadastral_unit": {"code": 838365, "name": "Nitra"},
        "parcel": {"no": "1234/5"}, "lv": {"no": lv_no} if lv_no else None,
        "owners": [], "lv_text": lv_text, "risk_flags": [],
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }


BUILDING_PARCEL = {
    "id": 123, "register": "C", "no": "1234/5", "house_no": "10",
    "land_use": "Zastavaná plocha a nádvorie", "utilisation": "Bytový dom",
    "municipality": "Nitra", "lv_no": 4321,
    "cadastral_unit": {"name": "Nitra", "code": 838365},
}


def _row(**kw):
    base = {"id": "l1", "address_raw": "", "district": "Nitra",
            "lat": None, "lng": None, "coords_source": None,
            "cadastral_area": None, "cadastral_number": None,
            "cadastral_unit_code": None, "plot_lv_number": None,
            "lv_number": None}
    return {**base, **kw}


def _no_network(monkeypatch):
    for name in ("enrich_parcel", "enrich_lv", "parcel_at"):
        monkeypatch.setattr(debt_bot, name,
                            lambda *a, _n=name, **k: pytest.fail(f"{_n} must not run"))


class TestNoTitleDeedRead:
    def test_no_pin_no_parcel_is_unverified_without_network(self, monkeypatch):
        _no_network(monkeypatch)
        res = debt_bot.check_listing(_row())
        assert res["status"] == "UNVERIFIED"
        assert "no map pin" in res["detail"]
        assert res["raw"] == {}          # nothing for Claude to read

    def test_geocoded_coordinates_are_not_used_to_pick_a_parcel(self, monkeypatch):
        # Google's geocode of "Petržalka, Bratislava" is a district centroid.
        _no_network(monkeypatch)
        res = debt_bot.check_listing(
            _row(lat=48.12, lng=17.11, coords_source="geocode"))
        assert res["status"] == "UNVERIFIED"

    @pytest.mark.parametrize("status,detail", [
        ("NOT_FOUND", "the map pin is not on a built-up parcel"),
        ("ERROR", "portal unreachable"),
    ])
    def test_pin_lookup_failure_is_unverified(self, monkeypatch, status, detail):
        _no_network(monkeypatch)
        monkeypatch.setattr(debt_bot, "parcel_at", lambda lat, lng: {
            "status": status, "detail": detail, "parcel": None})
        res = debt_bot.check_listing(
            _row(lat=48.3, lng=18.08, coords_source="listing"))
        assert res["status"] == "UNVERIFIED"
        assert detail in res["detail"]
        assert not res.get("parcel")


class TestPlotIsNotTheFlat:
    def _pin(self, monkeypatch, plot_text):
        monkeypatch.setattr(debt_bot, "parcel_at", lambda lat, lng: {
            "status": "OK", "detail": "", "parcel": dict(BUILDING_PARCEL)})
        calls = []
        def fake_enrich(area, parcel_no, **kw):
            calls.append((area, parcel_no, kw))
            return _lookup(lv_text=plot_text)
        monkeypatch.setattr(debt_bot, "enrich_parcel", fake_enrich)
        monkeypatch.setattr(debt_bot, "enrich_lv",
                            lambda *a, **k: pytest.fail("no flat LV is known"))
        return calls

    def test_clean_plot_lv_is_unverified_not_clean(self, monkeypatch):
        calls = self._pin(monkeypatch, CLEAN_LV)
        res = debt_bot.check_listing(
            _row(lat=48.3, lng=18.08, coords_source="listing"))
        assert res["status"] == "UNVERIFIED"
        assert "parcel 1234/5" in res["detail"] and "plot LV 4321" in res["detail"]
        assert "flat's own LV" in res["detail"]
        # The plot is captured for the dashboard / the next check.
        assert res["parcel"] == {"cadastral_area": "Nitra", "parcel_no": "1234/5",
                                 "ku_code": 838365, "plot_lv": 4321}
        # Looked up by the unit's numeric code, in the C register.
        assert calls == [("838365", "1234/5", {"register": "C"})]

    def test_flagged_plot_lv_is_unverified_not_rejected(self, monkeypatch):
        # The plot's LV may be shared by every flat in the building — an
        # exekúcia on it may be a neighbour's.
        self._pin(monkeypatch, EXEKUCIA_LV)
        res = debt_bot.check_listing(
            _row(lat=48.3, lng=18.08, coords_source="listing"))
        assert res["status"] == "UNVERIFIED"
        assert "exekúcia" in res["detail"]
        assert "another flat" in res["detail"]

    def test_pin_in_another_town_captures_nothing(self, monkeypatch):
        self._pin(monkeypatch, CLEAN_LV)
        res = debt_bot.check_listing(_row(
            district="Petržalka, Bratislava",
            lat=48.3, lng=18.08, coords_source="listing"))
        assert res["status"] == "UNVERIFIED"
        assert "not Petržalka, Bratislava" in res["detail"]
        assert not res.get("parcel")

    @pytest.mark.parametrize("district,municipality,ku,ok", [
        ("Bratislava", "Petržalka", "Petržalka", True),
        ("Bratislava IV", "Bratislava - Karlova Ves", "Karlova Ves", True),
        ("Košice II", "Západ", "Západ", True),
        ("Petržalka, Bratislava", "Petržalka", "Petržalka", True),
        ("Bratislava", "Nitra", "Nitra", False),
        ("Nitra", "Komárno", "Komárno", False),
        ("", "Nitra", "Nitra", True),          # nothing to compare against
    ])
    def test_pin_town_check(self, district, municipality, ku, ok):
        parcel = {**BUILDING_PARCEL, "municipality": municipality,
                  "cadastral_unit": {"name": ku, "code": 1}}
        assert debt_bot._pin_matches_listing(parcel, district) is ok

    def test_stored_parcel_skips_the_pin_lookup(self, monkeypatch):
        monkeypatch.setattr(debt_bot, "parcel_at",
                            lambda *a: pytest.fail("parcel already known"))
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda area, no, **k: _lookup(lv_text=CLEAN_LV))
        res = debt_bot.check_listing(_row(
            cadastral_area="Nitra", cadastral_number="1234/5",
            cadastral_unit_code="838365", plot_lv_number="4321"))
        assert res["status"] == "UNVERIFIED"
        assert res.get("parcel") is None   # nothing new to store


class TestFlatsOwnLv:
    def _flat(self, monkeypatch, text, status="OK"):
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: pytest.fail("the plot is irrelevant"))
        monkeypatch.setattr(debt_bot, "enrich_lv",
                            lambda area, lv: _lookup(status, "portal down", text))
        return debt_bot.check_listing(_row(
            lv_number="777", cadastral_area="Nitra", cadastral_unit_code="838365",
            cadastral_number="1234/5"))

    def test_clean_flat_lv_passes(self, monkeypatch):
        res = self._flat(monkeypatch, CLEAN_LV)
        assert res["status"] == "PASS"
        assert res["detail"].startswith("LV 777:")
        assert res["raw"] == CLEAN_LV      # real LV text flows to Claude

    def test_bank_mortgage_passes(self, monkeypatch):
        assert self._flat(monkeypatch, BANK_LV)["status"] == "PASS"

    def test_private_lien_rejects(self, monkeypatch):
        res = self._flat(monkeypatch, PRIVATE_LV)
        assert res["status"] == "REJECT" and "Ján Novák" in res["detail"]

    def test_exekucia_rejects(self, monkeypatch):
        res = self._flat(monkeypatch, EXEKUCIA_LV)
        assert res["status"] == "REJECT" and res["flag"] == "exekúcia"

    def test_shared_lv_flag_is_unverified(self, monkeypatch):
        res = self._flat(monkeypatch, SHARED_LV)
        assert res["status"] == "UNVERIFIED"
        assert "shared by 2 flats" in res["detail"]

    def test_shared_lv_without_flags_passes(self, monkeypatch):
        assert self._flat(monkeypatch, SHARED_CLEAN_LV)["status"] == "PASS"

    def test_lookup_failure_is_unverified(self, monkeypatch):
        res = self._flat(monkeypatch, None, status="ERROR")
        assert res["status"] == "UNVERIFIED" and "portal down" in res["detail"]

    def test_lv_number_without_cadastral_unit(self, monkeypatch):
        _no_network(monkeypatch)
        res = debt_bot.check_listing(_row(lv_number="777"))
        assert res["status"] == "UNVERIFIED"
        assert "katastrálne územie" in res["detail"]


# ── persistence: a real schema in a temp DB ──────────────────────────────────
@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    conn = sqlite3.connect(path)
    conn.executescript(db.SQLITE_SCHEMA)
    conn.commit()
    conn.close()

    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _conn)
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    yield path
    os.unlink(path)


def _insert(path, rid, **cols):
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": rid, "source": "test", "url": f"http://x/{rid}",
           "price_eur": 100000, "scraped_at": now, "last_seen_at": now,
           "district": "Nitra", **cols}
    conn = sqlite3.connect(path)
    conn.execute(f"INSERT INTO listings ({', '.join(row)}) "
                 f"VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()
    conn.close()


def _get(path, rid):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM listings WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row)


class TestRunDebtFilter:
    def test_unverified_is_stored_as_unverified(self, temp_db, monkeypatch):
        _no_network(monkeypatch)
        _insert(temp_db, "fresh", lv_status="PENDING")
        assert debt_bot.run_debt_filter() == (0, 0, 1)
        row = _get(temp_db, "fresh")
        assert row["lv_status"] == "UNVERIFIED"
        assert "no map pin" in row["lv_detail"]
        assert row["lv_checked_at"]

    def test_pin_captures_the_building_plot(self, temp_db, monkeypatch):
        _insert(temp_db, "pinned", lv_status="PENDING",
                lat=48.3, lng=18.08, coords_source="listing")
        monkeypatch.setattr(debt_bot, "parcel_at", lambda lat, lng: {
            "status": "OK", "detail": "", "parcel": dict(BUILDING_PARCEL)})
        monkeypatch.setattr(debt_bot, "enrich_parcel",
                            lambda *a, **k: _lookup(lv_text=CLEAN_LV))
        assert debt_bot.run_debt_filter() == (0, 0, 1)
        row = _get(temp_db, "pinned")
        assert row["lv_status"] == "UNVERIFIED"
        assert (row["cadastral_area"], row["cadastral_number"]) == ("Nitra", "1234/5")
        assert (row["cadastral_unit_code"], row["plot_lv_number"]) == ("838365", "4321")

    def test_flat_lv_entered_on_the_card_verifies(self, temp_db, monkeypatch):
        _insert(temp_db, "l1", lv_status="UNVERIFIED")
        monkeypatch.setattr(debt_bot, "enrich_lv",
                            lambda area, lv: _lookup(lv_text=BANK_LV))
        res = debt_bot.reverify("l1", lv_number="777", cadastral_area="Nitra")
        assert res["status"] == "PASS"
        row = _get(temp_db, "l1")
        assert (row["lv_status"], row["lv_number"]) == ("PASS", "777")

        monkeypatch.setattr(debt_bot, "enrich_lv",
                            lambda area, lv: _lookup(lv_text=PRIVATE_LV))
        assert debt_bot.reverify("l1")["status"] == "REJECT"   # stored number reused
        assert _get(temp_db, "l1")["lv_status"] == "REJECTED"

    def test_clearing_the_flat_lv(self, temp_db, monkeypatch):
        _no_network(monkeypatch)
        _insert(temp_db, "l1", lv_status="PASS", lv_number="777",
                cadastral_area="Nitra", lv_checked_at="2026-01-01")
        assert debt_bot.reverify("l1", lv_number="")["status"] == "UNVERIFIED"
        assert _get(temp_db, "l1")["lv_number"] is None


class TestPendingSelection:
    def test_recheck_only_what_can_get_further(self, temp_db):
        import database as db
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        _insert(temp_db, "pending", lv_status="PENDING")
        _insert(temp_db, "pin-old", lv_status="UNVERIFIED", coords_source="listing",
                lat=48.3, lng=18.08, lv_checked_at=old)
        _insert(temp_db, "pin-recent", lv_status="UNVERIFIED",
                coords_source="listing", lat=48.3, lng=18.08, lv_checked_at=new)
        _insert(temp_db, "lv-old", lv_status="UNVERIFIED", lv_number="5",
                lv_checked_at=old)
        _insert(temp_db, "nothing", lv_status="UNVERIFIED", lv_checked_at=old)
        _insert(temp_db, "clean", lv_status="PASS", lv_checked_at=old)
        ids = {r["id"] for r in db.get_pending_lv(recheck_days=7)}
        assert ids == {"pending", "pin-old", "lv-old"}


class TestLegacyPassMigration:
    def test_unstamped_pass_becomes_unverified(self, temp_db):
        import database as db
        _insert(temp_db, "legacy", lv_status="PASS")
        _insert(temp_db, "checked", lv_status="PASS", lv_checked_at="2026-09-01")
        conn = db.get_conn()
        assert db._mark_legacy_lv_passes_unverified(conn) == 1
        conn.close()
        assert _get(temp_db, "legacy")["lv_status"] == "UNVERIFIED"
        assert "No title deed was read" in _get(temp_db, "legacy")["lv_detail"]
        assert _get(temp_db, "checked")["lv_status"] == "PASS"


class TestMapPins:
    def _listing(self, **kw):
        now = datetime.now(timezone.utc).isoformat()
        return {"id": "l1", "source": "t", "url": "http://x/l1", "url_hash": "l1",
                "title": "Byt", "description": "", "price_eur": 100000.0,
                "size_m2": 50.0, "rooms": 2, "floor": None, "year_built": None,
                "energy_class": "UNKNOWN", "address_raw": "Nitra",
                "district": "Nitra", "city": "", "primary_image_url": "",
                "image_urls": "", "classification": "PENDING",
                "lv_status": "PENDING", "scraped_at": now, "last_seen_at": now,
                **kw}

    def test_pin_is_stored_and_kept(self, temp_db):
        import database as db
        db.upsert_listing(self._listing(lat=48.31, lng=18.09))
        db.upsert_listing(self._listing())      # a later read without a pin
        row = _get(temp_db, "l1")
        assert (row["lat"], row["lng"], row["coords_source"]) == (48.31, 18.09, "listing")

    def test_new_pin_reopens_an_unverified_check(self, temp_db):
        import database as db
        db.upsert_listing(self._listing())
        conn = sqlite3.connect(temp_db)
        conn.execute("UPDATE listings SET lv_status='UNVERIFIED', "
                     "cadastral_number='1/1', plot_lv_number='9' WHERE id='l1'")
        conn.commit()
        conn.close()
        db.upsert_listing(self._listing(lat=48.31, lng=18.09))
        row = _get(temp_db, "l1")
        assert row["lv_status"] == "PENDING"
        assert row["cadastral_number"] is None and row["plot_lv_number"] is None

    def test_same_pin_leaves_the_check_alone(self, temp_db):
        import database as db
        db.upsert_listing(self._listing(lat=48.31, lng=18.09))
        conn = sqlite3.connect(temp_db)
        conn.execute("UPDATE listings SET lv_status='UNVERIFIED', "
                     "cadastral_number='1/1' WHERE id='l1'")
        conn.commit()
        conn.close()
        db.upsert_listing(self._listing(lat=48.31001, lng=18.09001))
        row = _get(temp_db, "l1")
        assert row["lv_status"] == "UNVERIFIED" and row["cadastral_number"] == "1/1"

    def test_geocode_never_overwrites_a_listing_pin(self, temp_db):
        import database as db
        db.upsert_listing(self._listing(lat=48.31, lng=18.09))
        db.upsert_location({
            "listing_id": "l1", "lat": 48.30, "lng": 18.08,
            "nearest_transit_m": 1, "amenity_count": 0, "grocery_count": 0,
            "pharmacy_count": 0, "school_count": 0, "construction_risk": 0,
            "noise_flag": 0, "flood_zone": 0, "walkability_score": 0,
            "industrial_zone": 0, "industrial_zone_name": "",
            "location_score": 0, "location_tier": "STANDARD", "scored_at": "x"})
        row = _get(temp_db, "l1")
        assert (row["lat"], row["coords_source"]) == (48.31, "listing")


# ── [DEMO] healing (unchanged behaviour) ─────────────────────────────────────
@pytest.fixture
def demo_db(temp_db):
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(temp_db)
    for rid, status, detail in (
        ("demo1", "REJECTED", "[DEMO] Non-bank lien detected — private creditor"),
        ("demo2", "REJECTED", "[DEMO] Court execution order registered on title"),
        ("real1", "REJECTED", "LV encumbrance detected: 'exekúcia'"),
    ):
        conn.close()
        _insert(temp_db, rid, lv_status=status)
        conn = sqlite3.connect(temp_db)
        conn.execute("INSERT INTO rejections_log VALUES (?,?,?,?,?,?)",
                     (f"r-{rid}", rid, "flag", detail, "debt_bot", now))
        conn.commit()
    conn.close()
    return temp_db


class TestResetDemoRejections:
    def test_heals_demo_rows_only(self, demo_db):
        from database import reset_demo_rejections
        assert reset_demo_rejections() == 2
        assert _get(demo_db, "demo1")["lv_status"] == "PENDING"
        assert _get(demo_db, "real1")["lv_status"] == "REJECTED"
        conn = sqlite3.connect(demo_db)
        details = [r[0] for r in conn.execute("SELECT detail FROM rejections_log")]
        conn.close()
        assert all("[DEMO]" not in d for d in details)
        assert any("exekúcia" in d for d in details)

    def test_idempotent(self, demo_db):
        from database import reset_demo_rejections
        reset_demo_rejections()
        assert reset_demo_rejections() == 0

    def test_healed_rows_are_rechecked_honestly(self, demo_db, monkeypatch):
        _no_network(monkeypatch)
        assert debt_bot.run_debt_filter() == (0, 0, 2)
        assert _get(demo_db, "demo1")["lv_status"] == "UNVERIFIED"
        assert _get(demo_db, "real1")["lv_status"] == "REJECTED"
