"""Tests for live rent comps: prenájom listings → €/m² per district → rent.

Covers the rental-ad parsing in scraper/rentals.py, the normalisation and
blending in engine/rent_comps.py, get_rent_estimate's use of live rates, and
the rebuild that re-scores listings whose district rate moved.
"""

import pytest

import database as db
from config import (
    RENT_PER_M2, RENT_COMP_ASKING_HAIRCUT, RENT_COMP_MIN_SAMPLE,
    RENT_COMP_PRIOR_WEIGHT, FURNISHED_RENT_PREMIUM, INDUSTRIAL_RENT_PREMIUM,
)
from engine import rent_comps as rc
from engine.financial import (
    get_rent_estimate, match_rent_key, base_rent_rate, analyse,
)
from scraper import rentals
from tests.conftest import make_listing


# ── Rental-ad parsing ─────────────────────────────────────────────────────────
class TestRentFromText:
    @pytest.mark.parametrize("text,rent", [
        ("Prenájom 2-izbový byt, 650 € + energie, kaucia 1300 €", 650),
        ("Kaucia: 1 300 €. Cena 650 €/mes.", 650),          # monthly beats first
        ("Záloha 700 €, nájom 700 € mesačne", 700),
        ("Garsónka 25 m2, 480 €", 480),
        ("Energie cca 150 €, nájomné 690 €", 690),            # energies skipped
    ])
    def test_reads_the_rent(self, text, rent):
        assert rentals.rent_from_text(text) == rent

    def test_sale_prices_are_not_rents(self):
        assert rentals.rent_from_text("Predaj bytu 189 000 €") == 0.0


class TestEnergiesAndFurnishing:
    @pytest.mark.parametrize("text", [
        "Cena 900 € vrátane energií", "nájom s energiami 800 €",
        "Energie sú v cene", "všetko v cene, 750 €",
    ])
    def test_energies_included(self, text):
        assert rc.energies_included(text)

    @pytest.mark.parametrize("text", ["650 € + energie", "nájom 700 €, energie zvlášť"])
    def test_energies_extra(self, text):
        assert not rc.energies_included(text)

    @pytest.mark.parametrize("text,f", [
        ("kompletne zariadený byt", "furnished"),
        ("čiastočne zariadený", "semi"),
        ("nezariadený byt", "unfurnished"),
        ("2-izbový byt s balkónom", "unknown"),
    ])
    def test_furnishing(self, text, f):
        assert rc.furnishing_from_text(text) == f


class TestBuildRental:
    def test_a_whole_flat(self):
        r = rentals.build_rental(
            "bazos", "https://x/1", "Prenájom 2-izbového bytu, Ružinov, 55 m²",
            "Pekný byt 55 m2. 750 € + energie.", location="Bratislava")
        assert r["rent_eur"] == 750 and r["size_m2"] == 55
        assert r["district"] == "Ružinov, Bratislava" and r["rent_key"] == "ružinov"
        assert r["energies_included"] == 0 and r["rooms"] == 2

    @pytest.mark.parametrize("title", [
        "Prenájom izby v Petržalke 15 m²", "Ubytovanie na noc, Žilina 40 m2",
        "Prenájom garáže Žilina 18 m2", "Prenájom kancelárie Nitra 60 m2",
    ])
    def test_not_a_long_term_flat(self, title):
        assert rentals.build_rental("bazos", "https://x/2", title, f"{title}, 400 €") is None

    def test_needs_a_place(self):
        assert rentals.build_rental("bazos", "https://x/3", "Prenájom bytu 50 m2",
                                    "700 €") is None

    def test_implausible_rent(self):
        # €15/mo for 50 m² is a misread, not a market.
        assert rentals.build_rental("bazos", "https://x/4", "Prenájom bytu Nitra 50 m2",
                                    "150 € 15 €", rent=15) is None


class TestPortalParsers:
    BAZOS = """
    <div class="inzeraty inzeratyflex"><div class="inzeratynadpis">
      <a href="/inzerat/123/prenajom-2i.php">Prenájom 2-izbový byt Petržalka 52 m2</a></div>
      <div class="popis">Nezariadený byt, 52 m², balkón</div>
      <div class="inzeratycena"><b>690 €</b></div>
      <div class="inzeratylok">Bratislava<br>851 01</div></div>
    <div class="inzeraty inzeratyflex"><div class="inzeratynadpis">
      <a href="/inzerat/124/izba.php">Prenájom izby v Petržalke</a></div>
      <div class="inzeratycena"><b>300 €</b></div>
      <div class="inzeratylok">Bratislava</div></div>
    """

    def test_bazos_cards(self):
        rows = rentals.parse_bazos_page(self.BAZOS)
        assert len(rows) == 1
        r = rows[0]
        assert r["url"] == "https://reality.bazos.sk/inzerat/123/prenajom-2i.php"
        assert (r["rent_eur"], r["size_m2"], r["rent_key"]) == (690, 52, "petržalka")
        assert r["furnished"] == "unfurnished"

    def test_topreality_links_keep_rentals_drop_the_rest(self):
        html = """<a href="/prenajom-2-izbovy-byt-zilina-r1234567.html">a</a>
                  <a href="/prenajom-garaz-zilina-r7654321.html">b</a>
                  <a href="/vyhladavanie/byty/prenajom?page=2">c</a>"""
        assert rentals.topreality_links(html) == [
            "https://www.topreality.sk/prenajom-2-izbovy-byt-zilina-r1234567.html"]

    def test_topreality_detail_json_ld(self):
        html = """<html><head>
          <meta property="og:title" content="Prenájom 2-izbový byt, Žilina - Hliny">
          <script type="application/ld+json">{"@type": "Apartment",
            "offers": {"price": "620"}, "floorSize": {"value": "54"},
            "address": {"addressLocality": "Žilina"}}</script></head>
          <body>Kaucia 1240 €. Byt je čiastočne zariadený.</body></html>"""
        r = rentals.parse_topreality_detail("https://www.topreality.sk/x-r1234567.html", html)
        assert (r["rent_eur"], r["size_m2"], r["rent_key"], r["furnished"]) == (620, 54, "žilina", "semi")


# ── Normalisation, aggregation, blending ─────────────────────────────────────
def _rental(key, rent, size, **kw):
    return {"rent_key": key, "rent_eur": rent, "size_m2": size, "rooms": kw.get("rooms", 2),
            "furnished": kw.get("furnished", "unknown"),
            "energies_included": kw.get("energies", 0)}


class TestNormalisation:
    def test_two_room_unfurnished_is_the_baseline(self):
        assert rc.baseline_eur_per_m2(600, 50, rooms=2) == pytest.approx(12.0)

    def test_small_flats_and_furniture_are_backed_out(self):
        # A garsónka lets for 1.15× per m², furniture adds 10%.
        assert rc.baseline_eur_per_m2(600, 50, rooms=1) == pytest.approx(12.0 / 1.15)
        assert rc.baseline_eur_per_m2(660, 50, rooms=2, furnished="furnished") == \
            pytest.approx(13.2 / FURNISHED_RENT_PREMIUM)

    def test_blend_moves_with_sample_size(self):
        k = RENT_COMP_PRIOR_WEIGHT
        live = 15.0 * RENT_COMP_ASKING_HAIRCUT
        assert rc.blended_rate(15.0, k, 10.0) == pytest.approx((live + 10.0) / 2, abs=0.01)
        assert abs(rc.blended_rate(15.0, 400, 10.0) - live) < 0.2


class TestAggregate:
    def test_energies_included_and_junk_are_skipped(self):
        comps = rc.aggregate([
            _rental("nitra", 500, 50), _rental("nitra", 520, 50),
            _rental("nitra", 900, 50, energies=1),      # energies in the price
            _rental("nitra", 50, 50),                    # implausible
            _rental("default", 500, 50),                 # no real place
        ])
        assert list(comps) == ["nitra"]
        assert comps["nitra"]["n"] == 2
        assert comps["nitra"]["median_eur_per_m2"] == pytest.approx(10.2)

    def test_too_few_comps_keep_the_baseline(self):
        comps = rc.aggregate([_rental("nitra", 500, 50)] * (RENT_COMP_MIN_SAMPLE - 1))
        assert rc.rates_from_comps(comps) == {}

    def test_enough_comps_give_a_blended_rate(self):
        comps = rc.aggregate([_rental("nitra", 500, 50)] * RENT_COMP_MIN_SAMPLE)
        rate = rc.rates_from_comps(comps)["nitra"]
        assert rate == rc.blended_rate(10.0, RENT_COMP_MIN_SAMPLE, RENT_PER_M2["nitra"])


# ── The engine's use of live rates ────────────────────────────────────────────
class TestEngineUsesLiveRates:
    @pytest.mark.parametrize("district,key", [
        ("Bratislava - Rača", "rača"), ("okres Žilina", "žilina"),
        ("Staré Mesto, Košice", "košice ii"),   # not Bratislava's Staré Mesto ("", "default"),
        ("Kysucké Nové Mesto", "kysucké nové mesto"), ("Atlantis", "default"),
    ])
    def test_match_rent_key(self, district, key):
        assert match_rent_key(district) == key

    def test_live_rate_wins(self):
        assert base_rent_rate("Nitra", {"nitra": 11.0}) == (11.0, "nitra", "live")
        assert base_rent_rate("Nitra", {}) == (RENT_PER_M2["nitra"], "nitra", "baseline")
        assert get_rent_estimate("Nitra", 50, rates={"nitra": 11.0}) == 550.0

    def test_industrial_premium_only_on_the_baseline(self):
        base = get_rent_estimate("Bytča", 50)
        assert base == pytest.approx(RENT_PER_M2["bytča"] * INDUSTRIAL_RENT_PREMIUM * 50, abs=0.01)
        assert get_rent_estimate("Bytča", 50, rates={"bytča": 9.0}) == 450.0

    def test_analyse_takes_rent_rates(self):
        assert analyse(100_000, 50, "Nitra", rent_rates={"nitra": 11.0}).estimated_rent == 550.0


# ── DB: rebuild, load, re-score ───────────────────────────────────────────────
def _store_rentals(key, district, eur_per_m2, n):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for i in range(n):
        db.upsert_rental({
            "id": f"{key}{i}", "source": "bazos", "url": f"https://r/{key}/{i}",
            "title": "Prenájom", "rent_eur": eur_per_m2 * 50, "size_m2": 50, "rooms": 2,
            "district": district, "rent_key": key, "energies_included": 0,
            "furnished": "unknown", "scraped_at": now, "last_seen_at": now})


class TestRebuild:
    def test_rebuild_stores_comps_and_rescoring_follows(self, full_db):
        db.upsert_listing(make_listing("flat", district="Nitra"))
        db.upsert_listing(make_listing("elsewhere", district="Žilina"))
        c = full_db()
        for lid in ("flat", "elsewhere"):
            c.execute("INSERT INTO cashflow_scores (listing_id, classification) VALUES (?, 'WHITE')", (lid,))
        c.commit()
        c.close()

        _store_rentals("nitra", "Nitra", 12.0, 30)
        summary = rc.rebuild_rent_comps()
        assert summary["keys"] == 1 and summary["rentals"] == 30
        assert summary["changed"] == ["nitra"]
        assert summary["rescored"] == 1

        c = full_db()
        scored = {r[0] for r in c.execute("SELECT listing_id FROM cashflow_scores")}
        c.close()
        assert scored == {"elsewhere"}          # only Nitra's score was dropped

        rates = rc.load_live_rates()
        assert rates["nitra"] == rc.blended_rate(12.0, 30, RENT_PER_M2["nitra"])

    def test_an_unchanged_rebuild_rescores_nothing(self, full_db):
        _store_rentals("nitra", "Nitra", 12.0, 30)
        rc.rebuild_rent_comps()
        assert rc.rebuild_rent_comps()["changed"] == []

    def test_scoring_uses_and_records_the_live_rent(self, full_db):
        from modules.cashflow_runner import run_scoring
        _store_rentals("nitra", "Nitra", 12.0, 30)
        rc.rebuild_rent_comps()
        db.upsert_listing(make_listing("flat", district="Nitra", size_m2=50, rooms=2))
        assert run_scoring() == 1
        c = full_db()
        row = dict(c.execute("SELECT * FROM cashflow_scores WHERE listing_id='flat'").fetchone())
        c.close()
        assert row["rent_source"] == "live"
        assert row["estimated_rent_eur"] == pytest.approx(rc.load_live_rates()["nitra"] * 50, abs=0.01)
        for col in ("max_price_yellow", "max_price_green", "market_discount",
                    "regional_median_m2", "stress_ratio_sro", "irr_sro", "irr_personal"):
            assert row[col] is not None, col

    def test_no_comps_means_baseline(self, full_db):
        assert rc.load_live_rates() == {}
        assert rc.comps_table() == []

    def test_init_db_drops_the_old_invented_seed(self, full_db, monkeypatch):
        c = full_db()
        c.execute("INSERT INTO rent_comps (id, district, size_band, source) "
                  "VALUES ('x', 'Nitra', 'small', 'baseline_2026')")
        c.commit()
        c.close()
        db.init_db()
        c = full_db()
        assert c.execute("SELECT COUNT(*) FROM rent_comps").fetchone()[0] == 0
        c.close()
