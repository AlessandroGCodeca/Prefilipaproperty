"""
dashboard/login.py — the password gate (DASHBOARD_PASSWORD).
"""

import logging
import os
import threading
import time

import streamlit as st

log = logging.getLogger("sovereign")

# Wrong passwords allowed within LOCKOUT_S before the gate locks for
# LOCKOUT_S. Counted for the whole dashboard process, not per browser tab: a
# guesser simply opens new sessions. While locked, the right password waits
# too — fifteen minutes is the price of not being guessable.
MAX_TRIES = 5
LOCKOUT_S = 15 * 60
# Every wrong password also waits this long before the page answers.
WRONG_PASSWORD_DELAY_S = 1.0

# A session that has been idle this long asks for the password again
# (SESSION_IDLE_MINUTES; 0 = never): a phone or laptop left unlocked with the
# dashboard open doesn't stay logged in for good.
DEFAULT_IDLE_MIN = 60
# Shorter passwords get a warning after login: the gate slows guessing to five
# tries in 15 minutes, which a short or common password doesn't survive long.
MIN_PASSWORD_LEN = 12

_lock = threading.Lock()
_fails: list[float] = []          # times of the recent wrong passwords
_locked_until = 0.0

# A theme switch reloads the page (Streamlit reads its theme only when a page
# loads), and a reload is a new session: without this it asked for the
# password again. Just before that one reload the page gets a resume ticket:
# random, good once, for RESUME_TTL_S, in a cookie of its own that the
# reloaded page sends back. Kept here hashed, in memory only; a restart or
# a log-out drops them all.
RESUME_COOKIE = "sv_resume"
RESUME_TTL_S = 60
_tickets: dict[str, float] = {}   # sha256 of a ticket → when it expires


def _now() -> float:
    return time.time()


def _minutes(seconds: float) -> int:
    """Whole minutes, rounded up: 20 s left reads "1 min", not "0 min"."""
    return max(1, -(-int(seconds) // 60))


def reset_attempts() -> None:
    """Forget the wrong passwords and lift a lockout (tests; a restart does
    the same)."""
    global _locked_until
    with _lock:
        _fails.clear()
        _locked_until = 0.0


def _locked_for(now: float) -> float:
    """Seconds the gate stays locked; 0 when it is open."""
    with _lock:
        return max(_locked_until - now, 0.0)


def _record_failure(now: float) -> None:
    global _locked_until
    with _lock:
        _fails[:] = [t for t in _fails if now - t < LOCKOUT_S] + [now]
        if len(_fails) >= MAX_TRIES:
            _locked_until = now + LOCKOUT_S
            _fails.clear()


def idle_limit_s() -> float:
    """Seconds of inactivity before the password is asked again; 0 = never."""
    try:
        minutes = float(os.getenv("SESSION_IDLE_MINUTES", DEFAULT_IDLE_MIN))
    except ValueError:
        minutes = DEFAULT_IDLE_MIN
    return max(minutes, 0.0) * 60


def weak_password(password: str) -> bool:
    return 0 < len(password or "") < MIN_PASSWORD_LEN


def _digest(ticket: str) -> str:
    import hashlib
    return hashlib.sha256(ticket.encode()).hexdigest()


def issue_resume_ticket() -> str:
    """A ticket that logs the next page load back in, once, within
    RESUME_TTL_S. Only for a session that is logged in."""
    import secrets
    ticket = secrets.token_urlsafe(32)
    now = _now()
    with _lock:
        for k in [k for k, t in _tickets.items() if t <= now]:
            del _tickets[k]
        _tickets[_digest(ticket)] = now + RESUME_TTL_S
    return ticket


def redeem_resume_ticket(ticket: str | None) -> bool:
    """True, once, for a ticket issued here that hasn't expired."""
    import re
    # The cookie comes from the browser: only something shaped like a ticket
    # (token_urlsafe(32): 43 characters of A–Z a–z 0–9 - _) is looked up.
    if not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
        return False
    with _lock:
        expires = _tickets.pop(_digest(ticket), 0.0)
    return expires > _now()


def _resume_cookie() -> str | None:
    """The resume ticket the page sent with its first request, if any."""
    try:
        return st.context.cookies.get(RESUME_COOKIE)
    except Exception:
        return None


def log_out() -> None:
    """End this browser session's login (and any resume ticket not yet used)."""
    for k in ("_authed", "_last_active"):
        st.session_state.pop(k, None)
    with _lock:
        _tickets.clear()


def logout_button() -> None:
    """🔒 LOG OUT in the sidebar, shown only when a password is set."""
    from config import DASHBOARD_PASSWORD
    if DASHBOARD_PASSWORD and st.session_state.get("_authed"):
        st.sidebar.button("🔒 LOG OUT", key="logout", on_click=log_out, width="stretch")


def require_password() -> None:
    """Gate the page behind DASHBOARD_PASSWORD when one is set. Without one the
    dashboard is open to anyone who can reach its port — fine on 127.0.0.1,
    not on a network: its buttons spend paid API credits, and it shows deal
    notes and the buyer names in contract drafts."""
    import hmac
    from config import DASHBOARD_PASSWORD
    if not DASHBOARD_PASSWORD:
        return
    if st.session_state.get("_authed"):
        limit, now = idle_limit_s(), _now()
        last = st.session_state.get("_last_active", now)
        if limit and now - last > limit:
            log_out()
            st.session_state["_timed_out"] = True
        else:
            st.session_state["_last_active"] = now
            if weak_password(DASHBOARD_PASSWORD) and not st.session_state.get("_weak_warned"):
                st.session_state["_weak_warned"] = True
                st.warning(f"DASHBOARD_PASSWORD is shorter than {MIN_PASSWORD_LEN} characters. "
                           "Use a longer one in .env (a few unrelated words), then restart.")
            return
    # Back from the reload a theme switch makes: logged in still.
    elif redeem_resume_ticket(_resume_cookie()):
        st.session_state["_authed"] = True
        st.session_state["_last_active"] = _now()
        return
    st.markdown('<div class="wordmark">MFC PROPERTY</div>', unsafe_allow_html=True)
    if st.session_state.pop("_timed_out", False):
        st.info("Logged out after a while without activity. Enter the password again.")
    with st.form("login"):
        typed = st.text_input("Password", type="password", key="login_pw")
        entered = st.form_submit_button("ENTER")
    if entered:
        wait = _locked_for(_now())
        if wait:
            st.error(f"Too many wrong passwords. Try again in {_minutes(wait)} min.")
            st.stop()
        if hmac.compare_digest(typed.encode(), DASHBOARD_PASSWORD.encode()):
            with _lock:
                _fails.clear()
            st.session_state["_authed"] = True
            st.session_state["_last_active"] = _now()
            st.rerun()
        _record_failure(_now())
        # The attempt is logged, never what was typed.
        log.warning("Dashboard login: wrong password")
        time.sleep(WRONG_PASSWORD_DELAY_S)      # slows guessing
        wait = _locked_for(_now())
        st.error(f"Wrong password. Too many tries: locked for {_minutes(wait)} min."
                 if wait else "Wrong password.")
    # Who runs the dashboard and what happens to data: readable before login.
    from dashboard import legal
    legal.render_footer()
    st.stop()
