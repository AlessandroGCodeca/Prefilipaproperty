"""The dashboard's new screens from the audit of 12 November 2026, run as the
page runs: the ALERTS tab, a deal's due diligence in DEAL PIPELINE, a card's
"Read part C", "Why grade?" and offer sheet, the offer comparer in WHAT-IF,
YOUR SITUATION and the structure shown."""

import pytest

import tests.test_app_smoke as smoke
from tests.test_app_smoke import XSS_NOTE, XSS_TITLE, markdown_of, run_app

# The smoke tests' database fixtures, shared under the same names.
db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_the_alerts_tab_lists_saved_rules_escaped(populated_db):
    populated_db.save_alert_rules([{"name": XSS_NOTE, "classes": "GREEN", "district": "Trnava"}])
    at = run_app()
    _ok(at)
    md = markdown_of(at)
    assert "<b onmouseover" not in md and "&lt;b onmouseover" in md
    assert "district contains “Trnava”" in md


def test_the_alerts_preview_shows_what_fits(populated_db):
    at = run_app()
    at.toggle(key="alert_rules_preview").set_value(True).run()
    _ok(at)
    assert "listing(s) fit" in markdown_of(at)


def test_a_deal_has_its_checklist_documents_and_letter(populated_db):
    from database import deal_docs
    populated_db.set_deal_stage("g1", "OFFER", "viewing Sat")
    deal_docs.set_checklist("g1", {"bezdlznost": (True, XSS_NOTE)})
    deal_docs.add_deal_file("g1", "LV", "<b>lv</b>.pdf", b"%PDF-1.4", "application/pdf")
    at = run_app()
    opts = at.selectbox(key="pipe_pick").options
    at.selectbox(key="pipe_pick").set_value(next(o for o in opts if "[g1" in o)).run()
    _ok(at)
    md = markdown_of(at)
    assert "DUE DILIGENCE — 1 of 12 checked" in md
    assert "&lt;b&gt;lv&lt;/b&gt;.pdf" in md and "<b>lv</b>" not in md
    assert at.text_input(key="ddn_g1_bezdlznost").value == XSS_NOTE   # a widget, not HTML
    at.toggle(key="ddl_g1").set_value(True).run()
    _ok(at)
    letter = next(t.value for t in at.text_area if t.label == "Letter")
    assert "potvrdenie o bezdlžnosti" in letter


def test_a_card_has_why_grade_read_part_c_and_the_offer_sheet(populated_db):
    from kataster_scraper import _cache_put, _new_result
    populated_db.set_flat_lv("g1", "4521", "Petržalka")
    populated_db.set_lv_status("g1", "PASS", "", "LV 4521: Clean title")
    deed = ("ČASŤ B: VLASTNÍCI 1 Novák ČASŤ C: ŤARCHY 1 Záložné právo v prospech Tatra banka, "
            f"a.s. 2 Z 5/2020 - Právo stavby v prospech {XSS_TITLE} Poznámka: Bez zápisu.")
    r = _new_result({"cadastral_area": "Petržalka", "lv_no": "4521", "register": "LV"})
    r.update(status="OK", lv_text=deed)
    _cache_put("lv|petrzalka|4521", r)
    at = run_app(open_cards=["g1"])
    _ok(at)
    md = markdown_of(at)
    assert "→ grade" in md                          # the popover's breakdown
    assert "checked " in md                          # the LV check's date
    at.toggle(key="lvc_g1").set_value(True).run()
    _ok(at)
    md = markdown_of(at)
    assert '<span class="lvb">Záložné právo' in md and '<span class="lvu">Právo stavby' in md
    assert "<img src=x" not in md
    at.button(key="offer_g1").click().run()
    _ok(at)
    assert at.session_state["offer_ready"]["offer_g1"][1][:4] == b"%PDF"


def test_the_what_if_compares_offers(populated_db):
    at = run_app()
    at.toggle(key="wi_offers_on").set_value(True).run()
    _ok(at)
    assert any("Best over the hold" in c.value for c in at.caption)


def test_your_situation_saves_and_rescores(populated_db, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    from engine import financial
    for mod in (config, financial):
        monkeypatch.setattr(mod, "LOAN_TERM_YEARS", mod.LOAN_TERM_YEARS)
    at = run_app()
    box = next(n for n in at.sidebar.number_input if n.label == "Loan term (years)")
    box.set_value(30)
    next(b for b in at.sidebar.button if b.label == "💾 SAVE AND RE-SCORE").click()
    at.run()
    _ok(at)
    assert config.LOAN_TERM_YEARS == 30
    assert (tmp_path / "settings.json").exists()


@pytest.mark.parametrize("shown", ["Personal", "s.r.o.", "Recommended"])
def test_each_structure_can_be_shown(populated_db, shown):
    at = run_app(open_cards=["g1"])
    at.sidebar.radio(key="structure").set_value(shown).run()
    _ok(at)
    md = markdown_of(at)
    want = {"Personal": "COST BREAKDOWN</div>", "s.r.o.": "COST BREAKDOWN — s.r.o.",
            "Recommended": "COST BREAKDOWN"}[shown]
    assert want.split("</div>")[0] in md
