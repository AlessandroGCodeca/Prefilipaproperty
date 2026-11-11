"""
dashboard/listing_cache.py — the dashboard's listing load, cached (M5 in
docs/PROJECT_REVIEW.md).

The load grew with the database (0.39 s for 5,000 listings) and ran on every
click. A cache hit costs a few hundredths of a second. Whatever the dashboard
changes clears the cache: a pipeline step finishing (clear_after_finished_job)
and the in-page writes (clear_listing_cache, next to each). The time limit
covers writes from elsewhere: the scheduler, which runs in its own process.
"""

import streamlit as st

from modules import jobs

LISTINGS_TTL_S = 60


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _load_active(rejected: bool, db_path: str) -> list[dict]:
    # db_path is part of the key only, so a different database (one per
    # test) never gets another database's rows.
    import database
    return database.get_all_active(rejected=rejected)


def load_active(rejected: bool = False) -> list[dict]:
    import database
    return _load_active(rejected, database.SQLITE_PATH)


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _waiting_for_rent(market: str, db_path: str) -> dict[str, int]:
    from modules.cashflow_runner import waiting_for_rent
    return waiting_for_rent(market)


def waiting_for_rent(market: str = "cz") -> dict[str, int]:
    """{rent key: listings} of `market`'s listings that wait unscored for a
    rent figure (modules.cashflow_runner.waiting_for_rent), cached as the
    listing load is. {} when it can't be worked out: the page still draws."""
    import database
    try:
        return _waiting_for_rent(market, database.SQLITE_PATH)
    except Exception:                       # a banner, never a broken page
        import logging
        logging.getLogger("sovereign").exception("Listings waiting for a rent not counted")
        return {}


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _quiet_portals(db_path: str) -> list[dict]:
    import database
    return database.quiet_portals()


def quiet_portals() -> list[dict]:
    """The portals whose last runs returned no listings or failed
    (database.quiet_portals), cached as the listing load is. [] when they
    can't be read: the page still draws."""
    import database
    try:
        return _quiet_portals(database.SQLITE_PATH)
    except Exception:
        import logging
        logging.getLogger("sovereign").exception("Quiet portals not read")
        return []


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _page_context(db_path: str) -> tuple[dict, dict, dict]:
    import database
    return database.get_price_history(), database.get_deal_stages(), database.latest_vibes()


def page_context() -> tuple[dict, dict, dict]:
    """(price history, deal stages, latest vibe notes) of every listing — what
    the cards and tables show beside each row — cached as the listing load is.
    Each was a full-table read on every click. The page's own writes (SAVE
    STAGE, MOVE DEAL, SAVE ANNOTATION) clear it."""
    import database
    return _page_context(database.SQLITE_PATH)


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _price_drops(days: int, db_path: str) -> list[dict]:
    import database
    return database.get_price_drops(days=days)


def price_drops(days: int = 14) -> list[dict]:
    """database.get_price_drops, cached as the listing load is."""
    import database
    return _price_drops(days, database.SQLITE_PATH)


@st.cache_data(ttl=LISTINGS_TTL_S, show_spinner=False)
def _lv_documents(ids: tuple, db_path: str) -> dict[str, str]:
    import database
    return database.get_lv_documents(list(ids))


def lv_documents(ids) -> dict[str, str]:
    """database.get_lv_documents for these listing ids, cached as the listing
    load is. A pasted výpis is saved from the page, which clears it."""
    import database
    return _lv_documents(tuple(ids), database.SQLITE_PATH)


def clear_listing_cache() -> None:
    """After the dashboard changes listings: the next load reads the database."""
    _load_active.clear()
    _waiting_for_rent.clear()
    _quiet_portals.clear()
    _page_context.clear()
    _price_drops.clear()
    _lv_documents.clear()


@st.cache_resource
def _cleared_for() -> dict:
    # Process-wide, as the cache and the jobs are: the last finished job the
    # listing cache was cleared for.
    return {"job": None}


def clear_after_finished_job() -> None:
    """A pipeline step has finished since the last clear: every tab reloads,
    whether or not it watched the step run."""
    done = jobs.current()
    if done is not None and not done.running and _cleared_for()["job"] != done.id:
        _cleared_for()["job"] = done.id
        clear_listing_cache()
