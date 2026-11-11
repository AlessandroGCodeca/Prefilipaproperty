"""
dashboard/login.py — the password gate (DASHBOARD_PASSWORD).
"""

import threading
import time

import streamlit as st

# Wrong passwords allowed within LOCKOUT_S before the gate locks for
# LOCKOUT_S. Counted for the whole dashboard process, not per browser tab: a
# guesser simply opens new sessions. While locked, the right password waits
# too — fifteen minutes is the price of not being guessable.
MAX_TRIES = 5
LOCKOUT_S = 15 * 60
# Every wrong password also waits this long before the page answers.
WRONG_PASSWORD_DELAY_S = 1.0

_lock = threading.Lock()
_fails: list[float] = []          # times of the recent wrong passwords
_locked_until = 0.0


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


def require_password() -> None:
    """Gate the page behind DASHBOARD_PASSWORD when one is set. Without one the
    dashboard is open to anyone who can reach its port — fine on 127.0.0.1,
    not on a network: its buttons spend paid API credits, and it shows deal
    notes and the buyer names in contract drafts."""
    import hmac
    from config import DASHBOARD_PASSWORD
    if not DASHBOARD_PASSWORD or st.session_state.get("_authed"):
        return
    st.markdown('<div class="wordmark">SOVEREIGN</div>', unsafe_allow_html=True)
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
            st.rerun()
        _record_failure(_now())
        time.sleep(WRONG_PASSWORD_DELAY_S)      # slows guessing
        wait = _locked_for(_now())
        st.error(f"Wrong password. Too many tries: locked for {_minutes(wait)} min."
                 if wait else "Wrong password.")
    st.stop()
