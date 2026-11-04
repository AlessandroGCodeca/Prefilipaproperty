"""Regression tests for the third review, Slovak scrapers and rent comps: one
or more per finding, on synthetic text, synthetic pages and synthetic cards
only — no real listing, no real person, no request leaves the test."""

import json

import pytest
from bs4 import BeautifulSoup

from engine import regional_prices as rp
from engine import rent_comps
from engine.financial import match_rent_key
from scraper import bazos, rentals, topreality
from scraper.nehnutelnosti import (
    _apply_detail, _detail_district, _extract_location_from_text, _merge_ld,
    _minimal_listing, _parse_api_item,
)
from scraper.textparse import area_from_text, is_excluded_listing

NOW = "2026-10-21T00:00:00+00:00"
NEH_URL = "https://www.nehnutelnosti.sk/detail/JuTest1/"


def _bazos_card(title, desc, price, place, n=1):
    """A Bazoš card as the site lays it out: the photo link first, the title
    in h2, then the text, the price and the location."""
    html = (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="/inzerat/{n}/x.php"><img class="obrazek" src="x.jpg"></a>'
            f'<h2 class="nadpis"><a href="/inzerat/{n}/x.php">{title}</a></h2>'
            f'<div class="popis">{desc}</div></div>'
            f'<div class="inzeratycena"><b>{price}</b></div>'
            f'<div class="inzeratylok">{place}</div></div>')
    card = BeautifulSoup(html, "html.parser").select_one("div.inzeratyflex")
    return card, card.select_one("h2 a")


def _topreality_page(title, body, ld=None):
    script = (f'<script type="application/ld+json">{json.dumps(ld)}</script>'
              if ld else "")
    return (f'<html><head><meta property="og:title" content="{title}">{script}'
            f'</head><body>{body}</body></html>')


# ── #0: the listing's own town, not the longest name in the text ──────────────
@pytest.mark.parametrize("text,expected", [
    ("Predaj 2-izbového bytu, Senec. Ideálne pre ľudí pracujúcich v Bratislave.", "Senec"),
    ("Predaj 3-izbového bytu v Nitre. Maklér: Martin Testovací", "Nitra"),
    ("Predaj bytu Modra. Kontakt: Martin", "Modra"),
    ("Byty Bratislava | 2-izbový byt, Senec", "Senec"),
    ("Byty Bratislava | 2-izbový byt, Nitra", "Nitra"),
    ("Predaj 2-izbového bytu, Senec. Pracujete v Petržalke?", "Senec"),
])
def test_the_first_town_named_wins_not_the_longest(text, expected):
    assert _extract_location_from_text(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Maklér Martin Testovací ponúka byt v Nitre", "Nitra"),
    ("Kontakt: Ing. Martin Testovací, byt v Nitre", "Nitra"),
    ("Predaj bytu, Pezinok. Info: pán Martin", "Pezinok"),
    ("Info: pán Martin. Predaj bytu, Pezinok", "Pezinok"),
    ("Kontaktujte Martin Testovací. Byt v Senci", "Senec"),
    ("Ing. Martin Testovací ponúka 2-izbový byt, Senec", "Senec"),
    ("Bratislava, rýchly prístup na diaľnicu smer Trnava", "Bratislava"),
    ("Bratislava - Ružinov, diaľnica smer Senec", "Ružinov, Bratislava"),
])
def test_a_person_or_a_direction_is_not_the_flats_town(text, expected):
    assert _extract_location_from_text(text) == expected


@pytest.mark.parametrize("text", [
    "Predám 3-izbový byt v Martine", "Predaj bytu Martin - Sever", "Martin, 2-izbový byt",
])
def test_martin_the_town_is_still_martin(text):
    assert _extract_location_from_text(text) == "Martin"


@pytest.mark.parametrize("text,expected", [
    ("Bratislava 821 01", "Bratislava"),
    ("Bratislava - Petržalka, 2-izbový", "Petržalka, Bratislava"),
    ("Košice - Staré Mesto", "Staré Mesto, Košice"),
    ("Košice, 3-izbový byt", "Košice"),
])
def test_a_hub_counts_when_nothing_else_is_named(text, expected):
    assert _extract_location_from_text(text) == expected


def test_a_commuter_sentence_no_longer_prices_senec_as_bratislava():
    text = "Predaj 2-izbového bytu, Senec. Ideálne pre ľudí pracujúcich v Bratislave."
    district = _extract_location_from_text(text)
    assert rp.regional_median_price(district) == rp.regional_median_price("Senec")
    assert rp.regional_median_price(district) < rp.regional_median_price("Bratislava")


def test_topreality_body_text_gives_the_listings_own_town():
    page = _topreality_page(
        "Predaj 2-izbového bytu, Senec",
        "Predaj 2-izbového bytu, Senec. Byt 55 m2 pre ľudí pracujúcich v Bratislave. "
        "Cena 179 000 €")
    rec = topreality._build_listing_from_detail(
        "https://www.topreality.sk/x-r1234567.html", page, NOW)
    assert rec["district"] == "Senec"


@pytest.mark.parametrize("location,title,text,district", [
    ("Senec 903 01", "Prenájom 2-izbového bytu",
     "55 m2, pre ľudí pracujúcich v Bratislave. Cena 650 €", "Senec"),
    ("Nitra 949 01", "Prenájom 2-izbového bytu",
     "55 m2, volajte Martin. Cena 520 €", "Nitra"),
    ("Nitra 949 01", "Prenájom 2-izbového bytu",
     "55 m2. Bližšie info: Martin Testovací. Cena 520 €", "Nitra"),
    # The title may still refine the portal's city to one of its parts.
    ("Bratislava 851 01", "Prenájom 2-izbového bytu Petržalka",
     "55 m2. Cena 650 €", "Petržalka, Bratislava"),
    # Another town the text mentions does not replace the portal's own.
    ("Bratislava 851 01", "Prenájom 2-izbového bytu",
     "55 m2, 20 minút autom je Senec. Cena 650 €", "Bratislava"),
    # No location field: the text decides.
    ("", "Prenájom 2-izbového bytu v Petržalke", "55 m2. Cena 650 €",
     "Petržalka, Bratislava"),
])
def test_a_rental_keeps_the_portals_own_location(location, title, text, district):
    rec = rentals.build_rental("bazos", "https://x/" + title + location, title, text,
                               location=location, now=NOW)
    assert rec["district"] == district
    assert rec["rent_key"] == match_rent_key(district)


# ── #2: a detail page's district keeps its city part ──────────────────────────
@pytest.mark.parametrize("address,district", [
    ("Petržalka, Bratislava", "Petržalka, Bratislava"),
    ("Staré Mesto, Bratislava", "Staré Mesto, Bratislava"),
    ("Hlavná 12, Košice - Staré Mesto, Košický kraj, 040 01", "Staré Mesto, Košice"),
    ("Hlavná 12, Petržalka, Bratislavský kraj", "Petržalka, Bratislava"),
    ("Hlavná 5, Košice", "Košice"),
    # A last part that is the town with more detail stays as it was.
    ("Bratislava III", "Bratislava III"),
    ("Hlavná 1, Košice-Juh, Košický kraj", "Košice-Juh"),
    # A town the matcher does not know: the last part that is no region/postcode.
    ("Hlavná 1, Testovská Ves, Bratislavský kraj, 900 99", "Testovská Ves"),
])
def test_apply_detail_keeps_the_city_part(address, district):
    listing = _minimal_listing(NEH_URL, "2 izbový byt", NOW)
    _apply_detail(listing, {"address": address})
    assert listing["district"] == district
    assert listing["address_raw"] == address


def test_a_city_part_keeps_its_own_rent_and_median():
    listing = _minimal_listing(NEH_URL, "2 izbový byt", NOW)
    _apply_detail(listing, {"address": "Staré Mesto, Bratislava"})
    assert match_rent_key(listing["district"]) == match_rent_key("Staré Mesto, Bratislava")
    assert rp.regional_median_price(listing["district"]) == \
        rp.regional_median_price("Staré Mesto, Bratislava")
    assert rp.regional_median_price(listing["district"]) != \
        rp.regional_median_price("Bratislava")


def test_a_json_ld_address_with_postcode_last_is_not_the_postcode():
    data = {}
    _merge_ld(data, {"@type": "Apartment", "address": {
        "streetAddress": "Hlavná 12", "addressLocality": "Košice - Staré Mesto",
        "addressRegion": "Košický kraj", "postalCode": "040 01"}})
    listing = _minimal_listing(NEH_URL, "2 izbový byt", NOW)
    _apply_detail(listing, data)
    assert listing["district"] == "Staré Mesto, Košice"
    assert match_rent_key(listing["district"]) != "default"


def test_topreality_detail_without_json_ld_keeps_the_city_part():
    page = _topreality_page("Predaj 2-izbového bytu",
                            "Lokalita: Bratislava - Petržalka. Plocha 50 m2. Cena 150 000 €")
    rec = topreality._build_listing_from_detail(
        "https://www.topreality.sk/x-r1234568.html", page, NOW)
    assert rec["address_raw"] == "Petržalka, Bratislava"
    assert rec["district"] == "Petržalka, Bratislava"


def test_topreality_json_ld_address_ending_in_its_region():
    ld = {"@type": "Apartment", "name": "2-izbový byt", "offers": {"price": 150000},
          "floorSize": {"value": 50},
          "address": {"streetAddress": "Hlavná 12", "addressLocality": "Petržalka",
                      "addressRegion": "Bratislavský kraj"}}
    rec = topreality._build_listing_from_detail(
        "https://www.topreality.sk/x-r1234569.html",
        _topreality_page("2-izbový byt", "Hlavná 12", ld), NOW)
    assert rec["district"] == "Petržalka, Bratislava"


def test_a_harvested_item_keeps_the_city_part():
    rec = _parse_api_item({"url": "/detail/JuTest2/byt", "title": "2-izbový byt",
                           "location": {"fullAddress": "Hlavná 5, Ružinov, Bratislava"}},
                          NOW)
    assert rec["district"] == "Ružinov, Bratislava"


def test_detail_district_of_nothing_is_nothing():
    assert _detail_district("") == ""
    assert _detail_district(None) == ""


# ── #3: a share of a flat is not the flat ─────────────────────────────────────
@pytest.mark.parametrize("title", [
    "Predaj spoluvlastníckeho podielu 1/2 na 3-izbovom byte",
    "Predám 1/2 bytu v Petržalke",
    "Predám podiel na byte",
    "Predaj 2/3 podielu 3-izbového bytu, Petržalka",
    "Predám id. 1/2 bytu",
    "Predám ideálnu 1/2 bytu",
    "Spoluvlastnícky podiel 3/4 na byte v Ružinove",
    "Podiel na 3-izbovom byte, Nitra",
])
def test_a_share_of_a_flat_is_excluded(title):
    assert is_excluded_listing(title)
    assert is_excluded_listing(title, "https://www.topreality.sk/x-r1234567.html")


def test_a_share_in_a_url_slug_is_excluded():
    assert is_excluded_listing("", "https://www.topreality.sk/predaj-podielu-na-byte-r1234567.html")


@pytest.mark.parametrize("title", [
    "Predaj 3-izbového bytu s podielom na pozemku",
    "Predaj 3-izb. bytu s podielom 1/2 na pozemku",
    "3-izbový byt, podiel na pozemku 1/3",
    "2-izbový byt, 1/2 poschodia",
    "3-izb. byt, 7/8 poschodie",
    "Predaj 2-izb. bytu, 2/2 podlažie",
    "Byt, spoluvlastnícky podiel na spoločných častiach domu",
    "Predaj 3-izbového bytu, spoluvlastnícky podiel 1/1",
    "Predaj 3/4-izbového bytu",
])
def test_a_whole_flat_with_a_land_share_or_a_floor_fraction_is_kept(title):
    assert not is_excluded_listing(title)


def test_bazos_drops_a_share_card():
    card, link = _bazos_card("Predám 1/2 bytu v Petržalke", "3-izbový byt, 75 m2",
                             "135 000 €", "Bratislava 851 01")
    assert bazos._build_listing_from_card(card, link) is None


def test_bazos_drops_other_excluded_cards_and_keeps_a_flat():
    card, link = _bazos_card("Predám garáž pri byte", "18 m2", "25 000 €", "Nitra 949 01")
    assert bazos._build_listing_from_card(card, link) is None
    card, link = _bazos_card("Predám 3-izbový byt v Nitre", "Byt 75 m2, po rekonštrukcii",
                             "135 000 €", "Nitra 949 01")
    rec = bazos._build_listing_from_card(card, link)
    assert rec["price_eur"] == 135_000 and rec["size_m2"] == 75 and rec["district"] == "Nitra"


# ── #4: a garden flat is a flat ───────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "3-izbový záhradný byt v Ružinove",
    "Záhradný 2-izbový byt s terasou, Ivanka pri Dunaji",
    "Predaj: 3i záhradný byt v novostavbe",
    "Záhradný byt 2+kk",
    "Predaj záhradného bytu, Petržalka",
    "Záhradný apartmán, Senec",
    "https://www.topreality.sk/3-izbovy-zahradny-byt-v-ruzinove-r1234567.html",
])
def test_a_garden_flat_is_not_excluded(text):
    assert not is_excluded_listing(text)


@pytest.mark.parametrize("text", [
    "Predaj záhrady", "Záhrada s chatkou", "Rodinný dom so záhradou",
    "Bytový dom so záhradou", "Záhradný domček pri byte", "Záhradná chatka",
])
def test_a_garden_itself_is_still_excluded(text):
    assert is_excluded_listing(text)


def test_topreality_harvests_a_garden_flat_link():
    html = ('<html><body>'
            '<a href="/3-izbovy-zahradny-byt-v-ruzinove-r1234567.html">x</a>'
            '<a href="/predaj-zahrady-senec-r1234568.html">y</a></body></html>')
    assert topreality._extract_listing_links(html) == [
        "https://www.topreality.sk/3-izbovy-zahradny-byt-v-ruzinove-r1234567.html"]


# ── #5 and h3: a room let is no whole-flat rent comp ──────────────────────────
ROOM_TEXT = "v 3-izbovom byte 70 m2, Ružinov, 320 €"


@pytest.mark.parametrize("title,text", [
    ("Ponúkam izbu na prenájom", ROOM_TEXT),
    ("Ponúkam na prenájom izbu", ROOM_TEXT),
    ("Dám izbu do prenájmu", ROOM_TEXT),
    ("Voľná izba od 1.11.", ROOM_TEXT),
    ("Samostatná izba pre 1 osobu", ROOM_TEXT),
    ("Na prenájom izba v Petržalke",
     "Izba 16 m2 v 3-izbovom byte, spoločná kuchyňa a kúpeľňa. Cena 380 € mesačne."),
    ("Prenájom - Ružinov, 15 m2", "Izba na prenájom v 3-izbovom byte, 350 €"),
    ("Prenájom: izba v Ružinove", ROOM_TEXT),
    ("Prenájom 3-izbového bytu", "Izba k prenájmu, 320 €"),
])
def test_room_lets_are_not_whole_flats(title, text):
    assert rent_comps.is_long_term_flat(title, text) is False
    assert rentals.build_rental("bazos", "https://x/" + title, title, text,
                                location="Bratislava 821 01", now=NOW) is None


@pytest.mark.parametrize("title,text", [
    ("Prenájom 2-izbového bytu", "Obývacia izba s kuchyňou, spálňa, 55 m2, 650 €"),
    ("Prenájom 2-izbového bytu, Ružinov", "Obývačka s kuchyňou a samostatná izba, 650 €"),
    ("Garsónka na prenájom", "Garsónka na prenájom. Izba 20 m2, kuchyňa, 450 €"),
    ("2-izbový byt na prenájom", "Byt na prenájom, izba s balkónom, 600 €"),
    ("Prenájom 3-izbového bytu", "Každá izba má balkón, 800 €"),
])
def test_whole_flats_that_name_a_room_are_still_flats(title, text):
    assert rent_comps.is_long_term_flat(title, text) is True


# ── #6: a facility ("zariadenie") is not furniture ────────────────────────────
@pytest.mark.parametrize("text", [
    "Prenájom 2-izbového bytu, Ružinov. V blízkosti škola, predškolské zariadenie, obchody.",
    "Prenájom 3-izbového bytu, v okolí zdravotnícke zariadenie, MHD",
    "Občianska vybavenosť: školské zariadenia, pošta.",
    "V dome je posilňovacie zariadenie.",
    "Kúpeľňa s novým sanitárnym zariadením.",
])
def test_a_facility_is_not_furniture(text):
    assert rent_comps.furnishing_from_text(text) == "unknown"


@pytest.mark.parametrize("text", [
    "kompletne zariadený byt", "zariadený nábytkom", "plne zariadená garsónka",
    "Byt je zariadený.", "Zariadené bývanie", "prenájom zariadeného bytu",
    "Prenájom bytu so zariadením",
])
def test_a_furnished_flat_is_still_furnished(text):
    assert rent_comps.furnishing_from_text(text) == "furnished"


def test_a_facility_no_longer_cuts_the_comps_rate():
    text = "Prenájom 2-izbového bytu. V blízkosti predškolské zariadenie."
    kind = rent_comps.furnishing_from_text(text)
    assert rent_comps.baseline_eur_per_m2(750, 55, 2, kind) == \
        pytest.approx(rent_comps.baseline_eur_per_m2(750, 55, 2, "unknown"))


# ── #7: a distance in metres is not the flat's area ───────────────────────────
@pytest.mark.parametrize("text", [
    "Predám 2-izbový byt v Petržalke, 300 m od zastávky MHD, cena 165 000 €",
    "3 izbový byt, 2. poschodie, 150 m od školy",
    "Predám byt, 5 min. od centra, 200 m k lesu",
    "Predám byt, 100 m do centra",
    "Predám byt, obchod 150 m pešo",
])
def test_a_distance_is_not_an_area(text):
    assert area_from_text(text) == 0.0


@pytest.mark.parametrize("text,area", [
    ("Predám byt 58 m", 58.0),
    ("58 m, Petržalka", 58.0),
    ("1,5-izb. byt s 6m logiou, 40 m", 40.0),
    ("Byt 58 m2, 300 m od zastávky", 58.0),
    ("Byt 62 m, 200 m od lesa", 62.0),
])
def test_a_bare_area_is_still_read(text, area):
    assert area_from_text(text) == area


def test_a_bazos_card_with_a_distance_keeps_its_price():
    card, link = _bazos_card("Predám 2-izbový byt v Petržalke",
                             "Pekný byt, 300 m od zastávky MHD", "165 000 €",
                             "Bratislava 851 01")
    rec = bazos._build_listing_from_card(card, link)
    assert rec["size_m2"] != 300.0
    assert rec["price_eur"] == 165_000


# ── h10: the kitchen's state is not the flat's furniture ──────────────────────
@pytest.mark.parametrize("text,kind", [
    ("Nevybavená kuchyňa, inak zariadený byt", "furnished"),
    ("Kuchyňa je nevybavená, byt je zariadený", "furnished"),
    ("Prenájom 2-izbového bytu. Zariadená kuchyňa, obývačka s nábytkom.", "furnished"),
    ("Byt s nábytkom", "furnished"),
    ("Nábytok v cene", "furnished"),
    ("Nevybavený byt", "unfurnished"),
    ("Byt je nevybavený, kuchyňa je nevybavená", "unfurnished"),
    ("Nezariadený byt, zariadená kuchyňa", "unfurnished"),
    ("Byt bez nábytku", "unfurnished"),
    ("Čiastočne s nábytkom", "semi"),
    ("Čiastočne zariadený byt", "semi"),
    ("Prenájom 2-izbového bytu, nevybavená kuchyňa", "unknown"),
])
def test_the_kitchen_says_nothing_about_furniture(text, kind):
    assert rent_comps.furnishing_from_text(text) == kind
