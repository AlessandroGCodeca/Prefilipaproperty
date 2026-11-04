"""Regression tests for the fourth review, Slovak scrapers (C7, C8, C9, C10,
C12, C13): synthetic addresses, titles, cards and pages only — no real
listing, no real person, no request leaves the test."""

import json

import pytest
from bs4 import BeautifulSoup

from engine import regional_prices as rp
from engine.financial import match_rent_key
from scraper import bazos, rentals, rentals_cz, topreality
from scraper.nehnutelnosti import (
    _apply_detail, _detail_district, _extract_location_from_text,
    _minimal_listing, _parse_api_item,
)
from scraper.textparse import area_from_text, is_excluded_listing
from tests.conftest import make_listing

NOW = "2026-10-22T00:00:00+00:00"
NEH_URL = "https://www.nehnutelnosti.sk/detail/JuTest4/"


def _bazos_card(title, desc, price, place, n=1, href=None):
    """A Bazoš card as the site lays it out: the photo link first, the title
    in h2, then the text, the price and the location."""
    href = href or f"/inzerat/{n}/x.php"
    html = (f'<div class="inzeraty inzeratyflex"><div class="inzeratynadpis">'
            f'<a href="{href}"><img class="obrazek" src="x.jpg"></a>'
            f'<h2 class="nadpis"><a href="{href}">{title}</a></h2>'
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


# ── C7: an address's own okres decides its town ──────────────────────────────
OKRES_ADDRESSES = [
    ("Hlavná 12, Valaliky, okres Košice-okolie", "Košice-okolie"),
    ("Družstevná 5, Čaňa, okres Košice-okolie", "Košice-okolie"),
    ("Hlavná 3, Martin nad Žitavou, okres Zlaté Moravce", "Zlaté Moravce"),
    ("Hlavná 3, Nitra nad Ipľom, okres Lučenec", "Lučenec"),
    ("Hlavná 3, Trnava pri Laborci, okres Michalovce", "Michalovce"),
    ("Hlavná 3, Modra nad Cirochou, okres Humenné", "Humenné"),
    ("Hlavná 3, Testovce, okr. Zlaté Moravce", "Zlaté Moravce"),
]


@pytest.mark.parametrize("address,district", OKRES_ADDRESSES)
def test_the_addresss_own_okres_wins_over_a_town_named_earlier(address, district):
    listing = _minimal_listing(NEH_URL, "2 izbový byt", NOW)
    _apply_detail(listing, {"address": address})
    assert listing["district"] == district
    assert listing["address_raw"] == address
    # The okres's rent and median, as before audit 3 ("okres X" kept whole).
    assert match_rent_key(listing["district"]) == match_rent_key("okres " + district)
    assert rp.regional_median_price(listing["district"]) == \
        rp.regional_median_price("okres " + district)


def test_kosice_okolie_is_not_kosice_city():
    listing = _minimal_listing(NEH_URL, "3 izbový byt", NOW)
    _apply_detail(listing, {"address": "Hlavná 12, Valaliky, okres Košice-okolie"})
    assert match_rent_key(listing["district"]) == match_rent_key("Košice-okolie")
    assert match_rent_key(listing["district"]) != match_rent_key("Košice")
    assert rp.regional_median_price(listing["district"]) != \
        rp.regional_median_price("Košice")


def test_a_village_named_after_a_town_is_not_that_town():
    for address, district in OKRES_ADDRESSES[2:6]:
        first_word = address.split(", ")[1].split()[0]
        assert _detail_district(address) != first_word
        assert _detail_district(address) == district


@pytest.mark.parametrize("address,district", OKRES_ADDRESSES[:3])
def test_a_harvested_item_takes_its_own_okres(address, district):
    rec = _parse_api_item({"url": "/detail/JuTest5/byt", "title": "2-izbový byt",
                           "location": {"fullAddress": address}}, NOW)
    assert rec["district"] == district


@pytest.mark.parametrize("address,district", [
    # A city part named before the okres still refines it to that city.
    ("Hlavná 5, Ťahanovce, okres Košice I", "Ťahanovce, Košice"),
    ("Hlavná 5, Ružinov, okres Bratislava II", "Ružinov, Bratislava"),
    ("Hlavná 5, Bratislava - Petržalka, okres Bratislava V", "Petržalka, Bratislava"),
    # The same city part, placed by the whole address.
    ("Hlavná 5, Košice, Staré Mesto", "Staré Mesto, Košice"),
    ("Hlavná 5, Bratislava, Staré Mesto", "Staré Mesto, Bratislava"),
    # A village with no okres after it keeps its whole name.
    ("Hlavná 3, Martin nad Žitavou", "Martin nad Žitavou"),
    # "okres" only as its own word: a street called Okresná is a street.
    ("Okresná 3, Senec", "Senec"),
    ("okr. Bratislava II", "Bratislava II"),
])
def test_the_okres_rule_keeps_the_city_parts(address, district):
    assert _detail_district(address) == district


# ── C8: a whole flat sold with a share of an accessory is a flat ─────────────
@pytest.mark.parametrize("title", [
    "Predaj 3-izbového bytu so spoluvlastníckym podielom na garáži",
    "Predaj 3-izbového bytu s 1/2 podielom na garáži",
    "Predaj 3-izbového bytu s 1/4 podielom na záhrade",
    "Predaj 3i bytu vrátane 1/6 podielu na dvore",
    "Predám 2-izbový byt + 1/2 podiel garáže",
    "Predaj 2-izbového bytu, 1/8 podiel na parkovacom státí",
    "Predaj 2-izb. bytu, spoluvlastnícky podiel na záhrade",
    "Predaj 2-izbového bytu s 1/2 podiel na pivnici",
    "Predaj 2-izbového bytu, 1/2 podiel na garážovom státí",
    "Predaj 3-izbového bytu, 1/10 podiel na parkovisku",
])
def test_a_flat_with_a_share_of_an_accessory_is_kept(title):
    assert not is_excluded_listing(title)
    assert not is_excluded_listing(title, "https://www.topreality.sk/x-r1234567.html")


@pytest.mark.parametrize("title", [
    "Predám 1/2 bytu v Petržalke",
    "Predám podiel na byte",
    "Predaj 2/3 podielu 3-izbového bytu",
    "Predaj spoluvlastníckeho podielu 1/2 na 3-izbovom byte",
    "Predám 1/2 podiel na byte s garážou",
    "Predám podiel 1/2 na 2-izbovom byte so záhradkou",
    "Predaj 1/2 podielu 3-izbového bytu s garážou",
    "Predaj 1/3 bytu s pivnicou",
    # The accessory word describing the flat: still a share of the flat.
    "Predaj 1/2 podielu záhradného bytu",
    "Predaj 1/2 podielu dvorového bytu",
    # A share of the accessory alone is still no flat.
    "Predaj podielu na garáži",
    "Predám 1/2 podiel garáže",
    "Predaj 1/2 podielu na záhrade",
])
def test_a_share_of_the_flat_or_of_the_accessory_alone_is_still_excluded(title):
    assert is_excluded_listing(title)


def test_a_stored_flat_with_a_garage_share_is_not_deactivated(full_db):
    import database as db
    from scraper import nehnutelnosti
    rows = {
        "garage-share": "Predaj 3-izbového bytu so spoluvlastníckym podielom na garáži",
        "garden-share": "Predaj 3-izbového bytu s 1/4 podielom na záhrade",
        "flat-share": "Predám 1/2 bytu v Petržalke",
    }
    for rid, title in rows.items():
        db.upsert_listing(make_listing(rid, source="nehnutelnosti", title=title,
                                       price_eur=189_000.0,
                                       url=f"https://www.nehnutelnosti.sk/detail/{rid}/"))
    assert nehnutelnosti._deactivate_non_apartments() == 1
    conn = full_db()
    state = {r["id"]: (r["is_active"], r["price_eur"])
             for r in conn.execute("SELECT id, is_active, price_eur FROM listings")}
    conn.close()
    assert state["garage-share"] == (1, 189_000.0)
    assert state["garden-share"] == (1, 189_000.0)
    assert state["flat-share"] == (0, 0.0)


# ── C9: "N m za <price>" is the flat's area ───────────────────────────────────
@pytest.mark.parametrize("text,area", [
    ("Predám 2-izbový byt 58 m za 129 000 €", 58.0),
    ("Predám 2-izbový byt 58m za 129000€", 58.0),
    ("Prenájom 2-izbového bytu 55 m za 650 € mesačne", 55.0),
    ("Prenájom 1-izbového bytu 38 m za 480 € + energie", 38.0),
    ("Predám byt 58 m za cenu 129 000 €", 58.0),
    ("Predám byt 58 m za 129 tis. €", 58.0),
    ("Predám byt 58 m za 129.000,- €", 58.0),
    ("Predám byt 58 m za 129 000 EUR", 58.0),
    ("Pronájem bytu 2+kk 54 m za 15 000 Kč", 54.0),
])
def test_an_area_before_za_and_a_price_is_read(text, area):
    assert area_from_text(text) == area


@pytest.mark.parametrize("text", [
    "Predám byt, obchod 200 m za rohom",
    "Predám byt, zastávka 300 m za 3 minúty",
    "Predám byt, 300 m za 2 min",
    "Predám byt, 300 m od zastávky",
    "Predám byt, 200 m k lesu",
    "Predám byt, 100 m do centra",
])
def test_a_distance_before_za_is_still_no_area(text):
    assert area_from_text(text) == 0.0


def test_a_rental_with_za_and_its_rent_is_a_comp_again():
    title = "Prenájom 2-izbového bytu 55 m za 650 € mesačne"
    rec = rentals.build_rental("bazos", "https://reality.bazos.sk/inzerat/7/x.php",
                               title, title, location="Žilina 010 08", now=NOW)
    assert (rec["rent_eur"], rec["size_m2"], rec["district"]) == (650.0, 55.0, "Žilina")


def test_a_czech_rental_with_za_and_its_rent_is_a_comp_again():
    title = "Pronájem bytu 2+kk 54 m za 15 000 Kč"
    rec = rentals_cz.build_rental("bazos_cz", "https://reality.bazos.cz/inzerat/7/x.php",
                                  title, title, location="Brno 616 00", rent=15000, now=NOW)
    assert (rec["rent_eur"], rec["size_m2"], rec["district"]) == (15000.0, 54.0, "Brno")


def test_a_bazos_sale_card_with_za_and_its_price_keeps_its_size():
    card, link = _bazos_card("Predám 2-izbový byt 58 m za 129 000 €", "Pekný byt",
                             "129 000 €", "Žilina 010 08")
    rec = bazos._build_listing_from_card(card, link)
    assert (rec["price_eur"], rec["size_m2"], rec["district"]) == (129_000.0, 58.0, "Žilina")


# ── C10: a free-text title naming the flat by its room count ─────────────────
@pytest.mark.parametrize("title", [
    "Predám 3-izbový s garážou, Nitra Klokočina",
    "Predám 3 izbový + garáž, Žilina Vlčince",
    "Predám 2i so záhradkou, Senec",
    "Predám 2-izbový, Petržalka, parkovacie státie",
    "Predám 3i s garážou",
    "Predám 2 izbák so záhradkou",
    "Predám 2,5 izbový + parkovacie státie",
    "Predám 1,5-izb. s pozemkom",
])
def test_a_room_count_before_an_accessory_names_the_flat(title):
    assert not is_excluded_listing(title)
    card, link = _bazos_card(title, "Byt 68 m2, po rekonštrukcii", "159 000 €",
                             "Nitra 949 01")
    rec = bazos._build_listing_from_card(card, link)
    assert rec is not None
    assert (rec["price_eur"], rec["size_m2"], rec["district"]) == (159_000.0, 68.0, "Nitra")


@pytest.mark.parametrize("title", [
    "Predám 4-izbový dom s garážou",
    "Predám 4 izbový dom s pozemkom",
    "Predám 3-izbovú chalupu so záhradou",
    "Predám 3-izbový rodinný dom s garážou",
    "Predám 4 izbovú chatu so záhradou",
    "Predám 5i RD so záhradou",
    "Predám 4-izbový bungalov s garážou",
    "Predám 3-izbový dvojdom so záhradou",
    "Predám vilu, 5-izbová, garáž",
    "Predám garáž pri 3-izbovom byte",
    "Predám garáž",
    "Predám 2 garáže",
    "Predám pozemok 600 m2",
    "Prenájom 2-izbový s garážou",
    "Predám 1/2 bytu v Petržalke",
])
def test_a_house_a_garage_or_a_rental_is_still_excluded(title):
    assert is_excluded_listing(title)
    card, link = _bazos_card(title, "68 m2", "159 000 €", "Nitra 949 01")
    assert bazos._build_listing_from_card(card, link) is None


def test_a_rental_flat_named_by_its_room_count_with_a_garage_is_a_comp():
    rec = rentals.build_rental("bazos", "https://reality.bazos.sk/inzerat/8/x.php",
                               "Prenájom 2-izbový s garážou", "55 m2, 650 € mesačne",
                               location="Nitra 949 01", now=NOW)
    assert rec["district"] == "Nitra"
    assert rentals.build_rental("bazos", "https://reality.bazos.sk/inzerat/9/x.php",
                                "Prenájom garáže", "18 m2, 650 € mesačne",
                                location="Nitra 949 01", now=NOW) is None


# ── C12: a town named as a direction is not the flat's town ─────────────────
@pytest.mark.parametrize("text,expected", [
    ("Predaj 3-izbového bytu v Bratislave. Pekný byt, rýchly výjazd na Senec "
     "a diaľnicu D1.", "Bratislava"),
    ("Predaj 2-izbového bytu v Košiciach, rýchly výjazd na Prešov.", "Košice"),
    ("Predaj bytu, Košice - Juh, výjazd na Prešov", "Košice"),
    ("Bratislava III, rýchly výjazd na Pezinok", "Bratislava"),
    ("Predaj bytu v Bratislave, autobus priamo na Malacky", "Bratislava"),
    ("Ružinov, výjazd na Senec", "Ružinov, Bratislava"),
    # The audit-3 answers stand.
    ("Predaj 2-izbového bytu, Senec. Ideálne pre ľudí pracujúcich v Bratislave.", "Senec"),
    ("Predaj 3-izbového bytu v Nitre. Maklér: Martin Testovací", "Nitra"),
    ("Byty Bratislava | 2-izbový byt, Senec", "Senec"),
    ("v Senci, výjazd na Pezinok", "Senec"),
    ("Byt na predaj Senec", "Senec"),
    ("Na predaj: Senec", "Senec"),
    ("PREDAM BYT SENEC", "Senec"),
    ("Byt, Nové Mesto nad Váhom", "Nové Mesto nad Váhom"),
])
def test_a_town_after_na_is_a_direction(text, expected):
    assert _extract_location_from_text(text) == expected


def test_topreality_detail_with_a_direction_keeps_the_hub():
    page = _topreality_page(
        "Predaj 2-izbového bytu v Bratislave",
        "Predaj 2-izbového bytu v Bratislave. Byt 58 m2, rýchly výjazd na Senec "
        "a diaľnicu D1. Cena 189 000 €")
    rec = topreality._build_listing_from_detail(
        "https://www.topreality.sk/x-r1234570.html", page, NOW)
    assert rec["district"] == "Bratislava"
    assert match_rent_key(rec["district"]) == match_rent_key("Bratislava")


# ── C13: an unknown village's rental takes no town from the text ─────────────
@pytest.mark.parametrize("location,text", [
    ("Bernolákovo 900 27", "55 m2, ideálne pre ľudí pracujúcich v Bratislave. Cena 650 €"),
    ("Chorvátsky Grob 900 25",
     "55 m2. Priame spojenie autobusom Bratislava - Chorvátsky Grob. Cena 650 €"),
    ("Slovenský Grob 900 26", "55 m2, 10 min od Bratislava Vajnory. Cena 650 €"),
    ("Testovce pri Košiciach 040 99", "55 m2, pre pracujúcich v Košiciach. Cena 650 €"),
])
def test_an_unknown_location_takes_no_hub_from_a_commuter_sentence(location, text):
    assert rentals.build_rental("bazos", "https://x/" + location,
                                "Prenájom 2-izbového bytu", text,
                                location=location, now=NOW) is None


def test_a_bazos_rental_card_from_an_unknown_village_is_no_comp():
    card, _ = _bazos_card("Prenájom 2-izbového bytu",
                          "55 m2, ideálne pre ľudí pracujúcich v Bratislave.",
                          "650 €", "Bernolákovo<br>900 27")
    html = f"<html><body>{card}</body></html>"
    assert rentals.parse_bazos_page(html, now=NOW) == []


@pytest.mark.parametrize("location,title,district", [
    # A known location still decides, and the title still refines it.
    ("Senec 903 01", "Prenájom 2-izbového bytu", "Senec"),
    ("Bratislava 851 01", "Prenájom 2-izbového bytu Petržalka", "Petržalka, Bratislava"),
    # A location that names only a region or a postcode is no location.
    ("", "Prenájom 2-izbového bytu v Petržalke", "Petržalka, Bratislava"),
    ("Bratislavský kraj", "Prenájom 2-izbového bytu v Petržalke", "Petržalka, Bratislava"),
    ("851 01", "Prenájom 2-izbového bytu v Petržalke", "Petržalka, Bratislava"),
])
def test_known_and_empty_locations_are_unchanged(location, title, district):
    rec = rentals.build_rental("bazos", "https://x/" + title + location, title,
                               "55 m2, pre ľudí pracujúcich v Bratislave. Cena 650 €",
                               location=location, now=NOW)
    assert rec["district"] == district
    assert rec["rent_key"] == match_rent_key(district)


# ── A bare city part in a rental's location takes the city the ad names ─────
@pytest.mark.parametrize("location,title,text,want", [
    ("Staré Mesto", "Prenájom 2-izbového bytu Košice", "55 m2, cena 700 €", "Staré Mesto, Košice"),
    ("Staré Mesto", "Prenájom 2-izbového bytu", "55 m2, cena 700 €, v Košiciach",
     "Staré Mesto, Košice"),
    ("Staré Mesto", "Prenájom 2-izbového bytu", "55 m2, cena 700 €", "Staré Mesto, Bratislava"),
    ("Staré Mesto, Bratislava", "Prenájom 2-izbového bytu",
     "55 m2, cena 700 €, blízko vlaku do Košíc", "Staré Mesto, Bratislava"),
    ("Bratislava - Staré Mesto", "Prenájom 2-izbového bytu",
     "55 m2, cena 700 €, do Košíc vlakom", "Staré Mesto, Bratislava"),
    ("Košice - Staré Mesto", "Prenájom 2-izbového bytu Bratislava", "55 m2, cena 700 €",
     "Staré Mesto, Košice"),
])
def test_a_bare_city_part_takes_the_city_the_ad_names(location, title, text, want):
    from scraper.rentals import build_rental
    r = build_rental("bazos", "https://example.sk/r1", title, text, location=location)
    assert r and r["district"] == want
