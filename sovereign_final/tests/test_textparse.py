"""Tests for scraper/textparse.py::rooms_from_title — the title-based rooms
fallback that lets the ±15% per-m² rooms rent multiplier fire for sources that
carry no structured rooms count (bazos, topreality, most nehnutelnosti rows)."""

import pytest

from scraper.textparse import rooms_from_title


class TestIzbPatterns:
    @pytest.mark.parametrize("title,expected", [
        ("3-izbový byt, Dúbravka",              3),
        ("2-izbový byt na predaj, Petržalka",   2),
        ("1-izbovy byt v centre",                1),   # no diacritics
        ("4-IZBOVÝ BYT, Karlova Ves",           4),   # uppercase
        ("Predám 2-izb. byt, Nitra",            2),   # abbreviated
        ("3 izbový byt s balkónom",             3),   # space instead of hyphen
        ("2izb byt Žilina",                     2),   # no separator
        ("1-izb. byt (dražba), Klokočina",      1),
        ("5-izbový mezonet",                    5),
    ])
    def test_extracts_room_count(self, title, expected):
        assert rooms_from_title(title) == expected

    def test_garsonka_is_one_room(self):
        assert rooms_from_title("Garsónka na predaj, Ružinov") == 1
        assert rooms_from_title("garzónka v centre") == 1
        assert rooms_from_title("Predám garsonku") == 1


class TestNoFalsePositives:
    @pytest.mark.parametrize("title", [
        "",                                     # empty
        None,                                   # missing
        "Byt na predaj, Bratislava",            # no room count stated
        "Novostavba pri jazere",                # nothing numeric
        "Pozemok 800 m2, Senec",                # size, not rooms
        "Byt 65 m2 s balkónom",                 # only size
        "7-izbový kaštieľ",                     # out of 1–6 range → not matched
    ])
    def test_returns_none(self, title):
        assert rooms_from_title(title) is None

    def test_price_digits_not_mistaken_for_rooms(self):
        # "…129 000 € … 3-izbový…" must return 3, not something from the price
        assert rooms_from_title("Predaj za 129 000 €, 3-izbový byt") == 3


# ── area_from_text ────────────────────────────────────────────────────────────
from scraper.textparse import area_from_text  # noqa: E402


class TestAreaFromText:
    @pytest.mark.parametrize("text,expected", [
        ("3-izbový byt 74 m2", 74.0),
        ("58m² byt v centre", 58.0),
        ("Predaj 2-izb, 46,41 m²", 46.41),
        ("úžitková plocha 120 m²", 120.0),
    ])
    def test_reads_the_area(self, text, expected):
        assert area_from_text(text) == expected

    def test_loggia_is_not_the_flat(self):
        """This put a 6 m² flat priced at €182 000 into the database — the
        bare-m form matched the loggia before the flat's own area."""
        assert area_from_text("1,5-izb.byt s 6m logiou, komplet.rek, Jaltská") == 0.0

    def test_explicit_m2_wins_over_an_earlier_bare_m(self):
        assert area_from_text("balkón 6m, byt 62 m²") == 62.0

    def test_scans_past_an_implausible_first_match(self):
        assert area_from_text("pivnica 4 m², byt 70 m²") == 70.0

    @pytest.mark.parametrize("text", [
        "", "byt bez rozlohy", "garáž 12 m²", "pozemok 5000 m²",
    ])
    def test_nothing_plausible(self, text):
        assert area_from_text(text) == 0.0

    def test_bounds_are_tunable(self):
        assert area_from_text("garáž 12 m²", min_m2=5.0) == 12.0
