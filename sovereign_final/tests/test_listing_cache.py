"""The dashboard's listing load is cached (dashboard/listing_cache.py, M5 in docs/PROJECT_REVIEW.md).

It took 0.39 s for 5,000 listings and ran on every click. A write from outside
the page (the scheduler's) shows after LISTINGS_TTL_S; a pipeline step run
from the dashboard clears the cache as soon as it finishes.
"""

from datetime import datetime, timezone

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402

from tests.conftest import make_listing  # noqa: E402
from tests.test_app_smoke import run_app  # noqa: E402

pytestmark = pytest.mark.keeps_listing_cache


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    from modules import jobs

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setattr(jobs, "_job", None)     # no other test's finished job
    database.init_db()
    st.cache_data.clear()
    yield database
    st.cache_data.clear()


def _add(db, lid):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_listing(make_listing(lid, last_seen_at=now, scraped_at=now))


def _demo(at) -> bool:
    assert not at.exception, [e.value for e in at.exception]
    return any("demo listings" in i.value for i in at.info)


def test_a_rerun_reads_the_cached_listings(db, monkeypatch):
    calls = []
    real = db.get_all_active
    monkeypatch.setattr(db, "get_all_active",
                        lambda **kw: calls.append(kw) or real(**kw))
    at = run_app()
    n = len(calls)
    assert n
    at.run()
    at.run()
    assert len(calls) == n


def test_an_outside_write_waits_for_the_cache_but_a_finished_step_clears_it(db):
    from modules import jobs

    at = run_app()
    assert _demo(at)                    # empty database
    _add(db, "c1")                      # as the scheduler would, from outside
    assert _demo(at.run())              # still the cached (empty) load

    assert jobs.start("TEST STEP", lambda progress: ("success", "done")) is None
    jobs.wait(30)
    assert not _demo(at.run())          # the step finished: the page reloads


def test_the_cache_has_a_short_time_limit():
    import ast
    import os

    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "dashboard", "listing_cache.py"), encoding="utf-8").read()
    ttl = next(n.value.value for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "LISTINGS_TTL_S")
    assert 0 < ttl <= 300


# ── The other per-listing reads are cached too, and the page's writes clear them ─
def _green(db, lid="g1"):
    from engine.regional_prices import regional_median_price
    from modules.cashflow_runner import run_scoring
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_listing(make_listing(lid, district="Žilina", size_m2=55.0, title="Flat g1",
                                   price_eur=float(round(regional_median_price("Žilina") * 55 * 0.7)),
                                   last_seen_at=now, scraped_at=now))
    run_scoring()


def _triage(at):
    return next(d.value for d in at.dataframe if "Grade" in d.value.columns)


def test_a_rerun_reads_stages_history_and_vibes_from_the_cache(db, monkeypatch):
    _green(db)
    calls = []
    for name in ("get_price_history", "get_deal_stages", "latest_vibes", "get_price_drops"):
        real = getattr(db, name)
        monkeypatch.setattr(db, name, lambda *a, _n=name, _r=real, **k:
                            calls.append(_n) or _r(*a, **k))
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    n = len(calls)
    assert {"get_price_history", "get_deal_stages", "latest_vibes"} <= set(calls)
    at.run()
    at.run()
    assert len(calls) == n


def test_saving_a_stage_on_a_card_shows_at_once(db):
    _green(db)
    at = run_app(open_cards=("g1",))
    at.selectbox(key="stg_g1").select("OFFER").run()
    at.button(key="stgb_g1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("[OFFER]" in e.label for e in at.expander)
    assert _triage(at)["Stage"].tolist() == ["OFFER"]


def test_moving_a_deal_in_the_pipeline_shows_at_once(db):
    _green(db)
    at = run_app()
    at.selectbox(key="pipe_stage").select("VIEWING").run()
    next(b for b in at.button if b.label == "MOVE DEAL").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert db.get_deal_stages()["g1"]["stage"] == "VIEWING"
    assert _triage(at)["Stage"].tolist() == ["VIEWING"]


def test_a_saved_vibe_shows_at_once(db):
    _green(db)
    at = run_app()
    sb = next(s for s in at.selectbox if s.label == "Select listing")
    sb.select(next(o for o in sb.options if "[g1]" in o)).run()
    next(s for s in at.slider if s.label == "Score (1–10)").set_value(9)
    next(b for b in at.button if b.label == "SAVE ANNOTATION").click().run()
    assert not at.exception, [e.value for e in at.exception]
    # The triage table is drawn before the satellite viewer saves, so the
    # click's own run still shows the old vibe; the next one must not (a
    # cache left uncleared would for LISTINGS_TTL_S).
    assert _triage(at.run())["Vibe"].tolist() == [9]
