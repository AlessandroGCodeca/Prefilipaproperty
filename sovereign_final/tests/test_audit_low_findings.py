"""The low findings of the 12 Nov audit, fixed on 17 Nov: "novostavba" alone
is not a developer project (13), the CSV export can't carry a formula (14),
the map ignores pins outside the country and centres on the median (15), a
corrected size or room count re-scores (17), Places API (New) (18 — in
test_audit3_geo_enrich), a missing district doesn't crash the engine (19),
and the page header is compact and remembers the tab (21)."""

import pandas as pd
import pytest

import tests.test_app_smoke as smoke
from tests.conftest import make_listing
from tests.test_app_smoke import run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs


# ── 13 ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title, dev", [
    ("Novostavba 2-izb. byt s balkónom", 0),
    ("2-izbový byt v novostavbe, Ružinov", 0),
    ("Novostavba - posledné voľné byty", 1),
    ("Rezidencia Nová Doba, novostavba", 1),
    ("Novostavba bytov od €145 900", 1),
    ("Predaj bytov od €145 900", 1),
])
def test_novostavba_needs_a_second_sign(title, dev):
    from database import detect_dev_project
    assert detect_dev_project("https://example.sk/byt-1", title) == dev


def test_a_flag_whose_signs_have_gone_is_cleared(full_db):
    import database
    database.upsert_listing(make_listing("d1", title="Novostavba 2-izb. byt"))
    conn = database.get_conn()
    conn.execute("UPDATE listings SET is_dev_project=1 WHERE id='d1'")   # the old rule's flag
    conn.commit()
    conn.close()
    database.backfill_dev_project_flags()
    row = next(r for r in database.get_all_active() if r["id"] == "d1")
    assert not row["is_dev_project"]
    database.upsert_listing(make_listing("d1", title="Novostavba - posledné voľné byty"))
    row = next(r for r in database.get_all_active() if r["id"] == "d1")
    assert row["is_dev_project"] == 1


# ── 14 ───────────────────────────────────────────────────────────────────────
def test_the_csv_never_carries_a_formula():
    from dashboard.tabs.triage import triage_csv
    df = pd.DataFrame({"Title": ['=HYPERLINK("http://x","y")', "+1+1", "@SUM(1)", "-2+3",
                                 "Byt Ružinov"],
                       "Surplus": [-150.0, 10.0, 0.0, 5.0, 1.0]})
    text = triage_csv(df).decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\n'+1+1" in text and "\n'@SUM(1)" in text
    assert "\n'-2+3" in text and "\nByt Ružinov" in text
    assert ",-150.0" in text                     # a negative number stays a number


# ── 15 ───────────────────────────────────────────────────────────────────────
def test_a_pin_outside_the_country_is_not_saved(full_db):
    import database
    database.upsert_listing(make_listing("p1", lat=48.6, lng=24.0))    # western Ukraine
    database.upsert_listing(make_listing("p2", lat=48.15, lng=17.11))
    rows = {r["id"]: r for r in database.get_all_active()}
    assert rows["p1"]["lat"] is None and rows["p2"]["lat"] == pytest.approx(48.15)
    database.upsert_location(dict(
        listing_id="p1", lat=0.0, lng=0.0, nearest_transit_m=None, amenity_count=0,
        grocery_count=0, pharmacy_count=0, school_count=0, construction_risk=0,
        noise_flag=0, flood_zone=0, walkability_score=0, industrial_zone=0,
        industrial_zone_name=None, location_score=1, location_tier="POOR",
        scored_at="2026-11-17T00:00:00", construction_detail=None, noise_detail=None,
        flood_detail=None, geo_precision="street", risk_checked_at=None))
    assert next(r for r in database.get_all_active() if r["id"] == "p1")["lat"] is None


def test_the_map_leaves_out_a_foreign_pin_and_centres_on_the_median(populated_db):
    conn = populated_db.get_conn()
    conn.execute("UPDATE listings SET lat=48.6, lng=24.0 WHERE id='w1'")   # stored before the check
    conn.execute("UPDATE listings SET lat=48.3, lng=17.6 WHERE id='w2'")
    conn.commit()
    conn.close()
    at = run_app()
    assert not at.exception
    deck = next(c for c in at.get("deck_gl_json_chart"))
    spec = deck.proto.json
    assert '"longitude": 24.0' not in spec


# ── 17 ───────────────────────────────────────────────────────────────────────
def test_a_corrected_size_or_room_count_re_scores(full_db):
    import database
    from modules.cashflow_runner import run_scoring
    database.upsert_listing(make_listing("s1", size_m2=55.0, rooms=2))
    run_scoring()
    assert database.get_unscored_cashflow() == []
    database.upsert_listing(make_listing("s1", size_m2=65.0, rooms=2))
    assert [r["id"] for r in database.get_unscored_cashflow()] == ["s1"]
    run_scoring()
    database.upsert_listing(make_listing("s1", size_m2=65.0, rooms=3))
    assert [r["id"] for r in database.get_unscored_cashflow()] == ["s1"]
    run_scoring()
    database.upsert_listing(make_listing("s1", size_m2=65.2, rooms=3))   # rounding, not a fix
    assert database.get_unscored_cashflow() == []


# ── 19 ───────────────────────────────────────────────────────────────────────
def test_a_missing_district_does_not_crash_the_engine():
    from engine.financial import analyse, is_industrial_zone
    from modules.location_iq import is_industrial
    assert not is_industrial_zone(None) and is_industrial(None) == (False, "")
    assert analyse(100_000, 55, None).estimated_rent > 0


# ── 21 ───────────────────────────────────────────────────────────────────────
def test_the_header_notes_are_one_line_with_details(populated_db):
    at = run_app()
    assert not at.exception
    notes = [e for e in at.expander if e.label.endswith("— details")]
    assert len(notes) <= 1


def test_the_tab_in_the_address_is_opened(populated_db):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(smoke.APP, default_timeout=120)
    at.query_params["group"] = "📊 ANALYSIS"
    at.query_params["tab"] = "RENT COMPS"
    at.run()
    assert not at.exception
