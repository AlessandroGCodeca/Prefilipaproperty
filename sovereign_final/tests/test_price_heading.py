"""Tests for reading the listing's OWN price off a nehnutelnosti detail page.

Every detail page renders a promoted-listings carousel, and a live DOM probe of
a €342 000 Ružinov flat showed why scanning the page was wrong:

    €342,000    p.MuiTypography-root.MuiTypography-h3.mui-tokrpc      ← its own
    €1,399,000  p.MuiTypography-root.MuiTypography-body2.noWrap       ← carousel
    €570,720    p.MuiTypography-root.MuiTypography-body2.noWrap       ← carousel
    €446,736    p.MuiTypography-root.MuiTypography-body2.noWrap       ← carousel
    €279,800    p.MuiTypography-root.MuiTypography-body2.noWrap       ← carousel
    €1,200      p.MuiTypography-root.MuiTypography-body2.noWrap       ← "€/mes."

The ancestor chains are identical (MUI emotion hashes), so the discriminator is
the typography variant: the listing's own price is a heading, the carousel's are
body2. The listing's price is also NOT the largest on the page, which is how
€1 399 000 ended up stored against flats of 200, 188 and 114 m².
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.nehnutelnosti import (  # noqa: E402
    _fallback_price, _heading_price, _prices_in, _PRICE_HEADING_SELECTOR,
    _MULTI_PRICE_PAGE_THRESHOLD,
)

NBSP = " "

# The four carousel prices, verbatim from the live probe.
CAROUSEL = [1_399_000.0, 570_720.0, 446_736.0, 279_800.0]


class TestPricesIn:
    @pytest.mark.parametrize("text,expected", [
        (f"342{NBSP}000 €", [342_000.0]),
        ("342 000 €", [342_000.0]),
        ("342 000 €", [342_000.0]),      # narrow NBSP
        ("342 000 €", [342_000.0]),      # thin space
        ("68000 €", [68_000.0]),
        (f"1{NBSP}399{NBSP}000 € a 570{NBSP}720 €", [1_399_000.0, 570_720.0]),
    ])
    def test_reads_prices(self, text, expected):
        assert _prices_in(text) == expected

    @pytest.mark.parametrize("text", [
        "", None, "byt na predaj", "1 200 €",            # below the 30k floor
        "3 273 €/m²",                                    # per-m² rate, too small
        "99 000 000 €",                                  # above the 10M ceiling
    ])
    def test_implausible_or_absent(self, text):
        assert _prices_in(text) == []


class TestHeadingPrice:
    def test_reads_the_listings_own_price(self):
        assert _heading_price([f"342{NBSP}000 €"]) == 342_000.0

    def test_monthly_rent_is_not_a_sale_price(self):
        """The carousel carries a rental at '1 200 €/mes.'; a heading could too."""
        assert _heading_price([f"1{NBSP}200 €/mes."]) == 0.0
        assert _heading_price(["185 000 € mesiac"]) == 0.0

    def test_skips_headings_without_a_price(self):
        texts = ["3-izbový byt Ružinov", "", None, f"342{NBSP}000 €"]
        assert _heading_price(texts) == 342_000.0

    def test_takes_the_first_priced_heading(self):
        assert _heading_price([f"342{NBSP}000 €", f"999{NBSP}000 €"]) == 342_000.0

    def test_no_headings_at_all(self):
        assert _heading_price([]) == 0.0
        assert _heading_price(None) == 0.0


class TestFallbackPrice:
    """Reached only when the page has no price heading."""

    def test_multi_property_page_stores_no_price(self):
        """The €1 399 000 page: several prices, none of them identifiably ours.
        Guessing is exactly what put that price on three different flats."""
        text = " ".join(f"{p:,.0f} €".replace(",", NBSP) for p in CAROUSEL)
        assert _fallback_price(text, size_m2=200.0, district="Bratislava") == 0.0

    def test_single_price_page_is_trusted(self):
        assert _fallback_price(f"342{NBSP}000 €", 82.0, "Ružinov") == 342_000.0

    def test_two_prices_takes_the_larger(self):
        """A deposit or per-m² rate alongside the sale price — the case that
        motivated taking the maximum in the first place."""
        text = f"rezervačná záloha 35{NBSP}000 € … cena 189{NBSP}000 €"
        assert _fallback_price(text, 58.0, "Bratislava") == 189_000.0

    def test_repeated_price_is_one_distinct_value(self):
        """Pages render each figure twice (the probe saw every price doubled),
        which must not count as a multi-property page."""
        text = f"342{NBSP}000 € 342{NBSP}000 €"
        assert _fallback_price(text, 82.0, "Ružinov") == 342_000.0

    def test_threshold_is_on_distinct_values(self):
        prices = [100_000.0, 200_000.0, 300_000.0][:_MULTI_PRICE_PAGE_THRESHOLD]
        text = " ".join(f"{int(p)} €" for p in prices)
        assert _fallback_price(text, 60.0, "Bratislava") == 0.0

    def test_absurd_per_m2_still_filtered(self):
        """pick_sale_price's regional check still applies below the threshold."""
        text = f"250{NBSP}000 € … 1{NBSP}250{NBSP}000 €"
        assert _fallback_price(text, 54.0, "Bratislava") == 250_000.0

    def test_no_prices(self):
        assert _fallback_price("byt na predaj", 60.0, "Bratislava") == 0.0
        assert _fallback_price("", 60.0, "Bratislava") == 0.0


class TestHeadingSelector:
    def test_covers_mui_heading_variants(self):
        """MuiTypography-h3 is what the live page used; the emotion hash beside
        it (mui-tokrpc) changes between builds and must not be relied on."""
        for n in range(1, 6):
            assert f"[class*='MuiTypography-h{n}']" in _PRICE_HEADING_SELECTOR
        assert "mui-tokrpc" not in _PRICE_HEADING_SELECTOR

    def test_covers_plain_heading_tags(self):
        """So a move off MUI doesn't take the whole price path down with it."""
        for tag in ("h1", "h2", "h3"):
            assert tag in _PRICE_HEADING_SELECTOR.split(", ")

    def test_does_not_match_carousel_styling(self):
        assert "body2" not in _PRICE_HEADING_SELECTOR
        assert "noWrap" not in _PRICE_HEADING_SELECTOR
