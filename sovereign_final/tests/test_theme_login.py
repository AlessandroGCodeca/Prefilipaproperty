"""
A theme switch reloads the page, and a reload is a new Streamlit session: it
used to ask for the password again. Now the switch hands the reload a resume
ticket (dashboard/login.py): random, good once, for 60 seconds.
"""

import json
import re

import tests.test_app_smoke as smoke
from tests.test_security_eu import _log_in

db = smoke.db


def _ticket_in_page(at) -> str:
    """The ticket THEME_JS carries on this run ("" when none)."""
    for el in at.get("html"):
        body = getattr(el, "body", None) or getattr(el, "proto", None) and el.proto.body or ""
        m = re.search(r"const ticket = (\"[^\"]*\");", body)
        if m:
            return json.loads(m.group(1))
    raise AssertionError("THEME_JS not on the page")


def test_a_ticket_works_once():
    from dashboard import login
    t = login.issue_resume_ticket()
    assert login.redeem_resume_ticket(t) is True
    assert login.redeem_resume_ticket(t) is False          # used up


def test_a_ticket_expires(monkeypatch):
    from dashboard import login
    now = login._now()
    t = login.issue_resume_ticket()
    monkeypatch.setattr(login, "_now", lambda: now + login.RESUME_TTL_S + 1)
    assert login.redeem_resume_ticket(t) is False


def test_made_up_or_missing_tickets_do_nothing():
    from dashboard import login
    login.issue_resume_ticket()
    assert not login.redeem_resume_ticket(None)
    assert not login.redeem_resume_ticket("")
    assert not login.redeem_resume_ticket("x" * 43)
    assert not login.redeem_resume_ticket("y" * 5000)


def test_log_out_cancels_tickets_not_yet_used(db, monkeypatch):
    from dashboard import login
    at = _log_in(monkeypatch)
    t = login.issue_resume_ticket()
    next(b for b in at.sidebar.button if b.label == "🔒 LOG OUT").click().run()
    assert not login.redeem_resume_ticket(t)


def test_switching_the_theme_keeps_the_login(db, monkeypatch):
    from dashboard import login
    at = _log_in(monkeypatch)
    assert _ticket_in_page(at) == ""                       # no switch, no ticket
    at.sidebar.radio(key="theme").set_value("light").run()
    ticket = _ticket_in_page(at)
    assert ticket                                          # the reload takes one
    # The reload: a new session that sends the ticket back in its cookie.
    monkeypatch.setattr(login, "_resume_cookie", lambda: ticket)
    again = smoke.run_app()
    assert not again.exception, [e.value for e in again.exception]
    assert again.tabs                                      # in, no password asked
    # Sent again (a copied cookie, a second tab), it no longer works.
    third = smoke.run_app()
    assert not third.tabs


def test_no_ticket_without_a_login(db, monkeypatch):
    """With a password set, a visitor who isn't logged in gets no ticket."""
    import config
    from dashboard import prefs, style  # noqa: F401
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "correct-horse-battery")
    at = smoke.run_app()
    at.session_state["_theme_reload"] = True
    at.run()
    assert _ticket_in_page(at) == ""
    assert not at.tabs


def test_the_privacy_notice_names_the_resume_cookie_and_the_theme_storage():
    from dashboard import legal
    text = legal.privacy_md()
    assert "sv_resume" in text and "_streamlit_xsrf" in text and "local storage" in text
    assert "contact" in legal.imprint_html() and "Digital Services Act" in legal.imprint_html()
