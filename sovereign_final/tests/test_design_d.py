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
    assert at.tabs[0].label == ":material/home: TODAY"
    md = " ".join(m.value for m in at.markdown)
    assert "Since your last visit" in md
    assert 'class="td-h">Starred' in md
    # Each green or yellow line opens its card in DEALS.
    btn = next(b for b in at.button if b.key and b.key.startswith("td_Starre_g1"))
    btn.click().run()
    assert at.session_state["card_g1"] is True and at.session_state["_pin"] == "g1"
    assert at.session_state["_tabgen"] == 1
    assert at.query_params["group"] in (["deals"], "deals")


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
        assert any(b.key == "open_triage" for b in t.button) is has_button


# ── D8 · the cash flow and the price, drawn ──────────────────────────────────
def test_the_waterfall_steps_down_from_the_rent_to_the_surplus():
    from dashboard.charts import cost_rows, price_spec, waterfall_spec
    costs = cost_rows({"mortgage_monthly": 335, "hoa_monthly": 60, "property_tax_monthly": 7,
                       "management_monthly": 0, "income_tax_personal": None}, sro=False)
    assert costs == [("Mortgage", 335.0), ("HOA (incl. fond opráv)", 60.0), ("Property Tax", 7.0)]
    spec = waterfall_spec(421, costs, -123)
    rows = spec["data"]["values"]
    assert [r["step"] for r in rows] == ["Rent", "Mortgage", "HOA (incl. fond opráv)",
                                         "Property Tax", "Surplus"]
    assert rows[1]["start"] == 421 and rows[1]["end"] == 86
    assert rows[-1] == {"step": "Surplus", "start": 0.0, "end": -123.0, "kind": "net-",
                        "amount": -123.0}
    assert waterfall_spec(0, costs, 1) is None
    assert price_spec([("2026-11-03", 89900)]) is None
    pts = price_spec([("2026-11-03T08:00", 89900), ("2026-11-12", 83600)])["data"]["values"]
    assert pts == [{"date": "2026-11-03", "price": 89900.0}, {"date": "2026-11-12", "price": 83600.0}]


def test_an_open_card_draws_its_cash_flow(populated_db):
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    charts = at.get("arrow_vega_lite_chart") or at.get("vega_lite_chart")
    assert charts


# ── D9 · the map: a legend, its list, a picked pin ───────────────────────────
def test_the_map_has_a_legend_and_a_list(populated_db):
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    md = " ".join(m.value for m in at.markdown)
    assert 'class="lg"' in md and "faded: area, not street" in md
    assert any("Class" in d.value.columns and "Surplus" in d.value.columns for d in at.dataframe)


def test_the_legend_follows_the_colour_mode():
    from dashboard.tabs.map_view import legend_html
    assert "≥ +€100 a month" in legend_html(True) and "Green" not in legend_html(True)
    assert "Green: ≥20% under market" in legend_html(False)
    assert "rgb(61,220,151)" in legend_html(False)


# ── D6: one icon set ────────────────────────────────────────────────────────
def test_tabs_and_buttons_use_material_icons_not_emoji(populated_db):
    """The tab groups and the sidebar's buttons carry Material icons; the
    address keeps a plain word for the group."""
    at = run_app()
    assert not at.exception
    tabs = {t.label for t in at.tabs}
    for g in ("home: TODAY", "sell: DEALS", "analytics: ANALYSIS", "checklist: WORKFLOW"):
        assert f":material/{g}" in tabs, tabs
    labels = [b.label for b in at.button] + [t.label for t in at.tabs]
    assert not any(ch in l for l in labels for ch in "🔻👤📸🧪🩺▶🔗")


# ── D7: the cards' language ─────────────────────────────────────────────────
def _lang_app():
    import streamlit as st
    from dashboard import prefs
    from dashboard.fmt import _labels, czech_words
    if st.button("English", key="en"):
        st.session_state["card_lang"] = "en"
        prefs.save("card_lang")
    cz = {"_market": "cz"}
    st.markdown(f"{czech_words(cz)}|{_labels(cz)('Price')}|{czech_words({'_market': 'sk'})}")


def test_czech_cards_speak_czech_until_you_choose_english(populated_db):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_lang_app).run()
    assert at.markdown[0].value == "True|Cena|False"
    at.button(key="en").click().run()
    assert at.markdown[0].value == "False|Price|False"
    # Kept in the database: a new session (another device) starts in English.
    again = AppTest.from_function(_lang_app).run()
    assert again.markdown[0].value == "False|Price|False"


def test_the_language_setting_is_in_the_sidebar(populated_db):
    at = run_app()
    assert not at.exception
    radio = at.sidebar.radio(key="card_lang")
    assert radio.value == "auto"
    assert set(radio.options) == {"By the flat's country", "English on every card"}


# ── D12: what a failure means, and what to do ───────────────────────────────
def test_usual_failures_get_a_next_step():
    from dashboard.messages import next_step
    assert "turned the scraper away" in next_step("HTTP 403")
    assert "fewer visits" in next_step(429)
    assert "site was down" in next_step("503 Service Unavailable")
    assert "online" in next_step(TimeoutError("read timed out"))
    assert ".env" in next_step("REQUEST_DENIED: The provided API key is invalid")
    assert next_step(None) == "" and next_step("something odd") == ""


def test_a_failed_portal_chip_says_what_to_do():
    from dashboard.overview import portal_strip
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    health = {("sk", "nehnutelnosti"): {"daily": [3, 4], "last_good_at": now,
                                         "last": {"run_at": now, "listings": 0,
                                                  "error": "HTTP 403"}}}
    html = portal_strip(health, None)
    assert "HTTP 403" in html and "turned the scraper away" in html


def test_the_backtest_table_takes_missing_numbers(populated_db, monkeypatch):
    """A district with no flats that left had "—" among the numbers: Arrow
    refused the column (ArrowInvalid, in the log) and Streamlit showed it as
    text, sorting 900 after 2100. Now the cell is empty and the column numeric."""
    from engine import backtest
    col = "Last asking of flats that left €/m²"
    monkeypatch.setattr(backtest, "asking_vs", lambda market: [
        {"District key": "a", "Listed": 3, col: None},
        {"District key": "b", "Listed": 5, col: 2100}])
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    shown = next(df.value for df in at.dataframe if col in df.value.columns)
    assert shown[col].dtype.kind == "f"


# ── D14: a light theme ──────────────────────────────────────────────────────
def test_both_themes_are_configured_and_light_tokens_exist():
    import tomllib
    with open(os.path.join(os.path.dirname(__file__), "..", ".streamlit", "config.toml"), "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["theme"]["dark"]["base"] == "dark" and cfg["theme"]["light"]["base"] == "light"
    from dashboard.style import CSS
    light = CSS[CSS.index('html[data-theme="light"]'):]
    for token in ("--bg", "--text", "--good", "--bad", "--caution", "--info"):
        assert token + ":" in light[:light.index("}")]


def test_the_theme_slot_is_the_one_streamlit_reads():
    """THEME_JS writes Streamlit's own localStorage slot. Its name and values
    are Streamlit internals: if an upgrade changes them, this fails rather
    than the switch silently doing nothing."""
    import glob
    import streamlit
    from dashboard.style import ST_THEME_NAMES, THEME_JS
    js = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(
        os.path.dirname(streamlit.__file__), "static", "static", "js", "*.js")))
    assert re.search(r"\w+=2,\w+=`stActiveTheme-\$\{window\.location\.pathname\}`", js)
    assert "e===`System`||e===`Light`||e===`Dark`" in js
    assert set(ST_THEME_NAMES.values()) == {"System", "Light", "Dark"}
    assert '"stActiveTheme-" + window.location.pathname + "-v2"' in THEME_JS


def test_the_theme_setting_is_kept_and_sent_to_the_page(populated_db):
    at = run_app()
    assert not at.exception
    assert at.sidebar.radio(key="theme").value == "dark"
    at.sidebar.radio(key="theme").set_value("light").run()
    from dashboard import prefs
    assert prefs._read("theme") == "light"
    again = run_app()
    assert again.sidebar.radio(key="theme").value == "light"


def test_charts_take_the_light_palette():
    from dashboard.charts import price_spec, waterfall_spec
    wf = waterfall_spec(800, [("Mortgage", 500)], 300, theme="light")
    assert "#0a6b43" in wf["encoding"]["color"]["scale"]["range"]
    assert price_spec([("2026-01-01", 1), ("2026-02-01", 2)], theme="light")["mark"]["color"] == "#1a56c4"


# ── D15: the fonts come with the app ────────────────────────────────────────
def test_every_font_the_css_asks_for_is_in_static_with_its_licence():
    from dashboard.style import CSS
    root = os.path.join(os.path.dirname(__file__), "..")
    urls = re.findall(r"url\('app/static/(fonts/[^']+)'\)", CSS)
    assert len(urls) == 16
    for u in urls:
        with open(os.path.join(root, "static", u), "rb") as f:
            assert f.read(4) == b"wOF2", u
    for lic in ("OFL-IBM-Plex-Sans.txt", "OFL-IBM-Plex-Mono.txt"):
        text = open(os.path.join(root, "static", "fonts", lic), encoding="utf-8").read()
        assert "SIL Open Font License" in text and "IBM Corp" in text
    # Nothing but the fonts, their licences and the note is served publicly.
    served = os.listdir(os.path.join(root, "static", "fonts"))
    assert all(n.endswith((".woff2", ".txt", ".md")) for n in served)
    assert os.listdir(os.path.join(root, "static")) == ["fonts"]


def test_static_serving_is_on_and_no_font_server_is_asked():
    import tomllib
    from dashboard.style import CSS
    with open(os.path.join(os.path.dirname(__file__), "..", ".streamlit", "config.toml"), "rb") as f:
        assert tomllib.load(f)["server"]["enableStaticServing"] is True
    assert "googleapis" not in CSS and "@import" not in CSS


def test_no_strftime_code_that_only_works_on_linux_and_mac():
    """%-d, %-m … (no zero padding) are glibc and BSD extensions: Windows'
    strftime raises ValueError on them, which crashed the whole page there."""
    root = os.path.join(os.path.dirname(__file__), "..")
    bad = []
    for d in ("dashboard", "modules", "engine", "scraper", "database"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, d)):
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(dirpath, f), encoding="utf-8").read()
                    bad += [f"{f}: {m}" for m in re.findall(r"%[-#][a-zA-Z]", text)]
    for f in ("app.py", "scheduler.py"):
        bad += [f"{f}: {m}" for m in re.findall(r"%[-#][a-zA-Z]",
                                               open(os.path.join(root, f), encoding="utf-8").read())]
    assert not bad, bad


def test_today_says_when_the_last_visit_was(populated_db):
    at = run_app()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    when = re.search(r'Since your last visit</div><div class="muted"[^>]*>([^<]+)<', md)
    assert when and re.fullmatch(r"\d{1,2} [A-Z][a-z]{2}, \d{2}:\d{2}", when.group(1)), when
