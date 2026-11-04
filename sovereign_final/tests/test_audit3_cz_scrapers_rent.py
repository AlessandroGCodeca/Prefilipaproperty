"""Regression tests for the third review, Czech scrapers and rents: one or
more per finding (#53, #54, #55, h4, h6, h7), on synthetic titles, ad text,
cards and CSV files only — no request leaves the test."""

import pytest

from engine import regional_prices_cz as rpcz
from scraper import bazos_cz, rentals_cz
from scraper import cz_common as cz

BAZOS = "https://reality.bazos.cz/inzerat/1/"
NOW = "2026-10-21T00:00:00+00:00"


def _bazos_card(n, title, desc, price, place):
    """A Bazoš card as the site lays it out: the photo link, then the title."""
    return (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="/inzerat/{n}/x.php"><img class="obrazek" src="x.jpg" alt="{title}"></a>'
            f'<h2 class="nadpis"><a href="/inzerat/{n}/x.php">{title}</a></h2>'
            f'<div class="popis">{desc}</div></div>'
            f'<div class="inzeratycena"><b>{price}</b></div>'
            f'<div class="inzeratylok">{place}</div></div>')


# ── #53: a house with a layout and a plot or garage is no flat ────────────────
@pytest.mark.parametrize("title,slug", [
    ("Prodej domu 5+kk s pozemkem", "prodej-domu-5kk-s-pozemkem.php"),
    ("Prodej RD 4+kk se zahradou a pozemkem 800 m2",
     "prodej-rd-4kk-se-zahradou-a-pozemkem-800-m2.php"),
    ("Prodej domu 5+1 s pozemkem", None),
    ("Prodám RD 5+1 s garáží", None),
    ("Prodej domku 3+1 se zahradou a pozemkem", None),
    ("Prodej 4+1 rodinný dům", None),
    ("Prodej 3+1 chalupa", None),
])
def test_a_house_with_a_layout_and_a_plot_is_not_a_flat(title, slug):
    assert cz.is_excluded_cz(title) is True
    if slug:
        assert cz.is_excluded_cz(BAZOS + slug) is True
        assert cz.is_excluded_cz(title, BAZOS + slug) is True


@pytest.mark.parametrize("title", [
    "Prodej bytu 3+kk s pozemkem", "Prodej 3+1 s pozemkem", "Prodej 2+kk s garáží",
    BAZOS + "prodej-2kk-s-garazi.php", "Prodám 3+1 s parkovacím stáním",
    "Prodej 2+kk v domě s garáží", "Prodej bytu 2+1 v RD s pozemkem",
    "Prodej 2+1 v RD s pozemkem", "Prodej 3+1 v domku s garáží",
])
def test_a_flat_with_its_plot_or_garage_stays_a_flat(title):
    assert cz.is_excluded_cz(title) is False


def test_a_house_card_in_the_bazos_flat_feed_is_dropped():
    page = ("<html>"
            + _bazos_card(301, "Prodej domu 5+kk s pozemkem", "Dům se zahradou.",
                          "6 900 000 Kč", "Kolín<br>280 02")
            + _bazos_card(302, "Prodej 2+kk s garáží, 54 m2", "Byt s garáží.",
                          "4 200 000 Kč", "Kolín<br>280 02")
            + "</html>")
    recs = bazos_cz.parse_page(page, NOW)
    assert [r["title"] for r in recs] == ["Prodej 2+kk s garáží, 54 m2"]


# ── #54: a flat with a share of its garden, garage or yard is a whole flat ────
@pytest.mark.parametrize("title", [
    "Prodej bytu 3+1 s podílem 1/4 na zahradě",
    "Prodej bytu 2+1 + podíl 1/2 na garáži",
    "Prodám byt 3+kk, podíl 1/3 zahrady",
    "Prodej bytu 3+1 včetně podílu 1/6 na dvoře",
    "Prodej bytu 2+kk s podílem 1/8 na garáži",
    "Prodej bytu 2+kk, 1/2 podílu na parkovacím stání",
    "Prodej bytu 2+1 s podílem 1/12 na pozemku",
])
def test_a_flat_with_a_share_of_its_garden_garage_or_yard_is_kept(title):
    assert cz.is_excluded_cz(title) is False


@pytest.mark.parametrize("title", [
    "Prodej podílu 1/2 bytu 3+1", "Prodám 1/2 bytu", "Prodej id. 1/2 bytu 2+kk",
    "Prodej bytu 2+1, podíl 1/2", "Prodej bytu 2+kk, 1/2 podílu",
])
def test_a_share_of_a_flat_is_still_no_flat(title):
    assert cz.is_excluded_cz(title) is True


# ── #55: a deposit named a few words before its amount is not the rent ───────
@pytest.mark.parametrize("text", [
    "Vratná kauce ve výši dvou nájmů 30 000 Kč. Nájem 15 000 Kč.",
    "Kauce ve výši 2 nájmů 30 000 Kč. Nájem 15 000 Kč.",
    "Vratná kauce ve výši dvou měsíčních nájmů 30 000 Kč, nájemné 15 000 Kč.",
    "Vratná kauce ve výši trojnásobku měsíčního nájemného 45 000 Kč. Nájemné 15 000 Kč",
])
def test_a_deposit_named_several_words_before_its_amount_is_not_the_rent(text):
    assert rentals_cz.rent_from_text(text) == 15_000


@pytest.mark.parametrize("text,rent", [
    ("Kauce ve výši jednoho nájmu 15 000 Kč", 0),     # a deposit alone: no rent
    ("Kauce dva nájmy a nájem 15 000 Kč", 15_000),     # the rent's own label
    ("Kauce 30 000 Kč a nájem 15 000 Kč", 15_000),     # an earlier amount never bridges
    ("Kauce 30 000 Kč nájem 15 000 Kč", 15_000),
    ("Nájem 15 000 Kč, kauce ve výši dvou nájmů 30 000 Kč", 15_000),
])
def test_the_deposit_bridge_stops_at_the_rent(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


@pytest.mark.parametrize("text", [
    "Nájem 15 000 Kč energie zvlášť", "Nájem 15 000 Kč měsíčně energie zvlášť",
    "Nájem 15 000 Kč energie se platí zvlášť", "Nájem 15 000 Kč služby navíc",
    "Nájem 15 000 Kč energie v ceně",
])
def test_energies_billed_apart_or_included_leave_the_rent(text):
    assert rentals_cz.rent_from_text(text) == 15_000


@pytest.mark.parametrize("text,rent", [
    ("4 500 Kč měsíčně energie", 0), ("3 000 Kč na služby", 0),
    ("Cena 15 000 Kč + 4 500 Kč měsíčně energie", 15_000),
    ("Nájem 15 000 Kč, 4 500 Kč/měs. energie", 15_000),
])
def test_an_amount_labelled_energie_after_it_is_still_no_rent(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


def test_a_bazos_rental_card_without_a_price_reads_the_rent_not_the_deposit():
    page = ("<html>" + _bazos_card(
        401, "Pronájem bytu 2+kk, 55 m2",
        "Vratná kauce ve výši dvou nájmů 30 000 Kč. Nájem 15 000 Kč, energie zvlášť.",
        "Dohodou", "Kladno<br>272 01") + "</html>")
    (rec,) = rentals_cz.parse_bazos_page(page, NOW)
    assert rec["rent_eur"] == 15_000 and rec["size_m2"] == 55


# ── h4: a services line "bez energií" is no rent; "nájemné celkem" is ────────
@pytest.mark.parametrize("text", [
    "Nájemné 15 000 Kč. Zálohy na služby bez energií 2 500 Kč/měs.",
    "Nájemné 15 000 Kč, služby bez energií 2 500 Kč měsíčně",
    "Nájemné 15 000 Kč; zálohy na služby bez energií 2 500 Kč měsíčně",
])
def test_a_services_charge_without_energies_is_not_the_rent(text):
    assert rentals_cz.rent_from_text(text) == 15_000


@pytest.mark.parametrize("text,rent", [
    ("Zálohy bez energií 2 500 Kč", 0), ("Kauce bez provize 30 000 Kč", 0),
    ("Nájem bez energií 14 000 Kč", 14_000), ("Měsíční nájem bez energií 14 000 Kč", 14_000),
    ("Nájem bez energií a služeb 14 000 Kč", 14_000), ("Bez kauce 15 000 Kč", 15_000),
    ("Nájemné včetně služeb 18 000 Kč", 18_000),
])
def test_bez_and_vcetne_say_what_the_rent_covers_only_for_the_rent(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


@pytest.mark.parametrize("text,rent", [
    ("Nájemné celkem 15 000 Kč/měsíc.", 15_000),
    ("Pronájem celkem 15 000 Kč/měs.", 15_000), ("Celkové nájemné 15 000 Kč", 15_000),
    ("Nájemné vč. služeb celkem 18 000 Kč", 18_000),
    ("Nájem 12 000 Kč, nájemné celkem 15 000 Kč/měs.", 12_000),    # the bare rent wins
    ("Nájem bez energií 14 000 Kč, energie cca 2 500 Kč, celkem 16 500 Kč", 14_000),
    ("Celkem k úhradě 60 000 Kč", 0),
])
def test_a_rent_total_is_the_rent_only_without_a_bare_rent(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


# ── h6: "Benešov u Prahy" is the town Benešov ─────────────────────────────────
@pytest.fixture
def no_medians(monkeypatch):
    for table in ("KRAJ_MEDIAN", "OKRES_MEDIAN", "PRAHA_DISTRICT_MEDIAN",
                  "BRNO_DISTRICT_MEDIAN", "MEDIAN_SOURCE"):
        monkeypatch.setattr(rpcz, table, {})
    monkeypatch.setattr(rpcz, "_TABLES", {"kraj": rpcz.KRAJ_MEDIAN, "okres": rpcz.OKRES_MEDIAN,
                                          "praha": rpcz.PRAHA_DISTRICT_MEDIAN,
                                          "brno": rpcz.BRNO_DISTRICT_MEDIAN})
    monkeypatch.setattr(rpcz, "SOURCE", dict(rpcz._DEFAULT_SOURCE))


def test_benesov_u_prahy_is_okres_benesov(tmp_path, no_medians):
    district = bazos_cz.place("Benešov u Prahy 256 01")
    assert district == "Benešov u Prahy"
    for d in (district, "Benešov u Prahy 256 01", "benesov u prahy"):
        assert rpcz.okres_for_district(d) == "Benešov"
        assert rpcz.kraj_for_district(d) == "STC"
    # Other "Benešov nad / u X" places are still not okres Benešov.
    assert rpcz.okres_for_district("Benešov nad Ploučnicí") is None
    assert rpcz.okres_for_district("Benešov u Testova") is None
    assert rpcz.okres_for_district("Benešov nad Ploučnicí, okres Děčín") == "Děčín"
    f = tmp_path / "m.csv"
    f.write_text("level,name,median_czk_m2,period,source\n"
                 "okres,Benešov,62000,2026,test\n", encoding="utf-8")
    rpcz.load_medians(str(f))
    assert rpcz.median_source(district) == (62_000.0, "okres Benešov")


# ── h7: an obce CSV's header row is never a town ──────────────────────────────
@pytest.mark.parametrize("header,row", [
    ("Obec,Okres", "Abertamy,Karlovy Vary"), ("Název,Kód", "Abertamy,1"),
    ("Kód obce,Název obce", "1,Abertamy"), ("NÁZEV", "Abertamy"), ("nazev,kod", "Abertamy,1"),
])
def test_an_obce_csv_header_is_never_a_town(tmp_path, monkeypatch, header, row):
    f = tmp_path / "cz_obce.csv"
    f.write_text(f"{header}\n{row}\n", encoding="utf-8")
    monkeypatch.setattr(cz, "CZ_OBCE_CSV", str(f))
    monkeypatch.setattr(cz, "_places", None)
    assert cz._load_obce() == ["Abertamy"]


def test_the_word_obec_in_an_ad_is_no_place(tmp_path, monkeypatch):
    f = tmp_path / "cz_obce.csv"
    f.write_text("Obec,Okres\nAbertamy,Karlovy Vary\nAdamov,Blansko\n", encoding="utf-8")
    monkeypatch.setattr(cz, "CZ_OBCE_CSV", str(f))
    monkeypatch.setattr(cz, "_places", None)
    assert cz.place_from_text("Byt 2+1, Obec Abertamy") == "Abertamy"
    assert cz.place_from_text("Klidná lokalita. Obec má školu.") == ""
    # A file with no header still keeps its first town.
    f.write_text("Abertamy\nAdamov\n", encoding="utf-8")
    assert cz._load_obce() == ["Abertamy", "Adamov"]
