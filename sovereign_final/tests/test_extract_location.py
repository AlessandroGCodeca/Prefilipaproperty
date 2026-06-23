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
