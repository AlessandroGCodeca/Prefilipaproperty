"""Audit 3, dashboard: regression tests for the confirmed findings #25–#32.

Synthetic listings only (ids, titles and LV numbers are made up). No network:
the cadastre lookups are stubbed.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from engine.financial import compute_deal_score
from tests.conftest import make_listing

pytest.importorskip("streamlit")
from streamlit.proto.WidgetStates_pb2 import WidgetState  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402
from streamlit.testing.v1.element_tree import ElementTree  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    from modules import jobs, pipeline_state
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "status.json"))
    database.init_db()
    yield database
    jobs.wait(60)
    monkeypatch.setattr(jobs, "_job", None)


def _sql(db, query, *args):
    conn = sqlite3.connect(db.SQLITE_PATH)
    try:
        rows = conn.execute(query, args).fetchall()
        conn.commit()
    finally:
        conn.close()
    return rows


def add(db, lid, **over):
    now = datetime.now(timezone.utc)
    over.setdefault("last_seen_at", now.isoformat())
    over.setdefault("scraped_at", (now - timedelta(days=3)).isoformat())
    db.upsert_listing(make_listing(lid, **over))


def score(db, lid, price, district, market="sk", rent=650, size=55.0):
    from engine import financial as fin
    r = fin.analyse(price, size, district, listing_id=lid, rent_override=rent,
                    **({} if market == "sk" else {"market": market}))
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    db.upsert_cashflow(row)
    return r


def run(open_cards=(), pending=True, **state):
    at = AppTest.from_file(APP, default_timeout=120)
    if pending:
        at.session_state["pending_list"] = True
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    ok(at)
    return at


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def md(at):
    return "\n".join(m.value for m in at.markdown)


def pick_market(at, label):
    next(r for r in at.radio if r.key == "market_view").set_value(label).run()
    return ok(at)


def frame(at, column):
    return next(d.value for d in at.dataframe if column in d.value.columns)


# ── #25 LV TO-DO: a typed LV number stays with its listing ───────────────────
def _todo(db):
    """Two GREEN listings on the LV to-do queue, A first (deeper discount)."""
    for lid, price in (("todoA", 70_000.0), ("todoB", 72_000.0)):
        add(db, lid, district="Žilina", price_eur=price, title=f"Flat {lid}")
        score(db, lid, price, "Žilina")
    _sql(db, "UPDATE cashflow_scores SET classification='GREEN', market_discount=0.30 "
             "WHERE listing_id='todoA'")
    _sql(db, "UPDATE cashflow_scores SET classification='GREEN', market_discount=0.25 "
             "WHERE listing_id='todoB'")
    assert [t["id"] for t in db.get_lv_todo()] == ["todoA", "todoB"]


def _editor_id(at):
    return next(n.proto.id for n in at._tree
                if "lv_todo_editor" in getattr(getattr(n, "proto", None), "id", ""))


def _type_into_editor(monkeypatch, at, row, lv, area):
    """Type into the editor the way the browser does: its edits go back on
    every rerun, by row number, under the editor's element id at the time."""
    eid = _editor_id(at)
    edits = json.dumps({"edited_rows": {str(row): {"Flat LV no.": lv,
                                                     "Katastrálne územie": area}},
                        "added_rows": [], "deleted_rows": []})
    real = ElementTree.get_widget_states

    def with_edits(tree):
        ws = real(tree)
        ws.widgets.append(WidgetState(id=eid, string_value=edits))
        return ws
    monkeypatch.setattr(ElementTree, "get_widget_states", with_edits)
    at.run()
    return ok(at)


def _edited_caption(at):
    return next(c.value for c in at.caption if "listing(s) waiting" in c.value)


def _click_save_if_enabled(at):
    # AppTest refuses to click a disabled button, as a browser would.
    save = at.button(key="lv_todo_save")
    if not save.disabled:
        save.click().run()
    return ok(at)


def _lvs(db):
    return _sql(db, "SELECT id, lv_number, cadastral_area FROM listings "
                    "WHERE id IN ('todoA', 'todoB') ORDER BY id")


def test_lv_todo_edit_is_saved_on_the_listing_it_was_typed_for(db, monkeypatch):
    _todo(db)
    at = _type_into_editor(monkeypatch, run(), 1, "9876", "Testovo")   # row 1 = B
    assert _edited_caption(at).endswith("· 1 edited")
    at.button(key="lv_todo_save").click().run()
    ok(at)
    assert _lvs(db) == [("todoA", None, None), ("todoB", "9876", "Testovo")]


def test_lv_todo_edit_does_not_move_to_another_listing_after_a_resort(db, monkeypatch):
    _todo(db)
    at = _type_into_editor(monkeypatch, run(), 0, "4321", "Testovo")   # row 0 = A
    assert _edited_caption(at).endswith("· 1 edited")
    # A re-score puts B first: row 0 is now B.
    _sql(db, "UPDATE cashflow_scores SET market_discount=0.35 WHERE listing_id='todoB'")
    assert [t["id"] for t in db.get_lv_todo()] == ["todoB", "todoA"]
    at.run()
    ok(at)
    # The pending edit is dropped, not carried over to B.
    assert _edited_caption(at).endswith("· 0 edited")
    assert at.button(key="lv_todo_save").disabled
    assert at.button(key="lv_todo_verify").disabled
    assert _lvs(db) == [("todoA", None, None), ("todoB", None, None)]


def test_save_after_a_resort_never_stores_one_flats_lv_on_another(db, monkeypatch):
    # The audit's sequence end to end: type A's LV, the queue re-sorts, SAVE.
    _todo(db)
    at = _type_into_editor(monkeypatch, run(), 0, "4321", "Testovo")   # row 0 = A
    _sql(db, "UPDATE cashflow_scores SET market_discount=0.35 WHERE listing_id='todoB'")
    at.run()
    _click_save_if_enabled(ok(at))
    assert ("todoB", "4321", "Testovo") not in _lvs(db)
    assert _sql(db, "SELECT lv_number FROM listings WHERE id='todoB'") == [(None,)]


def test_lv_todo_edit_does_not_follow_a_switch_to_the_other_markets_view(db, monkeypatch):
    # One Slovak and one Czech flat on the queue: each market's view has one
    # row, so row 0 is a different listing in each.
    add(db, "todoS", district="Žilina", price_eur=70_000.0, title="Flat todoS")
    score(db, "todoS", 70_000.0, "Žilina")
    add(db, "todoC", district="Praha 2", title="Byt todoC", price_eur=4_000_000.0,
        source="sreality", url="https://example.cz/todoC", market="cz")
    score(db, "todoC", 4_000_000.0, "Praha 2", market="cz", rent=22_000)
    _sql(db, "UPDATE cashflow_scores SET classification='GREEN', market_discount=0.30 "
             "WHERE listing_id IN ('todoS', 'todoC')")
    at = pick_market(run(), "🇸🇰 Slovakia")
    at = _type_into_editor(monkeypatch, at, 0, "4321", "Testovo")      # row 0 = todoS
    assert _edited_caption(at).endswith("· 1 edited")
    at = pick_market(at, "🇨🇿 Czechia")
    assert _edited_caption(at).endswith("· 0 edited")
    assert at.button(key="lv_todo_save").disabled
    _click_save_if_enabled(at)
    assert _sql(db, "SELECT lv_number, cadastral_area FROM listings WHERE id='todoC'") \
        == [(None, None)]


def test_a_saved_lv_edit_is_not_replayed_onto_another_listing(db, monkeypatch):
    _todo(db)
    at = _type_into_editor(monkeypatch, run(), 0, "4321", "Testovo")
    at.button(key="lv_todo_save").click().run()
    ok(at)
    assert _lvs(db) == [("todoA", "4321", "Testovo"), ("todoB", None, None)]
    assert _edited_caption(at).endswith("· 0 edited")
    _sql(db, "UPDATE cashflow_scores SET market_discount=0.35 WHERE listing_id='todoB'")
    at.run()
    ok(at)
    assert _edited_caption(at).endswith("· 0 edited")
    assert at.button(key="lv_todo_save").disabled


def test_the_lv_todo_editor_is_the_same_while_its_rows_are(db):
    # A rerun with the queue unchanged keeps the editor (and so what is typed).
    _todo(db)
    at = run()
    first = _editor_id(at)
    at.run()
    assert _editor_id(ok(at)) == first
    _sql(db, "UPDATE cashflow_scores SET market_discount=0.35 WHERE listing_id='todoB'")
    at.run()
    assert _editor_id(ok(at)) != first


# ── #26 Deal stage boxes load the stored stage ───────────────────────────────
def _tracked(db):
    for lid, district in (("dealA", "Žilina"), ("dealB", "Trnava"), ("dealC", "Nitra")):
        add(db, lid, district=district, title=f"Deal {lid[-1]}")
        score(db, lid, 100_000.0, district)
    db.set_deal_stage("dealA", "VIEWING", "")
    db.set_deal_stage("dealB", "OFFER", "")


def _pipe_pick(at, lid):
    sb = at.selectbox(key="pipe_pick")
    sb.select(next(o for o in sb.options if f"[{lid}" in o)).run()
    return ok(at)


def test_picking_another_deal_shows_its_own_stage(db):
    _tracked(db)
    at = run()
    at = _pipe_pick(at, "dealC")
    assert at.selectbox(key="pipe_stage").value == "NEW"
    at = _pipe_pick(at, "dealB")
    assert at.selectbox(key="pipe_stage").value == "OFFER"
    at = _pipe_pick(at, "dealA")
    assert at.selectbox(key="pipe_stage").value == "VIEWING"


def test_move_deal_with_only_a_note_keeps_the_stage(db):
    _tracked(db)
    at = _pipe_pick(run(), "dealC")
    at = _pipe_pick(at, "dealB")
    at.text_input(key="pipe_note").set_value("called the agent").run()
    next(b for b in ok(at).button if b.label == "MOVE DEAL").click().run()
    ok(at)
    assert db.get_deal_stages()["dealB"]["stage"] == "OFFER"


def test_a_stage_picked_by_hand_is_kept_until_moved(db):
    _tracked(db)
    at = _pipe_pick(run(), "dealA")
    at.selectbox(key="pipe_stage").select("NEGOTIATING").run()
    at.text_input(key="pipe_note").set_value("counter-offer").run()
    assert ok(at).selectbox(key="pipe_stage").value == "NEGOTIATING"
    next(b for b in at.button if b.label == "MOVE DEAL").click().run()
    ok(at)
    assert db.get_deal_stages()["dealA"]["stage"] == "NEGOTIATING"
    assert at.selectbox(key="pipe_stage").value == "NEGOTIATING"


def test_the_cards_stage_box_follows_a_move_made_in_the_pipeline(db):
    _tracked(db)
    at = run(open_cards=("dealA",))
    assert at.selectbox(key="stg_dealA").value == "VIEWING"
    at = _pipe_pick(at, "dealA")
    at.selectbox(key="pipe_stage").select("OFFER").run()
    next(b for b in ok(at).button if b.label == "MOVE DEAL").click().run()
    ok(at)
    assert db.get_deal_stages()["dealA"]["stage"] == "OFFER"
    assert at.selectbox(key="stg_dealA").value == "OFFER"
    # SAVE STAGE pressed only to add a note keeps the stage that is stored.
    at.text_input(key="stgn_dealA").set_value("viewing done").run()
    ok(at).button(key="stgb_dealA").click().run()
    ok(at)
    saved = db.get_deal_stages()["dealA"]
    assert (saved["stage"], saved["note"]) == ("OFFER", "viewing done")


def test_a_reopened_card_shows_the_stored_stage(db):
    _tracked(db)
    at = run(open_cards=("dealA",))
    assert at.selectbox(key="stg_dealA").value == "VIEWING"
    at.session_state["card_dealA"] = False
    at.run()
    assert not any(s.key == "stg_dealA" for s in ok(at).selectbox)
    at.session_state["card_dealA"] = True
    at.run()
    assert ok(at).selectbox(key="stg_dealA").value == "VIEWING"


# ── #27 REJECTED: the Reason filter never hides reasons it was not shown ─────
def _rejections(db):
    add(db, "rejSK", district="Žilina", title="Rejected SK")
    add(db, "rejCZ", district="Praha 2", title="Rejected CZ", price_eur=4_000_000.0,
        source="sreality", url="https://example.cz/rejCZ", market="cz")
    db.set_lv_status("rejSK", "REJECTED", "lien", "synthetic lien")
    db.set_lv_status("rejCZ", "REJECTED", "zástavní právo", "synthetic lien")


def _rejected_titles(at):
    return set(frame(at, "Reason")["Listing"])


def test_rejections_of_the_other_market_reappear_after_switching_back(db):
    _rejections(db)
    at = run()
    assert _rejected_titles(at) == {"Rejected SK", "Rejected CZ"}
    at = pick_market(at, "🇸🇰 Slovakia")
    assert _rejected_titles(at) == {"Rejected SK"}
    at = pick_market(at, "All markets")
    assert _rejected_titles(at) == {"Rejected SK", "Rejected CZ"}


def test_a_new_rejection_reason_is_shown_and_counted(db):
    _rejections(db)
    at = pick_market(pick_market(run(), "🇸🇰 Slovakia"), "All markets")
    add(db, "rejNew", district="Trnava", title="Rejected later")
    db.set_lv_status("rejNew", "REJECTED", "exekúcia", "synthetic distraint")
    at.run()
    ok(at)
    assert _rejected_titles(at) == {"Rejected SK", "Rejected CZ", "Rejected later"}
    assert "3 rejection(s)" in md(at)


def test_a_reason_the_user_unticks_stays_hidden(db):
    _rejections(db)
    at = run()
    ms = next(m for m in at.multiselect if m.label == "Reason")
    ms.unselect("lien").run()
    assert _rejected_titles(ok(at)) == {"Rejected CZ"}
    at.run()
    assert _rejected_titles(ok(at)) == {"Rejected CZ"}


# ── #28 Deal grade: no benchmark earns none of the discount points ───────────
def test_no_benchmark_scores_below_a_real_discount():
    base = {"cap_rate": 0.05, "lv_status": "PENDING"}
    none = compute_deal_score({**base, "market_discount": None})
    cheap = compute_deal_score({**base, "market_discount": 0.20})
    assert none[0] < cheap[0]
    # It scores as a flat at the median does: 0 of the discount's 25.
    assert none == compute_deal_score({**base, "market_discount": 0.0})


def test_a_flat_without_a_benchmark_no_longer_grades_a():
    # The audit's case: cap 5 %, LV pending, no regional median.
    assert compute_deal_score({"cap_rate": 0.05, "market_discount": None,
                               "lv_status": "PENDING"}) == (48, "D")
    assert compute_deal_score({"cap_rate": 0.03, "market_discount": None,
                               "lv_status": "PENDING"})[0] < compute_deal_score(
        {"cap_rate": 0.03, "market_discount": 0.25, "lv_status": "PENDING"})[0]


@pytest.mark.parametrize("row,want", [
    # Values the grade had before the fix, for rows that have a benchmark.
    ({"cap_rate": 0.05, "market_discount": 0.20, "lv_status": "PENDING"}, (76, "B")),
    ({"cap_rate": 0.05, "market_discount": 0.0, "lv_status": "PENDING"}, (48, "D")),
    ({"cap_rate": 0.05, "market_discount": -0.15, "lv_status": "PENDING"}, (48, "D")),
    ({"cap_rate": 0.03, "market_discount": 0.25, "lv_status": "PENDING"}, (69, "B")),
    ({"market_discount": 0.0, "lv_status": "PASS"}, (29, "D")),
    ({"cap_rate": 0.07, "market_discount": 0.35, "location_score": 90,
      "energy_class": "A", "lv_status": "PASS"}, (97, "A")),
])
def test_a_score_with_a_benchmark_is_unchanged(row, want):
    assert compute_deal_score(row) == want


def _grade_before_the_fix(row):
    """compute_deal_score as it was at 929edbb, where a missing discount was
    left out of the maximum. Only that line differs from the fixed one."""
    from engine.financial import below_sanity_floor
    if below_sanity_floor(row.get("market_discount")):
        return 0, "—"
    points = max_pts = 0.0
    cap, discount = row.get("cap_rate"), row.get("market_discount")
    if cap is None and discount is None:
        return 0, "—"
    if cap is not None:
        points += max(0.0, min(cap / 0.06, 1.0)) * 25
        max_pts += 25
    if discount is not None:
        points += max(0.0, min(discount / 0.30, 1.0)) * 25
        max_pts += 25
    if row.get("location_score") is not None:
        points += max(0.0, min(row["location_score"] / 100.0, 1.0)) * 30
        max_pts += 30
    energy = (row.get("energy_class") or "").upper()
    if energy and energy != "UNKNOWN":
        points += {"A0": 10, "A1": 10, "A": 10, "B": 7, "C": 4,
                   "D": 2, "E": 1, "F": 0, "G": 0}.get(energy, 0)
        max_pts += 10
    cond = {"new": 10, "renovated": 8, "good": 5, "original": 2, "poor": 0}
    if (row.get("condition") or "").lower() in cond:
        points += cond[row["condition"].lower()]
        max_pts += 10
    points += 8 - 4 * sum(bool(row.get(k))
                          for k in ("construction_risk", "noise_flag", "flood_zone"))
    if row.get("lv_status") in ("PASS", "CLEAN", None):
        points += 2
    max_pts += 10
    score = max(0, round(points / max_pts * 100)) if max_pts else 0
    return score, ("A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D")


def _golden_cases():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fixtures", "sk_golden.json"), encoding="utf-8") as f:
        return json.load(f)


def _golden_row(case):
    from engine import financial as fin
    return fin.result_to_db_dict(fin.analyse(case["price"], case["size"], case["district"],
                                             rooms=case["rooms"]))


# What else is known about a flat: nothing; a clean LV with energy C and a
# location score; a site flag, a parsed condition and an unverified LV.
_EXTRAS = ({"lv_status": "PENDING"},
           {"lv_status": "PASS", "energy_class": "C", "location_score": 60},
           {"lv_status": "UNVERIFIED", "noise_flag": 1, "condition": "renovated",
            "location_score": 35, "energy_class": "UNKNOWN"})


def test_slovak_golden_cases_with_a_median_grade_as_before():
    with_median = [c for c in _golden_cases() if c["market_discount"] is not None]
    assert len(with_median) >= 10
    for c in with_median:
        row = _golden_row(c)
        assert row["market_discount"] is not None, c["district"]
        for extra in _EXTRAS:
            assert compute_deal_score({**row, **extra}) == _grade_before_the_fix(
                {**row, **extra}), (c["district"], extra)


@pytest.mark.parametrize("cap", [None, 0.0, 0.02, 0.045, 0.06, 0.09])
@pytest.mark.parametrize("discount", [-0.2, 0.0, 0.1, 0.29, 0.31, 0.49])
def test_any_row_with_a_benchmark_grades_as_before(cap, discount):
    for extra in _EXTRAS:
        row = {"cap_rate": cap, "market_discount": discount, **extra}
        assert compute_deal_score(row) == _grade_before_the_fix(row)


def test_a_slovak_place_without_a_median_is_no_longer_graded_on_cap_rate_alone():
    # The golden cases with no regional median (WHITE, no benchmark) grade as
    # a flat at the median would, not on cap rate alone.
    no_median = [c for c in _golden_cases() if c["market_discount"] is None]
    assert no_median
    for c in no_median:
        row = {**_golden_row(c), "lv_status": "PENDING"}
        assert row["market_discount"] is None
        assert compute_deal_score(row) == compute_deal_score({**row, "market_discount": 0.0})
    # Šurany has a cap rate and no median: it graded A on cap rate alone.
    row = {**_golden_row(next(c for c in no_median if c["district"] == "Šurany")),
           "lv_status": "PENDING"}
    assert row["cap_rate"]
    assert _grade_before_the_fix(row)[1] == "A"
    assert compute_deal_score(row)[0] < _grade_before_the_fix(row)[0]
    assert compute_deal_score(row)[1] != "A"


def test_a_czech_card_without_a_benchmark_shows_no_grade_a(db):
    add(db, "czNoMed", district="Praha 2", title="Byt 2+kk test", price_eur=4_500_000.0,
        source="sreality", url="https://example.cz/czNoMed", market="cz")
    r = score(db, "czNoMed", 4_500_000.0, "Praha 2", market="cz", rent=22_000)
    assert r.market_discount is None
    at = run(open_cards=("czNoMed",))
    assert "GRADE A" not in md(at)


# ── #29 WHAT-IF: a listing without a price is not given the example's ───────
def test_whatif_leaves_a_missing_price_blank(db):
    add(db, "noPrice", district="Žilina", title="No price flat", price_eur=0.0)
    at = run()
    sb = at.selectbox(key="wi_pick")
    sb.select(next(o for o in sb.options if "[noPric" in o)).run()
    ok(at)
    price = next(n for n in at.number_input if n.label == "Price €")
    assert price.value is None
    assert any("has no price" in c.value for c in at.caption)
    assert any("Enter a price" in i.value for i in at.info)
    assert not any(m.label == "Class" for m in at.metric)
    # A price typed in runs the numbers.
    price.set_value(90_000).run()
    ok(at)
    assert any(m.label == "Class" for m in at.metric)


def test_whatif_custom_property_still_starts_from_the_example_price(db):
    add(db, "priced", district="Žilina", title="Priced flat", price_eur=95_000.0)
    at = run()
    assert next(n for n in at.number_input if n.label == "Price €").value == 120_000
    sb = at.selectbox(key="wi_pick")
    sb.select(next(o for o in sb.options if "[priced" in o)).run()
    assert next(n for n in ok(at).number_input if n.label == "Price €").value == 95_000


def test_whatif_leaves_a_missing_czech_price_blank(db):
    add(db, "czNoPrice", district="Praha 2", title="Byt bez ceny", price_eur=0.0,
        source="sreality", url="https://example.cz/czNoPrice", market="cz")
    at = run()
    sb = at.selectbox(key="wi_pick")
    sb.select(next(o for o in sb.options if "[czNoPr" in o)).run()
    ok(at)
    assert next(n for n in at.number_input if n.label == "Price Kč").value is None
    assert not any(m.label == "Class" for m in at.metric)


# ── #30 Cards: no "None" for a listing without a Location IQ row ─────────────
def test_a_card_without_location_data_shows_dashes_not_none(db):
    add(db, "noLoc", district="Žilina", title="No location flat")
    score(db, "noLoc", 100_000.0, "Žilina")
    at = run(open_cards=("noLoc",))
    text = md(at)
    assert ">None<" not in text and "None/100" not in text and "None ⚠" not in text
    loc = next(m for m in at.metric if m.label == "Location")
    assert loc.value == "—"
    assert '<span class="l">Amenities</span><span class="v">—</span>' in text
    assert '<span class="l">Walkability</span><span class="v">—</span>' in text


def test_a_czech_card_without_location_data_shows_dashes_not_none(db):
    add(db, "czNoLoc", district="Praha 2", title="Byt bez lokality", price_eur=4_500_000.0,
        source="sreality", url="https://example.cz/czNoLoc", market="cz")
    score(db, "czNoLoc", 4_500_000.0, "Praha 2", market="cz", rent=22_000)
    at = run(open_cards=("czNoLoc",))
    text = md(at)
    assert ">None<" not in text and "None/100" not in text
    assert next(m for m in at.metric if m.label == "Lokalita").value == "—"


def test_a_real_zero_location_score_is_still_shown(db):
    add(db, "zeroLoc", district="Žilina", title="Zero location flat")
    score(db, "zeroLoc", 100_000.0, "Žilina")
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_location(dict(
        listing_id="zeroLoc", lat=49.2, lng=18.7, nearest_transit_m=None, amenity_count=0,
        grocery_count=0, pharmacy_count=0, school_count=0, construction_risk=0,
        noise_flag=0, flood_zone=0, walkability_score=0, industrial_zone=0,
        industrial_zone_name=None, location_score=0, location_tier="POOR",
        scored_at=now, construction_detail=None, noise_detail=None, flood_detail=None,
        geo_precision="street", risk_checked_at=now))
    at = run(open_cards=("zeroLoc",))
    text = md(at)
    assert next(m for m in at.metric if m.label == "Location").value == "0/100"
    assert '<span class="l">Amenities</span><span class="v">0 ⚠️</span>' in text
    assert '<span class="l">Walkability</span><span class="v">0/100</span>' in text
    assert ">POOR<" in text


# ── #31 EARLIER DRAFTS: listed and named in local time ───────────────────────
@pytest.fixture
def bratislava_time():
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Bratislava"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


@pytest.fixture
def download_names(monkeypatch):
    """The file names the page's download buttons offer."""
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    names = []
    real = MemoryMediaFileStorage.load_and_get_id

    def recording(self, path_or_data, mimetype, kind, filename=None):
        names.append(filename)
        return real(self, path_or_data, mimetype, kind, filename)
    monkeypatch.setattr(MemoryMediaFileStorage, "load_and_get_id", recording)
    return names


def test_earlier_drafts_show_the_local_time(db, bratislava_time, download_names):
    add(db, "draftL", district="Žilina", title="Draft flat")
    score(db, "draftL", 100_000.0, "Žilina")
    _sql(db, "INSERT INTO contract_drafts (id, listing_id, ownership_type, agreed_price, "
             "buyer_name, draft_text, generated_at) VALUES (?,?,?,?,?,?,?)",
         "d-test", "draftL", "Personal", 100_000.0, "Test Buyer", "draft text",
         "2026-10-16T23:30:00+00:00")       # 01:30 on the 17th in Bratislava (CEST)
    at = run()
    captions = [c.value for c in at.caption if "Test Buyer" in c.value]
    assert captions and captions[0].startswith("2026-10-17 01:30 · Test Buyer")
    assert not any("2026-10-16 23:30" in c for c in captions)
    assert "contract_draftL_20261017_0130.txt" in download_names


def test_a_fresh_draft_is_listed_at_the_time_written_into_it(db, bratislava_time):
    add(db, "draftN", district="Žilina", title="Draft flat")
    score(db, "draftN", 100_000.0, "Žilina")
    db.save_contract_draft("draftN", "Personal", 100_000.0, "Test Buyer", "", "",
                           "draft text")
    local_now = datetime.now()
    at = run()
    stamp = next(c.value for c in at.caption if "Test Buyer" in c.value).split(" · ")[0]
    listed = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    assert abs(listed - local_now.replace(second=0, microsecond=0)) <= timedelta(minutes=1)


def test_an_unreadable_draft_time_is_shown_as_stored(db, bratislava_time):
    add(db, "draftX", district="Žilina", title="Draft flat")
    score(db, "draftX", 100_000.0, "Žilina")
    _sql(db, "INSERT INTO contract_drafts (id, listing_id, ownership_type, agreed_price, "
             "buyer_name, draft_text, generated_at) VALUES (?,?,?,?,?,?,?)",
         "d-bad", "draftX", "Personal", 100_000.0, "Test Buyer", "draft text", "yesterday")
    at = run()
    assert any(c.value.startswith("yesterday · Test Buyer") for c in at.caption)


# ── #32 REJECTED: RE-VERIFY uses the listing's own market's short timeout ────
@pytest.fixture
def quick_contexts(monkeypatch):
    """Record which market's quick_requests() the re-check ran under, and
    answer the re-check without the network."""
    import kataster_scraper
    from modules import debt_bot, lv_cz
    used = []

    def recorder(name):
        @contextmanager
        def quick():
            used.append(name)
            yield
        return quick
    monkeypatch.setattr(kataster_scraper, "quick_requests", recorder("sk"))
    monkeypatch.setattr(lv_cz, "quick_requests", recorder("cz"))
    monkeypatch.setattr(debt_bot, "reverify",
                        lambda lid, **k: {"status": "UNVERIFIED", "detail": "stubbed"})
    return used


def _reverify(at, lid):
    sb = at.selectbox(key="rej_pick")
    sb.select(next(o for o in sb.options if f"[{lid}" in o)).run()
    ok(at).button(key="rej_rv").click().run()
    return ok(at)


def test_a_czech_recheck_runs_under_the_czech_timeout(db, quick_contexts):
    _rejections(db)
    _reverify(run(), "rejCZ")
    assert quick_contexts == ["cz"]


def test_a_slovak_recheck_still_runs_under_the_slovak_timeout(db, quick_contexts):
    _rejections(db)
    _reverify(run(), "rejSK")
    assert quick_contexts == ["sk"]
