"""A broken portal's listings are not retired without a warning (H3): the
stale check retires per portal, only for portals that returned listings this
run; each portal's count is recorded per run; and the dashboard flags a
portal that returned none, or failed, on its last two runs."""

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

import scheduler
from modules import pipeline_state
from tests.conftest import make_listing

OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _old(lid, source, market="sk"):
    return make_listing(lid, source=source, market=market, url=f"https://x/{source}/{lid}",
                        last_seen_at=OLD, scraped_at=OLD)


def _active(conn_for, lid):
    conn = conn_for()
    try:
        return conn.execute("SELECT is_active FROM listings WHERE id = ?", (lid,)).fetchone()[0]
    finally:
        conn.close()


# ── The stale check, per portal ───────────────────────────────────────────────
def test_stale_check_retires_only_the_portals_named(full_db):
    import database as db
    for lid, source in (("b1", "bazos"), ("t1", "topreality"), ("n1", "nehnutelnosti")):
        db.upsert_listing(_old(lid, source))
    assert db.deactivate_stale_listings(days=21, market="sk", sources=["bazos"]) == 1
    assert [_active(full_db, i) for i in ("b1", "t1", "n1")] == [0, 1, 1]
    assert db.deactivate_stale_listings(days=21, sources=[]) == 0          # none named: none
    assert db.deactivate_stale_listings(days=21, exclude_sources=["topreality"]) == 1
    assert [_active(full_db, i) for i in ("t1", "n1")] == [1, 0]


# ── The run log ───────────────────────────────────────────────────────────────
def test_a_run_counts_the_listings_it_saw_not_only_the_ones_it_upserted(full_db):
    """A run where every listing was already fresh upserts nothing, and the
    scraper returns 0 — it still saw them (touched last_seen_at)."""
    import database as db
    from database.portal_runs import now_iso
    db.upsert_listing(_old("b1", "bazos"))
    db.upsert_listing(_old("b2", "bazos"))
    started = now_iso()
    db.touch_listings(["https://x/bazos/b1", "https://x/bazos/b2"])
    assert db.record_portal_run("sk", "bazos", started, returned=0) == 2
    assert db.record_portal_run("sk", "bazos", now_iso(), returned=7) == 7
    runs = db.portal_runs("sk")[("sk", "bazos")]
    assert [r["listings"] for r in runs] == [7, 2]          # newest first


def test_a_portal_is_flagged_after_two_bad_runs_in_a_row(full_db):
    import database as db
    from database.portal_runs import now_iso
    db.record_portal_run("sk", "bazos", now_iso(), 40)
    db.record_portal_run("sk", "bazos", now_iso(), 0)
    assert db.quiet_portals() == []                         # one bad run: not yet
    db.record_portal_run("sk", "bazos", now_iso(), 0, "RuntimeError: HTTP 403")
    quiet = db.quiet_portals()
    assert [(q["market"], q["source"]) for q in quiet] == [("sk", "bazos")]
    assert quiet[0]["runs"][0]["error"] == "RuntimeError: HTTP 403"
    assert quiet[0]["last_good_at"] is not None
    db.record_portal_run("sk", "bazos", now_iso(), 12)      # back: no flag
    assert db.quiet_portals() == []


def test_a_failed_run_counts_as_bad_even_with_a_partial_count(full_db):
    import database as db
    from database.portal_runs import now_iso
    for _ in range(2):
        db.record_portal_run("cz", "idnes", now_iso(), 15, "TimeoutError: stopped")
    assert [q["source"] for q in db.quiet_portals("cz")] == ["idnes"]
    assert db.quiet_portals("sk") == []


def test_a_new_portal_with_one_run_is_not_flagged(full_db):
    import database as db
    from database.portal_runs import now_iso
    db.record_portal_run("cz", "bazos_cz", now_iso(), 0)
    assert db.quiet_portals() == []


# ── The pipeline ──────────────────────────────────────────────────────────────
_STEP_MODULES = ("scraper.nehnutelnosti", "scraper.bazos", "scraper.topreality",
                 "enrich_pending", "scraper.rentals", "scraper.rentals_cz",
                 "modules.debt_bot", "modules.address_enrichment",
                 "modules.description_enrichment", "modules.cashflow_runner",
                 "modules.location_iq")


@pytest.fixture
def pipeline(tmp_path, monkeypatch, full_db):
    from modules import backup
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", str(tmp_path / "data" / "last_run"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "data" / "status.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    for name in _STEP_MODULES:
        monkeypatch.setitem(sys.modules, name, None)

    def portal(name, run):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(run=run))
    return portal


def test_a_quiet_portal_fails_its_step_and_keeps_its_listings(pipeline, full_db):
    """Bazos runs without an error but returns nothing; Topreality works.
    Bazos's step fails, its old listings stay active, Topreality's are
    retired, and both runs are recorded."""
    import database as db
    db.upsert_listing(_old("b1", "bazos"))
    db.upsert_listing(_old("t1", "topreality"))
    pipeline("scraper.bazos", lambda max_pages=10: 0)
    pipeline("scraper.topreality", lambda max_pages=10: 25)
    assert scheduler.run_pipeline(trigger="test") is True     # one portal read
    status = pipeline_state.read_status("sk")
    steps = {s["step"]: s for s in status["steps"]}
    assert not steps["Bazos.sk"]["ok"] and "returned no listings" in steps["Bazos.sk"]["detail"]
    assert steps["Topreality.sk"]["ok"]
    assert "stale check skipped for Nehnutelnosti.sk, Bazos.sk" in steps["Housekeeping"]["detail"]
    assert _active(full_db, "b1") == 1 and _active(full_db, "t1") == 0
    runs = db.portal_runs("sk")
    assert runs[("sk", "bazos")][0]["listings"] == 0
    assert runs[("sk", "topreality")][0]["listings"] == 25
    assert runs[("sk", "nehnutelnosti")][0]["error"]          # it failed: recorded as such
    # A second quiet run: the dashboard flags Bazos.sk and Nehnutelnosti.sk.
    scheduler.run_pipeline(trigger="test")
    assert {q["source"] for q in db.quiet_portals("sk")} == {"bazos", "nehnutelnosti"}


def test_portal_names():
    assert scheduler.source_of("scraper.bazos_cz") == "bazos_cz"
    assert scheduler.portal_name("cz", "bazos_cz") == "Bazos.cz"
    assert scheduler.portal_name("cz", "sreality") == "Sreality.cz"     # blocked, still named
    assert scheduler.portal_name("sk", "legacy") == "legacy"


# ── The dashboard ─────────────────────────────────────────────────────────────
@pytest.fixture
def actions():
    pytest.importorskip("streamlit")
    from dashboard import actions
    return actions


def test_a_portal_button_records_its_run(full_db, actions, monkeypatch):
    import database as db
    from modules import address_enrichment, cashflow_runner, description_enrichment
    monkeypatch.setattr(address_enrichment, "run_address_enrichment", lambda **kw: 0)
    monkeypatch.setattr(description_enrichment, "run_description_enrichment", lambda **kw: 0)
    monkeypatch.setattr(cashflow_runner, "run_scoring", lambda **kw: 0)
    monkeypatch.setattr(db, "mark_duplicates", lambda **kw: 0)
    monkeypatch.setattr(actions, "_run_scraper_subprocess", lambda module: (0, "", False))
    level, msg = actions._scrape_step("bazos", "Bazos", "BAZOS")(None)
    assert level == "warning" and "returned no listings" in msg
    monkeypatch.setattr(actions, "_run_scraper_subprocess",
                        lambda module: (0, "Bazos blocked: HTTP 403", False))
    level, _ = actions._scrape_step("bazos", "Bazos", "BAZOS")(None)
    assert level == "error"
    runs = db.portal_runs("sk")[("sk", "bazos")]
    assert [r["error"] for r in runs] == ["Bazos blocked: HTTP 403", ""]
    assert [q["source"] for q in db.quiet_portals()] == ["bazos"]


def test_clean_stale_keeps_a_quiet_portals_listings(full_db, actions):
    import database as db
    from database.portal_runs import now_iso
    db.upsert_listing(_old("b1", "bazos"))
    db.upsert_listing(_old("t1", "topreality"))
    for _ in range(2):
        db.record_portal_run("sk", "bazos", now_iso(), 0, "HTTP 403")
    level, msg = actions._stale_step(None)
    assert level == "success" and "Deactivated 1 stale" in msg and "Kept the listings of Bazos.sk" in msg
    assert _active(full_db, "b1") == 1 and _active(full_db, "t1") == 0


def test_quiet_portal_note():
    pytest.importorskip("streamlit")
    from dashboard.overview import quiet_portal_note
    q = {"market": "cz", "source": "idnes", "last_good_at": None,
         "runs": [{"run_at": "x", "listings": 0, "error": "PortalBlocked: HTTP 403"},
                  {"run_at": "y", "listings": 0, "error": ""}]}
    note = quiet_portal_note(q)
    assert "🇨🇿 Reality.iDNES.cz returned no listings on its last 2 runs" in note
    assert "no listings from it on record; latest: PortalBlocked: HTTP 403" in note
    assert "kept, not retired" in note
