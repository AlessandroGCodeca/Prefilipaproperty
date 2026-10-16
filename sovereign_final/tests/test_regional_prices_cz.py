"""Czech regional prices (engine.regional_prices_cz): where a district
string resolves to, and that with no source loaded there is no median — a
Czech listing is WHITE, never a guessed GREEN. Synthetic figures only."""

import pytest

import markets
from engine import financial as fin
from engine import regional_prices as rp
from engine import regional_prices_cz as cz


class TestPlaces:
    @pytest.mark.parametrize("district,okres,kraj", [
        ("Praha 2 - Vinohrady", "Hlavní město Praha", "PHA"),
        ("Praha-východ", "Praha-východ", "STC"),
        ("Brno-střed", "Brno-město", "JHM"),
        ("Brno - Královo Pole", "Brno-město", "JHM"),
        ("Plzeň - Slovany", "Plzeň-město", "PLK"),
        ("Ostrava-Poruba", "Ostrava-město", "MSK"),
        ("Nový Jičín", "Nový Jičín", "MSK"),
        ("Jičín", "Jičín", "HKK"),
        ("Ústí nad Orlicí", "Ústí nad Orlicí", "PAK"),
        ("Ústí nad Labem - Střekov", "Ústí nad Labem", "ULK"),
        ("Zdar nad Sazavou", "Žďár nad Sázavou", "VYS"),     # typed without diacritics
        ("okres Sokolov", "Sokolov", "KVK"),
    ])
    def test_okres_and_kraj(self, district, okres, kraj):
        assert cz.okres_for_district(district) == okres
        assert cz.kraj_for_district(district) == kraj
        assert rp.kraj_for_district(district, market="cz") == kraj

    def test_every_okres_has_a_kraj(self):
        assert len(cz.OKRES_KRAJ) == 77                 # 76 okresy and Prague
        assert set(cz.OKRES_KRAJ.values()) == set(cz.KRAJ_NAMES)
        assert len(cz.BRNO_DISTRICTS) == 29

    def test_prague_and_brno_districts(self):
        assert cz.praha_district("Praha 7 - Holešovice") == "Praha 7"
        assert cz.praha_district("Praha 23") is None
        assert cz.brno_district("Brno - Královo Pole") == "Královo Pole"
        assert cz.brno_district("Vinohrady") is None    # Prague's too: needs "Brno"

    def test_nowhere(self):
        assert cz.kraj_for_district("") is None
        assert cz.kraj_for_district("Nowhereville") is None


class TestNoSourceNoMedian:
    def test_empty_tables_mean_white(self):
        assert rp.regional_median_price("Praha 2", market="cz") is None
        assert fin.class_at_price(1_000_000, 60, "Praha 2", market="cz") == "WHITE"
        assert fin.max_offer_price(60, "Praha 2", "GREEN", market="cz") is None
        assert "UNVERIFIED" in cz.SOURCE["source"]

    def test_backstops_apply_without_a_median(self):
        floor, ceiling = (markets.CZ.blank_district_floor_m2,
                          markets.CZ.blank_district_ceiling_m2)
        assert rp.regional_price_floor("Praha 2", market="cz") == floor
        assert rp.regional_price_ceiling("Praha 2", market="cz") == ceiling
        assert not rp.is_plausible_regional_price(500_000, 60, "Most", market="cz")
        assert rp.is_above_regional_ceiling(60_000_000, 60, "Praha 2", market="cz")
        # The Slovak ones are untouched.
        assert rp.regional_price_floor("") == rp.GLOBAL_BLANK_DISTRICT_FLOOR


class TestLoadedMedians:
    @pytest.fixture
    def loaded(self, tmp_path, monkeypatch):
        for table in ("KRAJ_MEDIAN", "OKRES_MEDIAN", "PRAHA_DISTRICT_MEDIAN",
                      "BRNO_DISTRICT_MEDIAN", "MEDIAN_SOURCE"):
            monkeypatch.setattr(cz, table, {})
        monkeypatch.setattr(cz, "_TABLES", {"kraj": cz.KRAJ_MEDIAN, "okres": cz.OKRES_MEDIAN,
                                            "praha": cz.PRAHA_DISTRICT_MEDIAN,
                                            "brno": cz.BRNO_DISTRICT_MEDIAN})
        monkeypatch.setattr(cz, "SOURCE", dict(cz.SOURCE))
        path = tmp_path / "cz_regional_prices.csv"
        path.write_text(
            "level,name,median_czk_m2,period,source\n"
            "kraj,Jihomoravský kraj,90000,TEST,synthetic\n"
            "okres,Blansko,70000,TEST,synthetic\n"
            "praha,Praha 7,150000,TEST,synthetic\n"
            "brno,Královo Pole,110000,TEST,synthetic\n"
            "okres,Atlantis,1,TEST,synthetic\n", encoding="utf-8")
        assert cz.load_medians(str(path)) == 4        # Atlantis skipped
        return cz

    def test_most_specific_first(self, loaded):
        assert cz.median_source("Praha 7 - Letná")[0] == 150_000
        assert cz.median_source("Brno - Královo Pole")[0] == 110_000
        assert cz.median_source("Blansko")[0] == 70_000
        assert cz.median_source("Znojmo") == (90_000, "Jihomoravský kraj (no median for the okres itself)")
        assert cz.median_source("Praha 2")[0] is None        # no Prague-wide figure loaded

    def test_classes_follow(self, loaded):
        # 20% under Blansko's median is GREEN, at it WHITE.
        assert fin.class_at_price(0.8 * 70_000 * 60, 60, "Blansko", market="cz") == "GREEN"
        assert fin.class_at_price(70_000 * 60, 60, "Blansko", market="cz") == "WHITE"
        assert fin.max_offer_price(60, "Blansko", "YELLOW", market="cz") % 10_000 == 0
        assert "70" in rp.benchmark_note("Blansko", market="cz")
