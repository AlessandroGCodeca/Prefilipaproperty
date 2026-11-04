"""Regression tests for the fourth review, Czech scrapers (C11, C14): on
synthetic titles, URL slugs and Bazoš cards only — no request leaves the test."""

import pytest

from scraper import bazos_cz
from scraper import cz_common as cz

BAZOS = "https://reality.bazos.cz/inzerat/1/"
NOW = "2026-10-22T00:00:00+00:00"


def _bazos_card(n, title, desc, price, place):
    """A Bazoš card as the site lays it out: the photo link, then the title."""
    return (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="/inzerat/{n}/x.php"><img class="obrazek" src="x.jpg" alt="{title}"></a>'
            f'<h2 class="nadpis"><a href="/inzerat/{n}/x.php">{title}</a></h2>'
            f'<div class="popis">{desc}</div></div>'
            f'<div class="inzeratycena"><b>{price}</b></div>'
            f'<div class="inzeratylok">{place}</div></div>')


# ── C11: a flat's own building named after its layout is no house ────────────
@pytest.mark.parametrize("title", [
    "Prodej 3+kk, cihlový dům, garáž",
    "Prodej 2+kk, bytový dům s garáží",
    "Prodám 2+1, cihlový dům, parkovací stání",
    "Prodej 2+kk, nový dům, garážové stání",
    "Prodej 3+1, dům s výtahem, garáž",
    "Prodej 2+kk - novostavba domu, parkovací stání",
    "Prodej 3+kk v novostavbě bytového domu s garáží",
    BAZOS + "prodej-3kk-cihlovy-dum-garaz.php",
    # Still kept, as before audit 3 and after it.
    "Prodej 2+kk s garáží", "Prodej 2+kk v domě s garáží", "Prodej 2+1 v RD s pozemkem",
])
def test_a_flat_naming_its_own_building_keeps_its_garage_or_parking(title):
    assert cz.is_excluded_cz(title) is False


@pytest.mark.parametrize("title", [
    # A house noun before the layout ...
    "Prodej domu 5+1 s pozemkem", "Prodej RD 4+kk se zahradou a pozemkem 800 m2",
    BAZOS + "prodej-domu-5kk-s-pozemkem.php", "Dům 5+1 s pozemkem",
    "RD 4+kk, pozemek 800 m2", "Prodej, dům 5+1, pozemek",
    # ... or right after it names the house that is sold.
    "Prodej 5+1 RD s pozemkem", "Prodej 4+kk dům se zahradou a garáží",
    BAZOS + "prodej-5kk-rd-s-pozemkem.php",
    "Prodej 4+1 rodinný dům", "Prodej 3+1 chalupa",
])
def test_a_house_with_a_layout_and_a_plot_is_still_not_a_flat(title):
    assert cz.is_excluded_cz(title) is True


def test_bazos_flat_cards_naming_their_building_are_kept():
    page = ("<html>"
            + _bazos_card(501, "Prodej 3+kk, cihlový dům, garáž", "Byt 72 m2.",
                          "6 490 000 Kč", "Brno<br>602 00")
            + _bazos_card(502, "Prodej 2+kk, bytový dům s garáží", "Byt 54 m2.",
                          "4 290 000 Kč", "Plzeň<br>301 00")
            + _bazos_card(503, "Prodej domu 5+kk s pozemkem", "Dům se zahradou.",
                          "6 900 000 Kč", "Kolín<br>280 02")
            + "</html>")
    recs = bazos_cz.parse_page(page, NOW)
    assert [(r["title"], r["price_eur"], r["size_m2"], r["district"]) for r in recs] == [
        ("Prodej 3+kk, cihlový dům, garáž", 6_490_000.0, 72.0, "Brno"),
        ("Prodej 2+kk, bytový dům s garáží", 4_290_000.0, 54.0, "Plzeň"),
    ]


# ── C14: a flat with a share of its land, common parts or cellar is a flat ────
@pytest.mark.parametrize("title", [
    "Prodej bytu 2+kk se spoluvlastnickým podílem na pozemku",
    "Prodej bytu 3+kk se spoluvlastnickým podílem na zahradě",
    "Prodej bytu 2+kk se spoluvlastnickým podílem 1/12 na pozemku",
    "Prodej bytu 2+kk se spoluvlastnickým podílem na garáži",
    "Prodej 2+kk se spoluvlastnickým podílem na pozemku",
    "Prodej bytu 3+1 se spoluvlastnickým podílem na společných částech domu",
    BAZOS + "prodej-bytu-2kk-se-spoluvlastnickym-podilem-na-pozemku.php",
    "Prodej bytu 3+1, podíl 1/10 na společných částech domu",
    "Prodej bytu 2+kk, 1/6 podíl na sklepě",
    "Prodej bytu 2+kk s podílem 1/2 na sklepní kóji",
])
def test_a_flat_with_a_share_of_its_land_common_parts_or_cellar_is_kept(title):
    assert cz.is_excluded_cz(title) is False


@pytest.mark.parametrize("title", [
    "Prodej spoluvlastnického podílu na bytě 2+1",
    "Prodej spoluvlastnického podílu 1/2 na bytě 3+1 se zahradou",
    "Spoluvlastnický podíl 1/2 bytu 2+kk",
    "Prodej bytu 2+1 - spoluvlastnický podíl 1/2",
    "Prodej spoluvlastnického podílu bytu se sklepem",
    BAZOS + "prodej-spoluvlastnickeho-podilu-bytu.php",
    "Prodej 1/2 bytu 2+kk se spoluvlastnickým podílem na pozemku",
    "Prodej bytu 2+1, podíl 1/2 společně s garáží",
    # A share of land, garden or cellar alone, with no flat named before it.
    "Prodej spoluvlastnického podílu 1/2 pozemku",
    "Prodej spoluvlastnického podílu na zahradě",
    "Prodej spoluvlastnického podílu 1/2 na sklepě",
    "Spoluvlastnický podíl na pozemku, byt 2+kk",
    # A house's co-owned garden or plot is no flat's.
    "Prodej domu 5+1 se spoluvlastnickým podílem na zahradě",
    "Prodej RD 4+kk se spoluvlastnickým podílem na pozemku",
])
def test_a_co_owned_share_of_a_flat_or_of_land_alone_is_still_excluded(title):
    assert cz.is_excluded_cz(title) is True


def test_a_bazos_flat_card_with_its_land_share_is_kept():
    page = ("<html>"
            + _bazos_card(601, "Prodej bytu 2+kk se spoluvlastnickým podílem na pozemku",
                          "Byt 54 m2.", "4 290 000 Kč", "Plzeň<br>301 00")
            + _bazos_card(602, "Prodej spoluvlastnického podílu na bytě 2+1",
                          "Podíl 1/2.", "1 900 000 Kč", "Plzeň<br>301 00")
            + "</html>")
    recs = bazos_cz.parse_page(page, NOW)
    assert [r["title"] for r in recs] == ["Prodej bytu 2+kk se spoluvlastnickým podílem na pozemku"]
