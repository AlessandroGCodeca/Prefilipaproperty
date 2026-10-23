"""Regression tests for the fourth review of the Czech title-deed check
(modules/lv_screen_cz): a person's right to use or live in the flat worded
with a verb or a room (C0), and a body-less entry behind a PDF bullet glyph,
a dash or no bullet (C5). Synthetic výpisy only — no real LV contents, no
personal data, no request leaves the test."""

import pytest

from modules import debt_bot, lv_cz
from modules.lv_screen import fold
from modules.lv_screen_cz import screen_lv_cz, unrecognised_entries
from tests.test_lv_cz import BANK_LIEN, lv


def status(text, lv_number="1234"):
    return lv_cz.check_text(text, lv_number)["status"]


def easement(kind, holder, description=""):
    return (f"  o {kind}\n" + (f"      {description}\n" if description else "")
            + f"      Oprávnění pro {holder}\n      Povinnost k Jednotka: č. 101/5\n"
            "      Listina Smlouva darovací ze dne 01.02.2015. V-1234/2015-101\n")


def easement_tiers(text):
    return [(e["tier"], e["note"]) for e in screen_lv_cz(text) if e["kind"] == "encumbrance"]


PERSON = "Osoba Testovací, Testovací 1, Testov, RČ/IČO: 000000/0000"
UTILITY = "Testovací Distribuce, a. s., Testovací 8, Testov, RČ/IČO: 00000000"
HARD_USE = [("hard", "lifetime right to use or live in it")]


# ── C0: a right of use worded with a verb, a room, "bydlet", "do smrti" ─────
@pytest.mark.parametrize("description", [
    "užívání pokoje v bytě a společných prostor, přístup ke koupelně",
    "právo užívat byt č. 101/5 a právo přístupu do sklepa",
    "právo bydlet v bytě č. 101/5 do smrti, údržbu nese povinný",
    "právo užívat jednotku č. 101/5 a povinnost údržby",
    "užívání místnosti v bytě č. 101/5, průchod chodbou",
    "právo užívat pokoj v bytě č. 101/5 a cesta ke sklepu",
    "do smrti oprávněné, s přístupem ke sklepu",
])
def test_a_persons_right_of_use_beside_an_access_word_rejects(monkeypatch, description):
    text = lv(BANK_LIEN + easement("Věcné břemeno užívání", PERSON, description))
    assert easement_tiers(text) == HARD_USE
    r = lv_cz.check_text(text, "1234")
    assert r["status"] == "REJECT"
    # With Claude off the screen's verdict is what is stored.
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    assert debt_bot._decide_lv(r)["status"] == "REJECT"


@pytest.mark.parametrize("kind", ["Věcné břemeno (podle listiny)", "Služebnost",
                                  "Věcné břemeno chůze a jízdy"])
def test_a_verb_right_of_use_rejects_whatever_the_easements_type(kind):
    text = lv(BANK_LIEN + easement(kind, PERSON,
                                   "právo užívat byt č. 101/5 a právo přístupu k němu"))
    assert easement_tiers(text) == HARD_USE
    assert status(text) == "REJECT"


@pytest.mark.parametrize("kind,holder,description", [
    ("Věcné břemeno užívání", UTILITY, "umístění a provozování kabelového vedení NN"),
    ("Věcné břemeno užívání", UTILITY, "právo užívat pozemek pro umístění trafostanice"),
    ("Věcné břemeno chůze a jízdy", PERSON, ""),
    ("Věcné břemeno chůze a jízdy", PERSON, "právo chůze a jízdy přes pozemek parc. č. 567"),
    ("Služebnost inženýrské sítě", UTILITY, "uložení vodovodní přípojky, přístup k údržbě"),
])
def test_utility_and_access_easements_stay_soft(kind, holder, description):
    # h5 (audit 3): a cable, a trafostanice, a right of way is no sitting
    # occupant — and "uživatel" or "užívat pozemek" names no flat.
    text = lv(BANK_LIEN + easement(kind, holder, description))
    assert easement_tiers(text) == [("soft", "utility / access easement")]
    assert status(text) == "PASS"


def test_a_user_of_the_land_is_no_right_to_live():
    text = lv(BANK_LIEN + easement("Věcné břemeno chůze a jízdy", PERSON,
                                   "pro každého uživatele pozemku parc. č. 567"))
    assert easement_tiers(text) == [("soft", "utility / access easement")]


# ── C5: a body-less entry behind a PDF glyph, a dash or no bullet ───────────
UNKNOWN = "Nařízení soudního prodeje zástavy"
BULLETS = ["o ", " ", "", "\n     ", "· ", "- ", "– ", "* ", ""]
BULLET_IDS = ["o", "f0b7", "f0b7-tight", "f0b7-own-line", "middot", "dash", "en-dash",
              "star", "none"]


@pytest.mark.parametrize("bullet", BULLETS, ids=BULLET_IDS)
def test_a_bodyless_unknown_part_d_entry_is_found(bullet):
    for part_d in (f"  {bullet}{UNKNOWN}\n", f" Typ vztahu\n  {bullet}{UNKNOWN}\n"):
        text = lv(BANK_LIEN, part_d)
        assert unrecognised_entries(text) == [UNKNOWN]
        assert status(text) == "UNVERIFIED"
    upper = lv(BANK_LIEN, f"  {bullet.replace('o', 'O')}{UNKNOWN}\n").upper()
    assert [fold(n) for n in unrecognised_entries(upper)] == [fold(UNKNOWN)]
    assert status(upper) == "UNVERIFIED"


@pytest.mark.parametrize("bullet", BULLETS[:-1], ids=BULLET_IDS[:-1])
def test_a_bodyless_unknown_entry_after_another_entry_is_found(bullet):
    # Behind a bullet glyph it is found anywhere in parts C–D, not only right
    # under a heading.
    c = lv(BANK_LIEN + f"  {bullet}Reálné břemeno\n")
    assert unrecognised_entries(c) == ["Reálné břemeno"]
    assert status(c) == "UNVERIFIED"
    note = ("  o Poznámka o uzavření smlouvy\n      Povinnost k Jednotka: 101/5\n"
            "      Listina Smlouva ze dne 01.10.2026. Z-4444/2026-101\n")
    d = lv(BANK_LIEN, note + f"  {bullet}{UNKNOWN}\n")
    assert unrecognised_entries(d) == [UNKNOWN]
    assert status(d) == "UNVERIFIED"


def test_a_bodyless_unknown_part_c_entry_without_a_bullet_is_found():
    for part_c in ("  Reálné břemeno\n", "  Reálné břemeno\n" + BANK_LIEN):
        text = lv(part_c)
        assert unrecognised_entries(text) == ["Reálné břemeno"]
        assert status(text) == "UNVERIFIED"


def test_a_vypis_pasted_as_one_line_keeps_its_unknown_entry():
    text = lv(BANK_LIEN, f"  {UNKNOWN}\n").replace("\n", " ")
    assert unrecognised_entries(text) == [UNKNOWN]
    assert status(text) == "UNVERIFIED"


@pytest.mark.parametrize("bullet", BULLETS, ids=BULLET_IDS)
def test_a_clean_vypis_with_any_bullet_still_passes(bullet):
    text = lv(BANK_LIEN.replace("  o ", f"  {bullet}"))
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"
    assert status(text.upper()) == "PASS"


@pytest.mark.parametrize("part_d", ["  Bez zápisu\n", "  - Bez zápisu\n",
                                    " Typ vztahu\n  Bez zápisu\n"])
def test_bez_zapisu_is_no_entry(part_d):
    text = lv(BANK_LIEN, part_d)
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


def test_a_dash_inside_a_creditors_name_is_no_bullet():
    text = lv(BANK_LIEN.replace("Testovací banka, a.s., Testovací 33",
                                "Testovací banka - Testovací spořitelna, a.s., Testovací 33"))
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


PAGE_HEADER = "Výpis z katastru nemovitostí\nLIST VLASTNICTVÍ: 1234\nKatastrální území: Testov\n"


@pytest.mark.parametrize("part_d", [
    PAGE_HEADER + "  Bez zápisu\n",
    PAGE_HEADER + "  o Poznámka o uzavření smlouvy\n      Povinnost k Jednotka: 101/5\n",
])
def test_a_page_break_under_the_part_d_heading_is_no_entry(part_d):
    text = lv(BANK_LIEN, part_d)
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


@pytest.mark.parametrize("where", ["v katastrálním území Testov",
                                   "k listu vlastnictví č. 55"])
def test_an_entry_naming_a_ku_or_an_lv_is_no_page_header(where):
    text = lv(BANK_LIEN, f"  {UNKNOWN} {where}\n")
    assert unrecognised_entries(text) == [f"{UNKNOWN} {where}"]
    assert status(text) == "UNVERIFIED"


def test_a_page_break_under_the_part_c_heading_is_no_entry():
    text = lv(" Typ vztahu\n" + PAGE_HEADER + BANK_LIEN)
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


def test_a_line_after_a_register_number_is_still_no_entry_without_a_bullet():
    # Elsewhere than under a heading a bulletless body-less line can't be told
    # from a page's header or footer, so it is not read as an entry.
    first = BANK_LIEN.split("  o Zákaz")[0]
    text = lv(first + "  Strana 2\n  o Zákaz zcizení nebo zatížení\n"
              "      Oprávnění pro Testovací banka, a.s.\n")
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


def test_known_entries_behind_a_pdf_glyph_still_decide():
    assert status(lv(BANK_LIEN, "   Zahájení exekuce\n")) == "REJECT"
    assert status(lv(BANK_LIEN, "  Zahájení exekuce\n")) == "REJECT"
