"""
dashboard/prefs.py — how the page looks to you: the language of the cards
(D7) and the theme (D14). Kept in the database (app_state, keys 'pref_…'),
so a choice holds after a reload and on your phone too.

Each setting is read once per browser session into st.session_state under
its own name, which is also the key of its widget in the sidebar; the
widget's on_change writes it back.
"""

from __future__ import annotations

import streamlit as st

# name → (allowed values, the first is the default)
CHOICES = {
    # "auto": a Czech flat's card in Czech, a Slovak one's in English.
    # "en": every card in English. The listing's own text stays as written.
    "card_lang": ("auto", "en"),
    # "auto": light or dark as the device is set (a phone in the sun, say).
    "theme": ("dark", "light", "auto"),
}


def _read(name: str) -> str | None:
    import database
    conn = database.get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (f"pref_{name}",)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get(name: str) -> str:
    """The setting's value: this session's, else the saved one, else the default."""
    allowed = CHOICES[name]
    try:
        val = st.session_state.get(name)
    except Exception:          # outside a Streamlit run (scripts, PDF builders)
        val = None
    if val in allowed:
        return val
    try:
        val = _read(name)
    except Exception:          # no database yet: the default
        val = None
    val = val if val in allowed else allowed[0]
    try:
        st.session_state[name] = val
    except Exception:
        pass
    return val


def theme_now() -> str:
    """"dark" or "light": the theme on screen, for what CSS can't colour
    (the charts). With "auto", the one Streamlit reports, else dark."""
    chosen = get("theme")
    if chosen != "auto":
        return chosen
    try:
        return "light" if st.context.theme.type == "light" else "dark"
    except Exception:
        return "dark"


def save(name: str) -> None:
    """on_change of the setting's widget: keep what was picked."""
    val = st.session_state.get(name)
    if val not in CHOICES[name]:
        return
    import database
    conn = database.get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                     (f"pref_{name}", val))
        conn.commit()
    finally:
        conn.close()
    if name == "theme":
        # The page reloads to switch (style.THEME_JS): it takes a resume
        # ticket with it, so the reload keeps the login (dashboard/login.py).
        st.session_state["_theme_reload"] = True
