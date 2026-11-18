"""The 18 Nov security and EU review: keys never reach logs, error messages or
the browser; scraped links can't run script; the login times out and can be
left; the robots.txt of every portal is respected; the browser sends no usage
statistics; files are private; the operator, privacy notice and terms are on
every page; an owner's data can be erased on request."""

import logging
import os
import stat
import sys

import pytest

import tests.test_app_smoke as smoke
from tests.conftest import make_listing
from tests.test_app_smoke import run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "AIzaTESTKEY0123456789abcdefghijklmnop"


# ── Keys out of logs and messages ────────────────────────────────────────────
def test_secret_values_are_masked(monkeypatch):
    from modules import redact
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")            # not a secret's name
    monkeypatch.setenv("SHORT_TOKEN", "abc")                   # too short to mask
    text = f"400 for url: https://maps.googleapis.com/x?address=Main+1&key={KEY} chat 12345 abc"
    out = redact.redact(text)
    assert KEY not in out and "key=***" in out and "12345" in out and "abc" in out


def test_the_log_filter_masks_messages_and_tracebacks(monkeypatch):
    from modules import redact
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-0123456789abcdef")
    lines = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    lg = logging.getLogger("redact-test")
    lg.propagate = False
    h = Keep()
    lg.addHandler(h)
    try:
        redact.install(lg)
        redact.install(lg)                                   # a second call adds nothing
        assert sum(isinstance(f, redact.RedactingFilter) for f in h.filters) == 1
        lg.warning("calling with %s", "sk-test-0123456789abcdef")
        try:
            raise ValueError("bad key sk-test-0123456789abcdef")
        except ValueError:
            lg.exception("failed")
    finally:
        lg.removeHandler(h)
    assert lines and all("sk-test-0123456789abcdef" not in s for s in lines)
    assert "calling with ***" in lines[0] and "bad key ***" in lines[1]


def test_the_scheduler_log_is_filtered(tmp_path, monkeypatch):
    import scheduler
    from modules import redact
    monkeypatch.setattr(scheduler, "LOGS_DIR", str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    for hd in before:
        root.removeHandler(hd)
    try:
        scheduler._setup_logging()
        assert root.handlers and all(
            any(isinstance(f, redact.RedactingFilter) for f in hd.filters) for hd in root.handlers)
    finally:
        for hd in list(root.handlers):
            root.removeHandler(hd)
            hd.close()
        for hd in before:
            root.addHandler(hd)


# ── The satellite key stays on the server ────────────────────────────────────
def test_the_satellite_picture_is_fetched_on_the_server(monkeypatch):
    import requests
    from dashboard.tabs import satellite
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", KEY)
    satellite.satellite_image.clear()
    asked = []

    class R:
        status_code, headers, content = 200, {"content-type": "image/png"}, b"\x89PNG"

    def get(url, params=None, timeout=None):
        asked.append((url, params))
        return R()

    monkeypatch.setattr(requests, "get", get)
    assert satellite.satellite_image(48.15, 17.11) == b"\x89PNG"
    assert asked[0][0] == satellite.STATIC_MAP_URL and asked[0][1]["key"] == KEY
    satellite.satellite_image.clear()
    R.headers = {"content-type": "text/html"}                 # an error page
    assert satellite.satellite_image(48.15, 17.11) is None
    satellite.satellite_image.clear()


def _png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return buf.getvalue()


def test_no_page_element_carries_the_key(populated_db, monkeypatch):
    import requests
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", KEY)
    from dashboard.tabs import satellite
    satellite.satellite_image.clear()
    asked = []

    class R:
        status_code, headers, content = 200, {"content-type": "image/png"}, _png()

    def get(url, params=None, **k):
        asked.append(url)
        return R()

    monkeypatch.setattr(requests, "get", get)
    conn = populated_db.get_conn()
    conn.execute("UPDATE listings SET lat=48.15, lng=17.11")    # whichever is picked has a pin
    conn.commit()
    conn.close()
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert satellite.STATIC_MAP_URL in asked                 # fetched by the server
    page = " ".join(str(e.proto) for e in at.get("imgs")) + " ".join(
        m.value for m in at.markdown)
    assert KEY not in page and "maps.googleapis.com/maps/api/staticmap" not in page
    satellite.satellite_image.clear()


# ── Links from scraped data ──────────────────────────────────────────────────
@pytest.mark.parametrize("url, out", [
    ("https://www.bazos.sk/inzerat/1", "https://www.bazos.sk/inzerat/1"),
    ("http://x.sk/a?b=1&c=2", "http://x.sk/a?b=1&amp;c=2"),
    ("javascript:alert(1)", "#"),
    (" JaVaScRiPt:alert(1)", "#"),
    ("data:text/html,<script>", "#"),
    (None, "#"),
    ("", "#"),
])
def test_only_web_links_reach_an_href(url, out):
    from dashboard.fmt import safe_href, safe_url
    assert safe_href(url) == out
    assert safe_url(url) == (out.replace("&amp;", "&") if out != "#" else "#")


def test_a_javascript_listing_link_is_not_rendered(populated_db):
    conn = populated_db.get_conn()
    conn.execute("UPDATE listings SET url='javascript:alert(document.cookie)' WHERE id='g1'")
    conn.commit()
    conn.close()
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    md = " ".join(m.value for m in at.markdown)
    buttons = " ".join(str(b.proto) for b in at.get("link_button"))
    assert "javascript:" not in md and "javascript:" not in buttons
    assert "VIEW LISTING" in buttons                            # the card was drawn


# ── Fetching only what may be fetched ────────────────────────────────────────
@pytest.mark.parametrize("url, ok", [
    ("https://www.notar.sk/listina/?actId=1&documentId=d1", True),
    ("https://notar.sk/listina/1", True),
    ("http://www.notar.sk/listina/1", False),
    ("https://notar.sk.evil.example/x", False),
    ("https://169.254.169.254/latest/meta-data", False),
    ("file:///etc/passwd", False),
])
def test_auction_documents_come_from_the_register_only(url, ok):
    from modules.auctions_sk import register_document
    assert register_document(url) is ok


def test_bazos_never_asks_for_a_search_url_robots_txt_forbids(monkeypatch):
    from scraper import bazos

    class R:
        status_code, text = 404, ""

    asked = []
    monkeypatch.setattr(bazos, "get", lambda url, **k: asked.append(url) or R())
    bazos.scrape_page(20)
    assert asked and not any(q in u for u in asked for q in ("hledat=", "cenaod=", "rubriky="))


# ── Streamlit's settings ─────────────────────────────────────────────────────
def test_streamlit_sends_no_usage_statistics_and_shows_no_raw_errors():
    import tomllib
    with open(os.path.join(ROOT, ".streamlit", "config.toml"), "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["client"]["showErrorDetails"] in ("type", "none")
    assert cfg["client"]["showErrorLinks"] is False
    assert cfg["server"]["maxUploadSize"] <= 25
    assert cfg["server"]["enableXsrfProtection"] and cfg["server"]["enableCORS"]


def test_ci_token_is_read_only():
    path = os.path.join(os.path.dirname(ROOT), ".github", "workflows", "test.yml")
    text = open(path, encoding="utf-8").read()
    assert "permissions:\n  contents: read" in text


# ── The login ────────────────────────────────────────────────────────────────
def _log_in(monkeypatch, password="correct-horse-battery"):
    import config
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", password)
    at = run_app()
    at.text_input(key="login_pw").input(password)
    at.button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.tabs
    return at


def test_an_idle_session_asks_for_the_password_again(db, monkeypatch):
    from dashboard import login
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "30")
    at = _log_in(monkeypatch)
    at.session_state["_last_active"] = login._now() - 31 * 60
    at.run()
    assert not at.tabs
    assert any("without activity" in i.value for i in at.info)


def test_the_idle_limit_can_be_switched_off(db, monkeypatch):
    from dashboard import login
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")
    at = _log_in(monkeypatch)
    at.session_state["_last_active"] = login._now() - 99 * 3600
    at.run()
    assert at.tabs


def test_log_out(db, monkeypatch):
    at = _log_in(monkeypatch)
    next(b for b in at.sidebar.button if b.label == "🔒 LOG OUT").click().run()
    assert not at.tabs


def test_a_short_password_is_warned_about(db, monkeypatch):
    at = _log_in(monkeypatch, password="s3cret")
    assert any("shorter than 12" in w.value for w in at.warning)
    at = _log_in(monkeypatch)
    assert not any("shorter than 12" in w.value for w in at.warning)


def test_a_wrong_password_is_logged_but_not_what_was_typed(db, monkeypatch, caplog):
    import config
    from dashboard import login
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "correct-horse-battery")
    monkeypatch.setattr(login, "WRONG_PASSWORD_DELAY_S", 0)
    at = run_app()
    with caplog.at_level(logging.WARNING, logger="sovereign"):
        at.text_input(key="login_pw").input("my-other-password")
        at.button[0].click().run()
    assert "wrong password" in caplog.text and "my-other-password" not in caplog.text


# ── Who runs it, and what happens to data ────────────────────────────────────
def test_the_legal_footer_is_on_the_login_page_and_every_page(db, monkeypatch):
    import config
    monkeypatch.setenv("OPERATOR_NAME", "Example s.r.o. <b>")
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "correct-horse-battery")
    at = run_app()
    labels = [e.label for e in at.expander]
    assert {"Imprint", "Privacy notice", "Terms of use"} <= set(labels)
    md = " ".join(m.value for m in at.markdown)
    assert "Not financial, investment, tax or legal advice" in md
    assert "Example s.r.o. &lt;b&gt;" in md                    # escaped
    assert "not set (OPERATOR_ADDRESS)" in md
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "")
    at = run_app()
    assert {"Imprint", "Privacy notice", "Terms of use"} <= {e.label for e in at.expander}


def test_missing_operator_details_are_listed(monkeypatch):
    from dashboard import legal
    for k, _ in legal.FIELDS:
        monkeypatch.delenv(k, raising=False)
    assert "OPERATOR_NAME" in legal.missing() and "OPERATOR_VAT_ID" not in legal.missing()
    monkeypatch.setenv("OPERATOR_NAME", "A")
    monkeypatch.setenv("OPERATOR_ADDRESS", "B")
    monkeypatch.setenv("OPERATOR_ID", "1")
    monkeypatch.setenv("OPERATOR_REGISTER", "OR")
    monkeypatch.setenv("OPERATOR_EMAIL", "a@b.sk")
    assert legal.missing() == []


def test_the_privacy_notice_names_each_processor_and_the_regulator():
    from dashboard import legal
    text = legal.privacy_md()
    for name in ("Anthropic", "Google Maps Platform", "Mapy.com", "Telegram", "Healthchecks.io",
                 "Úrad na ochranu osobných údajov", "_streamlit_xsrf", "LV_TEXT_RETENTION_DAYS"):
        assert name in text


# ── Erasing an owner's data ──────────────────────────────────────────────────
def test_an_owners_data_can_be_erased(full_db):
    import database
    database.upsert_listing(make_listing("e1"))
    database.upsert_listing(make_listing("e2"))
    database.set_lv_document("e1", "LIST VLASTNÍCTVA 1234\nČasť B: Ján Predajca")
    database.set_lv_document("e2", "LIST VLASTNÍCTVA 99\nČasť B: Iná Osoba")
    database.save_contract_draft("e1", "personal", 95_000, "Ján Kupec", "", "", "Predávajúci Ján")
    conn = database.get_conn()
    for lid in ("e1", "e2"):
        conn.execute("INSERT INTO lv_checks (id, listing_id, lv_status, raw_response, "
                     "llm_analysis, exekucia_detail) VALUES (?, ?, 'CLEAN', 'Ján Predajca', "
                     "'owner Ján', 'exekútor X proti Ján')", (f"c-{lid}", lid))
    conn.commit()
    conn.close()
    got = database.erase_owner_data("e1")
    assert got["lv_documents"] == 1 and got["lv_checks"] == 1 and got["contract_drafts"] == 1
    conn = database.get_conn()
    row = conn.execute("SELECT lv_status, raw_response, llm_analysis, exekucia_detail "
                       "FROM lv_checks WHERE listing_id='e1'").fetchone()
    assert tuple(row) == ("CLEAN", None, None, None)          # the verdict stays
    assert conn.execute("SELECT draft_text FROM contract_drafts WHERE listing_id='e1'"
                        ).fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM lv_documents WHERE listing_id='e2'"
                        ).fetchone()[0] == 1                   # other flats untouched
    assert conn.execute("SELECT raw_response FROM lv_checks WHERE listing_id='e2'"
                        ).fetchone()[0] == "Ján Predajca"
    conn.close()


def test_the_card_offers_the_erase(populated_db):
    populated_db.set_lv_document("g1", "LIST VLASTNÍCTVA 1\nČasť B: Ján Predajca")
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    at.toggle(key="erase_t_g1").set_value(True).run()
    assert at.button(key="erase_g1").disabled              # not before the tick
    at.checkbox(key="erase_ok_g1").check().run()
    at.button(key="erase_g1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Erased" in s.value for s in at.success)
    conn = populated_db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM lv_documents WHERE listing_id='g1'").fetchone()[0] == 0
    conn.close()


# ── Files only this computer's user can read ─────────────────────────────────
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_backups_are_private(full_db, tmp_path, monkeypatch):
    import database
    from modules import backup
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    database.upsert_listing(make_listing("b1"))
    path, written = backup.backup_database()
    assert written and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    export = backup.export_user_data()
    assert stat.S_IMODE(os.stat(export).st_mode) == 0o600
    dest = tmp_path / "icloud"
    backup.copy_off_site(str(dest))
    assert all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in dest.iterdir())


def test_the_start_file_locks_down_env_and_data():
    text = open(os.path.join(ROOT, "Start Sovereign.command"), encoding="utf-8").read()
    assert "chmod 600 .env" in text and "chmod 700 data backups logs" in text


def test_the_erase_of_an_unknown_flat_changes_nothing(full_db):
    import database
    database.upsert_listing(make_listing("k1"))
    database.set_lv_document("k1", "LIST VLASTNÍCTVA 7")
    assert sum(database.erase_owner_data("nope").values()) == 0
    conn = database.get_conn()
    try:                       # closed: Windows can't delete an open database file
        assert conn.execute("SELECT COUNT(*) FROM lv_documents").fetchone()[0] == 1
    finally:
        conn.close()


def test_ad_texts_of_long_gone_flats_are_cleared(full_db):
    from datetime import datetime, timedelta, timezone
    import database
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    for lid in ("gone", "live", "tracked"):
        database.upsert_listing(make_listing(lid, description="Volajte p. Novák 0905 123 456",
                                             last_seen_at=old, scraped_at=old))
    conn = database.get_conn()
    conn.execute("UPDATE listings SET is_active = 0, last_seen_at = ? "
                 "WHERE id IN ('gone', 'tracked')", (old,))
    conn.commit()
    conn.close()
    database.set_deal_stage("tracked", "OFFER", "")
    assert database.purge_old_lv_texts(180)["listings"] == 1
    conn = database.get_conn()
    got = dict(conn.execute("SELECT id, description FROM listings").fetchall())
    conn.close()
    assert got["gone"] is None and got["live"] and got["tracked"]
