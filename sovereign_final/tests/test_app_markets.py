"""The dashboard with both markets: the selector at the top filters every
tab, a Czech listing keeps its crowns on its own card, and the combined view
compares in EUR. Synthetic listings only."""

import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import config  # noqa: E402
from tests.conftest import make_listing  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
NB = " "


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import database
    from modules import jobs, pipeline_state
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "status.json"))
    database.init_db()
    yield database
    jobs.wait(60)
    monkeypatch.setattr(jobs, "_job", None)


@pytest.fixture
def two_markets(_isolated):
    db = _isolated
    now = datetime.now(timezone.utc)
    seen = dict(last_seen_at=now.isoformat(), scraped_at=(now - timedelta(days=3)).isoformat())
    db.upsert_listing(make_listing("sk1", district="Žilina", price_eur=100_000.0,
                                   size_m2=55.0, **seen))
    db.upsert_listing(make_listing("cz1", district="Praha 2", price_eur=4_500_000.0,
                                   size_m2=55.0, title="Byt 2+kk, Praha 2",
                                   source="sreality", url="https://example.cz/cz1",
                                   market="cz", **seen))
    return db


def run(open_cards=()):
    """Run the page with the PENDING list open: unscored listings show there."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["pending_list"] = True
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    return at.run()


def _md(at):
    return "\n".join(m.value for m in at.markdown)


def _pick(at, label):
    next(r for r in at.radio if r.key == "market_view").set_value(label).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_all_markets_is_the_default_and_shows_both(two_markets):
    at = run()
    assert not at.exception, [e.value for e in at.exception]
    radio = next(r for r in at.radio if r.key == "market_view")
    assert radio.value == "All markets"
    md = _md(at)
    assert "SK 1" in md and "CZ 1" in md
    # The Czech price is in crowns, Czech style, wherever it is listed.
    assert f"4{NB}500{NB}000{NB}Kč" in md


def test_the_selector_filters_every_list(two_markets):
    at = _pick(run(), "🇨🇿 Czechia")
    md = _md(at)
    assert "Byt 2+kk, Praha 2" in md and "2-izbový byt sk1" not in md
    at = _pick(at, "🇸🇰 Slovakia")
    md = _md(at)
    assert "2-izbový byt sk1" in md and "Byt 2+kk, Praha 2" not in md


def test_max_price_is_in_euros_for_a_czech_listing_too(two_markets):
    # 4.5M Kč ≈ €185k at the configured rate: under €200k, over €150k.
    eur = 4_500_000 / config.CZK_PER_EUR
    assert 150_000 < eur < 200_000
    at = _pick(run(), "🇨🇿 Czechia")
    slider = next(s for s in at.slider if s.label == "Max Price €")
    slider.set_value(200_000).run()
    assert "Byt 2+kk, Praha 2" in _md(at)
    next(s for s in at.slider if s.label == "Max Price €").set_value(150_000).run()
    assert not at.exception
    assert "Byt 2+kk, Praha 2" not in _md(at)


def test_a_slovak_only_database_looks_as_before(_isolated):
    db = _isolated
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_listing(make_listing("sk1", district="Žilina", last_seen_at=now, scraped_at=now))
    at = run()
    assert not at.exception, [e.value for e in at.exception]
    md = _md(at)
    assert "CZ 0" not in md and "Kč" not in md
    # Czechia has portals, so it has a status line of its own; Slovakia's
    # reads as before, tagged.
    captions = [c.value for c in at.caption]
    assert any(c.startswith("ℹ️ CZ · ") for c in captions)
    assert any(c.endswith(" · SK") for c in captions)


def test_no_czech_status_line_without_czech_portals(_isolated, monkeypatch):
    import scheduler
    monkeypatch.setitem(scheduler.SCRAPERS, "cz", ())
    db = _isolated
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_listing(make_listing("sk1", district="Žilina", last_seen_at=now, scraped_at=now))
    at = run()
    assert not at.exception, [e.value for e in at.exception]
    captions = [c.value for c in at.caption]
    assert not any(" CZ · " in c for c in captions)
    assert not any(c.endswith(" · SK") for c in captions)


def _score(lid, price, district, market, rent):
    from database import upsert_cashflow
    from engine import financial as fin
    r = fin.analyse(price, 55.0, district, listing_id=lid, rent_override=rent,
                    **({} if market == "sk" else {"market": market}))
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    upsert_cashflow(row)


def test_a_czech_card_takes_the_vypis_and_a_slovak_one_does_not(two_markets):
    _score("sk1", 100_000.0, "Žilina", "sk", 650)
    _score("cz1", 4_500_000.0, "Praha 2", "cz", 22_000)
    two_markets.set_lv_document("cz1", "LIST VLASTNICTVÍ: 1234")
    at = run(open_cards=("sk1", "cz1"))
    assert not at.exception, [e.value for e in at.exception]
    boxes = [t for t in at.text_area if t.key and t.key.startswith("lvdoc_")]
    assert [t.key for t in boxes] == ["lvdoc_cz1"]
    assert boxes[0].label == "Výpis z LV (text)" and boxes[0].value == "LIST VLASTNICTVÍ: 1234"


def test_one_click_close_drafts_a_czech_contract_for_a_czech_flat(two_markets):
    _score("cz1", 4_500_000.0, "Praha 2", "cz", 22_000)
    at = _pick(run(), "🇨🇿 Czechia")
    assert any(n.label == "Agreed Price Kč" for n in at.number_input)
    assert not any(n.label == "Agreed Price €" for n in at.number_input)
    next(t for t in at.text_input if t.label == "Full Name / s.r.o. Name").set_value("Test")
    next(b for b in at.button if b.label == "GENERATE CONTRACT DRAFT").click().run()
    assert not at.exception, [e.value for e in at.exception]
    draft = next(t for t in at.text_area if t.label == "CONTRACT DRAFT").value
    assert "KUPNÍ SMLOUVA" in draft and f"4{NB}500{NB}000{NB}Kč" in draft and "€" not in draft


def test_the_comps_tab_follows_the_market(two_markets):
    at = _pick(run(), "🇨🇿 Czechia")
    md = _md(at)
    assert "LIVE RENT COMPS — Kč/m²" in md and "PRENÁJOM LISTINGS" not in md
    assert any("Deloitte" in c.value for c in at.caption)
    at = _pick(at, "🇸🇰 Slovakia")
    md = _md(at)
    assert "PRENÁJOM LISTINGS" in md and "Kč/m²" not in md
