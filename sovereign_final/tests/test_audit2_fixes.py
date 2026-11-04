"""Regression tests for the second review of the whole app (both markets):
one or more per finding, on synthetic text and synthetic listings only — no
real výpis, no personal data, no request leaves the test."""

import dataclasses
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup

from engine import financial as fin
from engine import regional_prices as rp
from engine import regional_prices_cz as rpcz
from engine import rent_comps, rent_comps_cz, rent_cz
from modules import lv_cz
from modules.debt_bot import _parse_lv
from modules.lv_screen_cz import owner_is_cooperative, unrecognised_entries
from scraper import bazos_cz, rentals, rentals_cz
from scraper import cz_common as cz
from scraper.textparse import bazos_title_link, rooms_from_title
from tests.conftest import make_listing
from tests.test_lv_cz import BANK_LIEN, C, D, E, HEAD, lv

PRIVATE_LIEN = ("  o Zástavní právo smluvní\n      Oprávnění pro Osoba Testovací, Testov, "
                "RČ/IČO: 000000/0000\n")


def status(text, lv_number="1234", area="", **kw):
    return lv_cz.check_text(text, lv_number, area, **kw)["status"]


def kb_lien(claim="pohledávka ve výši 2 400 000 Kč"):
    return ("  o Zástavní právo smluvní\n      " + claim + "\n"
            "      Oprávnění pro Komerční banka, a.s., Na Příkopě 33, Praha 1, RČ/IČO: 0\n"
            "      Povinnost k Jednotka: č. 101/5\n"
            "      Listina Smlouva o zřízení zástavního práva podle obč.z. ze dne "
            "01.01.2020 V-1234/2020-101\n")


# ── Czech LV: what may and may not clear a title ──────────────────────────────
def test_page_one_of_two_is_never_clean():
    whole = lv(kb_lien(), "  o Zahájení exekuce\n")
    assert status(whole) == "REJECT"
    page1 = whole.split("D Poznámky")[0]
    assert status(page1) == "UNVERIFIED"
    assert status(HEAD + C) == "UNVERIFIED"
    from modules.llm_enrichment import lv_text_for_claude
    assert lv_text_for_claude(page1, market="cz")[1] is False
    assert lv_text_for_claude(whole, market="cz")[1] is True


BUILDING_LV = ("Výpis z katastru nemovitostí\n"
               "Kat.území: 727181 Vinohrady    List vlastnictví: 777\n"
               "A Vlastník, jiný oprávněný\n  Společenství vlastníků\n"
               "B Nemovitosti\n  Parcela 2345/1 zastavěná plocha a nádvoří\n"
               "  Součástí je stavba: Vinohrady, č.p. 1234, bytový dům\n"
               + C + "  Bez zápisu\n" + D + "  Bez zápisu\n" + E)


def test_the_buildings_lv_never_clears_a_flat():
    assert status(BUILDING_LV, None, building_lv="777") == "UNVERIFIED"
    assert status(BUILDING_LV, "777", building_lv="777") == "UNVERIFIED"
    assert status(BUILDING_LV, None) == "UNVERIFIED"         # no unit in part B
    assert status(lv()) == "PASS"


def test_check_listing_passes_the_building_lv(full_db):
    import database as db
    db.upsert_listing(make_listing("cz7", market="cz", currency="CZK",
                                   description="Vlastnictví: osobní."))
    conn = db.get_conn()
    try:
        conn.execute("UPDATE listings SET plot_lv_number='777' WHERE id='cz7'")
        conn.commit()
    finally:
        conn.close()
    db.set_lv_document("cz7", BUILDING_LV)
    r = lv_cz.check_listing(db.get_lv_row("cz7"))
    assert r["status"] == "UNVERIFIED" and "building" in r["detail"]


@pytest.mark.parametrize("kind", ["Služebnost bytu", "Věcné břemeno užívání",
                                  "Věcné břemeno bytu", "Věcné břemeno (podle listiny)"])
@pytest.mark.parametrize("holder", ["Kabelková Marie, Husitská 1, Žižkov",
                                    "Nováková Marie, Plynární 1096/23, Holešovice",
                                    "Nováková Marie, Elektrárenská 5, Michle"])
def test_a_right_to_live_in_the_flat_is_never_a_utility_line(kind, holder):
    entry = (f"  o {kind}\n      Oprávnění pro\n      {holder}\n      Povinnost k\n"
             f"      Jednotka: 101/5\n      Listina Smlouva darovací V-77/2015-101\n")
    assert status(lv(entry)) == "REJECT"


def test_a_utility_easement_is_still_soft():
    util = ("  o Věcné břemeno vedení a údržby kabelového vedení\n"
            "      Oprávnění pro ČEZ Distribuce, a.s., Teplická 874/8, Děčín\n"
            "      Povinnost k Parcela 2345/1\n"
            "      Listina Smlouva o zřízení věcného břemene V-5/2010-101\n")
    assert status(lv(util)) == "PASS"


@pytest.mark.parametrize("address,want", [("Hlavná 7, Bratislava", "REJECT"),
                                          ("Plynárenská 7, Bratislava", "REJECT"),
                                          ("Kabelova 2, Nitra", "REJECT")])
def test_slovak_residence_right_is_never_a_utility_line(address, want):
    text = (f"ČASŤ C: ŤARCHY\n1 Vecné bremeno in personam v prospech Jana Nováková, "
            f"{address} podľa V 512/2019")
    assert _parse_lv(text)["status"] == want
    utility = ("ČASŤ C: ŤARCHY\n1 Vecné bremeno v prospech Západoslovenská distribučná, "
               "a.s. - právo uloženia elektrického vedenia podľa V 512/2019")
    assert _parse_lv(utility)["status"] == "PASS"


def test_a_bank_mortgage_with_a_long_claim_line_or_a_page_break_passes():
    long = ("pohledávka ve výši 2 400 000 Kč s příslušenstvím a budoucí pohledávky do "
            "výše 2 600 000 Kč vzniklé do 31.12.2055")
    assert status(lv(kb_lien(long))) == "PASS"
    private = kb_lien(long).replace("Komerční banka, a.s., Na Příkopě 33, Praha 1",
                                    "Osoba Testovací, Testov")
    assert status(lv(private)) == "REJECT"
    footer = ("Nemovitosti jsou v územním obvodu, ve kterém vykonává státní správu katastru "
              "nemovitostí ČR Katastrální úřad pro hlavní město Prahu\nstrana 1\n"
              "VÝPIS Z KATASTRU NEMOVITOSTÍ\n")
    lines = kb_lien().splitlines(True)
    for i in range(1, len(lines)):
        assert status(lv("".join(lines[:i]) + footer + "".join(lines[i:]))) == "PASS", i
    wrapped = kb_lien().replace("Listina Smlouva o zřízení zástavního práva",
                                "Listina Smlouva o úvěru a o zřízení\n      zástavního práva")
    assert status(lv(wrapped)) == "PASS"


def test_an_amended_bank_mortgage_passes():
    amended = BANK_LIEN.replace(
        "V-1234/2020-101\n", "V-1234/2020-101\n      Listina Smlouva o změně zástavního "
        "práva ze dne 01.03.2015. V-5678/2015-101\n")
    assert status(lv(amended)) == "PASS"
    # A lien after another entry's "Listina … smlouva" is still a new lien.
    after = ("  o Předkupní právo\n      Oprávnění pro Město Testov\n"
             "      Listina Kupní smlouva V-2/2020-101\n" + PRIVATE_LIEN)
    assert status(lv(after)) == "REJECT"


@pytest.mark.parametrize("text,coop", [
    ("Prodej bytu 2+1 v osobním vlastnictví, ulice Družstevní, Hradec Králové", False),
    ("Byt 3+1, OV, Praha 4 - Nusle, Družstevní ochoz", False),
    ("Byt v OV, nikoliv družstevní", False), ("Byt v OV, ne družstevní", False),
    ("Družstevní 1234/5, Kladno", False),
    ("Vlastnictví: osobní. Byt na ulici Družstevní, družstevní kdysi", False),
    ("Vlastnictví: družstevní. Byt 2+1", True),
    ("Prodej bytu 2+1 (družstevní)", True),
    ("Převod členských práv a povinností v družstvu", True),
])
def test_cooperative_wording_and_street_names(text, coop):
    assert lv_cz.is_cooperative(text) is coop


def test_an_owner_on_a_druzstvo_street_is_no_cooperative(full_db):
    import database as db
    owner = lambda t: t.replace("Vlastník Testovací, Testovací 1, Testov",  # noqa: E731
                                "Nováková Eva, U Družstva Ideál 1234/5, 14000 Praha 4")
    assert not owner_is_cooperative(owner(lv()))
    assert owner_is_cooperative(lv().replace("Vlastník Testovací", "Bytové družstvo Testov"))
    db.upsert_listing(make_listing("cz6", market="cz", currency="CZK", description="Byt v OV."))
    db.set_lv_document("cz6", owner(lv(BANK_LIEN)))
    assert lv_cz.check_listing(db.get_lv_row("cz6"))["status"] == "PASS"
    db.set_lv_document("cz6", owner(lv(PRIVATE_LIEN)))
    assert lv_cz.check_listing(db.get_lv_row("cz6"))["status"] == "REJECT"


@pytest.mark.parametrize("sep", ["\xa0", " ", " - "])
def test_the_ku_header_with_odd_spaces_is_read(sep):
    head = HEAD.replace("Katastrální území: Testov",
                        f"Kat.území:{sep}727181{sep}Nové Město    List vlastnictví: 1234\n"
                        "V kat. území jsou pozemky vedeny v jedné číselné řadě")
    text = lv(BANK_LIEN, head=head)
    assert status(text, "1234", "Nové Město") == "PASS"
    assert status(lv(BANK_LIEN, "  o Zahájení exekuce\n", head=head), "1234", "Nové Město") \
        == "REJECT"


def test_the_standard_ku_line_is_no_ku():
    from modules.lv_screen_cz import ku_in
    assert ku_in("V kat. území jsou pozemky vedeny v jedné číselné řadě") is None


@pytest.mark.parametrize("bullet", ["○ ", " ", "· ", "- ", "* ", "O ", "", "o\n  ",
                                    "o\xa0"])
def test_an_unknown_entry_is_found_without_its_bullet(bullet):
    entry = (f"  {bullet}Reálné břemeno\n      Oprávnění pro Novák Petr\n"
             f"      Povinnost k Jednotka: 101/5\n      Listina Smlouva V-88/2018-101\n")
    assert unrecognised_entries(lv(entry)) == ["Reálné břemeno"]
    assert status(lv(entry)) == "UNVERIFIED"


def test_an_unknown_part_d_entry_after_a_bank_lien():
    d = ("  Omezení převodu nemovitostí\n      Povinnost k Jednotka: 101/5\n"
         "      Listina Rozhodnutí V-9/2019-101\n")
    assert status(lv(BANK_LIEN, d)) == "UNVERIFIED"
    assert unrecognised_entries(lv(BANK_LIEN)) == []
    assert unrecognised_entries(lv(BANK_LIEN.replace("  o ", "  "))) == []


def test_an_old_vypis_never_clears_a_title():
    def dated(d):
        return lv(BANK_LIEN, head=HEAD.replace(
            "LIST VLASTNICTVÍ: 1234",
            f"prokazující stav evidovaný k datu {d:%d.%m.%Y} 08:00:00\nLIST VLASTNICTVÍ: 1234"))
    r = lv_cz.check_text(dated(date(2018, 10, 15)), "1234")
    assert r["status"] == "UNVERIFIED" and "15.10.2018" in r["detail"]
    fresh = date.today() - timedelta(days=3)
    r = lv_cz.check_text(dated(fresh), "1234")
    assert r["status"] == "PASS" and f"{fresh:%d.%m.%Y}" in r["detail"]
    assert status(lv(PRIVATE_LIEN).replace("LIST VLASTNICTVÍ", "stav evidovaný k datu "
                                           "01.01.2015\nLIST VLASTNICTVÍ")) == "REJECT"


# ── Czech listings and rentals ────────────────────────────────────────────────
@pytest.mark.parametrize("title,excluded", [
    ("Prodej 5+kk rodinného domu, Kolín", True), ("Prodej 3+kk chaty, Lipno", True),
    ("Prodej 6+1 vily, Brno", True), ("Prodej 2+kk kanceláře", True),
    ("https://reality.bazos.cz/inzerat/1/prodej-5kk-rodinneho-domu-kolin.php", True),
    ("Prodej 2+kk s garáží, Praha 5", False), ("Prodej 3+1 s pozemkem", False),
    ("Prodej bytu 1+kk, Hotelová, Ostrava", False),
    ("https://reality.idnes.cz/detail/prodej/byt/ostrava-hrabuvka-hotelova/abc/", False),
    ("Prodej bytu 3+1, Penzionová, Praha", False),
    ("Prodej apartmánu v hotelu", True), ("Prodej bytu 2+1 v hotelovém domě", True),
])
def test_houses_and_hotel_streets(title, excluded):
    assert cz.is_excluded_cz(title) is excluded


@pytest.mark.parametrize("text,rent", [
    ("Nájem 15 000 Kč/měs. Kauce 30 000 Kč.", 15_000),
    ("Nájemné 15 000 Kč měsíčně. Služby 3 000 Kč.", 15_000),
    ("Cena 15 000 Kč/měs. Energie dle spotřeby.", 15_000),
    ("Nájem bez energií 14 000 Kč", 14_000),
    ("Nájem bez energií 14 000 Kč, energie cca 2 500 Kč, celkem 16 500 Kč", 14_000),
    ("Nájemné 15 000 Kč měsíčně. Kauce 30 000 Kč. Provize RK 15 000 Kč. "
     "Celkem k úhradě 60 000 Kč", 15_000),
    ("Nájem 15 000 Kč, 4 500 Kč/měs. energie", 15_000),
    ("15 000 Kč/měsíc + poplatky 3 500 Kč", 15_000),
])
def test_rent_wordings(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


@pytest.mark.parametrize("text,whole_flat", [
    ("Pronajmu pokoj v Brně", False), ("Nabízím k pronájmu pokoj 18 m²", False),
    ("Pronájem 1 pokoje v bytě 3+1", False), ("Pronájem samostatného pokoje", False),
    ("Podnajmu pokoj v Praze 4", False), ("Pronajmeme pokoj ve 3+1", False),
    ("Pronajmu byt 2+1, velký pokoj", True), ("Pronajmu byt s obývacím pokojem", True),
    ("Pronájem bytu 1+kk, pokoj 20 m2", True),
])
def test_room_lets_in_verb_form(text, whole_flat):
    assert rent_comps_cz.is_long_term_flat(text) is whole_flat


# A Bazoš card as the site lays it out: the photo link first, the title in h2.
def _real_bazos_card(n, title, desc, price, place, tld="cz"):
    return (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="/inzerat/{n}/x.php"><img class="obrazek" src="x.jpg" alt="{title}"></a>'
            f'<h2 class="nadpis"><a href="/inzerat/{n}/x.php">{title}</a></h2>'
            f'<div class="popis">{desc}</div></div>'
            f'<div class="inzeratycena"><b>{price}</b></div>'
            f'<div class="inzeratylok">{place}</div></div>')


def test_bazos_cards_take_the_title_not_the_photo():
    card = BeautifulSoup(_real_bazos_card(1, "Byt 2+1, 56 m2", "x", "1 Kč", "Kladno"),
                         "html.parser")
    assert bazos_title_link(card).get_text(strip=True) == "Byt 2+1, 56 m2"
    page = ("<html>" + _real_bazos_card(111, "Byt 2+1, 56 m2", "Prodám byt 2+1, ideální na "
                                        "pronájem.", "2 890 000 Kč", "Kladno<br>272 01")
            + "</html>")
    (rec,) = bazos_cz.parse_page(page)
    assert rec["title"] == "Byt 2+1, 56 m2" and rec["price_eur"] == 2_890_000
    room = ("<html>" + _real_bazos_card(5, "Pokoj 18 m2 Praha 3 - Žižkov", "Pokoj v bytě.",
                                        "7 500 Kč", "Praha 3<br>130 00") + "</html>")
    assert rentals_cz.parse_bazos_page(room) == []
    sk_room = ("<html>" + _real_bazos_card(6, "Izba v Petržalke", "Izba 15 m2.", "300 €",
                                           "Bratislava<br>851 01") + "</html>")
    assert rentals.parse_bazos_page(sk_room) == []


def test_the_warmup_skips_a_homepage_robots_disallows(monkeypatch):
    monkeypatch.setattr(cz, "_robots_cache", {
        "https://reality.idnes.cz": cz.Robots("User-agent: *\nDisallow: /\nAllow: /s/\n"),
        "https://reality.bazos.cz": cz.Robots("User-agent: *\nDisallow: /x\n")})
    assert cz.warmup_url("https://reality.idnes.cz") is None
    assert cz.warmup_url("https://reality.bazos.cz") == "https://reality.bazos.cz"


def test_a_headerless_obce_csv_keeps_its_first_town(tmp_path, monkeypatch):
    f = tmp_path / "cz_obce.csv"
    f.write_text("Abertamy\nAdamov\nŘíčany\n", encoding="utf-8")
    monkeypatch.setattr(cz, "CZ_OBCE_CSV", str(f))
    monkeypatch.setattr(cz, "_places", None)
    assert cz._load_obce() == ["Abertamy", "Adamov", "Říčany"]
    assert cz.place_from_text("Prodej bytu 2+kk, Abertamy") == "Abertamy"
    f.write_text("nazev,kod\nAbertamy,1\n", encoding="utf-8")
    assert cz._load_obce() == ["Abertamy"]
    monkeypatch.setattr(cz, "_places", None)


# ── Czech money ───────────────────────────────────────────────────────────────
@pytest.fixture
def no_medians(monkeypatch):
    for table in ("KRAJ_MEDIAN", "OKRES_MEDIAN", "PRAHA_DISTRICT_MEDIAN",
                  "BRNO_DISTRICT_MEDIAN", "MEDIAN_SOURCE"):
        monkeypatch.setattr(rpcz, table, {})
    monkeypatch.setattr(rpcz, "_TABLES", {"kraj": rpcz.KRAJ_MEDIAN, "okres": rpcz.OKRES_MEDIAN,
                                          "praha": rpcz.PRAHA_DISTRICT_MEDIAN,
                                          "brno": rpcz.BRNO_DISTRICT_MEDIAN})
    monkeypatch.setattr(rpcz, "SOURCE", dict(rpcz._DEFAULT_SOURCE))


def test_a_thousands_comma_in_the_medians_csv_is_skipped(tmp_path, no_medians):
    f = tmp_path / "m.csv"
    f.write_text('level,name,median_czk_m2,period,source\n'
                 'okres,Ostrava-město,"62,500",2026,test\n'
                 'okres,Kladno,62,500,2026\n'
                 'okres,Most,117\xa0223,2026,test\n'
                 'okres,Děčín,"70 000,5",2026,test\n'
                 'okres,Kolín,12,2026,test\n', encoding="utf-8")
    assert rpcz.load_medians(str(f)) == 2
    assert rpcz.OKRES_MEDIAN == {"Most": 117223.0, "Děčín": 70000.5}
    assert not rp.is_above_regional_ceiling(2_800_000, 60, "Ostrava", market="cz")


def test_a_town_named_after_another_okres_town(tmp_path, no_medians):
    f = tmp_path / "m.csv"
    f.write_text("level,name,median_czk_m2,period,source\n"
                 "okres,Benešov,62000,2026,test\nokres,Děčín,30000,2026,test\n",
                 encoding="utf-8")
    rpcz.load_medians(str(f))
    assert rpcz.okres_for_district("Benešov nad Ploučnicí") is None
    assert rpcz.okres_for_district("Benešov nad Ploučnicí, okres Děčín") == "Děčín"
    assert rpcz.okres_for_district("Teplice nad Metují") is None
    assert rpcz.okres_for_district("Benešov") == "Benešov"
    assert rpcz.okres_for_district("Ústí nad Labem") == "Ústí nad Labem"
    r = fin.analyse(2_400_000, 60, "Benešov nad Ploučnicí", rent_override=12_000, market="cz")
    assert r.classification != "GREEN"


@pytest.mark.parametrize("text,included", [
    ("Nájem 18 000 Kč vč. záloh", True), ("Cena 19 500 Kč včetně záloh na služby", True),
    ("Nájem 15 000 Kč s poplatky", True), ("16 000 Kč vč. inkasa", True),
    ("17 000 Kč i se zálohami", True), ("vč.poplatků", True),
    ("Nájem 15 000 Kč + energie", False), ("Nájem 15 000 Kč + zálohy 3 500 Kč", False),
    ("kauce 30 000 Kč, zálohy na energie 2 000 Kč", False),
])
def test_rent_including_advances(text, included):
    assert rent_comps_cz.energies_included(text) is included


def test_slovak_rent_including_advances():
    assert rent_comps.energies_included("Nájom 700 € vrátane záloh na energie")
    assert rent_comps.energies_included("Nájom 700 € so zálohami")
    assert not rent_comps.energies_included("Nájom 700 € + zálohy 150 €")


def test_the_sro_setup_cost_is_paid_in_year_zero():
    import markets
    sk = fin.project_irr(120_000, 60, "Nitra", structure="SRO", rent=650, ltv=0.8)
    from config import SRO_LTV_RATIO, ACQUISITION_COST_RATE, SRO_SETUP_COST
    assert sk.cash_flows[0] == pytest.approx(
        -(120_000 * (1 - SRO_LTV_RATIO) + 120_000 * ACQUISITION_COST_RATE + SRO_SETUP_COST))
    personal = fin.project_irr(120_000, 60, "Nitra", structure="PERSONAL", rent=650, ltv=0.8)
    assert personal.cash_flows[0] == pytest.approx(
        -(120_000 * 0.2 + 120_000 * ACQUISITION_COST_RATE))
    cz_sro = fin.project_irr(2_800_000, 60, "Ostrava", structure="SRO", rent=15_000,
                             market="cz")
    prof = markets.get("cz")
    assert cz_sro.cash_flows[0] == pytest.approx(
        -(2_800_000 * (1 - prof.sro_ltv_ratio) + fin.acquisition_costs(2_800_000, market="cz")
          + prof.sro_setup_cost))


@pytest.mark.parametrize("district,key", [
    ("Plzeň 2-Slovany", "plzeň"), ("Plzeň-Slovany", "plzeň"),
    ("Liberec XIV-Kunratice", "liberec"), ("Olomouc-Nová Ulice", "olomouc"),
    ("Zlín-Malenovice", "zlín"), ("Frýdek-Místek", "frýdek-místek"),
    ("Brno-střed", "brno"), ("Praha-východ", "praha-východ"),
])
def test_a_city_part_joined_by_a_hyphen_is_its_towns(district, key):
    assert rent_cz.match_rent_key(district) == key


def test_a_hyphenated_part_reaches_its_towns_live_rate():
    assert fin.base_rent_rate("Plzeň 2-Slovany", {"plzeň": 280.0}, market="cz") == \
        (280.0, "plzeň", "live")


# ── Slovak engine ─────────────────────────────────────────────────────────────
def _dup_rows(*rows):
    from engine.duplicates import group_duplicates
    base = {"rooms": None, "floor": None, "scraped_at": "2026-09-01", "lv_status": "PENDING"}
    return group_duplicates([{**base, "id": r[0], "url": f"u{r[0]}", "district": r[1],
                              "size_m2": r[2], "price_eur": r[3], **(r[4] if len(r) > 4 else {})}
                             for r in rows])


def test_different_towns_in_one_kraj_are_different_flats():
    assert _dup_rows(("a", "Prievidza", 62, 105_000), ("b", "Handlová", 62, 103_000)) == {}
    assert _dup_rows(("a", "Šamorín", 60, 150_000), ("b", "Sereď", 60.5, 148_000)) == {}
    assert _dup_rows(("a", "Praha 4", 55, 7_490_000, {"market": "cz"}),
                     ("b", "Praha 10", 55.5, 7_350_000, {"market": "cz"})) == {}
    same = _dup_rows(("a", "Prievidza", 62, 105_000), ("b", "Prievidza", 62, 104_000))
    assert set(same) == {"a", "b"} and len(set(same.values())) == 1


def test_kosice_okolie_is_not_kosice():
    assert rp.median_source("Košice-okolie")[0] == 2682
    assert rp.median_source("Moldava nad Bodvou, Košice-okolie")[0] == 2682
    assert rp.median_source("Košice II")[0] == 3196
    assert rp.kraj_for_district("Košice-okolie") == "KE"


@pytest.mark.parametrize("part", ["Vrakuňa", "Petržalka", "Rača", "Dúbravka", "Karlova Ves",
                                  "Devínska Nová Ves", "Podunajské Biskupice", "Ružinov"])
def test_a_bratislava_part_named_alone_is_bratislavas(part):
    assert rp.median_source(part) == rp.median_source(f"{part}, Bratislava")


def test_ambiguous_city_parts_still_need_bratislava():
    assert rp.median_source("Nové Mesto")[1].startswith("Bratislavský kraj")
    assert rp.median_source("Staré Mesto, Košice")[0] == 3196
    assert rp.median_source("Dúbravka, Michalovce")[0] == 2682
    assert fin.analyse(210_000, 70, "Vrakuňa", rooms=3).classification != "GREEN"


@pytest.mark.parametrize("district", ["Kráľovičove Kračany", "Modrany", "Modra nad Cirochou",
                                      "Nitra nad Ipľom", "Trnava pri Laborci"])
def test_a_village_is_not_the_town_inside_its_name(district):
    assert rp.median_source(district) == (None, "")
    assert rp.kraj_for_district(district) is None


def test_a_price_below_the_sanity_floor_scores_nothing():
    misread = fin.analyse(58_000, 30, "Bratislava - Petržalka", rooms=1)
    genuine = fin.analyse(110_000, 30, "Bratislava - Petržalka", rooms=1)
    row = lambda r: {**fin.result_to_db_dict(r), "energy_class": "C",  # noqa: E731
                     "lv_status": "PENDING"}
    assert fin.compute_deal_score(row(misread)) == (0, "—")
    assert fin.compute_deal_score(row(genuine))[0] > 0


@pytest.mark.parametrize("title,rooms", [
    ("1,5-izb.byt s 6m logiou, komplet.rek, Jaltská", 2), ("Predaj 2,5 izbový byt Košice", 3),
    ("1.5 izb byt", 2), ("4-izbový", 4), ("129 000 €, 3-izbový", 3), ("7-izbový", None),
])
def test_half_rooms(title, rooms):
    assert rooms_from_title(title) == rooms


def test_features_parsed_after_scoring_reach_the_score(full_db):
    import database as db
    from modules.cashflow_runner import run_scoring
    db.upsert_listing(make_listing("sk9", district="Žilina", price_eur=150_000.0,
                                   size_m2=60.0, rooms=2))
    assert run_scoring() == 1
    db.update_description_features("sk9", {"has_parking": 1, "has_balcony": 1,
                                           "furnished": "furnished"})
    assert run_scoring() == 1
    conn = db.get_conn()
    try:
        rent = conn.execute("SELECT estimated_rent_eur FROM cashflow_scores "
                            "WHERE listing_id='sk9'").fetchone()[0]
    finally:
        conn.close()
    assert rent == pytest.approx(fin.get_rent_estimate("Žilina", 60, 2, 1, "furnished", 1))
    db.update_description_features("sk9", {"has_parking": 1, "has_balcony": 1,
                                           "furnished": "furnished"})
    assert run_scoring() == 0                   # the same parse: nothing to redo


def test_scores_follow_the_lending_ltv(full_db, monkeypatch):
    import database as db
    from modules.cashflow_runner import run_scoring
    db.upsert_listing(make_listing("sk8", district="Žilina", price_eur=150_000.0, size_m2=60.0))
    monkeypatch.setattr(fin, "default_ltv", lambda *a, **k: 0.8)
    assert run_scoring() == 1
    monkeypatch.setattr(fin, "default_ltv", lambda *a, **k: 0.7)
    assert run_scoring() == 1
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT ltv_used FROM cashflow_scores "
                            "WHERE listing_id='sk8'").fetchone()[0] == pytest.approx(0.7)
    finally:
        conn.close()
    assert run_scoring() == 0


@pytest.mark.parametrize("text,whole_flat", [
    ("Prenájom 2-izbového bytu, Petržalka. Obývacia izba s kuchyňou, spálňa.", True),
    ("každá izba má balkón", True), ("Prenajmem byt, 3 izby", True),
    ("Izba v Petržalke", False), ("Prenájom izby v Petržalke", False),
    ("Voľná izba v 3-izbovom byte", False), ("Prenajmem izbu v Ružinove", False),
])
def test_slovak_room_lets(text, whole_flat):
    assert rent_comps.is_long_term_flat(text) is whole_flat


@pytest.mark.parametrize("text,kind", [
    ("Byt bez zariadenia, prázdny", "unfurnished"),
    ("prázdny, bez zariadenia. Nové sociálne zariadenie", "unfurnished"),
    ("Byt s novým sociálnym zariadením", "unknown"), ("sanitárne zariadenie", "unknown"),
    ("kompletne zariadený byt", "furnished"), ("nezariadený byt", "unfurnished"),
])
def test_slovak_fittings_are_not_furniture(text, kind):
    assert rent_comps.furnishing_from_text(text) == kind


@pytest.mark.parametrize("district,key", [
    ("Vrakuňa, Bratislava II", "vrakuňa"), ("Ružinov, Bratislava Ii", "ružinov"),
    ("Rača, Bratislava III", "rača"), ("Bratislava II", "bratislava ii"),
    ("Košice II", "košice ii"),
])
def test_a_named_city_part_beats_its_okres(district, key):
    assert fin.match_rent_key(district) == key


# ── Slovak LV: a cut or a non-LV page is never clean ─────────────────────────
def _flat_lv(monkeypatch, text):
    from modules import debt_bot
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv_no: {
        "status": "OK", "detail": "", "lv_text": text, "lv_no": lv_no})
    return debt_bot.check_flat_lv("Petržalka", 4321)


def test_a_cut_slovak_lv_is_never_clean(monkeypatch):
    from kataster_scraper import LV_TEXT_MAX_CHARS
    text = ("ČASŤ B: " + "Novák Ján, Hlavná 1, Bratislava, 1/380 " * 5000)[:LV_TEXT_MAX_CHARS]
    r = _flat_lv(monkeypatch, text)
    assert r["status"] == "UNVERIFIED" and "cut" in r["detail"]


@pytest.mark.parametrize("page", [
    "<h1>Chyba</h1> List vlastníctva č. 99999 v katastrálnom území Petržalka neexistuje.",
    "Služba je momentálne nedostupná z dôvodu údržby. Skúste to neskôr, prosím.",
])
def test_a_slovak_error_page_is_never_clean(monkeypatch, page):
    r = _flat_lv(monkeypatch, page)
    assert r["status"] == "UNVERIFIED" and "part C" in r["detail"]
    assert _flat_lv(monkeypatch, "Výpis z LV 4321. ČASŤ C: ŤARCHY: Bez zápisu.")["status"] \
        == "PASS"


def test_the_model_version_moved():
    assert fin.SCORING_MODEL_VERSION >= 3
    assert dataclasses.is_dataclass(fin.project_irr(120_000, 60, "Nitra"))
