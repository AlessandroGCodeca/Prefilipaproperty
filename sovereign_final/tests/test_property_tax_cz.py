"""Czech property tax (engine.property_tax_cz): daň z nemovitých věcí on a flat,
with Prague's and the statutory cities' 2026 coefficients."""

import math

import pytest

from engine import financial as fin
from engine import property_tax_cz as ptax


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

    @pytest.mark.parametrize("district", ["Praha-východ", "Praha-západ, Černošice"])
    def test_the_okresy_around_prague_are_not_prague(self, district):
        assert ptax.coefficients(district)[2].startswith("UNVERIFIED")


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
        ("Přerov", (3.5, 1.0)), ("Přerov - Henčlov", (3.5, 0.8)),
        ("Mladá Boleslav", (3.5, 1.7)), ("Třinec", (3.5, 0.5)),
    ])
    def test_statutory_cities(self, district, coef):
        assert _coef(district) == coef

    @pytest.mark.parametrize("district", [
        "Brno-venkov", "Plzeň-jih", "Teplice nad Metují", "Benešov", "", None,
    ])
    def test_elsewhere_is_unverified_at_3_5(self, district):
        size, local, where = ptax.coefficients(district)
        assert (size, local) == (3.5, ptax.LOCAL_COEFFICIENT)
        assert where.startswith("UNVERIFIED")


class TestTax:
    def test_rounding_follows_section_11d(self):
        # 60 m² × 1.22 = 73.2 → 74 m²; 74 × 3.50 × 5.0 = 1,295 Kč; × 2.0 = 2,590 Kč.
        assert ptax.annual_tax(60, "Praha 3") == 2590
        # 55.5 m² × 1.22 = 67.71 → 68 m²; 68 × 3.50 × 3.5 = 833 Kč; × 1.7 = 1,416.1 → 1,417.
        assert ptax.annual_tax(55.5, "Mladá Boleslav") == 1417
        assert ptax.annual_tax(0, "Praha 3") == 0

    def test_inflation_coefficient_is_1_for_2026(self):
        assert ptax.INFLATION_COEFFICIENT == 1.0
        assert math.floor(155.0 / 147.6 * 10) / 10 == 1.0    # ČSÚ, May 2025 / May 2023

    def test_the_engine_uses_it_and_not_the_price(self):
        assert fin.property_tax_annual(3_000_000, 60, "Liberec", market="cz") == \
            fin.property_tax_annual(9_000_000, 60, "Liberec", market="cz") == 1814

    def test_source_names_the_ordinances(self):
        src = ptax.SOURCE["source"]
        assert "11/2024" in src and "12/2025" in src and "UNVERIFIED" in src
