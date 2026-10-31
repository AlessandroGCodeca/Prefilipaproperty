"""Slovak property tax (engine.property_tax_sk): daň z bytov per started m² at
the municipality's rate, never a share of the price."""

import pytest

import markets
from engine import financial as fin
from engine import property_tax_sk as ptax


def _rate(district):
    return ptax.rate_source(district)[0]


class TestRates:
    @pytest.mark.parametrize("district, rate", [
        ("Bratislava - Staré Mesto", 1.35),     # pásmo D
        ("Bratislava-Ruzinov", 1.35),           # Nivy (D) is part of Ružinov
        ("Ružinov", 1.35),                      # a city part named alone
        ("Bratislava - Nové Mesto", 1.25),      # C
        ("Petržalka", 1.25),                    # C
        ("Bratislava IV, Dúbravka", 1.20),      # B
        ("Bratislava - Devínska Nová Ves", 1.20),  # A
        ("Vrakuňa", 1.20),                      # A
    ])
    def test_bratislava_by_pasmo(self, district, rate):
        assert _rate(district) == rate

    @pytest.mark.parametrize("district, rate", [
        ("Bratislava I", 1.35), ("Bratislava II", 1.35), ("Bratislava III", 1.25),
        ("Bratislava - IV", 1.20), ("okres Bratislava V", 1.25), ("Bratislava", 1.35),
    ])
    def test_bratislava_okres_or_city_takes_its_dearest_part(self, district, rate):
        assert _rate(district) == rate

    @pytest.mark.parametrize("district, rate", [
        ("Košice II", 1.27), ("Staré Mesto, Košice", 1.27), ("Kosice - Juh", 1.27),
        ("Žilina", 1.20), ("Trnava", 1.00), ("Banská Bystrica", 1.00),
        ("Prešov", 0.953), ("Trencin", 0.88), ("Nitra", 0.75),
    ])
    def test_cities(self, district, rate):
        assert _rate(district) == rate

    @pytest.mark.parametrize("district", [
        "Staré Mesto",            # Košice has one too: not Bratislava's on its own
        "Nové Mesto nad Váhom",   # a town, not Bratislava's Nové Mesto
        "Nitra nad Ipľom",        # a village, not Nitra
        "Košice-okolie",          # the villages around Košice
        "Dúbravka, Michalovce",   # a Bratislava name beside another town
        "Poprad", "", None,
    ])
    def test_a_place_not_in_the_table_is_unverified_at_the_highest_rate(self, district):
        rate, where = ptax.rate_source(district)
        assert rate == ptax.UNKNOWN_PLACE_RATE_PER_M2 == 1.35
        assert where.startswith("UNVERIFIED")

    def test_the_act_default_is_far_below_every_city(self):
        assert ptax.STATUTORY_RATE_PER_M2 == 0.033
        assert all(r > 20 * ptax.STATUTORY_RATE_PER_M2
                   for r, _ in ptax.CITY_RATE_PER_M2.values())


class TestTax:
    def test_every_started_m2_is_taxed(self):
        assert ptax.annual_tax(55.0, "Nitra") == pytest.approx(55 * 0.75)
        assert ptax.annual_tax(55.2, "Nitra") == pytest.approx(56 * 0.75)
        assert ptax.annual_tax(0, "Nitra") == 0
        assert ptax.annual_tax(None, "Nitra") == 0

    def test_the_price_plays_no_part(self):
        cheap = fin.property_tax_annual(90_000, 60, "Žilina")
        dear = fin.property_tax_annual(900_000, 60, "Žilina")
        assert cheap == dear == pytest.approx(60 * 1.20)

    def test_the_cash_flow_carries_it_monthly(self):
        r = fin.analyse(185_000, 52, "Bratislava II", rooms=2)
        assert r.property_tax_monthly == pytest.approx(round(52 * 1.35 / 12, 2))

    def test_a_czech_listing_keeps_the_czech_tax(self):
        from engine import property_tax_cz
        assert fin.property_tax_annual(5_000_000, 60, "Praha 2", market="cz") == \
            property_tax_cz.annual_tax(60, "Praha 2")


def test_the_market_records_its_source():
    pt = markets.SK.property_tax
    assert pt["kind"] == "per_m2" and pt["module"] == "engine.property_tax_sk"
    assert pt["checked"] and "UNVERIFIED" in ptax.SOURCE["source"]


def test_older_scores_are_redone():
    assert fin.SCORING_MODEL_VERSION >= 4
