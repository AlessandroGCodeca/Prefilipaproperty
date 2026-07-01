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
