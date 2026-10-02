"""Tests for scraper/nehnutelnosti.py::_parse_slug's city/district hint — the
fallback location for listings whose JSON-LD and rendered text name none."""

import unicodedata

import pytest

from config import RENT_PER_M2
from engine.financial import get_rent_estimate
from scraper.nehnutelnosti import _SLUG_CITIES, _parse_slug


def _district(slug: str) -> str:
    return _parse_slug(f"https://www.nehnutelnosti.sk/detail/Ju1/{slug}").get(
        "district", "")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).lower()


class TestLongerTownNamesWin:
    @pytest.mark.parametrize("slug,expected", [
        ("2-izbovy-byt-nove-mesto-nad-vahom", "Nové Mesto nad Váhom"),
        ("3-izbovy-byt-nove-mesto-n-vahom",   "Nové Mesto nad Váhom"),
        # One town, not that town plus Bratislava's "Nové Mesto".
        ("byt-kysucke-nove-mesto",            "Kysucké Nové Mesto"),
    ])
    def test_town_not_read_as_bratislava(self, slug, expected):
        assert _district(slug) == expected

    def test_bratislava_nove_mesto_still_resolves(self):
        assert _district("3-izbovy-byt-nove-mesto") == "Nové Mesto"
        assert _district("byt-petrzalka-bratislava") == "Petržalka, Bratislava"

    def test_no_slug_town_is_checked_after_a_name_it_contains(self):
        # A name checked earlier would match inside the longer one first.
        for i, longer in enumerate(_SLUG_CITIES):
            for shorter in _SLUG_CITIES[:i]:
                assert f"-{shorter}-" not in f"-{longer}-", (
                    f"{shorter!r} is checked before {longer!r}, which contains it")


class TestDiacritics:
    @pytest.mark.parametrize("slug,expected", [
        ("byt-komarno",           "Komárno"),
        ("byt-nove-zamky-centrum", "Nové Zámky"),
        ("byt-partizanske",       "Partizánske"),
        ("byt-lucenec",           "Lučenec"),
        ("byt-sala",              "Šaľa"),
        ("byt-vrable",            "Vráble"),
    ])
    def test_town_spelled_like_its_rent_key(self, slug, expected):
        district = _district(slug)
        assert district == expected
        assert district.lower() in RENT_PER_M2

    def test_every_slug_town_with_a_rent_rate_uses_its_spelling(self):
        # An unaccented "Komarno" matches no RENT_PER_M2 key and falls to the
        # default rate. Any slug town that has a rate must be spelled like it.
        keys = {_fold(k): k for k in RENT_PER_M2}
        for slug in _SLUG_CITIES:
            name = _district(f"byt-{slug}")
            key = keys.get(_fold(name))
            if key:
                assert name.lower() == key, f"{slug!r} -> {name!r}, key {key!r}"

    def test_lucenec_priced_at_its_own_rate(self):
        assert get_rent_estimate(_district("byt-lucenec"), 1) == \
            pytest.approx(RENT_PER_M2["lučenec"])
