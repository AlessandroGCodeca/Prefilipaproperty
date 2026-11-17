"""The dashboard's screens added on 17 November 2026, run as the page runs:
AUCTIONS, PORTFOLIO and BACKTEST, a card's building / renovation / flip and
short-let sections, the seller checks and building facts of a deal, travel
times on the map, the market rate in YOUR SITUATION and the banners."""

from datetime import date

import pytest

import tests.test_app_smoke as smoke
from tests.test_app_smoke import XSS_NOTE, XSS_TITLE, markdown_of, run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_the_auctions_tab_lists_the_register_escaped(populated_db):
    from database.auctions import upsert_auction
    upsert_auction({"act_id": "ab12", "ncr_no": "1/2026", "auction_date": "2099-01-15",
                    "proposer": XSS_TITLE, "auctioneer": "D s.r.o.", "subject_kind": "Nehnuteľná vec",
                    "municipality": "Trnava", "size_m2": 54, "min_bid_eur": 60_000, "read_at": "x",
                    "notes": XSS_NOTE})
    at = run_app()
    _ok(at)
    assert any("Trnava" in e.label and "lowest bid €60,000" in e.label for e in at.expander)
    md = markdown_of(at)
    assert "<img src=x" not in md


def test_the_portfolio_takes_a_flat_and_its_months(populated_db):
    from database.portfolio import get_ledger, get_owned_flats, save_owned_flat, set_ledger_month
    fid = save_owned_flat({"name": XSS_NOTE, "district": "Žilina", "size_m2": 55, "rooms": 2,
                           "bought_on": "2025-01-10", "price": 110_000, "loan_principal": 80_000,
                           "loan_rate": 0.04, "loan_years": 25, "rent_monthly": 620,
                           "hoa_monthly": 80})
    set_ledger_month(fid, f"{date.today().year}-{date.today().month:02d}", 620, 95, 0)
    at = run_app()
    _ok(at)
    assert any(m.label == "Equity" for m in at.metric)
    assert any(f"✏️ {XSS_NOTE}" in e.label for e in at.expander)
    assert get_owned_flats() and get_ledger(fid)


def test_the_backtest_renders_and_takes_a_sold_price(populated_db):
    at = run_app()
    _ok(at)
    at.text_input(key="bt_d").set_value("Trnava")
    at.number_input(key="bt_s").set_value(54.0)
    at.number_input(key="bt_p").set_value(90_000.0)
    next(b for b in at.button if b.label == "💾 ADD A SOLD PRICE").click().run()
    _ok(at)
    from engine.backtest import sold_prices
    assert sold_prices()[0]["district"] == "Trnava"


def test_a_card_has_the_building_and_flip(populated_db):
    at = run_app(open_cards=["g1"])
    at.toggle(key="bld_g1").set_value(True).run()
    _ok(at)
    md = markdown_of(at)
    assert "Renovation estimate" in md and "FLIP" in md


def test_a_card_in_bratislava_i_has_the_short_let(populated_db):
    populated_db.upsert_listing(smoke.make_listing("s1", district="Bratislava I", price_eur=120_000.0,
                                                   size_m2=45.0))
    populated_db.set_lv_status("s1", "PASS", "", "clean")
    from modules.cashflow_runner import run_scoring
    run_scoring()
    at = run_app(open_cards=["s1"])
    at.toggle(key="str_s1").set_value(True).run()
    _ok(at)
    assert "Beats the long let from" in markdown_of(at)


def test_a_deal_has_seller_checks_and_building_facts(populated_db):
    at = run_app()
    opts = at.selectbox(key="pipe_pick").options
    at.selectbox(key="pipe_pick").set_value(next(o for o in opts if "[g1" in o)).run()
    _ok(at)
    assert "SELLER CHECKS" in markdown_of(at) and "BUILDING FACTS" in markdown_of(at)
    at.number_input(key="bf_hoa_g1").set_value(150.0)
    next(b for b in at.button if b.label == "💾 SAVE BUILDING FACTS").click().run()
    _ok(at)
    from database.building import get_building_facts
    assert get_building_facts("g1")["hoa_monthly"] == 150
    g1 = next(r for r in populated_db.get_all_active() if r["id"] == "g1")
    assert g1["hoa_monthly"] == 150


def test_the_map_filters_by_travel_time(populated_db, monkeypatch):
    from modules import travel
    monkeypatch.setattr(travel, "travel_times", lambda point, origins, mode, **k:
                        {i: 12.0 for i in origins})
    at = run_app()
    at.text_input(key="map_near").set_value("48.40, 17.60").run()
    at.radio(key="map_how").set_value("On foot").run()
    _ok(at)
    assert "within 30 min (on foot)" in markdown_of(at)


def test_your_situation_shows_the_market_rate(populated_db):
    at = run_app()
    _ok(at)
    assert any("ECB rate hasn't been read yet" in c.value or "Market average" in c.value
               for c in at.sidebar.caption)


def test_the_overdue_run_and_the_december_reminder_show(populated_db, monkeypatch):
    from modules import pipeline_state, yearly
    monkeypatch.setattr(yearly, "reminders", lambda today=None: yearly.due(date(2026, 12, 2)))
    monkeypatch.setattr(pipeline_state, "read_status", lambda market="sk": {
        "state": "ok", "trigger": "06:00", "finished_at": "2026-01-01T06:30:00+01:00",
        "steps": [], "summary": ""})
    at = run_app()
    _ok(at)
    assert any("collect the 2027 tax figures" in i.value for i in at.info)
    assert any("none since" in w.value and "HEALTHCHECK_URL" in w.value for w in at.warning)


@pytest.mark.parametrize("tab", ["AUCTIONS", "BACKTEST", "PORTFOLIO"])
def test_the_new_tabs_are_there(populated_db, tab):
    at = run_app()
    assert tab in [t.label for t in at.tabs]
