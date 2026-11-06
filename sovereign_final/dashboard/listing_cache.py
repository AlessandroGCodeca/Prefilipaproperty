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


def clear_listing_cache() -> None:
    """After the dashboard changes listings: the next load reads the database."""
    _load_active.clear()


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
