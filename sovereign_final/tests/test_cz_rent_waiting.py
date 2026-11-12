"""Czech listings that wait unscored for a rent figure (H2): the regional
capitals have one, the Czech rentals are read before a Czech listing is
scored, and the dashboard says how many listings wait and in which towns."""

from datetime import datetime, timedelta, timezone

import pytest

from engine import financial as fin
from engine import rent_cz
from tests.conftest import make_listing

NOW = datetime.now(timezone.utc).isoformat()


def _cz(lid, district, **kw):
    return make_listing(lid, market="cz", currency="CZK", district=district,
                        price_eur=3_500_000.0, url=f"https://example.cz/{lid}", **kw)


def _rental(i, key, rent=14_000, size=50, last_seen=NOW):
    return {"id": f"r{key}{i}", "source": "t", "url": f"https://x/cz/{key}/{i}", "title": "t",
            "rent_eur": rent, "size_m2": size, "rooms": 2, "district": key.title(),
            "rent_key": key, "energies_included": 0, "furnished": "unknown",
            "scraped_at": last_seen, "last_seen_at": last_seen, "market": "cz",
            "currency": "CZK"}


# ── The regional capitals have a published rent ───────────────────────────────
@pytest.mark.parametrize("district,key", [
    ("Plzeň 3", "plzeň"), ("Plzeň-Slovany", "plzeň"), ("Olomouc - Nová Ulice", "olomouc"),
    ("Liberec XIV-Kunratice", "liberec"), ("České Budějovice 2", "české budějovice"),
    ("Zlín-Malenovice", "zlín"), ("Karlovy Vary", "karlovy vary")])
def test_every_regional_capital_has_a_rent(district, key):
    assert rent_cz.match_rent_key(district) == key
    assert fin.get_rent_estimate(district, 50, market="cz") == rent_cz.RENT_PER_M2_CZ[key] * 50


@pytest.mark.parametrize("key,label", [
    ("kladno", "Kladno"), ("ústí nad labem", "Ústí nad Labem"),
    ("praha-východ", "Praha-východ"), ("frýdek-místek", "Frýdek-Místek"),
    ("dvůr králové nad labem", "Dvůr Králové nad Labem")])
def test_key_label(key, label):
    assert rent_cz.key_label(key) == label


# ── Which listings wait ───────────────────────────────────────────────────────
def test_waiting_for_rent_counts_the_towns_without_one(full_db):
    import database as db
    from engine import rent_comps_cz
    from modules.cashflow_runner import run_scoring, waiting_for_rent
    # Names many municipalities share: the MF rent map can't say which, so
    # they have no figure. Kladno has the map's own: it doesn't wait.
    for i in range(3):
        db.upsert_listing(_cz(f"nv{i}", "Nová Ves 3"))
    db.upsert_listing(_cz("lh1", "Lhota"))
    db.upsert_listing(_cz("pl1", "Plzeň 3"))             # has a figure: not waiting
    db.upsert_listing(_cz("kl1", "Kladno - Kročehlavy"))  # the MF map's: not waiting
    db.upsert_listing(_cz("pe1", "Petrovice"))
    db.upsert_listing(make_listing("sk1", district="Žilina"))
    assert waiting_for_rent("cz") == {"nová ves": 3, "lhota": 1, "petrovice": 1}
    assert list(waiting_for_rent("cz"))[0] == "nová ves"   # most first
    assert waiting_for_rent("sk") == {}

    # Petrovice's comps give it a live rate: its listing no longer waits.
    for i in range(6):
        db.upsert_rental(_rental(i, "petrovice"))
    rent_comps_cz.rebuild_rent_comps()
    assert waiting_for_rent("cz") == {"nová ves": 3, "lhota": 1}

    # Scored listings don't wait; the ones without a rent still do.
    assert run_scoring(market="cz") == 3               # Plzeň, Kladno and Petrovice
    assert waiting_for_rent("cz") == {"nová ves": 3, "lhota": 1}


def test_a_rejected_listing_does_not_wait(full_db):
    import database as db
    from modules.cashflow_runner import waiting_for_rent
    db.upsert_listing(_cz("kl1", "Kladno", lv_status="REJECTED"))
    assert waiting_for_rent("cz") == {}


# ── The Czech rentals are read before scoring ─────────────────────────────────
def test_last_rental_read(full_db):
    import database as db
    from engine.rent_comps_cz import last_rental_read
    assert last_rental_read() is None
    earlier = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    db.upsert_rental(_rental(1, "kladno", last_seen=earlier))
    db.upsert_rental(_rental(2, "kladno", last_seen=NOW))
    assert last_rental_read() == datetime.fromisoformat(NOW)


@pytest.fixture
def actions(monkeypatch):
    pytest.importorskip("streamlit")
    from dashboard import actions
    return actions


def _fake_rentals(monkeypatch, calls, fail=False):
    import scraper.rentals_cz as rcz

    def run(max_pages=5):
        calls.append("rentals_cz")
        if fail:
            raise RuntimeError("blocked")
        return {"rentals": 12, "keys": 2, "changed": ["kladno"], "rescored": 0}
    monkeypatch.setattr(rcz, "run", run)


@pytest.mark.parametrize("hours_ago,reads", [(None, True), (30, True), (2, False)])
def test_czech_rentals_are_read_when_stale(full_db, actions, monkeypatch, hours_ago, reads):
    import database as db
    calls = []
    _fake_rentals(monkeypatch, calls)
    if hours_ago is not None:
        when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        db.upsert_rental(_rental(1, "kladno", last_seen=when))
    note = actions._czech_rentals_if_stale()
    assert (calls == ["rentals_cz"]) is reads
    assert ("Read 12 Czech rentals first" in note) is reads


def test_a_failed_czech_rental_read_is_a_note_not_an_error(full_db, actions, monkeypatch):
    _fake_rentals(monkeypatch, [], fail=True)
    assert "couldn't be read (RuntimeError: blocked)" in actions._czech_rentals_if_stale()


def _stub_follow_ups(monkeypatch, actions, calls):
    from modules import address_enrichment, cashflow_runner, description_enrichment
    import database
    monkeypatch.setattr(actions, "_run_scraper_subprocess", lambda module: (4, "", False))
    monkeypatch.setattr(address_enrichment, "run_address_enrichment", lambda **kw: 0)
    monkeypatch.setattr(description_enrichment, "run_description_enrichment", lambda **kw: 0)
    monkeypatch.setattr(database, "mark_duplicates", lambda **kw: 0)

    def score(progress_callback=None, market=None):
        calls.append(f"score:{market}")
        return 3
    monkeypatch.setattr(cashflow_runner, "run_scoring", score)


def test_a_czech_portal_button_reads_the_rentals_before_it_scores(full_db, actions, monkeypatch):
    calls = []
    _fake_rentals(monkeypatch, calls)
    _stub_follow_ups(monkeypatch, actions, calls)
    level, msg = actions._scrape_step("bezrealitky", "Bezrealitky", "BEZREALITKY",
                                      market="cz")(None)
    assert calls == ["rentals_cz", "score:cz"]
    assert level == "success" and "scored 3" in msg and "Czech rentals first" in msg


def test_a_slovak_portal_button_reads_no_czech_rentals(full_db, actions, monkeypatch):
    calls = []
    _fake_rentals(monkeypatch, calls)
    _stub_follow_ups(monkeypatch, actions, calls)
    level, msg = actions._scrape_step("bazos", "Bazos", "BAZOS")(None)
    assert calls == ["score:None"] and "Czech" not in msg


def test_the_rent_comps_button_reads_both_markets(full_db, actions, monkeypatch):
    import scraper.rentals as rsk
    from modules import cashflow_runner
    calls = []
    _fake_rentals(monkeypatch, calls)
    monkeypatch.setattr(rsk, "run", lambda max_pages=5: calls.append("rentals_sk") or
                        {"rentals": 5, "keys": 1, "changed": []})
    monkeypatch.setattr(cashflow_runner, "run_scoring",
                        lambda progress_callback=None, market=None: calls.append("score") or 7)
    level, msg = actions._rent_step(None)
    assert calls == ["rentals_sk", "rentals_cz", "score"]
    assert level == "success" and "🇸🇰 5 rentals" in msg and "🇨🇿 12 rentals across 2 towns" in msg


def test_one_market_failing_leaves_the_other_comps(full_db, actions, monkeypatch):
    import scraper.rentals as rsk
    from modules import cashflow_runner
    calls = []
    _fake_rentals(monkeypatch, calls)

    def blocked(max_pages=5):
        raise RuntimeError("403")
    monkeypatch.setattr(rsk, "run", blocked)
    monkeypatch.setattr(cashflow_runner, "run_scoring",
                        lambda progress_callback=None, market=None: 1)
    level, msg = actions._rent_step(None)
    assert calls == ["rentals_cz"]
    assert level == "warning" and "🇸🇰 rent comps failed: RuntimeError: 403" in msg


def test_the_czech_pipeline_reads_rentals_before_scoring():
    import scheduler
    steps = list(scheduler._CZ_STEPS)
    assert steps.index("Rent comps") < steps.index("Cash-Flow Scoring")


# ── What the dashboard shows ──────────────────────────────────────────────────
def test_waiting_note():
    pytest.importorskip("streamlit")
    from dashboard.overview import WAITING_TOWNS_SHOWN, waiting_note
    note = waiting_note({"kladno": 5, "ústí nad orlicí": 2})
    assert "7 Czech listings wait unscored for a rent figure" in note
    assert "Kladno 5 · Ústí nad Orlicí 2" in note
    many = {f"town{i}": 1 for i in range(WAITING_TOWNS_SHOWN + 2)}
    assert "· 2 more towns" in waiting_note(many)
    assert "1 Czech listing waits" in waiting_note({"opava": 1})


def test_waiting_rows_show_the_comps_so_far():
    pytest.importorskip("streamlit")
    from dashboard.tabs.rent_comps import waiting_rows
    rows = waiting_rows({"kladno": 3, "opava": 1},
                        [{"District key": "kladno", "Comps": 2}])
    assert rows == [{"Town": "Kladno", "Listings waiting": 3, "Rental comps so far": 2},
                    {"Town": "Opava", "Listings waiting": 1, "Rental comps so far": 0}]
