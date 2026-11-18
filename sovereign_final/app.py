"""
app.py — Sovereign Investor Dashboard
Slovakia + Czechia 2026 | Private Use Only
Run: streamlit run app.py

Two markets (markets.py) share the page. The selector at the top of the main
area filters every tab; "All markets" ranks both together with Czech prices
converted to EUR at the one dated rate in config. A card always shows its own
currency, and a Czech card is labelled in Czech.

This file is the page, top to bottom; what each part draws lives in
dashboard/: the sidebar, the page state every tab reads (dashboard/view.py),
the tiles over the tabs, and one module per tab (dashboard/tabs/). Streamlit
runs it again on every click, and each run builds its own state and hands it
to the tabs.
"""

import logging
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

# Pipeline steps log their progress. The scheduler writes the lines to
# logs/scheduler.log; the dashboard's go to its terminal (in Docker,
# `docker compose logs dashboard`). A no-op on every rerun after the first.
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per Claude call
from modules import redact as _redact  # noqa: E402
_redact.install()        # no key from .env in the terminal's log, even inside a URL

from modules import market_rates as _market_rates  # noqa: E402
from modules import settings as _settings  # noqa: E402

# Your own figures (👤 YOUR SITUATION), when another process — or another
# browser tab — saved a change since this one last looked: one stat() a run.
# The same for the market rate the scheduler last read from the ECB.
_settings.sync()
_market_rates.sync()

from dashboard import actions, diagnostics, legal, overview, sidebar, style, view  # noqa: E402
from dashboard.login import logout_button, require_password  # noqa: E402
from dashboard.tabs import (  # noqa: E402
    alert_rules, auctions, backtest, close, compare, deal_pipeline, lv_todo, map_view, portfolio,
    rejected, rent_comps, satellite, snag_list, tax_rates, triage, what_if,
)

st.set_page_config(
    page_title="Sovereign RE",
    page_icon="🏛",
    layout="wide",
    # "auto": open on desktop, collapsed on a phone where it would cover the page.
    initial_sidebar_state="auto",
)
style.inject()
require_password()

# ── Init ──────────────────────────────────────────────────────────────────────
import database  # noqa: E402
from database import init_db, backfill_dev_project_flags  # noqa: E402


@st.cache_resource
def _init_db_once(db_path: str) -> bool:
    # Streamlit reruns this whole script on every click. init_db() re-applies
    # the schema, runs the column checks and backfills, and commits, which takes
    # the write lock: while the scheduler commits a big batch, a click could
    # wait up to the 30 s lock timeout. Once per process per database is enough.
    init_db()
    return True


_init_db_once(database.SQLITE_PATH)


@st.cache_resource
def _startup_backfill():
    # Flag existing rows by URL/title pattern. cache_resource runs this once per
    # session instead of on every Streamlit rerun (every widget interaction).
    return backfill_dev_project_flags()


_startup_backfill()

# ── Sidebar, market, the buttons clicked ──────────────────────────────────────
sb = sidebar.render()
logout_button()
view_market = view.pick_market()
actions.dispatch(sb)
diagnostics.render(sb)

# ── This run's listings, filtered and sorted ──────────────────────────────────
v = view.build(sb, view_market)
overview.render(v, sb)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Three groups, each with its own tabs: a dozen in one row overflowed at
# 1440 px and hid the last behind an arrow.
TAB_GROUPS = (
    ("🎯 DEALS",    (("TRIAGE TABLE", triage), ("ACTIVE SNAG LIST", snag_list),
                     ("MAP", map_view), ("SATELLITE VIEWER", satellite),
                     ("AUCTIONS", auctions))),
    ("📊 ANALYSIS", (("WHAT-IF / TAX", what_if), ("COMPARE", compare),
                     ("RENT COMPS", rent_comps), ("TAX RATES", tax_rates),
                     ("BACKTEST", backtest))),
    ("🗂 WORKFLOW", (("DEAL PIPELINE", deal_pipeline), ("LV TO-DO", lv_todo),
                     ("REJECTED", rejected), ("ONE-CLICK CLOSE", close),
                     ("ALERTS", alert_rules), ("PORTFOLIO", portfolio))),
)
# Drawn in the order the tabs were always drawn in, whatever group holds them.
DRAW_ORDER = (triage, snag_list, map_view, what_if, deal_pipeline, rejected, lv_todo,
              rent_comps, tax_rates, satellite, close, compare, alert_rules, auctions, portfolio,
              backtest)

# The tab you were on comes back after a reload (and in a bookmark): kept in
# the address as ?group=…&tab=….
def _remember(param: str, key: str) -> None:
    value = st.session_state.get(key)
    if value:
        st.query_params[param] = value


_groups = [g for g, _ in TAB_GROUPS]
_qp_group = st.query_params.get("group")
_page_tab = {}
for group, (_label, pages) in zip(
        st.tabs(_groups, key="tab_group", default=_qp_group if _qp_group in _groups else None,
                on_change=_remember, args=("group", "tab_group")),
        TAB_GROUPS):
    with group:
        _names = [n for n, _ in pages]
        _qp_tab = st.query_params.get("tab")
        _key = f"tab_in_{_names[0]}"
        for tab, (_name, page) in zip(
                st.tabs(_names, key=_key, default=_qp_tab if _qp_tab in _names else None,
                        on_change=_remember, args=("tab", _key)),
                pages):
            _page_tab[page] = tab
for page in DRAW_ORDER:
    with _page_tab[page]:
        page.render(v)

# The disclaimer, and the imprint, privacy notice and terms (dashboard/legal.py).
legal.render_footer()
