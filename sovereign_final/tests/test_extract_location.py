"""Tests for scraper/nehnutelnosti.py::_extract_location_from_text — the
shared Slovak city/suburb detector used by all three scrapers."""

import pytest

from scraper.nehnutelnosti import _extract_location_from_text


class TestKnownCities:
    @pytest.mark.parametrize("text,expected_substring", [
        ("Predaj bytu Bratislava centrum",          "Bratislava"),
        ("Byt na predaj Košice - sídlisko KVP",     "Košice"),
        ("Trnava 91701, novostavba",                "Trnava"),
        ("Banská Bystrica - centrum, 3-izbový",     "Banská Bystrica"),
        ("Žilina, Hájik, predaj",                   "Žilina"),
        ("Prešov, Sídlisko III",                    "Prešov"),
    ])
    def test_known_city_detected(self, text, expected_substring):
        result = _extract_location_from_text(text)
        assert expected_substring in result, (
            f"{text!r} should match {expected_substring!r}, got {result!r}"
        )


class TestSuburbsWinOverCity:
    @pytest.mark.parametrize("text,expected", [
        ("Bratislava - Petržalka, 2-izbový",   "Petržalka, Bratislava"),
        ("Predaj v Karlova Ves, Bratislava",   "Karlova Ves, Bratislava"),
        ("Ružinov - Štrkovec, BA",             "Ružinov, Bratislava"),
        ("Staré Mesto Bratislava centrum",     "Staré Mesto, Bratislava"),
    ])
    def test_suburb_matches_with_parent_city(self, text, expected):
        # The helper returns "Suburb, City" so engine.get_rent_estimate
        # finds the specific suburb (Petržalka → €12/m²) and not the
        # city anchor (Bratislava → €12.5/m²).
        result = _extract_location_from_text(text)
        assert result == expected

    @pytest.mark.xfail(
        reason="Slovak grammatical declension not handled — 'v Petržalke' "
               "(locative case) doesn't match 'Petržalka' nominative pattern. "
               "Known limitation; revisit if it materially affects coverage."
    )
    def test_declension_locative_form(self):
        # "byt v Petržalke" — locative case ('-e' suffix) — would need either
        # a stemmer or expanded regex patterns to recognise.
        assert _extract_location_from_text("byt v Petržalke") == "Petržalka, Bratislava"


class TestBoundaries:
    def test_empty_string_returns_empty(self):
        assert _extract_location_from_text("") == ""

    def test_none_safe(self):
        # Helper should not crash on None
        assert _extract_location_from_text(None) == ""

    def test_no_match_returns_empty(self):
        assert _extract_location_from_text("Lorem ipsum dolor sit amet") == ""

    def test_partial_match_not_returned(self):
        # "kosicepiece" should NOT match "Košice" — diacritic-required prevents
        # false positives, AND word-boundary regex prevents substring matches
        # like "barack" → "rača"
        result = _extract_location_from_text("xxx kosicepiece yyy")
        assert "Košice" not in result


class TestPostcodeStripping:
    def test_postcode_does_not_pollute(self):
        # Bratislava postcodes (821 01, 851 02) should be in the text but
        # the helper returns just the city name, not the postcode
        result = _extract_location_from_text("Bratislava 821 01")
        assert result == "Bratislava"


class TestLongerTownNamesWin:
    """A Bratislava city-part name inside a longer town name is part of that
    town. Checking suburbs first used to send "Nové Mesto nad Váhom" and
    "Kysucké Nové Mesto" to Bratislava's Nové Mesto."""

    @pytest.mark.parametrize("text,expected", [
        ("Byt, Nové Mesto nad Váhom",            "Nové Mesto nad Váhom"),
        ("Kysucké Nové Mesto, 2-izbový",         "Kysucké Nové Mesto"),
        ("PREDAM BYT NOVÉ MESTO NAD VÁHOM",      "Nové Mesto nad Váhom"),
        ("Byt Nové Mesto n. Váhom, centrum",     "Nové Mesto nad Váhom"),
        ("Nové  Mesto\nnad Váhom",               "Nové Mesto nad Váhom"),
    ])
    def test_town_not_read_as_bratislava(self, text, expected):
        assert _extract_location_from_text(text) == expected

    def test_bratislava_nove_mesto_still_bratislava(self):
        assert _extract_location_from_text("Nové Mesto, Bratislava") == \
            "Nové Mesto, Bratislava"
        # Named on its own, it is still Bratislava's.
        assert _extract_location_from_text("Nové Mesto, 3-izbový byt") == \
            "Nové Mesto, Bratislava"

    def test_town_wins_even_when_bratislava_is_also_named(self):
        # Detail pages render menus and "similar listings" around the address.
        text = "Byty Bratislava | 2-izbový byt, Nové Mesto nad Váhom"
        assert _extract_location_from_text(text) == "Nové Mesto nad Váhom"


class TestGenericCityParts:
    """"Staré Mesto" and "Nové Mesto" are generic names: Košice has a Staré
    Mesto of its own."""

    @pytest.mark.parametrize("text", [
        "Košice - Staré Mesto, 3-izbový",
        "Staré Mesto, Košice",
        "STARÉ MESTO KOŠICE",
    ])
    def test_kosice_stare_mesto_is_kosice(self, text):
        assert _extract_location_from_text(text) == "Staré Mesto, Košice"

    def test_declined_bratislava_keeps_the_part_in_bratislava(self):
        # "v Bratislave" never matches the "Bratislava" pattern, but it still
        # says which Staré Mesto this is.
        text = "Staré Mesto, byt v Bratislave, 30 min do Trnava"
        assert _extract_location_from_text(text) == "Staré Mesto, Bratislava"


class TestSmallTownsKeepTheirRent:
    """The reported cases end to end: the location a matcher finds, priced by
    engine.get_rent_estimate, is the town's rate and not Bratislava's."""

    def test_reported_cases(self):
        from engine.financial import get_rent_estimate
        from scraper.nehnutelnosti import _parse_slug

        town_rate = get_rent_estimate("nové mesto nad váhom", 1)
        assert town_rate == pytest.approx(7.62)

        slug = _parse_slug(
            "https://x/detail/Ju1/2-izbovy-byt-nove-mesto-nad-vahom")["district"]
        assert slug == "Nové Mesto nad Váhom"
        assert get_rent_estimate(slug, 1) == pytest.approx(town_rate)

        text = _extract_location_from_text("Byt, Nové Mesto nad Váhom")
        assert get_rent_estimate(text, 1) == pytest.approx(town_rate)

        knm = _extract_location_from_text("Kysucké Nové Mesto, 2-izbový")
        assert get_rent_estimate(knm, 1) == \
            pytest.approx(get_rent_estimate("kysucké nové mesto", 1))

    def test_kosice_stare_mesto_not_priced_as_bratislava(self):
        from engine.financial import get_rent_estimate
        location = _extract_location_from_text("Košice - Staré Mesto")
        assert get_rent_estimate(location, 1) < \
            get_rent_estimate("Staré Mesto, Bratislava", 1)
