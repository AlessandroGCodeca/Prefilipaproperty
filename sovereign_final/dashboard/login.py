"""
dashboard/login.py — the password gate (DASHBOARD_PASSWORD).
"""

import streamlit as st


def require_password() -> None:
    """Gate the page behind DASHBOARD_PASSWORD when one is set. Without one the
    dashboard is open to anyone who can reach its port — fine on 127.0.0.1,
    not on a network: its buttons spend paid API credits, and it shows deal
    notes and the buyer names in contract drafts."""
    import hmac
    import time
    from config import DASHBOARD_PASSWORD
    if not DASHBOARD_PASSWORD or st.session_state.get("_authed"):
        return
    st.markdown('<div class="wordmark">SOVEREIGN</div>', unsafe_allow_html=True)
    with st.form("login"):
        typed = st.text_input("Password", type="password", key="login_pw")
        entered = st.form_submit_button("ENTER")
    if entered:
        if hmac.compare_digest(typed.encode(), DASHBOARD_PASSWORD.encode()):
            st.session_state["_authed"] = True
            st.rerun()
        time.sleep(1)                  # slows guessing
        st.error("Wrong password.")
    st.stop()
