"""Audit 5: what a regression hunt found in the audit-4 changes, each case
reproduced first. Synthetic fixtures only — bank and utility names are
public, every IČO, address and person here is made up.

Slovak cadastre reports reach the screen on ONE line: kataster_scraper
collapses all whitespace. Every Slovak LV text below is written that way,
which is what the audit-4 tests (written with line breaks) missed.
"""
import pytest

from modules import lv_cz
from modules.debt_bot import _parse_lv
from scraper import cz_common, rentals, textparse
from scraper.nehnutelnosti import _detail_district, _extract_location_from_text
from tests.test_lv_cz import BANK_LIEN, lv as cz_lv

# ── Slovak LV, one line as fetch_lv_text gives it ────────────────────────────
SK_HEAD = ("LIST VLASTNÍCTVA č. 4321 ČASŤ A: MAJETKOVÁ PODSTATA Byt č. 12 vchod 1, 4. p. "
           "ČASŤ B: VLASTNÍCI A INÉ OPRÁVNENÉ OSOBY 1 Novák Ján, Hlavná 1, Vzorovo "
           "Spoluvlastnícky podiel: 1/1 Titul nadobudnutia: Kúpna zmluva V 1000/2012 ")
TATRA = "Tatra banka, a.s., IČO 12345678"
SPOR = "Slovenská sporiteľňa, a.s., Testovacia 48, 832 37 Bratislava, IČO: 11223344"
VUB = "Všeobecná úverová banka, a.s., Testovacia 1, 829 90 Bratislava"


def sk(part_c, part_b_note=""):
    return SK_HEAD + part_b_note + "ČASŤ C: ŤARCHY " + part_c


def status(text):
    return _parse_lv(text)["status"]


@pytest.mark.parametrize("part_c", [
    # A private lien does not borrow the next entry's bank …
    "1 V 100/2015 - Záložné právo na zabezpečenie pohľadávky z úveru 2 Zmluva o zriadení "
    "záložného práva v prospech Tatra banka, a.s.",
    "1 V 100/2015 - Záložné právo: Kováč Peter, Hlavná 1, Testov 2 Zmluva o zriadení "
    "záložného práva v prospech Tatra banka, a.s.",
    "1 V 100/2015 - Záložné právo: Kováč Peter, Hlavná 1, Testov 2 P 55/2022 - Poznámka "
    "v prospech Tatra banka, a.s.",
    "1 V 100/2015 - Záložné právo Kováč Peter 2 P 55/2022 - Poznámka v prospech Tatra banka, a.s.",
    # … and a second lien in its own entry is no back-reference to the first.
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s. 2 Zmluva o zriadení záložného "
    "práva pre Kováč Peter",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s. 2 V 200/2021 Zmluva o zriadení "
    "záložného práva pre Kováč Peter",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s. 2 V 200/2016 - zmluva o zriadení "
    "záložného práva pre Kováč Peter",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s. 2. V 200/2016 - zmluva o zriadení "
    "záložného práva pre Kováč Peter",
    "1 Záložné právo v prospech Tatra banka, a.s. V 100/2015 2 Zmluva o zriadení záložného "
    "práva pre Kováč Peter V 200/2016",
])
def test_a_one_line_report_keeps_each_lien_in_its_own_entry(part_c):
    assert status(sk(part_c)) == "REJECT"


@pytest.mark.parametrize("part_c", [
    # The lien's own contract, cited after it, is part of the same entry.
    f"1 V 2797/2013 - Záložné právo v prospech {SPOR} V 2797/2013 - Zmluva o zriadení "
    "záložného práva zo dňa 15.05.2013",
    f"1 V 2797/2013 - Záložné právo v prospech {TATRA} V 2797/2013 - Zmluva o zriadení "
    "záložného práva",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., IČO 12 345 678 V 2797/2013 - "
    "zmluva o zriadení záložného práva",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s. na byt číslo 12 V 2797/2013 - "
    "zmluva o zriadení záložného práva",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., na byt č. 12, vchod 2 "
    "V 2797/2013 - zmluva o zriadení záložného práva",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., Testovacia 3, 811 06 "
    "Bratislava 1 V 2797/2013 - zmluva o zriadení záložného práva",
    f"1 V 2797/2013 - Záložné právo v prospech {VUB} 25 V 2797/2013 - zmluva o zriadení "
    "záložného práva",
    "1 V 2797/2013 - ZÁLOŽNÉ PRÁVO V PROSPECH TATRA BANKA, A.S., IČO 12345678 V 2797/2013 - "
    "ZMLUVA O ZRIADENÍ ZÁLOŽNÉHO PRÁVA",
    # "podľa V … - Zmluva" cites the contract; it opens no entry.
    f"1 Záložné právo v prospech {SPOR} na byt č. 12 podľa V 2797/2013 - Zmluva o zriadení "
    "záložného práva zo dňa 15.05.2013",
    # The bank named after a long claim description still clears its own lien.
    "1 V 2797/2013 - Záložné právo na byt č. 12 a na spoluvlastnícky podiel na spoločných "
    "častiach a zariadeniach domu a na pozemku parc. č. 1234/5 vo veľkosti 5432/100000 "
    f"v prospech {SPOR}",
    "1 V 2797/2013 - Záložné právo na zabezpečenie pohľadávky vo výške 120 000 EUR s "
    "príslušenstvom a budúcich pohľadávok do výšky 50 000 EUR zo zmluvy o úvere č. 123/2013 "
    f"v prospech {SPOR}",
])
def test_a_bank_lien_and_its_own_contract_pass(part_c):
    assert status(sk(part_c)) == "PASS"


@pytest.mark.parametrize("note", [
    "Poznámka: konanie na Okresnom súde Bratislava I o určenie vlastníckeho práva ",
    "Poznámka: začaté konanie sp. zn. 12C/45/2023 o určenie vlastníckeho práva ",
    "Poznámka: spor o určenie vlastníckeho práva k bytu č. 12 ",
    "Poznámka: návrh na určenie vlastníckeho práva podaný na Okresnom súde ",
    "Poznámka: prebieha konanie vedené Okresným súdom vo veci určenia vlastníckeho práva ",
    "Poznámka: konanie č. 12C/45/2023 o určení vlastníckeho práva k bytu ",
    "Poznámka: určenie vlastníckeho práva - konanie prebieha ",
    "Poznámka: začatie konania o neplatnosť kúpnej zmluvy a určenie vlastníckeho práva ",
])
def test_ownership_proceedings_noted_in_part_b_reject(note):
    assert status(sk(f"1 V 100/2015 - Záložné právo v prospech {TATRA} na byt č. 12",
                     part_b_note=note)) == "REJECT"


def test_a_bank_called_sporitelna_is_no_dispute():
    assert status(sk(f"1 V 2797/2013 - Záložné právo v prospech {SPOR} na byt č. 12 "
                     "podľa zmluvy o úvere")) == "PASS"


def test_a_title_won_in_court_still_passes_on_one_line():
    head = SK_HEAD.replace("Kúpna zmluva V 1000/2012",
                           "Rozsudok Okresného súdu Testov o určení vlastníckeho práva 12C/1/2010")
    assert status(head + f"ČASŤ C: ŤARCHY 1 V 100/2015 - Záložné právo v prospech {TATRA}") \
        == "PASS"


@pytest.mark.parametrize("holder", [
    "Západoslovenská distribučná, akciová spoločnosť, Testovacia 6, Bratislava, IČO 12345678",
    "Slovak Telekom, akciová spoločnosť, Testovacia 28, Bratislava, IČO 12345678",
    "Západoslovenská distribučná a.s, Testovacia 6, Bratislava, IČO 12345678",
])
def test_a_utility_with_its_legal_form_written_out_is_soft(holder):
    assert status(sk(f"1 Z 1234/2005 - Vecné bremeno v prospech {holder}")) == "PASS"


# ── Czech výpis ──────────────────────────────────────────────────────────────
def _ease(desc, holder="ČEZ Distribuce, a. s., Testovací 8, Testov, RČ/IČO: 00000000"):
    return (f"  o Věcné břemeno (podle listiny)\n      {desc}\n      Oprávnění pro {holder}\n"
            "      Povinnost k Parcela: 123/4\n"
            "      Listina Smlouva o zřízení věcného břemene V-1234/2015-101\n")


@pytest.mark.parametrize("desc,holder", [
    ("právo zřídit, provozovat a užívat stavbu vodovodní přípojky", None),
    ("právo zřídit, provozovat, udržovat a užívat stavbu distribuční soustavy", None),
    ("právo užívat nemovitost v rozsahu geometrického plánu za účelem umístění plynovodní "
     "přípojky", "Testovací plynárenská, s.r.o., Testovací 1, Testov, RČ/IČO: 00000000"),
])
def test_a_utility_right_to_use_a_structure_is_no_home(desc, holder):
    text = cz_lv(BANK_LIEN + (_ease(desc, holder) if holder else _ease(desc)))
    assert lv_cz.check_text(text, "1234")["status"] == "PASS"


def test_a_persons_right_to_use_the_flat_is_still_hard():
    text = cz_lv(BANK_LIEN + _ease("právo užívat byt č. 101/5 a právo přístupu do sklepa",
                                   "Nováková Marie, Testovací 1, Testov, RČ/IČO: 000000/0000"))
    assert lv_cz.check_text(text, "1234")["status"] == "REJECT"


def test_a_dash_list_of_claims_inside_an_entry_is_no_entry():
    claims = BANK_LIEN.replace(
        "      k zajištění pohledávky ve výši 2 400 000 Kč\n",
        "      k zajištění pohledávek:\n      - Pohledávka z úvěru ve výši 2 400 000 Kč\n"
        "      - Budoucí pohledávky do výše 500 000 Kč\n")
    assert "k zajištění pohledávek:" in claims
    assert lv_cz.check_text(cz_lv(claims), "1234")["status"] == "PASS"


def test_an_unknown_entry_behind_a_dash_is_still_caught():
    text = cz_lv(BANK_LIEN, part_d="  - Nařízení soudního prodeje zástavy\n")
    assert lv_cz.check_text(text, "1234")["status"] == "UNVERIFIED"


def test_a_part_c_heading_with_a_comma_is_no_entry():
    text = cz_lv(BANK_LIEN).replace("v části B včetně", "v části B, včetně")
    assert ", včetně" in text
    assert lv_cz.check_text(text, "1234")["status"] == "PASS"


# ── Slovak listings ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("address,want", [
    ("Hlavná 5, Modra, okres Pezinok", "Modra"),
    ("Štúrova 10, Modra, okres Pezinok, Bratislavský kraj", "Modra"),
    ("Hlavná 5, Stupava, okres Malacky", "Stupava"),
    ("Okres Pezinok, Modra", "Modra"),
    # A village named after a town still takes its own okres.
    ("Martin nad Žitavou, okres Zlaté Moravce", "Zlaté Moravce"),
    ("Valaliky, okres Košice-okolie", "Košice-okolie"),
])
def test_a_town_the_address_names_keeps_its_name(address, want):
    assert _detail_district(address) == want


@pytest.mark.parametrize("title", [
    "Predaj 4-izbovej drevostavby s pozemkom",
    "Predám 5-izbovú drevostavbu so záhradou",
    "Predaj 4-izbovej novostavby s garážou a pozemkom",
    "Predám 4-izbovú radovku s garážou",
    "Predám 3-izbovú usadlosť s pozemkom",
    "Predám 5-izbovú kúriu so záhradou",
    "Predaj 4-izbovej stavby s pozemkom 800 m2",
    # A share of an accessory alone, or of an accessory and the flat.
    "Predaj 1/2 podielu na pivnici",
    "Predaj 1/6 podielu na dvore",
    "Predám 1/8 podiel na parkovacom státí",
    "Predám spoluvlastnícky podiel 1/10 na parkovisku",
    "Predaj podielu 1/2 na parkovacom státí a byte",
    "Predám podiel 1/3 pivnica a byt",
    "Predaj 1/2 podielu na dvore a byte",
])
def test_houses_and_shares_are_no_flat(title):
    assert textparse.is_excluded_listing(title)


@pytest.mark.parametrize("title", [
    "Predám 3-izbový s garážou",
    "Predám 2-izbový, Petržalka, parkovacie státie",
    "Predaj 3-izbového bytu s podielom na garáži",
])
def test_flats_with_their_accessories_are_kept(title):
    assert not textparse.is_excluded_listing(title)


def test_a_house_to_let_is_no_rent_comp():
    assert rentals.build_rental("bazos", "https://x/h1", "Prenájom 4-izbovej drevostavby so "
                                "záhradou", "120 m2, 1 100 € mesačne", location="Senec 903 01") is None


@pytest.mark.parametrize("title,text,location,want", [
    # A bare city part takes only the city that has that part.
    ("Prenájom 2-izbového bytu", "55 m2, 750 € mesačne. Volajte 0905 000 000, Martin",
     "Staré Mesto", "Staré Mesto, Bratislava"),
    ("Prenájom 2-izbového bytu", "55 m2, 750 € mesačne. RK Domov, Nitra", "Staré Mesto",
     "Staré Mesto, Bratislava"),
    ("Prenájom 2-izbového bytu Košice", "55 m2, 750 € mesačne", "Staré Mesto",
     "Staré Mesto, Košice"),
    # A location the matcher can't read: the title may name the town.
    ("Prenájom 2-izbového bytu, Nitra", "55 m2, 600 € mesačne", "Štefánikova trieda 12", "Nitra"),
    ("Prenájom 2-izbového bytu v Žiline", "55 m2, 600 € mesačne", "Slovensko", "Žilina"),
    ("Prenájom 2-izbového bytu Košice", "55 m2, 600 € mesačne", "Kosice 040 01", "Košice"),
])
def test_a_rental_takes_the_town_its_ad_gives(title, text, location, want):
    r = rentals.build_rental("bazos", "https://x/" + location, title, text, location=location)
    assert r and r["district"] == want


def test_a_commuter_sentence_still_names_no_town():
    assert rentals.build_rental("bazos", "https://x/b", "Prenájom 2-izbového bytu",
                                "55 m2, pre pracujúcich v Bratislave. 600 € mesačne",
                                location="Bernolákovo 900 27") is None


@pytest.mark.parametrize("text,want", [
    ("Predám 3-izbový byt. Parkovanie 100 m za 30 € mesačne.", 0.0),
    ("Predám 2-izbový byt. Garáž 50 m za 15 000 € možné dokúpiť.", 0.0),
    ("Predám byt, MHD 150 m za 1,20 € lístok", 0.0),
    ("Prenájom bytu. Terasa 40 m za 600 € mesačne aj s energiami.", 0.0),
    ("Predám byt 58 m za 129 000 €", 58.0),
    ("Byt 65 m2, parkovanie 100 m", 65.0),
    # "with a garden / terrace / garage": the number is the flat's.
    ("Byt so záhradou 72 m, cena 150 000 €", 72.0),
    ("Predám byt s terasou 68 m", 68.0),
    ("Predám byt s garážou 72 m", 72.0),
    ("Záhrada 120 m, byt 3+1 75 m", 75.0),
])
def test_a_parking_garage_stop_or_terrace_size_is_not_the_flats(text, want):
    assert textparse.area_from_text(text) == want


@pytest.mark.parametrize("text,want", [
    ("Predám byt na Petržalka", "Petržalka, Bratislava"),
    ("Prenájom 2i bytu na Martin", "Martin"),
    ("Predaj bytu: Košice, na Ťahanovce", "Ťahanovce, Košice"),
    # A way of getting there makes "na" a direction.
    ("Predaj bytu Bratislava, výhľad na Nové Mesto", "Bratislava"),
    ("Predaj bytu v Bratislave, autobus priamo na Malacky", "Bratislava"),
    ("Ružinov, výjazd na Senec", "Ružinov, Bratislava"),
])
def test_na_is_a_direction_only_after_a_way_there(text, want):
    assert _extract_location_from_text(text) == want


# ── Czech listings ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", [
    "Prodej 5+kk, RD s garáží",
    "Prodám 5+1 - RD se zahradou a garáží",
    "Prodej 4+1, řadový RD, garáž",
    "Prodej 4+kk, novostavba RD, pozemek 600 m2",
    "prodam-4kk-cihlovy-rd-s-pozemkem",
    "Prodej 4+1, domek s pozemkem",
    "Prodej 4+1, samostatně stojící dům s garáží",
    "Prodám 4+1 řadový dům s garáží",
    "Prodej 4+kk (dům), pozemek 900 m2",
    # A share of a basement flat, of a cellar alone, of the land "and the flat".
    "podíl 1/2 na sklepním bytě",
    "1/2 podíl na sklepě",
    "Byt 3+1 - spoluvlastnický podíl 1/2 na pozemku a bytě",
])
def test_czech_houses_and_shares_are_no_flat(title):
    assert cz_common.is_excluded_cz(title)


@pytest.mark.parametrize("title", [
    "Prodej 3+kk, cihlový dům, garáž",
    "Prodej 2+kk, bytový dům s garáží",
    "Prodej 2+1 v RD s pozemkem",
    "Prodej bytu 2+kk, 1/6 podíl na sklepě",
    "Prodej bytu 3+1 se spoluvlastnickým podílem na pozemku",
])
def test_czech_flats_with_their_building_or_shares_are_kept(title):
    assert not cz_common.is_excluded_cz(title)
