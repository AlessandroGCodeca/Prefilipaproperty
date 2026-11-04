"""Czech property tax for every municipality: reading the coefficient
ordinances (scraper/tax_coefficients_cz), combining them as the act says,
storing them (modules/tax_rates_cz) and charging them (engine/property_tax_cz).

The wording below is quoted from real ordinances in sbirkapp.gov.cz, read in
November 2026 (the municipality is named), including the split words and
numbers a Word file leaves ("m ístní", "2 , 6", "č. 11/20 2 4").
"""

from datetime import date

import pytest

from engine import property_tax_cz as ptc
from scraper import tax_coefficients_cz as cz
from tests.conftest import make_listing


# ── The act ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, population, coef", [
    ("Malínky", 300, 1.0), ("Stod", 3_600, 1.4), ("Sedlčany", 7_400, 1.6),
    ("Beroun", 20_000, 2.0), ("Kolín", 33_000, 2.5), ("Třinec", 34_000, 3.5),   # statutory
    ("Luhačovice", 5_000, 3.5),                                                 # spa town
    ("Brno", 404_296, 3.5), ("Praha", 1_397_880, 4.5),
    ("Obec", 1_000, 1.0), ("Obec", 1_001, 1.4),                                 # "do 1000"
])
def test_the_size_coefficient_follows_the_act(name, population, coef):
    assert cz.size_coefficient(name, population) == coef


def test_raising_one_category():
    assert [cz.raised(c) for c in (1.0, 1.4, 3.5, 4.5, 5.0)] == [1.4, 1.6, 4.5, 5.0, 5.0]


@pytest.mark.parametrize("published, effective, year", [
    (date(2025, 9, 8), date(2026, 1, 1), 2026),
    (date(2025, 10, 1), date(2026, 1, 1), 2026),     # published on the last day
    (date(2025, 10, 20), date(2026, 1, 1), 2027),    # § 16a: too late for 2026
    (date(2026, 9, 9), date(2026, 9, 24), 2027),     # in effect mid-year
    (None, date(2025, 1, 1), 2025),
])
def test_the_first_tax_year_an_ordinance_counts_for(published, effective, year):
    assert cz.first_tax_year(published, effective) == year


def test_a_municipalitys_name_and_district_are_split():
    assert cz.split_name("Brno (okr. Brno-město)") == ("Brno", "Brno-město")
    assert cz.split_name("Lhota (okr. Plzeň-jih)") == ("Lhota", "Plzeň-jih")
    assert cz.split_name("Praha") == ("Praha", "")


# ── Reading an ordinance ──────────────────────────────────────────────────────
def test_a_coefficient_for_the_whole_municipality():
    p = cz.parse("Čl. 2 Místní koeficient pro obec Obec Drhovy stanovuje místní koeficient pro "
                 "obec ve výši 1,5. Místní koeficient pro obec se vztahuje na všechny nemovité "
                 "věci na území celé obce Drhovy s výjimkou pozemků. Čl. 3 Účinnost Tato "
                 "vyhláška nabývá účinnosti dnem 1. ledna 2027.")
    assert (p.municipality, p.units, p.areas) == (1.5, None, {})


def test_split_words_and_numbers_are_read():
    # Česká Kamenice: "stanovuje se m ístní koeficient pro město ve výši 2 , 6".
    p = cz.parse("Článek 1 Stanovuje se m ístní koeficient pro město ve výši 2 , 6 . Článek 2")
    assert p.municipality == 2.6


def test_the_coefficient_for_the_group_of_flats():
    # Česká Kamenice / Železná Ruda: a list of groups, flats among them.
    p = cz.parse("Město stanovuje místní koeficient pro jednotlivé skupiny staveb a jednotek dle "
                 "§ 10a odst. 1 zákona, a to v následující výši: rekreační budovy koeficient 5, "
                 "garáže koeficient 3,3, zdanitelné stavby a zdanitelné jednotky pro ostatní druhy "
                 "podnikání koeficient 3, ostatní zdanitelné jednotky koeficient 2,7.")
    assert p.units == 2.7 and p.municipality is None


def test_a_table_by_cadastral_area():
    # Valtice 8/2025.
    p = cz.parse("Čl. 2 Místní koeficient pro jednotlivá katastrální území Město Valtice touto "
                 "vyhláškou stanovuje místní koeficient pro jednotlivá katastrální území: Úvaly u "
                 "Valtic ve výši 1,5 Valtice ve výši 2. Místní koeficient pro jednotlivá "
                 "katastrální území se vztahuje na všechny nemovité věci na území daného "
                 "katastrálního území s výjimkou pozemků zařazených do skupiny vybraných "
                 "zemědělských pozemků, trvalých travních porostů nebo nevyužitelných ostatních "
                 "ploch 1.")
    assert p.areas == {"uvaly u valtic": 1.5, "valtice": 2.0}


def test_the_size_coefficient_raised_in_named_areas():
    # Vítkov 1/2026 — the act's paragraph number has a full stop in it.
    p = cz.parse("Čl. 3 U zdanitelných jednotek zařazených ve skupině ostatních zdanitelných "
                 "jednotek se koeficient, jímž se násobí sazba daně, zvyšuje o jednu kategorii "
                 "podle členění koeficientů dle § 11 odst. 4 zákona o dani z nemovitých věcí, a to "
                 "pro všechny tyto zdanitelné jednotky na území jednotlivého katastrálního území: "
                 "Vítkov , Klokočov u Vítkova , Nové Těchanovice . Čl. 4 Zrušovací ustanovení "
                 "Zrušuje se obecně závazná vyhláška č. 2/2024.")
    assert p.raise_areas == ["vitkov", "klokocov u vitkova", "nove techanovice"]
    assert p.repeals == ["2/2024"]


def test_the_wording_before_2024():
    # Janová 1/2016: one coefficient on everything.
    p = cz.parse("Obec Janová stanovuje místní koeficient ve výši 2, kterým se násobí daň "
                 "poplatníka za jednotlivé druhy pozemků, zdanitelných staveb nebo zdanitelných "
                 "jednotek, popřípadě jejich souhrny.")
    assert p.municipality == 2.0


def test_a_coefficient_for_land_only_sets_nothing_for_a_flat():
    p = cz.parse("Obec stanovuje místní koeficient pro jednotlivou skupinu pozemků dle § 5a, a to "
                 "pro: vybrané zemědělské pozemky ve výši 1,5, trvalé travní porosty ve výši 1,5.")
    assert p.empty()


PRAGUE_2024 = (
    "§ 2 U zdanitelných staveb zařazených ve skupině obytných budov a u zdanitelných jednotek "
    "zařazených ve skupině ostatních zdanitelných jednotek se koeficient, jímž se násobí sazba "
    "daně, stanovuje pro území jednotlivých městských částí hlavního města Prahy ve výši po dle "
    "přílohy č. 1 k této vyhlášce. § 4 (1) Na území hlavního města Prahy se stanovuje místní "
    "koeficient pro obec ve výši 1,5. § 5 (1) Na území hlavního města Prahy se stanovuje místní "
    "koeficient pro jednotlivou městskou část ve výši po dle přílohy č. 2 k této vyhlášce. "
    "Příloha č. 1 k obecně závazné vyhlášce Městská část Koeficient podle § 1 a 2 Praha 1 5 "
    "Praha 2 4,5 Praha 3 5 Praha-Zbraslav 5 Příloha č. 2 k obecně závazné vyhlášce Městská "
    "část Koeficient podle § 5 Praha 3 2 Praha 8 1,7 Praha-Šeberov 2")
PRAGUE_2025 = (
    "OBECNĚ ZÁVAZNÁ VYHLÁŠKA hlavního města Prahy, kterou se mění obecně závazná vyhláška "
    "hlavního města Prahy č. 11/20 2 4, o stanovení koeficientů Čl. I Obecně závazná vyhláška se "
    "mění takto: P řílo ha č. 1 zní: „ Příloha č. 1 k obecně závazné vyhlášce Městská část "
    "Koeficient po dle § 1 a 2 Praha 1 5 Praha 2 4,5 Praha 3 5 Praha-Zbraslav 4, 5 “. Příloha "
    "č. 2 zní: „ Příloha č. 2 k obecně závazné vyhlášce Městská část Koeficient podle § 5 Praha 3 "
    "2 Praha 8 1,7 “. Čl. II Tato vyhláška nabývá účinnosti dnem 1. ledna 20 26 .")


def prague():
    return [cz.Ordinance("a", "11/2024", date(2024, 7, 1), date(2025, 1, 1), cz.parse(PRAGUE_2024)),
            cz.Ordinance("b", "12/2025", date(2025, 9, 20), date(2026, 1, 1), cz.parse(PRAGUE_2025))]


def test_prague_by_city_part():
    base = prague()[0].parsed
    assert base.municipality == 1.5
    assert base.size_areas == {"praha 1": 5.0, "praha 2": 4.5, "praha 3": 5.0, "praha-zbraslav": 5.0}
    assert base.areas == {"praha 3": 2.0, "praha 8": 1.7, "praha-seberov": 2.0}
    assert base.annex_role == {"1": "size_areas", "2": "areas"}


def test_an_amendment_replaces_the_annexes_from_its_year():
    c25 = cz.coefficients("Praha", 1_397_880, prague(), 2025)
    c26 = cz.coefficients("Praha", 1_397_880, prague(), 2026)
    assert c25.size["praha-zbraslav"] == 5.0 and c26.size["praha-zbraslav"] == 4.5
    assert "praha-seberov" in c25.local and "praha-seberov" not in c26.local
    assert c26.local[""] == 1.5 and c26.local["praha 3"] == 2.0
    assert c26.sources == ["11/2024 (from 2025)", "12/2025 (from 2026)"]


def test_a_flat_in_praha_3_pays_size_5_and_local_2():
    c = cz.coefficients("Praha", 1_397_880, prague(), 2026)
    assert round(60 * 1.22 * 3.5 * c.size["praha 3"] * c.local["praha 3"]) == 2562


def o(no, effective, published=None, **kw):
    return cz.Ordinance(no, no, published, effective, cz.Parsed(**kw))


def test_a_repealed_ordinance_stops_counting():
    old = o("1/2023", date(2024, 1, 1), municipality=2.0)
    new = o("2/2025", date(2026, 1, 1), units=1.5, repeals=["1/2023"])
    assert cz.coefficients("X", 500, [old, new], 2025).local[""] == 2.0
    c = cz.coefficients("X", 500, [old, new], 2026)
    assert c.local[""] == 1.5 and c.sources == ["2/2025 (from 2026)"]


def test_an_ordinance_published_too_late_waits_a_year():
    late = o("3/2026", date(2027, 1, 1), published=date(2026, 10, 15), municipality=3.0)
    assert cz.coefficients("X", 500, [late], 2027).local[""] == 1.0
    assert cz.coefficients("X", 500, [late], 2028).local[""] == 3.0


def test_the_group_of_flats_replaces_the_municipalitys_and_the_higher_of_group_and_area_counts():
    # § 12 odst. 5 and 7.
    both = o("1/2025", date(2025, 1, 1), municipality=3.0, units=1.5,
             areas={"horni ves": 2.0, "dolni ves": 1.2})
    c = cz.coefficients("Ves", 800, [both], 2025)
    assert c.local == {"": 1.5, "horni ves": 2.0, "dolni ves": 1.5}


def test_the_main_part_takes_its_own_areas_coefficient():
    c = cz.coefficients("Valtice", 3_600, [o("8/2025", date(2026, 1, 1),
                                             areas={"valtice": 2.0, "uvaly u valtic": 1.5})], 2026)
    assert c.local[""] == 2.0


def test_a_raise_in_the_municipalitys_own_area_raises_its_main_part():
    c = cz.coefficients("Mimoň", 6_500, [o("2/2026", date(2026, 1, 1), raise_areas=["mimon"])], 2026)
    assert c.size[""] == 2.0                       # 1.6 one step up


def test_no_ordinance_leaves_the_acts_figures():
    c = cz.coefficients("Kladno", 70_000, [], 2026)
    assert (c.size, c.local, c.sources) == ({"": 3.5}, {"": 1.0}, [])


# ── The engine ────────────────────────────────────────────────────────────────
def place(name, okres, size, local, sources=("1/2024 (from 2025)",)):
    return {"name": name, "okres": okres,
            "years": {2026: (size, local, list(sources))}}


def stored(*places):
    data = {"places": {str(i): p for i, p in enumerate(places)}}
    count = {}
    for p in places:
        count[ptc._fold(p["name"])] = count.get(ptc._fold(p["name"]), 0) + 1
    data["names"] = sorted(((ptc._fold(p["name"]),
                             ptc._fold(p["okres"]) if count[ptc._fold(p["name"])] > 1 else "",
                             str(i)) for i, p in enumerate(places)), key=lambda t: -len(t[0]))
    return data


@pytest.fixture
def cities(monkeypatch):
    c = cz.coefficients("Praha", 1_397_880, prague(), 2026)
    monkeypatch.setattr(ptc, "_stored", stored(
        place("Praha", "Praha", c.size, c.local),
        place("Olomouc", "Olomouc", {"": 3.5}, {"": 2.0}),
        place("Pelhřimov", "Pelhřimov", {"": 2.0}, {"": 1.0, "bitetice": 0.8}),
        place("Lhota", "Plzeň-jih", {"": 1.0}, {"": 1.5}),
        place("Lhota", "Kladno", {"": 1.0}, {"": 3.0}),
        place("Brno", "Brno-město", {"": 3.5}, {"": 1.0}, sources=())))


def test_a_city_part_is_charged_its_own_coefficients(cities):
    assert ptc.coefficients("Praha 3", 2026)[:2] == (5.0, 2.0)
    assert ptc.coefficients("Praha 2 - Vinohrady", 2026)[:2] == (4.5, 1.5)
    assert ptc.annual_tax(60, "Praha 3", 2026) == round(60 * 1.22 * 3.5 * 5 * 2, 2)


def test_praha_10_is_not_praha_1(monkeypatch):
    monkeypatch.setattr(ptc, "_stored", stored(
        place("Praha", "Praha", {"": 4.5, "praha 1": 5.0, "praha 10": 4.5}, {"": 1.5})))
    assert ptc.coefficients("Praha 10", 2026)[:2] == (4.5, 1.5)
    assert ptc.coefficients("Praha 1", 2026)[:2] == (5.0, 1.5)


def test_a_city_without_its_part_named_pays_its_highest(cities):
    size, local, why = ptc.coefficients("Praha", 2026)
    assert (size, local) == (5.0, 2.0) and "none named" in why


def test_outlying_areas_leave_the_town_at_its_own_figure(cities):
    assert ptc.coefficients("Pelhřimov", 2026)[:2] == (2.0, 1.0)


def test_a_shared_name_needs_its_district(cities):
    assert ptc.coefficients("Lhota", 2026)[2].startswith("UNVERIFIED")
    assert ptc.coefficients("Lhota, okres Kladno", 2026)[:2] == (1.0, 3.0)


def test_an_okres_around_a_city_is_not_the_city(cities):
    assert ptc.coefficients("Brno-venkov", 2026)[2].startswith("UNVERIFIED")
    assert ptc.coefficients("Brno-střed", 2026)[:2] == (3.5, 1.0)


def test_without_stored_coefficients_the_old_estimate_stands():
    assert ptc.coefficients("Olomouc")[:2] == (3.5, ptc.LOCAL_COEFFICIENT)
    assert ptc.coefficients("Praha 3")[:2] == (4.5, ptc.LOCAL_COEFFICIENT)


# ── The update ────────────────────────────────────────────────────────────────
class FakeSources:
    def __init__(self):
        self.read, self.pop_calls = [], 0
        self.listed = [
            cz.Listed("SPP1", "Hlavní město Praha", "00064581", "11/2024",
                      "o výši koeficientů", date(2024, 9, 1), date(2025, 1, 1)),
            cz.Listed("SPP2", "Obec Krakov", "00000002", "4/2025", "o koeficientu",
                      date(2025, 9, 1), date(2026, 1, 1)),
        ]

    def populations(self, years):
        self.pop_calls += 1
        return {y: {"500496": ("Olomouc", "Olomouc", 101_000), "500000": ("Krakov", "Rakovník", 200),
                    "554782": ("Praha", "Praha", 1_397_880)} for y in years}

    def list_ordinances(self):
        return self.listed

    def text(self, oid):
        from scraper.property_tax_rates import Doc
        self.read.append(oid)
        if oid == "SPP2":
            return Doc(oid, "pdf", "", problem="a scanned PDF with no text layer — it can't be read")
        return Doc(oid, "docx", "§ 4 (1) Na území hlavního města Prahy se stanovuje místní "
                                "koeficient pro obec ve výši 1,5. Čl. 3 Účinnost")

    def municipality_of(self, ico):
        return {"00064581": {"code": "554782", "name": "Praha", "district": "Praha"},
                "00000002": {"code": "500000", "name": "Krakov", "district": "Rakovník"}}.get(ico)


@pytest.fixture
def db(full_db, monkeypatch):
    import database
    monkeypatch.setattr(ptc, "_stored", None)
    return database


def test_one_click_reads_every_municipality_once(db):
    from modules import tax_rates_cz as trc
    src = FakeSources()
    s = trc.update(year=2026, sources=src)
    assert (s["municipalities"], s["with_ordinances"], s["ordinances"]) == (3, 1, 2)
    assert len(s["unreadable"]) == 1 and "Krakov" in s["unreadable"][0]
    assert ptc.coefficients("Praha 5", 2026)[:2] == (4.5, 1.5)
    assert ptc.coefficients("Krakov", 2026)[:2] == (1.0, 1.0)      # unreadable: the act's
    assert ptc.coefficients("Olomouc", 2026)[:2] == (3.5, 1.0)     # no ordinance: the act's
    rows = {r["name"]: r for r in trc.table(2026)}
    assert set(rows) == {"Praha"} and rows["Praha"]["sources"] == ["11/2024 (from 2025)"]

    again = trc.update(year=2026, sources=src)
    assert again["read_now"] == 0 and src.read.count("SPP1") == 1 and src.pop_calls == 1
    assert "6,258" not in trc.summary_text(again) and "Czech municipalities" in trc.summary_text(again)


def test_a_czech_listing_is_rescored_when_its_coefficient_moves(db):
    from modules import tax_rates_cz as trc
    from modules.cashflow_runner import run_scoring
    db.upsert_listing(make_listing("c1", district="Praha 2", price_eur=6_000_000.0,
                                   size_m2=60.0, market="cz"))
    db.set_lv_status("c1", "PASS", "", "clean")
    run_scoring(market="cz")

    def tax_of():
        conn = db.get_conn()
        try:
            r = conn.execute("SELECT property_tax_monthly FROM cashflow_scores WHERE listing_id='c1'"
                             ).fetchone()
            return r[0] if r else None
        finally:
            conn.close()
    before = tax_of()
    assert before == round(round(60 * 1.22 * 3.5 * 4.5, 2) / 12, 2)
    s = trc.update(year=2026, sources=FakeSources())
    assert s["requeued"] == 1
    run_scoring(market="cz")
    assert tax_of() == round(round(60 * 1.22 * 3.5 * 4.5 * 1.5, 2) / 12, 2)
