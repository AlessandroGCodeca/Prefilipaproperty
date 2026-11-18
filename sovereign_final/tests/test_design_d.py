"""The design and UX items D1–D15 of the 18 Nov review (PDF section 13)."""

import os
import re

import tests.test_app_smoke as smoke
from tests.test_app_smoke import run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── D13 · keyboard and screen readers; the colour tokens ─────────────────────
def test_every_colour_is_a_token_and_focus_is_visible():
    from dashboard.style import CSS
    assert "--good: #3ddc97" in CSS and "var(--good)" in CSS
    rules = CSS[CSS.index(":root {", CSS.index("--bad-line")):]          # after the token block
    assert not re.search(r"#3ddc97|#ff8a8a|#f5b84a", rules.split("--mono")[1])
    assert ":focus-visible" in CSS and "outline:2px solid var(--info)" in CSS


def test_a_skip_link_leads_to_the_tabs(populated_db):
    at = run_app()
    md = " ".join(m.value for m in at.markdown)
    assert 'class="skip" href="#tabs"' in md and 'id="tabs"' in md


# ── D2 · fewer chips: only what needs action ─────────────────────────────────
def _card_md(at, lid="g1"):
    return " ".join(m.value for m in at.markdown if "facts" in m.value or "badge" in m.value)


def test_a_card_shows_chips_only_for_what_needs_action(populated_db):
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    md = _card_md(at)
    assert '<div class="facts">' in md
    facts = md.split('<div class="facts">')[1].split("</div>")[0]
    assert "Green" in facts and "grade" in facts                 # informational: one line
    chips = md.split('<div class="facts">')[0]
    assert "GRADE" not in chips and ">PERSONAL<" not in chips    # no longer chips
    assert chips.count('class="badge') <= 6


# ── D10 · star a flat ────────────────────────────────────────────────────────
def test_a_flat_can_be_starred_and_unstarred(populated_db):
    at = run_app(open_cards=("g1",))
    at.button(key="star_g1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "g1" in populated_db.get_starred()
    assert at.button(key="star_g1").label == "★ Starred"
    at.button(key="star_g1").click().run()
    assert "g1" not in populated_db.get_starred()


# ── D5 · filters and order beside the list ───────────────────────────────────
def _snag_titles(at):
    return [e.label for e in at.expander if e.label.startswith(("🟢", "🟡"))]


def test_quick_filters_narrow_the_list_and_the_order_changes(populated_db):
    at = run_app()
    every = _snag_titles(at)
    assert every
    at.pills(key="quick_filters").set_value(["Cash-flow positive"]).run()
    assert not at.exception, [e.value for e in at.exception]
    positive = _snag_titles(at)
    assert len(positive) <= len(every)
    assert all("+€" in t or "+" in t.split("·")[-1] for t in positive)
    at.pills(key="quick_filters").set_value(["Starred"]).run()
    assert _snag_titles(at) == []
    populated_db.set_starred("g1", True)
    at.run()
    assert len(_snag_titles(at)) == 1
    at.pills(key="quick_filters").set_value([]).run()
    at.selectbox(key="list_order").set_value("Lowest price").run()
    assert not at.exception, [e.value for e in at.exception]


# ── D1 · TODAY first; D11 · the setup checklist ──────────────────────────────
def test_today_is_the_first_tab_and_lists_what_changed(populated_db):
    populated_db.set_starred("g1", True)
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert at.tabs[0].label == "🏠 TODAY"
    md = " ".join(m.value for m in at.markdown)
    assert "Since your last visit" in md
    assert 'class="td-h">Starred' in md
    # Each green or yellow line opens its card in DEALS.
    btn = next(b for b in at.button if b.key and b.key.startswith("td_Starre_g1"))
    btn.click().run()
    assert at.session_state["card_g1"] is True and at.session_state["_pin"] == "g1"
    assert at.session_state["_tabgen"] == 1
    assert at.query_params["group"] == ["🎯 DEALS"] or at.query_params["group"] == "🎯 DEALS"


def test_the_last_visit_is_remembered_across_sessions(populated_db):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
    conn = populated_db.get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('last_visit', ?)",
                 ((now - timedelta(days=2)).isoformat(),))
    conn.commit()
    conn.close()
    at = run_app()
    assert at.session_state["_since"] == now - timedelta(days=2)


def test_sections_pick_new_deals_cuts_on_followed_flats_and_stale_lv():
    from datetime import datetime, timezone
    from dashboard.tabs.today import sections

    class V:
        surplus = staticmethod(lambda l: l.get("s"))
        cf_negative = staticmethod(lambda l: (l.get("s") or 0) < 0)

    since = datetime(2026, 11, 10, tzinfo=timezone.utc)
    ls = [
        {"id": "new", "classification": "GREEN", "scraped_at": "2026-11-15T08:00:00+00:00"},
        {"id": "old", "classification": "GREEN", "scraped_at": "2026-10-01T08:00:00+00:00"},
        {"id": "cut", "classification": "WHITE", "scraped_at": "2026-10-01",
         "_stage": {"stage": "OFFER"}, "lv_status": "PASS", "lv_checked_at": None,
         "_ph": {"change_pct": -0.05, "history": [("2026-11-01", 1), ("2026-11-12", 0.95)]}},
    ]
    got = {t: [l["id"] for l in s] for t, _h, s in sections(ls, V(), since, {"old"})}
    assert got["Starred"] == ["old"]
    assert got["New deals"] == ["new"]
    assert got["Price cuts on flats you follow"] == ["cut"]
    assert got["Title deed to check"] == ["cut"]          # no check date on record


def test_the_setup_checklist_lists_what_is_missing(populated_db, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY", "MAPY_API_KEY",
              "HEALTHCHECK_URL", "BACKUP_COPY_DIR", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    at = run_app()
    setup = next(e for e in at.expander if e.label.startswith("Setup ·"))
    assert "of 9 done" in setup.label
    from dashboard.tabs.today import setup_items
    names = {w for w, ok, _ in setup_items() if not ok}
    assert {"Telegram alerts", "Daily-run watcher", "Mapy.com addresses"} <= names


# ── D4 · a card redraws on its own ───────────────────────────────────────────
def test_the_card_is_a_fragment():
    import inspect
    from dashboard import cards
    src = inspect.getsource(cards)
    assert "@st.fragment\ndef render_card(l, v):" in src


# ── D3 · a row in the triage table opens its flat ────────────────────────────
def test_picking_a_row_shows_the_flat_and_a_way_to_its_card(populated_db):
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    from dashboard.tabs.triage import triage_csv
    at = run_app()
    df = next(d for d in at.dataframe if "Grade" in d.value.columns)
    assert "_id" in df.value.columns                       # kept for the pick, not shown
    assert "_id" not in triage_csv(pd.DataFrame({"Title": ["x"], "_id": ["g1"]})).decode("utf-8-sig")

    def panel(cls):
        import sys
        sys.path.insert(0, ".")
        from dashboard.tabs.triage import render_summary

        class V:
            sro = staticmethod(lambda l: True)
            surplus = staticmethod(lambda l: -123.0)
            cf_negative = staticmethod(lambda l: True)
        render_summary({"id": "g1", "title": "<b>Byt</b> Martin", "price_eur": 83600,
                        "classification": cls, "market_discount": 0.4,
                        "max_price_yellow": 125000, "_market": "sk"}, V())

    for cls, has_button in (("GREEN", True), ("WHITE", False)):
        t = AppTest.from_function(panel, args=(cls,), default_timeout=60)
        t.run()
        assert not t.exception, [e.value for e in t.exception]
        md = " ".join(m.value for m in t.markdown)
        assert 'class="pick-k"' in md and "&lt;b&gt;Byt" in md
        assert "−€123" in md or "-€123" in md
        assert any(b.key == "triage_open" for b in t.button) is has_button
