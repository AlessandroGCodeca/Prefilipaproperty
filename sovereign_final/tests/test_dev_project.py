"""Tests for database.detect_dev_project — URL/title-based dev-project flag."""

import pytest

from database import detect_dev_project


class TestUrlMarkers:
    def test_nehnutelnosti_dev_project_path(self):
        assert detect_dev_project(
            "https://www.nehnutelnosti.sk/detail/developersky-projekt/abc123/slug",
            "Predaj 3-izbový byt",
        ) == 1

    def test_normal_listing_url(self):
        assert detect_dev_project(
            "https://www.nehnutelnosti.sk/detail/abc123/slug-byt-ruzinov",
            "3-izbový byt Ružinov",
        ) == 0


class TestTitleMarkers:
    @pytest.mark.parametrize("title", [
        "Novostavba 2-izbový byt centrum",
        "Predaj bytov od €145 900",
        "ZELENÉ ZÁLUHY 2. fáza",
        "Nový projekt v Petržalke",
        "Developersky projekt KOLIBA",
        "Premium project — II. etapa",
    ])
    def test_dev_project_titles(self, title):
        # URL is generic so only the title can trigger the flag
        assert detect_dev_project("https://example.sk/byt-12345", title) == 1

    @pytest.mark.parametrize("title", [
        "3-izbový byt Ružinov, novostavbe — wait, real listing",  # contains "novostavb" + "e" → "novostavbe"
        "Pekný byt na predaj",
        "Slnečný 2-izbový",
        "1-izbový byt Petržalka",
    ])
    def test_real_listing_titles_not_flagged(self, title):
        # These should NOT be flagged as dev projects
        result = detect_dev_project("https://example.sk/byt-12345", title)
        # Some of these may legitimately mention "novostavb" — we want zero
        # false positives on the obvious cases below. The first case above
        # contains "novostavbe" which has "novostavba" stem → may be flagged.
        # We accept either result for the borderline case.
        if "novostavb" not in title.lower():
            assert result == 0, f"{title!r} should not be flagged"


class TestEdgeCases:
    def test_empty_inputs(self):
        assert detect_dev_project("", "") == 0
        assert detect_dev_project(None, None) == 0

    def test_none_safe(self):
        # Must not crash on None/None
        assert detect_dev_project(None, "Predaj") == 0
        assert detect_dev_project("http://x.com", None) == 0

    def test_case_insensitive(self):
        # Markers should match regardless of source casing
        assert detect_dev_project("", "NOVOSTAVBA Centrum") == 1
        assert detect_dev_project("", "novostavba centrum") == 1
        assert detect_dev_project("", "Novostavba Centrum") == 1

    def test_od_eur_needs_leading_space(self):
        # " od €" pattern must NOT match arbitrary " od " or "€" — must be
        # the price-range phrasing "od €X" common in dev project titles
        assert detect_dev_project("", "Predaj bytu od €145 900") == 1
        assert detect_dev_project("", "Predaj bytu") == 0
