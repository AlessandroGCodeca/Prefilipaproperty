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

from dashboard import actions, diagnostics, overview, sidebar, style, view  # noqa: E402
from dashboard.login import require_password  # noqa: E402
from dashboard.tabs import (  # noqa: E402
    close, deal_pipeline, lv_todo, map_view, rejected, rent_comps, satellite, snag_list,
    tax_rates, triage, what_if,
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
view_market = view.pick_market()
actions.dispatch(sb)
diagnostics.render(sb)

# ── This run's listings, filtered and sorted ──────────────────────────────────
v = view.build(sb, view_market)
overview.render(v, sb)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Three groups, each with its own tabs: eleven in one row overflowed at
# 1440 px and hid the last behind an arrow.
TAB_GROUPS = (
    ("🎯 DEALS",    (("TRIAGE TABLE", triage), ("ACTIVE SNAG LIST", snag_list),
                     ("MAP", map_view), ("SATELLITE VIEWER", satellite))),
    ("📊 ANALYSIS", (("WHAT-IF / TAX", what_if), ("RENT COMPS", rent_comps),
                     ("TAX RATES", tax_rates))),
    ("🗂 WORKFLOW", (("DEAL PIPELINE", deal_pipeline), ("LV TO-DO", lv_todo),
                     ("REJECTED", rejected), ("ONE-CLICK CLOSE", close))),
)
# Drawn in the order the tabs were always drawn in, whatever group holds them.
DRAW_ORDER = (triage, snag_list, map_view, what_if, deal_pipeline, rejected, lv_todo,
              rent_comps, tax_rates, satellite, close)

_page_tab = {}
for group, (_label, pages) in zip(st.tabs([g for g, _ in TAB_GROUPS]), TAB_GROUPS):
    with group:
        for tab, (_name, page) in zip(st.tabs([n for n, _ in pages]), pages):
            _page_tab[page] = tab
for page in DRAW_ORDER:
    with _page_tab[page]:
        page.render(v)
