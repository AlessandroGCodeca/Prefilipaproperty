"""Czech rents, rent comps, rentals, place names, flood / noise, the
contract draft and the memo — on synthetic data only."""

import pytest

from engine import financial as fin
from engine import rent_comps, rent_comps_cz, rent_cz
from scraper import czech_cases, rentals_cz
from scraper.cz_common import place_from_text
from tests.conftest import make_listing

NOW = "2099-01-01T00:00:00+00:00"


# ── Rents ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("district,key,rate", [
    ("Praha 2 - Vinohrady", "praha", 462), ("Praha 7 - Holešovice", "praha 7", 493),
    ("Brno-střed", "brno", 390), ("Ostrava-Poruba", "ostrava", 254),
    ("Hradec Králové", "hradec králové", 318), ("Ústí nad Labem - Střekov", "ústí nad labem", 221),
    ("Říčany, Praha-východ", "říčany", None), ("Brno-venkov", "brno-venkov", None),
    ("Plzeň 3", "plzeň", None), ("Kladno - Kročehlavy", "kladno", None), ("", "default", None),
])
def test_rent_keys(district, key, rate):
    assert rent_cz.match_rent_key(district) == key
    assert rent_cz.baseline_rent(key) == rate


def test_a_czech_rent_has_no_rooms_multiplier_and_no_borrowed_figure():
    assert fin.get_rent_estimate("Praha 2", 40, rooms=1, market="cz") == 462 * 40
    assert fin.get_rent_estimate("Praha 2", 40, rooms=1) != fin.get_rent_estimate(
        "Praha 2", 40, rooms=2)                                   # Slovakia: still applies
    with pytest.raises(LookupError, match="engine/rent_cz.py"):
        fin.get_rent_estimate("Plzeň 3", 55, market="cz")
    # Live comps give a town without a published figure its rate.
    assert fin.get_rent_estimate("Plzeň 3", 55, rates={"plzeň": 280.0}, market="cz") == 280 * 55
    assert fin.rent_fallback_kind("plzeň", market="cz") is None


# ── Rent comps: Czech rows stay Czech, Slovak stay Slovak ─────────────────────
def _rental(i, key, rent, size=50, market="cz", district=None, **kw):
    return {"id": f"r{market}{key}{i}", "source": "t", "url": f"https://x/{market}/{key}/{i}",
            "title": "t", "rent_eur": rent, "size_m2": size, "rooms": 2,
            "district": district or key.title(), "rent_key": key, "energies_included": 0,
            "furnished": "unknown", "scraped_at": NOW, "last_seen_at": NOW, "market": market,
            "currency": "CZK" if market == "cz" else "EUR", **kw}


def test_czech_comps(full_db):
    import database as db
    for i in range(6):
        db.upsert_rental(_rental(i, "plzeň", 14_000 + i * 100))      # ~280 Kč/m²
        db.upsert_rental(_rental(i, "praha", 25_000))                 # 500 Kč/m²
    db.upsert_rental(_rental(9, "plzeň", 15_000, energies_included=1))  # not a comp
    db.upsert_rental(_rental(10, "plzeň", 200_000))                   # implausible
    for i in range(6):
        db.upsert_rental(_rental(i, "žilina", 650, size=55, market="sk"))
    db.upsert_listing(make_listing("cz1", market="cz", currency="CZK", district="Plzeň 3",
                                   price_eur=3_000_000.0, url="https://x/l/cz1"))
    out = rent_comps_cz.rebuild_rent_comps()
    assert out["keys"] == 2 and out["rentals"] == 12 and "plzeň" in out["changed"]
    rates = rent_comps_cz.load_live_rates()
    from config import RENT_COMP_ASKING_HAIRCUT, RENT_COMP_PRIOR_WEIGHT
    plzen_median = sorted((14_000 + i * 100) / 50 for i in range(6))
    med = (plzen_median[2] + plzen_median[3]) / 2
    assert rates["plzeň"] == round(med * RENT_COMP_ASKING_HAIRCUT, 2)   # no baseline: live
    k = RENT_COMP_PRIOR_WEIGHT
    assert rates["praha"] == round((6 * 500 * RENT_COMP_ASKING_HAIRCUT + k * 462) / (6 + k), 2)
    # The Slovak rebuild reads only Slovak rentals and keeps the Czech comps.
    sk = rent_comps.rebuild_rent_comps()
    assert sk["keys"] == 1 and sk["rentals"] == 6
    assert set(rent_comps.load_live_rates()) <= {"žilina"}
    assert set(rent_comps_cz.load_live_rates()) == {"plzeň", "praha"}
    rows = rent_comps_cz.comps_table()
    assert {r["District key"]: r["Source"] for r in rows} == {
        "plzeň": "live", "praha": "live blend"}


def test_slovak_comps_never_touch_czech_scores(full_db):
    import database as db
    db.upsert_listing(make_listing("cz1", market="cz", currency="CZK", district="Žilina",
                                   price_eur=3_000_000.0, url="https://x/l/cz1"))
    r = fin.analyse(3_000_000, 55, "Praha 2", listing_id="cz1", rent_override=20_000, market="cz")
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    db.upsert_cashflow(row)
    for i in range(6):
        db.upsert_rental(_rental(i, "žilina", 900, size=55, market="sk"))
    rent_comps.rebuild_rent_comps()
    conn = full_db()
    assert conn.execute("SELECT COUNT(*) FROM cashflow_scores WHERE listing_id='cz1'").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("text,flag", [
    ("Pronájem bytu 2+kk, nájem včetně energií", True), ("Nájem 15 000 Kč vč. poplatků", True),
    ("Nájem 15 000 Kč + energie", False)])
def test_energies(text, flag):
    assert rent_comps_cz.energies_included(text) is flag


@pytest.mark.parametrize("text,kind", [
    ("Byt je nezařízený", "unfurnished"), ("částečně zařízený byt", "semi"),
    ("Byt je kompletně zařízený", "furnished"), ("Pronájem bytu", "unknown")])
def test_furnishing(text, kind):
    assert rent_comps_cz.furnishing_from_text(text) == kind


# ── Rentals ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,rent", [
    ("15 000 Kč", 15_000), ("15 000 Kč/měsíc + poplatky 3 500 Kč", 15_000),
    ("kauce 30 000 Kč, nájem 14 500 Kč měsíčně", 14_500),
    ("Nájemné 18 000 Kč za měsíc, 320 Kč/m2", 18_000), ("vratná kauce 25 000 Kč", 0),
    ("cena dohodou", 0)])
def test_rent_from_text(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


BAZOS_RENTALS = ("<html>"
                 '<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
                 '<a href="/inzerat/201/a.php">Pronájem bytu 2+kk 50 m2</a></div>'
                 '<div class="inzeratycena"><b>16 500 Kč</b></div>'
                 '<div class="inzeratylok">Brno<br>602 00</div></div>'
                 '<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
                 '<a href="/inzerat/202/b.php">Pronájem pokoje 15 m2</a></div>'
                 '<div class="inzeratycena"><b>6 000 Kč</b></div>'
                 '<div class="inzeratylok">Praha<br>110 00</div></div>'
                 '<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
                 '<a href="/inzerat/203/c.php">Byt 1+1 40 m2 k pronájmu</a></div>'
                 '<div class="inzeratycena"><b>Dohodou</b></div>'
                 '<div class="inzeratylok">Kladno<br>272 01</div></div>'
                 "</html>")


def test_bazos_rental_cards():
    (rec,) = rentals_cz.parse_bazos_page(BAZOS_RENTALS, NOW)   # a room; no rent
    assert rec["rent_eur"] == 16_500 and rec["size_m2"] == 50
    assert rec["district"] == "Brno" and rec["rent_key"] == "brno"
    assert rec["market"] == "cz" and rec["currency"] == "CZK"


def test_bezrealitky_rental_advert():
    advert = {"id": "5", "offerType": "PRONAJEM", "estateType": "BYT", "price": 22_000,
              "surface": 55, "disposition": "DISP_2_KK", "city": "Praha",
              "cityDistrict": "Praha 7", "description": "Nezařízený byt"}
    rec = rentals_cz.rental_from_advert(advert, "https://www.bezrealitky.cz/nemovitosti-byty-"
                                                "domy/5-nabidka-pronajem-bytu-x-praha", NOW)
    assert rec["rent_eur"] == 22_000 and rec["rent_key"] == "praha 7"
    assert rec["furnished"] == "unfurnished"
    assert rentals_cz.rental_from_advert({**advert, "offerType": "PRODEJ"}, "u", NOW) is None


def test_the_rentals_step_fails_soft(monkeypatch, full_db):
    import scraper.cz_common as cz
    monkeypatch.setattr(cz, "_robots_cache", {"https://reality.bazos.cz": cz.Robots(
        "User-agent: *\nDisallow: /\n"), "https://www.bezrealitky.cz": cz.Robots(
        "User-agent: *\nDisallow: /\n")})
    out = rentals_cz.run(max_pages=1)
    assert out["bazos_cz"] == 0 and out["bezrealitky"] == 0 and out["keys"] == 0


# ── Place names ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,forms", [
    ("Praha", ["praze"]), ("Brno", ["brně"]), ("Ostrava", ["ostravě"]),
    ("Plzeň", ["plzni"]), ("Pardubice", ["pardubicích"]), ("Zlín", ["zlíně"]),
    ("Hradec Králové", ["hradci králové"]), ("Ústí nad Labem", ["ústí nad labem"]),
    ("České Budějovice", ["českých budějovicích"]), ("Karlovy Vary", ["karlových varech"]),
    ("Mladá Boleslav", ["mladé boleslavi"]), ("Frýdek-Místek", ["frýdku-místku"]),
    ("Liberec", ["liberci"]), ("Písek", ["písku"]), ("Kladno", ["kladně"]),
    ("Blansko", ["blansku"]), ("Třebíč", ["třebíči"]), ("Jindřichův Hradec", ["jindřichově hradci"]),
    ("Uherské Hradiště", ["uherském hradišti"]), ("Líšeň", ["líšni"]), ("Praha 2", ["praze 2"]),
])
def test_czech_locatives(name, forms):
    assert czech_cases.locative_phrases(name) == forms


@pytest.mark.parametrize("text,place", [
    ("Pronájem bytu 2+kk v Praze 2 - Vinohradech", "Praha 2"),
    ("Prodám byt ve Zlíně", "Zlín"), ("Prodej bytu v Brně na Žabovřeskách", "Brno - Žabovřesky"),
    ("Byt v Českých Budějovicích", "České Budějovice"), ("PRODEJ BYTU KLADNO", "Kladno"),
    ("20 min do Prahy, byt v Berouně", "Beroun"), ("Hezký byt, Ostrava-Poruba", "Ostrava"),
    ("Prodej, most přes Vltavu", ""), ("byt na Kladně", "Kladno"),
])
def test_place_from_text(text, place):
    assert place_from_text(text) == place


# ── Flood and noise ───────────────────────────────────────────────────────────
class _R:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def test_czech_flood(monkeypatch):
    from modules import risk_data_cz as rd
    monkeypatch.setattr(rd, "_layers_checked", {})
    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(url)
        if url.endswith("/82"):
            return _R({"name": "T0601 Záplavová území Q100 a QA", "geometryType": "esriGeometryPolygon"})
        return _R({"results": [{"layerName": "Q100"}]})
    monkeypatch.setattr(rd.requests, "get", fake_get)
    hit, detail = rd.check_flood(50.08, 14.42)
    assert hit is True and "indicative" in detail and calls[-1].endswith("/identify")
    assert rd.classify_flood({"results": []})[0] is False
    assert rd.classify_flood({"error": {}})[0] is None
    # A line layer can't answer "outside": unknown instead.
    monkeypatch.setattr(rd, "_layers_checked", {})
    monkeypatch.setattr(rd.requests, "get", lambda *a, **k: _R(
        {"name": "x", "geometryType": "esriGeometryPolyline"}))
    assert rd.check_flood(50.0, 14.0)[0] is None


@pytest.mark.parametrize("payload,db,flag", [
    ({"value": "70"}, 70.0, True), ({"value": "60"}, 60.0, False),
    ({"value": "NoData"}, None, False), ({"value": "3"}, None, False)])
def test_czech_noise_map(monkeypatch, payload, db, flag):
    from modules import risk_data_cz as rd
    assert rd.noise_db(payload) == db
    monkeypatch.setattr(rd.requests, "get", lambda *a, **k: _R(payload))
    out = rd.refine_noise(50.0, 14.0, {})
    assert bool(out.get("noise")) is flag


def test_assess_uses_the_czech_maps(monkeypatch):
    from modules import risk_data, risk_data_cz
    monkeypatch.setattr(risk_data_cz, "check_flood", lambda lat, lng: (True, "inside (CZ)"))
    monkeypatch.setattr(risk_data_cz, "refine_noise", lambda lat, lng, out: {
        "noise": True, "noise_detail": "70+ dB"})
    monkeypatch.setattr(risk_data, "check_flood", lambda lat, lng: pytest.fail("SK map on CZ"))
    out = risk_data.assess(50.0, 14.0, "address", osm_elements=[], market="cz")
    assert out["flood"] is True and out["noise"] is True and out["noise_detail"] == "70+ dB"


# ── Contract draft and memo ──────────────────────────────────────────────────
def _cz_listing(**over):
    r = fin.analyse(4_500_000, 55, "Praha 2", listing_id="cz1", rent_override=22_000, market="cz")
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    return {**row, "id": "cz1", "title": "Prodej bytu 2+kk 55 m²", "district": "Praha 2",
            "price_eur": 4_500_000, "size_m2": 55.0, "market": "cz", "currency": "CZK",
            "url": "https://x/cz1", "source": "bezrealitky", "lv_status": "UNVERIFIED",
            "estimated_rent_eur": 22_000, "rent_key": "praha", "rent_source": "baseline", **over}


def test_the_czech_contract_draft():
    from datetime import datetime
    from modules.contract_draft_cz import build_contract_draft_cz, build_internal_analysis_cz
    l = _cz_listing(lv_number="1234", cadastral_area="Vinohrady")
    d = build_contract_draft_cz(l, buyer_name="Kupující Testovací", agreed_price=4_400_000,
                                deposit=50_000, generated_at=datetime(2026, 10, 16, 12, 0))
    assert "KUPNÍ SMLOUVA — NÁVRH" in d and "není právní rada" in d
    nb = "\u00a0"
    assert f"4{nb}400{nb}000{nb}Kč" in d and f"4{nb}350{nb}000{nb}Kč" in d and "€" not in d
    assert "č. 1234" in d and "Vinohrady" in d and "[Doplnit]" in d
    assert "§ 2079" in d and "256/2013" in d and "úschov" in d
    a = build_internal_analysis_cz(l, agreed_price=4_400_000)
    assert "NEPOSÍLAT ADVOKÁTOVI" in a and "Kč" in a
    assert "Přebytek" not in d                     # the numbers stay out of the draft


def test_the_czech_memo(monkeypatch):
    from modules import memo
    seen = []
    orig = memo._Memo.txt
    monkeypatch.setattr(memo._Memo, "txt", lambda self, s: (seen.append(str(s)), orig(self, s))[1])
    pdf = memo.build_memo_pdf(_cz_listing())
    assert pdf[:4] == b"%PDF"
    text = "\n".join(seen)
    nb = "\u00a0"
    assert f"4{nb}500{nb}000{nb}Kč" in text and "SVJ (fond oprav + správa)" in text
    assert "Kč / month" in text and "daňový poradce" in text and "Deloitte" in text
    assert "€" not in text
