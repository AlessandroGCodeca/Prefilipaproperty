"""Audit 6: what a regression hunt found in the audit-5 scraper changes,
each case reproduced on the pushed code first. Synthetic ads only."""
import pytest

from scraper import cz_common, rentals, textparse
from scraper.nehnutelnosti import _detail_district, _extract_location_from_text


# ── A room count names the flat, unless a house noun follows it ──────────────
@pytest.mark.parametrize("text", [
    "Predám 3-izbový s garážou",
    "https://reality.bazos.sk/inzerat/1/predam-3-izbovy-s-garazou.php",
    "Predám 3-izbový tehlový s garážou",
    "Predám 3-izbový po rekonštrukcii s garážou",
    "Predám 3-izbový - Petržalka, s garážou",
    "Predám 3-izbový (tehla) s garážou",
    "Predám 2i tehla garáž",
    "Predaj 3-izbový na Dlhých dieloch s garážou",
    "https://reality.bazos.sk/inzerat/1/predam-4-izbovy-v-senci-so-zahradou.php",
    "Predám 3-izbový v novostavbe s garážou",
])
def test_a_flat_named_by_its_room_count_is_kept(text):
    assert not textparse.is_excluded_listing(text)


@pytest.mark.parametrize("text", [
    "Predaj 4-izbovej drevostavby s pozemkom",
    "https://x/predaj-4-izbovej-drevostavby-s-pozemkom.php",
    "Predám 4-izbovú radovku s garážou",
    "Predám 4-izbový murovaný objekt so záhradou",
    "Predaj 5 izbovej nehnuteľnosti s garážou a záhradou",
    "Predaj 6-izbového dvojgeneračného s garážou",
    "Predám 3-izbový dom s garážou",
])
def test_a_house_named_by_its_room_count_is_still_excluded(text):
    assert textparse.is_excluded_listing(text)


# ── "na <place>" names the flat's place only right after the flat itself ────
@pytest.mark.parametrize("text,want", [
    ("Predaj 2-izbového bytu v Bratislave, električka priamo na Nové Mesto", "Bratislava"),
    ("Predaj 3-izbového bytu v Bratislave, krásny pohľad na Staré Mesto", "Bratislava"),
    ("Predaj bytu Bratislava, rýchle napojenie na Ružinov", "Bratislava"),
    ("Predaj bytu v Košiciach, linka MHD na Ťahanovce", "Košice"),
    ("Vymením byt v Bratislave na Senec", "Bratislava"),
    ("Predaj bytu v Bratislave, ideálne pre dochádzajúcich na Malacky", "Bratislava"),
    ("Predám byt na Petržalka", "Petržalka, Bratislava"),
    ("Prenájom 2i bytu na Martin", "Martin"),
    ("Predaj bytu: Košice, na Ťahanovce", "Ťahanovce, Košice"),
    ("Byt na Senec", "Senec"),
])
def test_na_is_a_direction_unless_it_follows_the_flat(text, want):
    assert _extract_location_from_text(text) == want


# ── A village named like a city part takes its own okres ────────────────────
@pytest.mark.parametrize("address,want", [
    ("Barca, okres Rimavská Sobota", "Rimavská Sobota"),
    ("Dúbravka, okres Michalovce", "Michalovce"),
    ("Hlavná 5, Modra, okres Pezinok", "Modra"),
    ("Valaliky, okres Košice-okolie", "Košice-okolie"),
    ("Barca, Košice IV", "Barca, Košice"),
    ("Petržalka, Bratislava, okres Bratislava V", "Petržalka, Bratislava"),
])
def test_a_village_named_like_a_city_part_takes_its_okres(address, want):
    assert _detail_district(address) == want


# ── Rentals: the city a title names, never one it only refers to ─────────────
@pytest.mark.parametrize("title,text,location,want", [
    ("Prenájom 2-izbového bytu v Nitre", "55 m2, 600 € mesačne", "Staré Mesto",
     "Staré Mesto, Nitra"),
    ("Prenájom 2-izbového bytu - Nové Mesto, Žilina", "55 m2, 650 € mesačne", "Nové Mesto",
     "Nové Mesto, Žilina"),
    ("Prenájom 2-izbového bytu", "55 m2, 650 € mesačne. RK Domov Trnava", "Nové Mesto",
     "Nové Mesto, Bratislava"),
    ("Prenájom 2-izbového bytu Košice", "55 m2, 600 € mesačne", "Kosice 040 01", "Košice"),
    ("Prenájom 2-izbového bytu, Nitra", "55 m2, 600 € mesačne", "Štefánikova trieda 12", "Nitra"),
])
def test_a_rental_takes_the_city_its_title_names(title, text, location, want):
    r = rentals.build_rental("bazos", "https://x/" + title + location, title, text,
                             location=location)
    assert r and r["district"] == want


@pytest.mark.parametrize("title,location", [
    ("Prenájom 2-izbového bytu, 10 min od Bratislava Vajnory", "Bernolákovo 900 27"),
    ("Prenájom 2i bytu pre pracujúcich v Bratislave", "Bernolákovo 900 27"),
    ("Prenájom 2-izbového bytu, Martin Novák", "Vrútky 038 61"),
    ("Prenájom 2-izb. bytu - Lužianky, 5 km od Nitra", "Lužianky 951 41"),
])
def test_a_village_rental_takes_no_town_its_title_only_refers_to(title, location):
    assert rentals.build_rental("bazos", "https://x/" + title, title, "55 m2, 600 € mesačne",
                                location=location) is None


# ── Areas after a feature list, a street or a "with a …" phrase are kept ────
@pytest.mark.parametrize("text,want", [
    ("Predám 3-izbový byt, Petržalka, garáž, 75 m", 75.0),
    ("Predám 2-izbový byt Obchodná 65 m", 65.0),
    ("Prenájom 2-izbového bytu s garážovým státím 58 m", 58.0),
    ("Prodej 2+kk, sklep, 56 m", 56.0),
    ("Prodej 3+kk s garáží 75 m", 75.0),
    ("Záhradnícka 70 m", 70.0),
    # An accessory named on its own is still not the flat's size.
    ("Parkovanie 100 m za 30 €", 0.0),
    ("Garáž 50 m za 15 000 €", 0.0),
    ("Terasa 40 m za 600 €", 0.0),
])
def test_the_flats_area_after_a_feature_or_street(text, want):
    assert textparse.area_from_text(text) == want


# ── A share of the land "and the building" is no share of the flat ───────────
@pytest.mark.parametrize("excluded,text", [
    (cz_common.is_excluded_cz,
     "Prodej bytu 3+1 se spoluvlastnickým podílem na pozemku a bytovém domě"),
    (textparse.is_excluded_listing,
     "Predaj 3-izbového bytu so spoluvlastníckym podielom na pozemku a bytovom dome"),
    (textparse.is_excluded_listing,
     "Predaj 3-izbového bytu s podielom na pozemku a byt je po rekonštrukcii"),
])
def test_a_share_of_the_land_and_the_building_keeps_the_flat(excluded, text):
    assert not excluded(text)


@pytest.mark.parametrize("excluded,text", [
    (cz_common.is_excluded_cz, "Byt 3+1 - spoluvlastnický podíl 1/2 na pozemku a bytě"),
    (textparse.is_excluded_listing, "Predaj 1/2 podielu na dvore a byte"),
])
def test_a_share_of_an_accessory_and_the_flat_is_still_a_share(excluded, text):
    assert excluded(text)


# ── Czech: a flat in a house ─────────────────────────────────────────────────
@pytest.mark.parametrize("title", [
    "Prodám 2+kk v přízemí RD se zahradou a garáží",
    "Prodám 3+kk v 1. patře RD s garáží",
    "Prodej 2+kk v podkroví RD, parkovací stání",
    "Prodám 2+kk v řadovém RD, garáž",
    "Prodám 2+kk ve 2. patře patrového domu s garáží",
    "Prodej 3+1 v přízemí řadového domu, garáž",
])
def test_a_czech_flat_in_a_house_is_kept(title):
    assert not cz_common.is_excluded_cz(title)


@pytest.mark.parametrize("title", [
    "Prodej 4+1 ve Zlíně, RD s garáží",
    "Prodej 5+kk, RD s garáží",
    "Prodej 4+1, řadový RD, garáž",
])
def test_a_czech_house_is_still_excluded(title):
    assert cz_common.is_excluded_cz(title)
