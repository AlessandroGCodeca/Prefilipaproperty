"""Smoke test for app.py: run the real dashboard script, top to bottom, with
Streamlit's AppTest — on an empty database and on a populated one.

The unit tests never import app.py, so a typo in it goes unnoticed until
someone opens the page. A stray trailing comma after `k1.metric(...)` once made
Streamlit try to render a tuple and the script died on the What-If tab, taking
every tab after it down with it. Any uncaught exception in the script shows up
here as `at.exception`.

Skipped where streamlit isn't installed.
"""

import os
import re
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.conftest import make_listing  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

# Text a stranger can put in a portal listing. Rendered raw, the tags would be
# live HTML on the dashboard.
XSS_TITLE = '<img src=x onerror="alert(1)"> Byt'
XSS_LV = "<script>alert('lv')</script> záložné právo"
XSS_NOTE = "<b onmouseover=alert(2)>note</b>"


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    return database


@pytest.fixture
def populated_db(db):
    now = datetime.now(timezone.utc)
    seen = dict(last_seen_at=now.isoformat(), scraped_at=(now - timedelta(days=9)).isoformat())

    def add(lid, district, price, size, **kw):
        db.upsert_listing(make_listing(lid, district=district, price_eur=float(price),
                                       size_m2=float(size), **seen, **kw))

    add("g1", "Trnava", 99_000, 54)                 # far below the regional median
    add("w1", "Žilina", 100_000, 55)                # at market
    add("w2", "Nitra", 70_000, 60, title=XSS_TITLE)
    add("r1", "Prešov", 55_000, 50)
    add("p1", "Poprad", 75_000, 0, title=XSS_TITLE)  # no size → never scored: pending
    for lid in ("g1", "w1", "w2"):
        db.set_lv_status(lid, "PASS", "", "clean")
    db.set_lv_status("r1", "REJECTED", "záložné právo", XSS_LV)

    from modules.cashflow_runner import run_scoring
    run_scoring()
    db.upsert_location(dict(
        listing_id="g1", lat=48.4, lng=17.6, nearest_transit_m=300, amenity_count=5,
        grocery_count=1, pharmacy_count=1, school_count=1, construction_risk=0,
        noise_flag=1, flood_zone=0, walkability_score=70, industrial_zone=0,
        industrial_zone_name=None, location_score=80, location_tier="PRIME",
        scored_at=now.isoformat(), construction_detail=None, noise_detail=XSS_LV,
        flood_detail=None, geo_precision="street", risk_checked_at=now.isoformat()))
    db.set_deal_stage("g1", "VIEWING", XSS_NOTE)
    db.add_annotation("g1", XSS_NOTE, 8)
    return db


def run_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def markdown_of(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def stats_bar(at: AppTest) -> dict:
    html = next(m.value for m in at.markdown if 'class="sg"' in m.value)
    return {label: int(n) for n, label in
            re.findall(r'class="sn">(\d+)</div><div class="sl">(\w+)', html)}


def test_empty_database_renders_the_demo_view(db):
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert [i.value for i in at.info if "demo listings" in i.value]
    assert ">None<" not in markdown_of(at)


def test_populated_database_renders_every_tab(populated_db):
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 9


def test_stats_bar_shows_the_real_counts(populated_db):
    # A real zero used to be replaced by the demo rows' count (`x or demo`).
    real = populated_db.get_stats()
    assert real["yellow"] == 0 and real["rejected"] == 1
    shown = stats_bar(run_app())
    assert shown["Yellow"] == 0
    assert shown["Green"] == real["green"]
    assert shown["Rejected"] == real["rejected"]
    assert shown["Pending"] == real["pending"]


def test_text_from_portals_and_notes_is_escaped(populated_db):
    md = markdown_of(run_app())
    for raw in ("<img src=x", "<script>", "<b onmouseover"):
        assert raw not in md
    # …and it is still shown, as text.
    assert "&lt;script&gt;" in md
    assert "&lt;b onmouseover" in md
