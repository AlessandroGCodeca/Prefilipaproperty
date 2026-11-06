"""The dashboard's listing load is cached (dashboard/listing_cache.py, M5 in docs/PROJECT_REVIEW.md).

It took 0.39 s for 5,000 listings and ran on every click. A write from outside
the page (the scheduler's) shows after LISTINGS_TTL_S; a pipeline step run
from the dashboard clears the cache as soon as it finishes.
"""

from datetime import datetime, timezone

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402

from tests.conftest import make_listing  # noqa: E402
from tests.test_app_smoke import run_app  # noqa: E402

pytestmark = pytest.mark.keeps_listing_cache


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    from modules import jobs

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setattr(jobs, "_job", None)     # no other test's finished job
    database.init_db()
    st.cache_data.clear()
    yield database
    st.cache_data.clear()


def _add(db, lid):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_listing(make_listing(lid, last_seen_at=now, scraped_at=now))


def _demo(at) -> bool:
    assert not at.exception, [e.value for e in at.exception]
    return any("demo listings" in i.value for i in at.info)


def test_a_rerun_reads_the_cached_listings(db, monkeypatch):
    calls = []
    real = db.get_all_active
    monkeypatch.setattr(db, "get_all_active",
                        lambda **kw: calls.append(kw) or real(**kw))
    at = run_app()
    n = len(calls)
    assert n
    at.run()
    at.run()
    assert len(calls) == n


def test_an_outside_write_waits_for_the_cache_but_a_finished_step_clears_it(db):
    from modules import jobs

    at = run_app()
    assert _demo(at)                    # empty database
    _add(db, "c1")                      # as the scheduler would, from outside
    assert _demo(at.run())              # still the cached (empty) load

    assert jobs.start("TEST STEP", lambda progress: ("success", "done")) is None
    jobs.wait(30)
    assert not _demo(at.run())          # the step finished: the page reloads


def test_the_cache_has_a_short_time_limit():
    import ast
    import os

    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "dashboard", "listing_cache.py"), encoding="utf-8").read()
    ttl = next(n.value.value for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "LISTINGS_TTL_S")
    assert 0 < ttl <= 300
