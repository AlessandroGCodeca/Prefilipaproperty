"""Czech property tax (engine.property_tax_cz): daň z nemovitých věcí on a flat,
with Prague's, the statutory cities' and the larger towns' 2026 coefficients,
and every municipality's size coefficient from its population."""

import csv
import io
import json
import math
import sys
import zipfile
from pathlib import Path

import pytest

from engine import financial as fin
from engine import property_tax_cz as ptax

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))
import build_cz_property_tax_data as build  # noqa: E402


def _coef(district):
    return ptax.coefficients(district)[:2]


class TestPrague:
    @pytest.mark.parametrize("district, coef", [
        ("Praha 2", (4.5, 1.5)), ("Praha 10 - Strašnice", (4.5, 1.5)),
        ("Praha 1 - Staré Město", (5.0, 1.5)),            # size raised to 5.0
        ("Praha 3 - Žižkov", (5.0, 2.0)), ("Praha 6", (5.0, 2.0)), ("Praha 7", (5.0, 2.0)),
        ("Praha 8 - Karlín", (5.0, 1.7)),                  # its own local coefficient
        ("Praha-Kolovraty", (5.0, 2.0)),
        ("Praha 4 - Kunratice", (4.5, 1.5)),               # 5.0 until 2025
        ("Praha 5 - Zbraslav", (4.5, 1.5)),                # a named city part wins
        ("Praha - Šeberov", (4.5, 1.5)),                   # its 2.0 dropped for 2026
    ])
    def test_city_parts(self, district, coef):
        assert _coef(district) == coef

    def test_prague_unnamed_takes_its_dearest_part(self):
        assert _coef("Praha") == (5.0, 2.0)

    @pytest.mark.parametrize("district, coef", [
        ("Praha 4 - Chodov", (4.5, 1.5)),          # Chodov is city part Praha 11
        ("Praha 9 - Černý Most", (5.0, 1.5)),      # … Praha 14, raised to 5.0
        ("Praha 9 - Prosek", (4.5, 1.5)),          # … Praha 9
        ("Praha - Vinohrady", (5.0, 2.0)),         # Praha 2, 3 and 10: Praha 3's
        ("Praha 21 - Újezd nad Lesy", (4.5, 1.5)),  # not city part Újezd (5.0)
    ])
    def test_a_quarter_names_its_city_part(self, district, coef):
        assert _coef(district) == coef

    def test_a_bare_praha_n_may_be_the_postal_district(self):
        # Postal district Praha 9 also covers Praha 14 (5.0), 20 and 21.
        size, local, where = ptax.coefficients("Praha 9")
        assert (size, local) == (5.0, 1.5) and "Praha 14" in where
        # Praha 2's postal district is city part Praha 2 alone.
        assert _coef("Praha 2") == (4.5, 1.5)
        # Praha 11–22 are city parts only.
        assert _coef("Praha 11") == (4.5, 1.5)

    def test_the_okresy_around_prague_are_not_prague(self):
        assert ptax.coefficients("Praha-východ")[2].startswith("UNVERIFIED")
        size, _, where = ptax.coefficients("Praha-západ, Černošice")
        assert size == 1.6 and where.startswith("Černošice")


class TestCities:
    @pytest.mark.parametrize("district, coef", [
        ("Brno-střed", (3.5, 1.0)), ("Kladno", (3.5, 1.0)), ("Prostějov", (3.5, 1.0)),
        ("České Budějovice", (3.5, 1.0)),
        ("Ostrava - Moravská Ostrava", (4.5, 1.0)), ("Ostrava-Poruba", (3.5, 1.0)),
        ("Ostrava", (4.5, 1.0)),
        ("Plzeň", (4.5, 1.0)), ("Plzeň - Malesice", (3.5, 0.5)),
        ("Liberec", (3.5, 2.0)), ("Olomouc", (3.5, 2.0)), ("Ústí nad Labem", (3.5, 2.0)),
        ("Hradec Králové", (4.5, 1.3)), ("Hradec Králové - Slatina", (3.5, 1.3)),
        ("Pardubice", (3.5, 2.0)), ("Havířov", (3.5, 1.8)),
        ("Zlín", (3.5, 2.0)), ("Zlín - Malenovice", (3.5, 1.6)), ("Zlín - Salaš", (3.5, 1.4)),
        ("Most", (3.5, 2.0)), ("Karviná", (3.5, 2.0)), ("Karviná - Doly", (3.5, 0.9)),
        ("Opava", (3.5, 1.5)), ("Frýdek-Místek", (4.5, 1.0)),
        ("Frýdek-Místek - Skalice", (3.5, 0.7)), ("Karlovy Vary", (4.5, 2.0)),
        ("Teplice", (4.5, 1.0)), ("Děčín", (3.5, 2.0)), ("Chomutov", (3.5, 2.0)),
        ("Jihlava", (3.5, 1.8)), ("Jablonec nad Nisou", (3.5, 2.0)),
        ("Přerov", (3.5, 1.0)), ("Přerov - Přerov XIII-Penčice", (3.5, 0.8)),
        ("Mladá Boleslav", (3.5, 1.7)), ("Třinec", (3.5, 0.5)),
    ])
    def test_statutory_cities(self, district, coef):
        assert _coef(district) == coef

    @pytest.mark.parametrize("district, coef", [
        ("Ostrava - Zábřeh", (3.5, 1.0)),          # in district Ostrava-Jih
        ("Ostrava - Přívoz", (4.5, 1.0)),          # in Moravská Ostrava a Přívoz
        ("Nová Ves, Ostrava", (3.5, 1.0)),         # Ostrava's Nová Ves, not a village
        ("Plzeň - Koterov", (4.5, 1.0)),           # its flats are partly in Hradiště u Plzně
        ("Plzeň - Lhota", (3.5, 1.0)),             # k.ú. Lhota u Dobřan
        ("Zlín - Chlum", (3.5, 1.4)),              # k.ú. Lhotka u Zlína
        ("Frýdek-Místek - Zelinkovice", (3.5, 0.7)),  # k.ú. Lysůvky
        ("Frýdek-Místek - Frýdek", (4.5, 1.0)),
        ("Karviná - Mizerov", (3.5, 2.0)), ("Karviná - Lázně Darkov", (3.5, 0.9)),
        # Quarter Přerov VIII-Henčlov spans k.ú. Henčlov (0.8) and Přerov (1.0).
        ("Přerov - Henčlov", (3.5, 1.0)),
    ])
    def test_a_quarter_takes_its_areas(self, district, coef):
        assert _coef(district) == coef

    @pytest.mark.parametrize("district", ["Brno-venkov", "Plzeň-jih", "Atlantis", "", None])
    def test_no_municipality_is_unverified_at_3_5(self, district):
        size, local, where = ptax.coefficients(district)
        assert (size, local) == (3.5, ptax.LOCAL_COEFFICIENT)
        assert where.startswith("UNVERIFIED")


def _municipalities():
    return {(n, o): p for n, o, p in ptax._DATA["municipalities"]}


class TestTowns:
    @pytest.mark.parametrize("people, coef", [
        (1, 1.0), (1000, 1.0), (1001, 1.4), (6000, 1.4), (6001, 1.6), (10000, 1.6),
        (10001, 2.0), (25000, 2.0), (25001, 2.5), (50000, 2.5), (50001, 3.5),
    ])
    def test_population_bands(self, people, coef):
        assert ptax.population_coefficient(people) == coef

    def test_every_town_in_the_table_is_a_municipality_over_10000(self):
        muni = _municipalities()
        for (name, okres), (size, local, areas, acts) in ptax.TOWN_COEFFICIENTS.items():
            assert (name, okres) in muni, name
            assert muni[(name, okres)] > 10000, name
            band = 3.5 if (name, okres) in ptax.SPA_TOWNS else ptax.population_coefficient(
                muni[(name, okres)])
            steps = [1.0, 1.4, 1.6, 2.0, 2.5, 3.5, 4.5]
            # The band, or one step up by ordinance (§ 11 odst. 5).
            assert size in (band, steps[steps.index(band) + 1]), name
            assert 0.5 <= local <= 5.0 and acts, name
            for pair in areas.values():
                assert 0.5 <= pair[1] <= 5.0

    def test_every_town_over_10000_is_read(self):
        cities = set(ptax.CITY_COEFFICIENTS) | {"Praha"}
        missing = [k for k, p in _municipalities().items()
                   if p > 10000 and k[0] not in cities and k not in ptax.TOWN_COEFFICIENTS]
        assert missing == []

    @pytest.mark.parametrize("district, coef", [
        ("Benešov", (2.0, 2.0)),
        ("Říčany - Radošovice, Praha-východ", (2.5, 5.0)),  # raised; 5.0 from 2026
        ("Mariánské Lázně", (4.5, 1.2)),          # a spa town (3.5), raised
        ("Poděbrady", (3.5, 0.7)),
        ("Litvínov", (2.0, 2.5)),
        ("Litvínov - Záluží", (2.0, 5.0)),        # 5.0 only there and in Růžodol
        ("Orlová - Lutyně, Karviná", (2.5, 2.0)),  # a town, then its okres
        ("Orlová, okres Karviná", (2.5, 2.0)),
        ("Hranice", (2.0, 1.0)),                  # three Hranice: okres Přerov's is dearest
    ])
    def test_towns_over_10000(self, district, coef):
        assert _coef(district) == coef

    @pytest.mark.parametrize("district, size", [
        ("Pečky, okres Kolín", 1.4),
        ("Teplice nad Metují", 1.4),             # not Teplice
        ("Benešov nad Ploučnicí", 1.4),          # not Benešov
        ("Hranice, Cheb", 1.4),                  # the okres picks the namesake
        ("Kladno, Chrudim", 1.0),                # a village of 232, not the city
        ("Luhačovice", 3.5),                     # a spa town
    ])
    def test_smaller_municipalities_by_population(self, district, size):
        got, local, where = ptax.coefficients(district)
        assert (got, local) == (size, ptax.LOCAL_COEFFICIENT)
        assert "UNVERIFIED" in where

    def test_their_local_coefficient_is_the_setting(self, monkeypatch):
        monkeypatch.setattr(ptax, "LOCAL_COEFFICIENT", 2.0)
        ptax.coefficients.cache_clear()
        try:
            assert _coef("Pečky, okres Kolín") == (1.4, 2.0)
            assert _coef("Benešov") == (2.0, 2.0)    # read from its ordinance
        finally:
            monkeypatch.undo()
            ptax.coefficients.cache_clear()

    def test_missing_data_fails_soft(self, tmp_path):
        assert ptax.load_data(str(tmp_path / "absent.json")) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert ptax.load_data(str(bad)) == {}

    def test_the_data_names_its_official_sources(self):
        src = ptax._DATA["sources"]
        assert src["addresses"].endswith("_OB_ADR_csv.zip")
        assert all(f.endswith("_UKSH.xml.zip") for f in src["cadastral"])
        assert src["population"].endswith(".xlsx") and src["share_min"] == 0.10
        assert len(ptax._DATA["municipalities"]) > 6000


def _zip_csv(path, rows_by_code):
    head = ["Kód obce", "Název obce", "Název MOMC", "Název obvodu Prahy", "Název části obce"]
    with zipfile.ZipFile(path, "w") as z:
        for code, rows in rows_by_code.items():
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(head)
            w.writerows(rows)
            z.writestr(f"CSV/20990101_OB_{code}_ADR.csv", buf.getvalue().encode("cp1250"))


class TestBuild:
    """dev/build_cz_property_tax_data.py on synthetic files."""

    def test_addresses_keep_places_over_a_tenth(self, tmp_path):
        rows = ([[build.PRAHA, "Praha", "Praha 4", "Praha 4", "Chodov"]] * 1 +
                [[build.PRAHA, "Praha", "Praha 11", "Praha 4", "Chodov"]] * 19 +
                [[build.PRAHA, "Praha", "Praha-Kunratice", "Praha 4", "Kunratice"]] * 5)
        ostrava = [[build.OSTRAVA, "Ostrava", "Ostrava-Jih", "", "Zábřeh"]] * 3
        path = tmp_path / "adr.zip"
        _zip_csv(path, {build.PRAHA: rows, build.OSTRAVA: ostrava})
        got = build.addresses(str(path))
        assert got["praha_quarters"]["Chodov"] == ["Praha 11"]      # 1 of 20 dropped
        assert got["praha_quarters"]["Kunratice"] == ["Kunratice"]   # "Praha-" dropped
        assert got["praha_old_districts"]["Praha 4"] == ["Praha 11", "Kunratice"]
        assert got["ostrava_quarters"] == {"Zábřeh": ["Ostrava-Jih"]}

    def test_cadastral_quarters_count_flats(self, tmp_path):
        ns = 'xmlns="urn:x"'
        so = ("<StavebniObjekt><CastObce><Kod>{q}</Kod></CastObce><IdentifikacniParcela>"
              "<Id>{p}</Id></IdentifikacniParcela><PocetBytu>{n}</PocetBytu></StavebniObjekt>")
        xml = (f"<Data {ns}><Obec><Kod>1</Kod><Nazev>Testov</Nazev></Obec>"
               "<CastObce><Kod>7</Kod><Nazev>Horní Testov</Nazev></CastObce>"
               "<KatastralniUzemi><Kod>81</Kod><Nazev>Testov</Nazev></KatastralniUzemi>"
               "<KatastralniUzemi><Kod>82</Kod><Nazev>Dolní Testov</Nazev></KatastralniUzemi>"
               "<Parcela><Id>p1</Id><KatastralniUzemi><Kod>81</Kod></KatastralniUzemi></Parcela>"
               "<Parcela><Id>p2</Id><KatastralniUzemi><Kod>82</Kod></KatastralniUzemi></Parcela>"
               + so.format(q=7, p="p1", n=95) + so.format(q=7, p="p2", n=5) + "</Data>")
        path = tmp_path / "vfr.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("20990101_OB_1_UKSH.xml", xml)
        city, quarters = build.cadastral_quarters(str(path))
        assert city == "Testov"
        assert quarters == {"Horní Testov": ["Testov"]}       # 5 of 100 flats dropped

    def test_main_writes_the_data_file(self, tmp_path, monkeypatch):
        adr = tmp_path / "adr.zip"
        _zip_csv(adr, {build.PRAHA: [[build.PRAHA, "Praha", "Praha 2", "Praha 2", "Nusle"]],
                       build.OSTRAVA: []})
        monkeypatch.setattr(build, "municipalities", lambda path: [["Testov", "Kolín", 1200]])
        out = tmp_path / "data.json"
        assert build.main(["--adr", str(adr), "--population", "pop.xlsx", "--out", str(out)]) == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["praha_quarters"] == {"Nusle": ["Praha 2"]}
        assert data["municipalities"] == [["Testov", "Kolín", 1200]]
        assert data["sources"]["population"] == "pop.xlsx"


class TestTax:
    def test_rounding_follows_section_11d(self):
        # 60 m² × 1.22 = 73.2 → 74 m²; 74 × 3.50 × 5.0 = 1,295 Kč; × 2.0 = 2,590 Kč.
        assert ptax.annual_tax(60, "Praha 3") == 2590
        # 55.5 m² × 1.22 = 67.71 → 68 m²; 68 × 3.50 × 3.5 = 833 Kč; × 1.7 = 1,416.1 → 1,417.
        assert ptax.annual_tax(55.5, "Mladá Boleslav") == 1417
        assert ptax.annual_tax(0, "Praha 3") == 0

    def test_a_town_over_10000(self):
        # 60 m² → 74 m²; 74 × 3.50 × 2.5 = 647.5 → 648 Kč; × 5.0 = 3,240 Kč (Říčany).
        assert ptax.annual_tax(60, "Říčany, Praha-východ") == 3240
        # 74 × 3.50 × 2.0 = 518 Kč; × 1.0 (Klatovy).
        assert ptax.annual_tax(60, "Klatovy") == 518

    def test_inflation_coefficient_is_1_for_2026(self):
        assert ptax.INFLATION_COEFFICIENT == 1.0
        assert math.floor(155.0 / 147.6 * 10) / 10 == 1.0    # ČSÚ, May 2025 / May 2023

    def test_the_engine_uses_it_and_not_the_price(self):
        assert fin.property_tax_annual(3_000_000, 60, "Liberec", market="cz") == \
            fin.property_tax_annual(9_000_000, 60, "Liberec", market="cz") == 1814

    def test_source_names_the_ordinances(self):
        src = ptax.SOURCE["source"]
        assert "11/2024" in src and "12/2025" in src and "UNVERIFIED" in src
