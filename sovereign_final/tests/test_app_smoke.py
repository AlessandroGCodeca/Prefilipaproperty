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

import pandas as pd
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


def run_app(open_cards=()) -> AppTest:
    """Run the dashboard. A card builds its body only once it is opened, so
    a test that reads one opens it first, as a click on its header would."""
    at = AppTest.from_file(APP, default_timeout=120)
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    return at.run()


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
    assert len(at.tabs) == 10


def test_stats_bar_counts_the_listings_on_the_page(populated_db):
    # A real zero used to be replaced by the demo rows' count (`x or demo`).
    at = run_app()
    shown = stats_bar(at)
    assert shown["Yellow"] == 0
    # The tiles are the lists below: Total is their sum, and the scored ones
    # are the triage table's rows. p1 (no size) is under the Min Size filter.
    assert shown["Total"] == shown["Green"] + shown["Yellow"] + shown["White"] + shown["Pending"]
    assert shown["Green"] + shown["White"] == len(_frame(at, "Grade")) == 3
    assert shown["Pending"] == 0
    # r1 failed LV: counted as rejected, and only there.
    assert shown["Rejected"] == 1


def test_stats_bar_follows_the_sidebar_filters(populated_db):
    # get_stats() ignored every filter: the tiles stayed put while the
    # cards below dropped from 53 to 10.
    at = run_app()
    max_price = next(s for s in at.slider if s.label == "Max Price €")
    max_price.set_value(60_000).run()
    assert not at.exception, [e.value for e in at.exception]
    shown = stats_bar(at)
    assert shown["Total"] == shown["Green"] == shown["White"] == 0
    assert shown["Rejected"] == 1                 # r1 asks €55,000
    assert "Showing 0 of 4 listings · 4 hidden by the sidebar filters" in markdown_of(at)
    next(s for s in at.slider if s.label == "Max Price €").set_value(50_000).run()
    assert stats_bar(at)["Rejected"] == 0


def test_text_from_portals_and_notes_is_escaped(populated_db):
    md = markdown_of(run_app(open_cards=("g1", "w2")))
    for raw in ("<img src=x", "<script>", "<b onmouseover"):
        assert raw not in md
    # …and it is still shown, as text.
    assert "&lt;script&gt;" in md
    assert "&lt;b onmouseover" in md


# ── Review fixes ──────────────────────────────────────────────────────────────
def _now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _add_scored(db, lid, district, price, size, **kw):
    seen = dict(last_seen_at=_now_iso(), scraped_at=_now_iso(9))
    db.upsert_listing(make_listing(lid, district=district, price_eur=float(price),
                                   size_m2=float(size), **{**seen, **kw}))
    db.set_lv_status(lid, "PASS", "", "clean")
    from modules.cashflow_runner import run_scoring
    run_scoring()


def _frame(at, column):
    """The st.dataframe that has `column`."""
    return next(d.value for d in at.dataframe if column in d.value.columns)


def test_demo_mode_writes_nothing(db):
    # The demo rows (d1–d3) are not in the database; saving a stage, a note
    # or an LV check for them left rows pointing at listings that don't exist.
    at = run_app(open_cards=("d1",))
    assert not at.exception, [e.value for e in at.exception]
    assert at.button(key="stgb_d1").disabled
    assert at.button(key="rv_d1").disabled
    for label in ("MOVE DEAL", "SAVE ANNOTATION"):
        assert all(b.disabled for b in at.button if b.label == label), label
    assert db.get_deal_stages() == {}


def test_triage_to_yellow_matches_the_card_and_no_benchmark_is_blank(populated_db):
    _add_scored(populated_db, "nb", "", 90_000, 50, title="No district flat")
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    df = _frame(at, "Grade")
    assert "To 🟡" in df.columns and "Ask vs 🟡" not in df.columns
    nb = df[df["Title"] == "No district flat"].iloc[0]
    assert pd.isna(nb["Below%"])                  # not "0% below" = at market
    w1 = df[df["District"] == "Žilina"].iloc[0]
    my = populated_db.get_all_active()
    my = next(l for l in my if l["id"] == "w1")["max_price_yellow"]
    assert w1["To 🟡"] == pytest.approx((my / 100_000 - 1) * 100)   # as on the card


def test_price_cut_banner_names_the_class_at_the_new_price(db):
    # Trnava, 50 m²: median ≈ €2,616/m², so max YELLOW is ≈ €117,500.
    from engine.regional_prices import regional_median_price
    median = regional_median_price("Trnava") * 50
    for lid, before, after in (("cy", 0.95, 0.88),     # WHITE → YELLOW
                               ("cf", 0.80, 0.49)):    # GREEN → below the floor
        db.upsert_listing(make_listing(lid, district="Trnava", size_m2=50.0,
                                       price_eur=round(median * before), title=f"Flat {lid}",
                                       scraped_at=_now_iso(30), last_seen_at=_now_iso(30)))
        db.upsert_listing(make_listing(lid, district="Trnava", size_m2=50.0,
                                       price_eur=round(median * after), title=f"Flat {lid}",
                                       scraped_at=_now_iso(30), last_seen_at=_now_iso(2)))
        db.set_lv_status(lid, "PASS", "", "clean")
    from modules.cashflow_runner import run_scoring
    run_scoring()
    md = markdown_of(run_app())
    banner = {lid: next(line for line in md.split("</div>") if f"Flat {lid}" in line
                        and "open ↗" in line) for lid in ("cy", "cf")}
    assert "now YELLOW" in banner["cy"]
    assert "below the sanity floor" in banner["cf"]
    assert "within YELLOW" not in md


def test_whatif_tooltip_says_below_the_median(populated_db):
    at = run_app()
    sb = at.selectbox(key="wi_pick")
    sb.select(next(o for o in sb.options if "[g1]" in o)).run()
    help_ = next(m.help for m in at.metric if m.label == "Class")
    assert "below the regional median" in help_ and "+" not in help_.split("below")[0]


def test_whatif_keeps_a_blank_district_blank(populated_db):
    _add_scored(populated_db, "nd", "", 90_000, 50, title="No district flat")
    at = run_app()
    # A custom property still starts from the example district…
    assert at.text_input(key="wi_dist_custom").value == "Bratislava II"
    # …but a listing without one isn't benchmarked against it.
    sb = at.selectbox(key="wi_pick")
    sb.select(next(o for o in sb.options if "[nd]" in o)).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.text_input(key="wi_dist_nd").value == ""
    assert next(m.value for m in at.metric if m.label == "Class") == "WHITE"


def test_rejected_tab_shows_the_current_status_and_hides_overturned(populated_db):
    db = populated_db
    db.upsert_listing(make_listing("o1", district="Košice", title="Cleared since"))
    db.set_lv_status("o1", "REJECTED", "exekúcia", "exekúcia on the LV")
    db.set_lv_status("o1", "PASS", "", "lien cleared")
    at = run_app()
    rej = _frame(at, "Reason")
    assert "Now" in rej.columns
    assert "Cleared since" not in set(rej["Listing"])
    assert set(rej["Now"]) == {"❌ LV REJECTED"}
    at.toggle(key="rej_overturned").set_value(True).run()
    rej = _frame(at, "Reason")
    row = rej[rej["Listing"] == "Cleared since"].iloc[0]
    assert row["Now"].startswith("✅ LV CLEAN")


def test_a_recheck_that_comes_back_unverified_is_not_called_clean(populated_db, monkeypatch):
    import modules.debt_bot as bot
    monkeypatch.setattr(bot, "reverify",
                        lambda lid, **k: {"status": "UNVERIFIED", "detail": "no title deed read"})
    at = run_app()
    at.button(key="rej_rv").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("unverified" in w.value for w in at.warning)
    assert not any("Now clean" in s.value for s in at.success)


def test_pipeline_warns_when_a_tracked_deal_failed_lv(populated_db):
    populated_db.set_deal_stage("r1", "OFFER", "")
    at = run_app()
    assert any("failed the LV check" in e.value for e in at.error)
    assert "LV REJECTED" in markdown_of(at)


def test_a_rejected_portal_copy_is_flagged_on_the_card(db):
    for lid, source in (("n1", "nehnutelnosti"), ("t1", "topreality")):
        _add_scored(db, lid, "Trnava", 99_000, 54, source=source, title=f"Copy {lid}")
    db.set_lv_status("t1", "REJECTED", "záložné právo", "lien")
    db.mark_duplicates()
    assert "A COPY FAILED LV" in markdown_of(run_app(open_cards=("n1",)))


# ── Review follow-ups ─────────────────────────────────────────────────────────
def _copies_of_one_flat(db):
    """Trnava, 54 m²: n1 (verified, €161k) is the primary; t1 (€157k) the copy."""
    for lid, source, price in (("n1", "nehnutelnosti", 161_000), ("t1", "topreality", 157_000)):
        _add_scored(db, lid, "Trnava", price, 54, source=source, title=f"Copy {lid}")
    db.set_lv_status("t1", "UNVERIFIED", "", "no flat LV")
    db.mark_duplicates()


def test_hidden_copies_are_picked_after_the_filters(db):
    # The primary alone fails the price cap; its copy passes it. Picking the
    # primary first dropped the flat from the list altogether.
    _copies_of_one_flat(db)
    at = run_app()
    assert set(_frame(at, "Grade")["Title"]) == {"Copy n1"}
    next(s for s in at.slider if s.label == "Max Price €").set_value(160_000).run()
    assert not at.exception, [e.value for e in at.exception]
    assert set(_frame(at, "Grade")["Title"]) == {"Copy t1"}


def test_a_recheck_redraws_the_page_whatever_it_finds(populated_db, monkeypatch):
    # Only a PASS used to rerun: an UNVERIFIED result left the table above
    # still listing the flat as rejected.
    import modules.debt_bot as bot

    def reverify(lid, **k):
        populated_db.set_lv_status(lid, "UNVERIFIED", "", "no title deed read")
        return {"status": "UNVERIFIED", "detail": "no title deed read"}
    monkeypatch.setattr(bot, "reverify", reverify)
    at = run_app()
    at.button(key="rej_rv").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("unverified" in w.value for w in at.warning)
    assert "❌ LV REJECTED" not in set(_frame(at, "Reason")["Now"])


def test_a_recheck_updates_the_flats_other_copies(db, monkeypatch):
    for lid, source in (("n1", "nehnutelnosti"), ("t1", "topreality")):
        _add_scored(db, lid, "Trnava", 99_000, 54, source=source, title=f"Copy {lid}")
    db.set_lv_status("t1", "REJECTED", "záložné právo", "lien")
    db.mark_duplicates()
    import modules.debt_bot as bot

    def reverify(lid, **k):
        db.set_lv_status(lid, "PASS", "", "lien cleared")
        return {"status": "PASS", "detail": "lien cleared"}
    monkeypatch.setattr(bot, "reverify", reverify)
    at = run_app(open_cards=("n1",))
    assert "A COPY FAILED LV" in markdown_of(at)
    at.button(key="rej_rv").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Now clean" in s.value for s in at.success)
    assert "A COPY FAILED LV" not in markdown_of(at)


def test_demo_mode_still_moves_a_real_tracked_deal(populated_db):
    at = run_app()
    next(t for t in at.toggle if t.label == "Demo data (no DB)").set_value(True).run()
    move = next(b for b in at.button if b.label == "MOVE DEAL")
    assert move.disabled                          # first pick is a demo row
    pick = at.selectbox(key="pipe_pick")
    pick.select(next(o for o in pick.options if "[g1]" in o)).run()
    at.selectbox(key="pipe_stage").select("OFFER").run()
    move = next(b for b in at.button if b.label == "MOVE DEAL")
    assert not move.disabled
    move.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert populated_db.get_deal_stages()["g1"]["stage"] == "OFFER"
    assert "d1" not in populated_db.get_deal_stages()


def test_the_card_shows_claudes_lv_summary_once(populated_db):
    populated_db.set_lv_analysis("g1", "LOW", "Only a bank mortgage on the flat.")
    populated_db.set_lv_status("g1", "PASS", "", "[Claude LOW] Only a bank mortgage on the flat.")
    assert markdown_of(run_app(open_cards=("g1",))).count("Only a bank mortgage on the flat.") == 1


# ── Audit B1–B6 ───────────────────────────────────────────────────────────────
def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_a_card_builds_its_body_only_when_opened(populated_db):
    # B1: a collapsed card ran its ~40 widgets on every click all the same.
    def stage_buttons(at):
        return [b.key for b in at.button if (b.key or "").startswith("stgb_")]
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert stage_buttons(at) == []
    assert stage_buttons(run_app(open_cards=("g1",))) == ["stgb_g1"]


def click_open(monkeypatch, at, label_part):
    """Open a card the way a click in the browser does: the page reports an
    open expander under its element id, which changes with its label, for as
    long as that expander is on the page. (run_app(open_cards=…) sets the
    state under the key instead, which outlives a label change.)"""
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    from streamlit.testing.v1.element_tree import ElementTree
    exp_id = next(e.proto.id for e in at.expander if label_part in e.label)
    real = ElementTree.get_widget_states

    def with_the_card_open(tree):
        ws = real(tree)
        if any(e.proto.id == exp_id for e in tree.get("expander")):
            ws.widgets.append(WidgetState(id=exp_id, bool_value=True))
        return ws
    monkeypatch.setattr(ElementTree, "get_widget_states", with_the_card_open)
    return at.run()


def test_saving_a_stage_keeps_the_card_open(populated_db, monkeypatch):
    # The stage is in the card's header, and an expander whose label changes
    # comes back closed — saving a stage would fold the card away.
    at = click_open(monkeypatch, run_app(), "[VIEWING]")
    assert any(b.key == "stgb_g1" for b in at.button)
    at.selectbox(key="stg_g1").select("OFFER").run()
    at.text_input(key="stgn_g1").set_value("offer €95k").run()
    at.button(key="stgb_g1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert populated_db.get_deal_stages()["g1"]["stage"] == "OFFER"
    assert populated_db.get_deal_stages()["g1"]["note"] == "offer €95k"
    assert any("[OFFER]" in e.label for e in at.expander)
    assert any(b.key == "stgb_g1" for b in at.button)    # still open


def test_cards_come_a_page_at_a_time(db):
    # B1: 30 WHITE listings — 25 cards on the first page, 5 on the second.
    from engine.regional_prices import regional_median_price
    from modules.cashflow_runner import run_scoring
    at_market = round(regional_median_price("Žilina") * 55)
    for i in range(30):
        db.upsert_listing(make_listing(f"w{i:02d}", district="Žilina", size_m2=55.0,
                                       price_eur=float(at_market), title=f"White {i:02d}",
                                       scraped_at=_now_iso(9), last_seen_at=_now_iso()))
    run_scoring()

    def white_cards(at):
        return [e.label for e in at.expander if e.label.startswith("⚪")]
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert len(white_cards(at)) == 25
    at.selectbox(key="page_white_30").select_index(1).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(white_cards(at)) == 5


def test_seeded_sample_rows_show_with_the_default_filters(db):
    # B3: the seed's rows are source='sample', which the fixed Source filter
    # could not select — the tabs said "No listings in DB yet".
    import seed_market_data
    seed_market_data.seed()
    from collections import Counter
    assert Counter(l["cf_class"] for l in db.get_all_active()) == {
        "WHITE": 37, "YELLOW": 8, "GREEN": 5}   # was 34 GREEN of 50
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert "sample" in next(m for m in at.multiselect if m.label == "Source").value
    shown = stats_bar(at)
    assert (shown["Green"], shown["Yellow"]) == (5, 8)
    assert not [i for i in at.info if "No listings in DB yet" in i.value]


def test_filters_that_hide_everything_say_so(populated_db):
    # B3: an empty list blamed the database for what the filters hid.
    at = run_app()
    next(t for t in at.text_input if t.label == "District contains").set_value("Nowhere").run()
    assert not at.exception, [e.value for e in at.exception]
    infos = [i.value for i in at.info]
    assert not [i for i in infos if "No listings in DB yet" in i]
    assert [i for i in infos if "hidden by them" in i]


def test_a_steps_result_survives_the_rerun(populated_db):
    # B4: st.success(...) then st.rerun() wiped the message straight away.
    populated_db.upsert_listing(make_listing("old", district="Trnava", scraped_at=_now_iso(40),
                                             last_seen_at=_now_iso(30)))
    at = run_app()
    _button(at, "🧹 CLEAN STALE (21d)").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Deactivated 1 stale listings" in s.value for s in at.success)
    assert any("Deactivated 1 stale listings" in t.value for t in at.toast)
    at.run()                                      # shown once, not for good
    assert not any("Deactivated" in s.value for s in at.success)


def test_parse_desc_says_why_nothing_was_parsed(populated_db, monkeypatch):
    import modules.llm_enrichment as llm
    monkeypatch.setattr(llm, "ANTHROPIC_API_KEY", "")
    at = run_app()
    _button(at, "📝 PARSE DESC").click().run()
    assert any("set ANTHROPIC_API_KEY" in i.value for i in at.info)


def test_a_scrapers_count_is_shown_after_the_rerun(populated_db, monkeypatch):
    import subprocess
    import modules.llm_enrichment as llm
    monkeypatch.setattr(llm, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 0, '{"ok": true, "n": 7}\n', ""))
    at = run_app()
    _button(at, "BAZOS").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Scraped 7 listings" in s.value for s in at.success)


def test_a_scraper_that_runs_out_of_time_is_reported_not_a_crash(populated_db, monkeypatch):
    # B5: TimeoutExpired went uncaught and the page showed a traceback.
    import subprocess
    import modules.llm_enrichment as llm
    monkeypatch.setattr(llm, "ANTHROPIC_API_KEY", "")
    scored = []
    import modules.cashflow_runner as cf
    real_scoring = cf.run_scoring
    monkeypatch.setattr(cf, "run_scoring", lambda *a, **k: scored.append(1) or real_scoring(*a, **k))

    def too_slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, k.get("timeout"))
    monkeypatch.setattr(subprocess, "run", too_slow)
    at = run_app()
    _button(at, "NEHNUT").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("5-minute limit" in w.value and "NEHNUT again" in w.value for w in at.warning)
    assert scored                                 # the pages it finished are scored


def test_contract_draft_reads_like_a_draft(populated_db):
    # B6: "Katastrálne územie: None", €99,000.00, and the deal analysis in
    # the text meant for the notár.
    at = run_app()
    sb = at.selectbox(key="close_sel")
    sb.select(next(o for o in sb.options if "[g1]" in o)).run()
    next(t for t in at.text_input if t.label == "Full Name / s.r.o. Name").set_value("Filip Test").run()
    _button(at, "GENERATE CONTRACT DRAFT").click().run()
    assert not at.exception, [e.value for e in at.exception]
    draft = next(t.value for t in at.text_area if t.label == "CONTRACT DRAFT")
    assert "None" not in draft
    assert "FINANČNÁ ANALÝZA" not in draft
    assert "99 000,00 €" in draft and "€99,000" not in draft
    assert any("FINANČNÁ ANALÝZA" in c.value for c in at.code)
    assert populated_db.get_contract_drafts("g1")[0]["draft_text"] == draft


# ── Audit B12–B16 ─────────────────────────────────────────────────────────────
def _pick_listing(at, tag):
    """Select the satellite viewer's listing whose label carries [tag]."""
    sb = next(s for s in at.selectbox if s.label == "Select listing")
    sb.select(next(o for o in sb.options if f"[{tag}]" in o)).run()
    assert not at.exception, [e.value for e in at.exception]


def _satellite_inputs(at):
    # The deal pipeline has a "Note" box too (key pipe_note).
    note = next(t for t in at.text_input if t.label == "Note" and t.key != "pipe_note")
    vibe = next(s for s in at.slider if s.label == "Score (1–10)")
    return note, vibe


def test_a_typed_note_does_not_follow_you_to_the_next_listing(populated_db):
    # The note box and the vibe slider had no per-listing key, so what was typed
    # for one flat stayed in them after picking another and could be saved there.
    at = run_app()
    _pick_listing(at, "g1")
    note, vibe = _satellite_inputs(at)
    note.set_value("note for g1")
    vibe.set_value(9)
    at.run()
    _pick_listing(at, "w1")
    note, vibe = _satellite_inputs(at)
    assert note.value == "" and vibe.value == 5
    next(b for b in at.button if b.label == "SAVE ANNOTATION").click().run()
    assert not any(n["note"] == "note for g1" for n in populated_db.get_annotations("w1"))


def test_the_page_makes_no_external_font_request(db):
    # The CSS used to @import IBM Plex from fonts.googleapis.com: a request to
    # Google on every page view, and a silent fallback whenever it was blocked.
    css = next(m.value for m in run_app().markdown if "<style>" in m.value)
    assert not re.search(r"@import|url\(\s*['\"]?(https?:)?//", css)


def _card_titles(at, prefix):
    return [re.search(rf"{prefix}\w+", e.label).group(0) for e in at.expander
            if re.search(rf"{prefix}\w+", e.label)]


def test_best_deal_ranking_puts_near_floor_discounts_after_the_rest(db):
    # Trnava, 50 m². Deepest-discount-first used to float the 45%-below rows —
    # the ones the card itself warns may be a deposit or an "od €X" price — to
    # the top of the GREEN list.
    from config import NEAR_FLOOR_DISCOUNT
    from engine.regional_prices import benchmark_median
    # make_listing's flats are 2-room: the benchmark is the room-adjusted median.
    median = benchmark_median("Trnava", 2) * 50
    for name, below in (("Suspect45", 0.45), ("Deal30", 0.30), ("Suspect41", 0.41),
                        ("Deal22", 0.22), ("Deal39", 0.39)):
        assert (below >= NEAR_FLOOR_DISCOUNT) == name.startswith("Suspect")
        _add_scored(db, name, "Trnava", round(median * (1 - below)), 50, title=name)
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert _card_titles(at, "(?:Deal|Suspect)") == [
        "Deal39", "Deal30", "Deal22",      # real bargains, deepest first
        "Suspect41", "Suspect45",          # near the floor, least extreme first
    ]


# ── Audit B7–B11 ──────────────────────────────────────────────────────────────
def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_money_puts_the_sign_ahead_of_the_euro(populated_db):
    # Prešov, €55k for 50 m² at default financing runs a monthly deficit.
    at = run_app(open_cards=("g1", "w1", "w2"))
    values = [m.value for m in at.metric] + [m.label for m in at.expander]
    assert not [v for v in values if "€-" in v or "€+" in v]
    assert any(re.match(r"^-€\d", v) for v in values), values


def test_vs_market_fits_its_metric(populated_db):
    at = run_app(open_cards=("g1",))
    g1 = next(m for m in at.metric if m.label == "Below market")
    assert re.fullmatch(r"\d+%", g1.value)


def test_table_money_columns_use_the_euro_format():
    # "€%d" has no thousands separator and prints negatives as €-41.
    src = _read(APP)
    assert 'format="€%' not in src
    assert 'NumberColumn(format="euro", step=1' in src


def test_test_sites_fetches_the_scrapers_own_urls(db, monkeypatch):
    from scraper import _http, bazos, nehnutelnosti, topreality
    fetched = []

    class _Resp:
        status_code, text = 200, "<html>"

    monkeypatch.setattr(_http, "get", lambda url, **k: fetched.append(url) or _Resp())
    at = run_app()
    next(b for b in at.button if b.label == "🔗 TEST SITES").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert fetched == [nehnutelnosti.SEARCH_PAGE.format(page=1),
                       bazos.BASE + bazos.CATEGORY,
                       topreality.SEARCH_URL_CANDIDATES[0].format(page=1)]


def test_theme_file_is_dark_and_the_grid_wraps():
    root = os.path.dirname(APP)
    cfg = _read(os.path.join(root, ".streamlit", "config.toml"))
    assert 'base = "dark"' in cfg and 'primaryColor = "#00e676"' in cfg
    src = _read(APP)
    assert "repeat(6,1fr)" not in src and "auto-fit" in src
    assert "#2a3450" not in src                   # 1.6:1 muted text
    assert not re.search(r"\.stButton>button\s*\{", src)   # missed buttons with a tooltip



# ── Audit A1 / A8 / A12 ───────────────────────────────────────────────────────
def test_a_green_that_loses_money_is_flagged_and_can_be_hidden(populated_db):
    # g1 and w1 are GREEN (far under their medians) but cost money every month.
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    md = markdown_of(at)
    assert "CASH-FLOW NEGATIVE" in md
    assert re.search(r"GREEN — ≥20% BELOW MARKET \((\d+)\) · ⛔ \1 CASH-FLOW NEGATIVE", md)
    next(t for t in at.toggle if t.label.startswith("💶")).set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "CASH-FLOW NEGATIVE" not in markdown_of(at)


def test_days_count_from_the_first_scrape_and_say_so(populated_db):
    at = run_app(open_cards=("g1",))
    labels = {m.label for m in at.metric}
    assert "Days tracked" in labels and "Days listed" not in labels


def test_the_lv_to_do_lists_unverified_deals(populated_db):
    # g1's title deed was never read: it belongs on the queue.
    populated_db.set_lv_status("g1", "UNVERIFIED", "", "no map pin")
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert any("1 listing(s) waiting · 0 edited" in c.value for c in at.caption)
    assert at.button(key="lv_todo_save").disabled
    assert at.button(key="lv_todo_verify").disabled


def test_a_soft_flag_on_the_lv_is_shown_not_rejected(populated_db):
    populated_db.set_lv_status("g1", "PASS", "", "LV 4321: Clean title",
                               soft_flags="vecné bremeno — utility / access easement: <b>x</b>")
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    md = markdown_of(at)
    assert "LV SOFT FLAG" in md
    assert "soft flags (not rejected" in md
    assert "<b>x</b>" not in md        # escaped like every LV note
