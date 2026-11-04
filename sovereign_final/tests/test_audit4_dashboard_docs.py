"""Audit 4, dashboard and documents: regression tests for C18–C21.

C18 the card's RE-VERIFY LV wrote its stale LV boxes over an LV number saved
    since (in LV TO-DO), and checked that stale number
C19 the card's stage-note box kept the old note after a DEAL PIPELINE move,
    and SAVE STAGE wrote it back
C20 the memo printed a real 0 location score as "—/100"
C21 stage and note dates in the memo, DEAL PIPELINE and SATELLITE VIEWER were
    the stored UTC text, not Bratislava time

Synthetic listings only (ids, titles, notes and LV numbers are made up). No
network: the cadastre check is stubbed. The expected times are Bratislava
time worked out from fixed UTC stamps, so they hold on a host in any zone.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import make_listing

pytest.importorskip("streamlit")
from streamlit.proto.WidgetStates_pb2 import WidgetState  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402
from streamlit.testing.v1.element_tree import ElementTree  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

# 22:30 UTC on 16 Oct is 00:30 on 17 Oct in Bratislava (CEST, UTC+2).
LATE_UTC = "2026-10-16T22:30:00.123456+00:00"
# 23:30 UTC on 1 Dec is 00:30 on 2 Dec in Bratislava (CET, UTC+1).
WINTER_UTC = "2026-12-01T23:30:00+00:00"


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


def run(open_cards=(), pending=True):
    at = AppTest.from_file(APP, default_timeout=120)
    if pending:
        at.session_state["pending_list"] = True
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    at.run()
    return ok(at)


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def md(at):
    return "\n".join(m.value for m in at.markdown)


def box(at, key):
    return at.text_input(key=key).value


# ── C18 the card's LV boxes load the stored LV number ────────────────────────
@pytest.fixture
def checks(monkeypatch):
    """The LV rows the cadastre check would read, recorded instead of sent."""
    from modules import debt_bot
    seen = []

    def fake_check(row, **kw):
        seen.append((row.get("id"), row.get("lv_number"), row.get("cadastral_area")))
        return {"status": "UNVERIFIED", "detail": "stubbed (no network)"}
    monkeypatch.setattr(debt_bot, "_check_and_store", fake_check)
    return seen


def _flat(db, lid="lvA", **over):
    """A GREEN flat on the LV to-do queue, its own LV not yet known."""
    add(db, lid, district="Žilina", price_eur=70_000.0, title=f"Flat {lid}", **over)
    score(db, lid, 70_000.0, "Žilina")
    _sql(db, "UPDATE cashflow_scores SET classification='GREEN', market_discount=0.30 "
             "WHERE listing_id=?", lid)
    _sql(db, "UPDATE listings SET lv_status='UNVERIFIED' WHERE id=?", lid)


def _lv(db, lid="lvA"):
    return _sql(db, "SELECT lv_number, cadastral_area FROM listings WHERE id=?", lid)[0]


def _reverify_on_card(at, lid="lvA"):
    at.button(key=f"rv_{lid}").click().run()
    return ok(at)


def _save_in_lv_todo(monkeypatch, at, lv, area):
    """Type row 0 of the LV TO-DO editor the way the browser does (its edits
    come back on every rerun under the editor's element id), then SAVE."""
    eid = next(n.proto.id for n in at._tree
               if "lv_todo_editor" in getattr(getattr(n, "proto", None), "id", ""))
    edits = json.dumps({"edited_rows": {"0": {"Flat LV no.": lv, "Katastrálne územie": area}},
                        "added_rows": [], "deleted_rows": []})
    real = ElementTree.get_widget_states

    def with_edits(tree):
        ws = real(tree)
        ws.widgets.append(WidgetState(id=eid, string_value=edits))
        return ws
    monkeypatch.setattr(ElementTree, "get_widget_states", with_edits)
    ok(at.run())
    at.button(key="lv_todo_save").click().run()
    monkeypatch.setattr(ElementTree, "get_widget_states", real)
    return ok(at)


def test_card_reverify_keeps_an_lv_number_saved_in_lv_todo(db, checks, monkeypatch):
    # The audit's first case: the card is open with empty LV boxes, the LV is
    # typed and saved in LV TO-DO, then RE-VERIFY LV is pressed on the card.
    _flat(db)
    at = run(open_cards=("lvA",))
    assert (box(at, "lvno_lvA"), box(at, "lvku_lvA")) == ("", "")
    at = _save_in_lv_todo(monkeypatch, at, "4321", "Testovo")
    assert _lv(db) == ("4321", "Testovo")
    assert (box(at, "lvno_lvA"), box(at, "lvku_lvA")) == ("4321", "Testovo")
    _reverify_on_card(at)
    assert checks == [("lvA", "4321", "Testovo")]
    assert _lv(db) == ("4321", "Testovo")


def test_card_reverify_does_not_put_back_a_superseded_lv_number(db, checks):
    # The second case: an LV checked from the card, then corrected elsewhere.
    _flat(db)
    at = run(open_cards=("lvA",))
    at.text_input(key="lvno_lvA").set_value("1111")
    at.text_input(key="lvku_lvA").set_value("Testovo")
    _reverify_on_card(at)
    assert _lv(db) == ("1111", "Testovo")
    db.set_flat_lv("lvA", "4321", "Testovo")          # corrected, e.g. in LV TO-DO
    ok(at.run())
    assert box(at, "lvno_lvA") == "4321"
    _reverify_on_card(at)
    assert checks == [("lvA", "1111", "Testovo"), ("lvA", "4321", "Testovo")]
    assert _lv(db) == ("4321", "Testovo")


def test_an_lv_number_typed_on_the_card_is_kept_and_checked(db, checks):
    _flat(db)
    at = run(open_cards=("lvA",))
    at.text_input(key="lvno_lvA").set_value("7777").run()
    ok(at.run())                                       # an unrelated rerun
    assert box(at, "lvno_lvA") == "7777"
    _reverify_on_card(at)
    assert checks == [("lvA", "7777", None)]
    assert _lv(db) == ("7777", None)
    assert box(at, "lvno_lvA") == "7777"


def test_untouched_card_boxes_keep_the_stored_lv(db, checks):
    _flat(db)
    db.set_flat_lv("lvA", "4321", "Testovo")
    at = run(open_cards=("lvA",))
    assert (box(at, "lvno_lvA"), box(at, "lvku_lvA")) == ("4321", "Testovo")
    _reverify_on_card(at)
    assert checks == [("lvA", "4321", "Testovo")]
    assert _lv(db) == ("4321", "Testovo")


def test_a_reopened_card_shows_the_stored_lv_number(db, checks):
    _flat(db)
    at = run(open_cards=("lvA",))
    at.text_input(key="lvno_lvA").set_value("9999").run()  # typed, never checked
    at.session_state["card_lvA"] = False
    ok(at.run())
    db.set_flat_lv("lvA", "4321", "Testovo")
    at.session_state["card_lvA"] = True
    ok(at.run())
    assert (box(at, "lvno_lvA"), box(at, "lvku_lvA")) == ("4321", "Testovo")
    assert checks == []


def test_a_czech_cards_lv_boxes_follow_the_stored_lv(db, checks):
    add(db, "lvCZ", district="Praha 2", title="Byt lvCZ", price_eur=4_000_000.0,
        source="sreality", url="https://example.cz/lvCZ", market="cz")
    score(db, "lvCZ", 4_000_000.0, "Praha 2", market="cz", rent=22_000)
    at = run(open_cards=("lvCZ",))
    assert box(at, "lvno_lvCZ") == ""
    db.set_flat_lv("lvCZ", "1234", "Vinohrady")
    ok(at.run())
    assert (box(at, "lvno_lvCZ"), box(at, "lvku_lvCZ")) == ("1234", "Vinohrady")
    _reverify_on_card(at, "lvCZ")
    assert checks == [("lvCZ", "1234", "Vinohrady")]
    assert _lv(db, "lvCZ") == ("1234", "Vinohrady")


# ── C19 the card's stage-note box loads the stored note ──────────────────────
def _deal(db):
    add(db, "dealA", district="Žilina", title="Deal A")
    score(db, "dealA", 100_000.0, "Žilina")
    db.set_deal_stage("dealA", "VIEWING", "viewing Sat 10:00")


def _pipe_move(at, lid, stage, note):
    sb = at.selectbox(key="pipe_pick")
    sb.select(next(o for o in sb.options if f"[{lid}" in o)).run()
    ok(at).selectbox(key="pipe_stage").select(stage).run()
    ok(at).text_input(key="pipe_note").set_value(note).run()
    next(b for b in ok(at).button if b.label == "MOVE DEAL").click().run()
    return ok(at)


def _stored(db, lid="dealA"):
    s = db.get_deal_stages()[lid]
    return s["stage"], s["note"]


def test_the_cards_note_box_follows_a_move_made_in_the_pipeline(db):
    _deal(db)
    at = run(open_cards=("dealA",))
    assert box(at, "stgn_dealA") == "viewing Sat 10:00"
    at = _pipe_move(at, "dealA", "OFFER", "offer sent 92k")
    assert _stored(db) == ("OFFER", "offer sent 92k")
    assert at.selectbox(key="stg_dealA").value == "OFFER"
    assert box(at, "stgn_dealA") == "offer sent 92k"
    # SAVE STAGE on the card keeps the newer note.
    at.selectbox(key="stg_dealA").select("NEGOTIATING").run()
    ok(at).button(key="stgb_dealA").click().run()
    ok(at)
    assert _stored(db) == ("NEGOTIATING", "offer sent 92k")


def test_a_note_only_move_in_the_pipeline_reaches_the_card(db):
    # The stage stays VIEWING; only the note (and the row's time) changes.
    _deal(db)
    at = run(open_cards=("dealA",))
    at = _pipe_move(at, "dealA", "VIEWING", "moved to Sunday")
    assert _stored(db) == ("VIEWING", "moved to Sunday")
    assert box(at, "stgn_dealA") == "moved to Sunday"
    ok(at).button(key="stgb_dealA").click().run()
    ok(at)
    assert _stored(db) == ("VIEWING", "moved to Sunday")


def test_a_note_typed_on_the_card_is_kept_until_saved(db):
    _deal(db)
    at = run(open_cards=("dealA",))
    at.text_input(key="stgn_dealA").set_value("agent called back").run()
    at.selectbox(key="stg_dealA").select("OFFER").run()
    ok(at.run())                                       # an unrelated rerun
    assert box(at, "stgn_dealA") == "agent called back"
    assert at.selectbox(key="stg_dealA").value == "OFFER"
    ok(at).button(key="stgb_dealA").click().run()
    ok(at)
    assert _stored(db) == ("OFFER", "agent called back")
    assert box(at, "stgn_dealA") == "agent called back"


def test_a_reopened_card_shows_the_stored_note(db):
    _deal(db)
    at = run(open_cards=("dealA",))
    at.text_input(key="stgn_dealA").set_value("typed, never saved").run()
    at.session_state["card_dealA"] = False
    ok(at.run())
    at.session_state["card_dealA"] = True
    ok(at.run())
    assert box(at, "stgn_dealA") == "viewing Sat 10:00"
    assert at.selectbox(key="stg_dealA").value == "VIEWING"


def test_a_card_without_a_stage_starts_new_and_blank(db):
    add(db, "dealN", district="Žilina", title="Deal N")
    score(db, "dealN", 100_000.0, "Žilina")
    at = run(open_cards=("dealN",))
    assert at.selectbox(key="stg_dealN").value == "NEW"
    assert box(at, "stgn_dealN") == ""


# ── C20 the memo tells a real 0 location score from a missing one ────────────
def _printed(monkeypatch):
    """Every string the memo prints, as given to it (before any font fold)."""
    from modules import memo
    seen = []
    real = memo._Memo.txt
    monkeypatch.setattr(memo._Memo, "txt", lambda self, s: (seen.append(str(s)), real(self, s))[1])
    return seen


def _kv(seen, label):
    """The value printed next to a label in a memo's label/value table (a
    page break between the two prints the page footer in between)."""
    after = seen[seen.index(label) + 1:]
    return next(s for s in after if not s.startswith("Sovereign RE · investment memo"))


def _memo_row(**over):
    from engine import financial as fin
    r = fin.analyse(100_000, 55, "Žilina", rooms=2)
    row = {**fin.result_to_db_dict(r), **fin.deal_extras(r),
           "id": "memoL", "title": "2-izbový byt, Testovacia", "district": "Žilina",
           "price_eur": 100_000.0, "size_m2": 55.0, "lv_status": "PENDING"}
    row.update(over)
    return row


@pytest.mark.parametrize("loc,want", [
    ({"location_score": 0, "location_tier": "POOR"}, "0/100 POOR"),
    ({"location_score": None, "location_tier": None}, "—"),
    ({}, "—"),
    ({"location_score": 70, "location_tier": "SOLID"}, "70/100 SOLID"),
    ({"location_score": 45, "location_tier": None}, "45/100"),
])
def test_the_memo_prints_the_location_score_as_the_card_does(monkeypatch, loc, want):
    from modules import memo
    seen = _printed(monkeypatch)
    memo.build_memo_pdf(_memo_row(**loc))
    assert _kv(seen, "Location score") == want


@pytest.mark.parametrize("metres,want", [(0.0, "0 m"), (None, "—"), (312.4, "312 m")])
def test_the_memo_prints_the_nearest_transit_as_given(monkeypatch, metres, want):
    from modules import memo
    seen = _printed(monkeypatch)
    memo.build_memo_pdf(_memo_row(nearest_transit_m=metres))
    assert _kv(seen, "Nearest transit") == want


def test_the_cards_zero_location_score_reads_the_same_in_its_memo(db, monkeypatch):
    # The card's own row (get_all_active), as the 📄 MEMO button passes it.
    from modules import memo
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
    row = next(r for r in db.get_all_active() if r["id"] == "zeroLoc")
    assert row["location_score"] == 0
    seen = _printed(monkeypatch)
    memo.build_memo_pdf(row)
    assert _kv(seen, "Location score") == "0/100 POOR"
    at = run(open_cards=("zeroLoc",))
    assert next(m for m in at.metric if m.label == "Location").value == "0/100"


# ── C21 stage and note dates in Bratislava time ──────────────────────────────
def _memo_notes(monkeypatch, stamp):
    from modules import memo
    from modules.contract_draft import LOCAL_TZ
    seen = _printed(monkeypatch)
    made = LOCAL_TZ.localize(datetime(2026, 10, 17, 0, 35))
    memo.build_memo_pdf(_memo_row(),
                        stage={"stage": "OFFER", "note": "offer sent", "updated_at": stamp},
                        notes=[{"created_at": stamp, "vibe_score": 8, "note": "viewed it"}],
                        generated_at=made)
    return seen


def test_the_memo_dates_a_stage_and_a_note_in_bratislava_time(monkeypatch):
    seen = _memo_notes(monkeypatch, LATE_UTC)
    assert "Memo generated 2026-10-17 00:35" in "\n".join(seen)
    assert "Stage: OFFER (since 2026-10-17) — offer sent" in seen
    assert "2026-10-17 · vibe 8/10 · viewed it" in seen
    assert not any("2026-10-16" in s for s in seen)


def test_the_memo_dates_a_winter_stage_in_bratislava_time(monkeypatch):
    seen = _memo_notes(monkeypatch, WINTER_UTC)
    assert "Stage: OFFER (since 2026-12-02) — offer sent" in seen
    assert "2026-12-02 · vibe 8/10 · viewed it" in seen


def test_the_memo_keeps_a_daytime_date_and_an_unreadable_stamp(monkeypatch):
    # A stamp that is the same day in both zones reads as before; one that
    # is not a time at all is printed as stored.
    seen = _memo_notes(monkeypatch, "2026-09-13T08:00:00+00:00")
    assert "Stage: OFFER (since 2026-09-13) — offer sent" in seen
    seen.clear()
    seen += _memo_notes(monkeypatch, "sometime")
    assert "Stage: OFFER (since sometime) — offer sent" in seen
    assert "sometime · vibe 8/10 · viewed it" in seen


def test_the_memo_from_stored_rows_uses_bratislava_dates(db, monkeypatch):
    # The rows the 📄 MEMO button passes, written by the real DB writers.
    from modules import memo
    add(db, "dealT", district="Žilina", title="Deal T")
    db.set_deal_stage("dealT", "OFFER", "offer sent")
    db.add_annotation("dealT", "viewed it", 8)
    _sql(db, "UPDATE deal_stages SET updated_at=?", LATE_UTC)
    _sql(db, "UPDATE annotations SET created_at=?", LATE_UTC)
    seen = _printed(monkeypatch)
    memo.build_memo_pdf(_memo_row(id="dealT"), stage=db.get_deal_stages()["dealT"],
                        notes=db.get_annotations("dealT"))
    assert "Stage: OFFER (since 2026-10-17) — offer sent" in seen
    assert "2026-10-17 · vibe 8/10 · viewed it" in seen


def _late_deal(db):
    add(db, "dealT", district="Žilina", title="Deal T")
    score(db, "dealT", 100_000.0, "Žilina")
    db.set_deal_stage("dealT", "OFFER", "offer sent")
    db.add_annotation("dealT", "viewed it", 8)
    _sql(db, "UPDATE deal_stages SET updated_at=?", LATE_UTC)
    _sql(db, "UPDATE deal_stage_history SET changed_at=?", LATE_UTC)
    _sql(db, "UPDATE annotations SET created_at=?", LATE_UTC)


def test_deal_pipeline_shows_stage_times_in_bratislava_time(db):
    _late_deal(db)
    at = run()
    sb = at.selectbox(key="pipe_pick")
    sb.select(next(o for o in sb.options if "[dealT" in o)).run()
    text = md(ok(at))
    assert '<span class="l">2026-10-17 00:30</span>' in text      # stage history
    assert "· 2026-10-17</div>" in text                            # the board's card
    assert "2026-10-16 22:30" not in text
    assert "· 2026-10-16</div>" not in text


def test_satellite_viewer_shows_note_times_in_bratislava_time(db):
    _late_deal(db)
    at = run()
    text = md(at)
    assert '<span class="l">2026-10-17 00:30 · 8/10</span>' in text
    assert "2026-10-16 22:30" not in text


def test_dashboard_times_agree_with_earlier_drafts(db):
    # The same instant reads the same on one page: a draft saved with the
    # stage move and the note is listed at 00:30 too.
    _late_deal(db)
    _sql(db, "INSERT INTO contract_drafts (id, listing_id, ownership_type, agreed_price, "
             "buyer_name, draft_text, generated_at) VALUES (?,?,?,?,?,?,?)",
         "d-late", "dealT", "Personal", 100_000.0, "Test Buyer", "draft text", LATE_UTC)
    at = run()
    sb = at.selectbox(key="pipe_pick")
    sb.select(next(o for o in sb.options if "[dealT" in o)).run()
    text = md(ok(at))
    drafts = [c.value for c in at.caption if "Test Buyer" in c.value]
    assert drafts and drafts[0].startswith("2026-10-17 00:30 · ")
    assert '<span class="l">2026-10-17 00:30</span>' in text
    assert '<span class="l">2026-10-17 00:30 · 8/10</span>' in text


def test_an_unreadable_stage_time_is_shown_as_stored(db):
    _late_deal(db)
    _sql(db, "UPDATE deal_stage_history SET changed_at='sometime'")
    _sql(db, "UPDATE annotations SET created_at='sometime'")
    at = run()
    sb = at.selectbox(key="pipe_pick")
    sb.select(next(o for o in sb.options if "[dealT" in o)).run()
    text = md(ok(at))
    assert '<span class="l">sometime</span>' in text
    assert '<span class="l">sometime · 8/10</span>' in text


# ── The Czech card's výpis box loads the stored výpis, as the LV boxes do ────
_VYPIS_OLD = "LIST VLASTNICTVÍ: 1234\nC Omezení vlastnického práva\nBez zápisu\n"
_VYPIS_NEW = "LIST VLASTNICTVÍ: 1234\nC Omezení vlastnického práva\no Zástavní právo smluvní\n"


def _cz_flat(db):
    add(db, "docCZ", district="Praha 2", title="Byt docCZ", price_eur=4_000_000.0,
        source="sreality", url="https://example.cz/docCZ", market="cz")
    score(db, "docCZ", 4_000_000.0, "Praha 2", market="cz", rent=22_000)


def _doc(db):
    return db.get_lv_documents(["docCZ"]).get("docCZ", "")


def test_card_reverify_keeps_a_vypis_pasted_since(db, checks):
    _cz_flat(db)
    db.set_lv_document("docCZ", _VYPIS_OLD)
    at = run(open_cards=("docCZ",))
    assert at.text_area(key="lvdoc_docCZ").value.strip() == _VYPIS_OLD.strip()
    db.set_lv_document("docCZ", _VYPIS_NEW)          # pasted elsewhere meanwhile
    ok(at.run())
    assert at.text_area(key="lvdoc_docCZ").value.strip() == _VYPIS_NEW.strip()
    _reverify_on_card(at, "docCZ")
    assert _doc(db).strip() == _VYPIS_NEW.strip()


def test_a_vypis_typed_on_the_card_is_kept_and_stored(db, checks):
    _cz_flat(db)
    at = run(open_cards=("docCZ",))
    at.text_area(key="lvdoc_docCZ").input(_VYPIS_NEW).run()
    ok(at.run())                                      # an unrelated rerun keeps it
    assert at.text_area(key="lvdoc_docCZ").value == _VYPIS_NEW
    _reverify_on_card(at, "docCZ")
    assert _doc(db).strip() == _VYPIS_NEW.strip()
