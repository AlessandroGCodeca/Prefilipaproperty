"""
dashboard/filters.py — the sidebar's filters remembered, and saved searches
(UX1).

The last filters are kept in the database (app_state, key 'filters_last'),
so a reload, a new session or your phone starts where you left off; each
filter writes them back when it changes. A saved search is a named set of
them (table saved_searches): Apply puts it back, and Alert rule turns it
into a rule of the ALERTS tab.

Every value read back is checked against what its widget accepts now (a
portal no longer read, a price outside the slider) and falls back to the
default otherwise, so a stored value can never break the sidebar.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

CLASSES = ["GREEN", "YELLOW", "WHITE", "PENDING", "REJECTED"]
CONDITIONS = ["new", "renovated", "good", "original", "poor"]
PRICE_RANGE, PRICE_STEP = (10_000, 600_000), 5_000
SIZE_RANGE, SIZE_STEP = (20, 150), 5

# widget key → its default. "fl_sources" defaults to every portal offered.
DEFAULTS = {
    "fl_max_price": 300_000,
    "fl_min_size": 25,
    "fl_classes": ["GREEN", "YELLOW", "WHITE", "PENDING"],
    "fl_sources": None,
    "fl_district": "",
    "fl_cond": [],
    "fl_parking": False,
    "fl_furnished": False,
    "fl_elevator": False,
    "fl_drops": False,
    "fl_cf": False,
    "fl_hide_dev": True,
    "fl_hide_dups": True,
    "structure": None,            # the first of the sidebar's STRUCTURES
}
_LAST = "filters_last"


def _conn():
    import database
    conn = database.get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS saved_searches (name TEXT PRIMARY KEY, "
                 "filters TEXT NOT NULL, saved_at TEXT NOT NULL)")
    return conn


def _valid(key: str, value, sources: list[str], structures: list[str]):
    """`value` if `key`'s widget accepts it now, else its default."""
    default = DEFAULTS[key]
    if key == "fl_sources":
        default = list(sources)
    if key == "structure":
        default = structures[0] if structures else None
    if key in ("fl_max_price", "fl_min_size"):
        (lo, hi), step = ((PRICE_RANGE, PRICE_STEP) if key == "fl_max_price"
                          else (SIZE_RANGE, SIZE_STEP))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi:
            return int(round(value / step) * step)
        return default
    if key in ("fl_classes", "fl_sources", "fl_cond"):
        allowed = {"fl_classes": CLASSES, "fl_sources": sources, "fl_cond": CONDITIONS}[key]
        if isinstance(value, list):
            return [v for v in value if v in allowed]
        return default
    if key == "fl_district":
        return str(value)[:80] if isinstance(value, str) else default
    if key == "structure":
        return value if value in structures else default
    return value if isinstance(value, bool) else default


def current() -> dict:
    """The filters as they are on the page."""
    return {k: st.session_state[k] for k in DEFAULTS if k in st.session_state}


def _read_last() -> dict:
    try:
        conn = _conn()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (_LAST,)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else {}
    except Exception:            # no database yet, or a broken value: the defaults
        return {}


def init(sources: list[str], structures: list[str]) -> None:
    """Before the filter widgets are drawn: each one this session hasn't set
    yet gets its remembered value, else its default."""
    saved = None
    for key in DEFAULTS:
        if key in st.session_state:
            continue
        if saved is None:
            saved = _read_last()
        st.session_state[key] = _valid(key, saved.get(key, object()), sources, structures)


def _write(key: str, values: dict) -> None:
    conn = _conn()
    try:
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                     (key, json.dumps(values, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def save_last() -> None:
    """A filter's on_change: remember the filters as they are now."""
    try:
        _write(_LAST, current())
    except Exception:            # a read-only or busy database: forget, don't fail
        pass


# ── Saved searches ────────────────────────────────────────────────────────────
def saved_names() -> list[str]:
    conn = _conn()
    try:
        return [r[0] for r in conn.execute("SELECT name FROM saved_searches ORDER BY name")]
    finally:
        conn.close()


def _saved(name: str) -> dict:
    conn = _conn()
    try:
        row = conn.execute("SELECT filters FROM saved_searches WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else {}


def save_as() -> None:
    """SAVE: the filters as they are, under the name typed."""
    name = (st.session_state.get("fl_save_name") or "").strip()[:60]
    if not name:
        st.toast("Type a name for the search first.")
        return
    conn = _conn()
    try:
        conn.execute("INSERT OR REPLACE INTO saved_searches (name, filters, saved_at) "
                     "VALUES (?, ?, ?)", (name, json.dumps(current(), ensure_ascii=False),
                                          datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    st.session_state["fl_save_name"] = ""
    st.session_state["fl_saved_pick"] = name
    st.toast(f"Saved: {name}")


def apply_saved(sources: list[str], structures: list[str]) -> None:
    """APPLY: put the picked search's filters back (and remember them)."""
    name = st.session_state.get("fl_saved_pick")
    values = _saved(name) if name else {}
    if not values:
        return
    for key in DEFAULTS:
        st.session_state[key] = _valid(key, values.get(key, object()), sources, structures)
    save_last()


def delete_saved() -> None:
    name = st.session_state.get("fl_saved_pick")
    if not name:
        return
    conn = _conn()
    try:
        conn.execute("DELETE FROM saved_searches WHERE name = ?", (name,))
        conn.commit()
    finally:
        conn.close()
    st.session_state["fl_saved_pick"] = None
    st.toast(f"Deleted: {name}")


def rule_from(values: dict, name: str) -> dict:
    """An ALERTS rule from a search's filters: the classes it shows (only
    GREEN and YELLOW ever alert), its district text, smallest size and
    highest price, and a surplus of at least 0 with "cash-flow positive"."""
    classes = [c for c in values.get("fl_classes") or [] if c in ("GREEN", "YELLOW")]
    return {"name": name[:60], "enabled": True, "market": "",
            "classes": ",".join(classes) or "GREEN,YELLOW", "grades": "",
            "district": values.get("fl_district") or "",
            "min_size": values.get("fl_min_size"),
            "max_price_eur": values.get("fl_max_price"),
            "min_surplus": 0 if values.get("fl_cf") else None}


def alert_rule_from_saved() -> None:
    """ALERT RULE: add the picked search to the ALERTS tab's rules."""
    from database import get_alert_rules, save_alert_rules
    name = st.session_state.get("fl_saved_pick")
    values = _saved(name) if name else {}
    if not values:
        return
    rules = get_alert_rules()
    if any(r.get("name") == name for r in rules):
        st.toast(f"ALERTS already has a rule named {name}.")
        return
    save_alert_rules(rules + [rule_from(values, name)])
    st.toast(f"Alert rule added: {name} — see WORKFLOW → ALERTS.")
