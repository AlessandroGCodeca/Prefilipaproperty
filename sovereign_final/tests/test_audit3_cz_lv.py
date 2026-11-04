"""Regression tests for the third review of the Czech title-deed check
(modules/lv_screen_cz, lv_cz, the Czech Claude prompt, markets.CZ's bank
names): one or more per finding, on synthetic výpisy only — no real LV
contents, no personal data, no request leaves the test."""

import pytest

from modules import debt_bot, lv_cz
from modules import llm_enrichment as llm
from modules.lv_screen import fold
from modules.lv_screen_cz import screen_lv_cz, unit_numbers, unrecognised_entries
from tests.test_lv_cz import BANK_LIEN, lv


def status(text, lv_number="1234", **kw):
    return lv_cz.check_text(text, lv_number, **kw)["status"]


def liens(text):
    return [(e["creditor"], e["blocking"]) for e in screen_lv_cz(text)
            if e["kind"] == "lien"]


def easement(kind, holder, description=""):
    return (f"  o {kind}\n" + (f"      {description}\n" if description else "")
            + f"      Oprávnění pro {holder}\n      Povinnost k Parcela: 567\n"
            "      Listina Smlouva o zřízení věcného břemene ze dne 01.02.2015. "
            "V-1234/2015-101\n")


# ── #39: a claim line that names the lien again ──────────────────────────────
def repeated(creditor):
    return ("  o Zástavní právo smluvní\n"
            "      zástavní právo k zajištění pohledávky ve výši 3 200 000 Kč\n"
            f"      Oprávnění pro {creditor}, Testovací 33, Testov, RČ/IČO: 00000000\n"
            "      Povinnost k Jednotka: č. 101/5\n"
            "      Listina Smlouva o zřízení zástavního práva V-1234/2020-101\n")


def test_a_bank_lien_whose_claim_line_names_the_lien_again_passes():
    text = lv(repeated("Testovací banka, a.s."))
    assert liens(text) == [("Testovací banka", False), ("Testovací banka", False)]
    assert status(text) == "PASS"


def test_a_private_lien_whose_claim_line_names_the_lien_again_still_rejects():
    text = lv(repeated("Osoba Testovací"))
    assert liens(text) == [("Osoba Testovací", True), ("Osoba Testovací", True)]
    r = lv_cz.check_text(text, "1234")
    assert r["status"] == "REJECT" and "smluvní" not in r["detail"]


def test_a_creditor_name_read_past_another_hit_stops_at_the_next_hit():
    # The marker lies past the claim line's own "zástavní právo"; the name
    # after it must not run on into another hit and the word "banka".
    entry = ("  o Zástavní právo smluvní\n"
             "      zástavní právo k zajištění pohledávky\n"
             "      Oprávnění pro Osoba Testovací předkupní právo banka\n"
             "      Listina Smlouva o zřízení zástavního práva V-1234/2020-101\n")
    found = liens(lv(entry))
    assert found and all(blocking for _, blocking in found)
    assert status(lv(entry)) == "REJECT"


def test_a_creditor_is_never_taken_from_the_next_entry():
    # Two liens on one line, no bullet or register number between them: the
    # first one's own creditor is read, not the bank of the second.
    text = ("Zástavní právo smluvní Oprávnění pro Osoba Testovací "
            "zástavní právo smluvní Oprávnění pro Testovací banka, a.s.")
    assert liens(text)[0] == ("Osoba Testovací", True)


@pytest.mark.parametrize("bullet", ["", "- ", "o ", "O "])
def test_a_lien_without_its_creditor_never_borrows_the_next_entrys_bank(bullet):
    # The next entry's type line ("Zástavní právo smluvní", with a capital)
    # ends this entry even when its bullet was lost.
    entry = (f"  {bullet}Zástavní právo smluvní\n      Povinnost k Jednotka: č. 101/5\n"
             f"  {bullet}Zástavní právo smluvní\n      Oprávnění pro Testovací banka, a.s.\n")
    for text in (lv(entry), lv(entry).upper()):
        assert liens(text)[0][1] is True
        assert status(text) == "REJECT"


def test_a_creditor_named_before_the_next_hit_still_wins():
    # The old reading stands whenever a creditor marker comes before the
    # next hit: only a lien with none reads on to its entry's end.
    entry = ("  o Zástavní právo smluvní\n      věřitel Osoba Testovací\n"
             "      zákaz zcizení\n      Oprávnění pro Testovací banka, a.s.\n")
    assert liens(lv(entry))[0] == ("Osoba Testovací", True)


# ── #45: a body-less entry behind an odd bullet ──────────────────────────────
UNKNOWN_D = "     o Nařízení soudního prodeje zástavy\n"
UNKNOWN_C = "  o Reálné břemeno\n"


@pytest.mark.parametrize("variant", [
    lambda t: t,
    lambda t: t.upper(),
    lambda t: t.replace("o Nařízení", "o\u00a0Nařízení").replace("o Reálné", "o\u00a0Reálné"),
    lambda t: t.replace("o Nařízení", "○ Nařízení").replace("o Reálné", "○ Reálné"),
    lambda t: t.replace("o Nařízení", "o\n     Nařízení").replace("o Reálné", "o\n  Reálné"),
], ids=["as-is", "upper", "nbsp", "circle", "own-line"])
def test_a_bodyless_unknown_entry_is_found_behind_any_bullet(variant):
    d = variant(lv(BANK_LIEN, UNKNOWN_D))
    assert [fold(n) for n in unrecognised_entries(d)] == ["narizeni soudniho prodeje zastavy"]
    assert status(d) == "UNVERIFIED"
    c = variant(lv(BANK_LIEN + UNKNOWN_C))
    assert [fold(n) for n in unrecognised_entries(c)] == ["realne bremeno"]
    assert status(c) == "UNVERIFIED"


@pytest.mark.parametrize("variant", [
    lambda t: t.upper(),
    lambda t: t.replace("o Zá", "o\u00a0Zá"),
    lambda t: t.replace("o Zá", "○ Zá"),
    lambda t: t.replace("o Zá", "o\n  Zá"),
], ids=["upper", "nbsp", "circle", "own-line"])
def test_a_bank_lien_behind_any_bullet_still_passes(variant):
    text = variant(lv(BANK_LIEN))
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


def test_a_capital_o_inside_a_line_is_no_bullet():
    # "POZNÁMKA O UZAVŘENÍ SMLOUVY" in capitals: one note, not a note and an
    # unknown "UZAVŘENÍ SMLOUVY".
    text = lv(BANK_LIEN, "  o Poznámka o uzavření smlouvy\n").upper()
    assert unrecognised_entries(text) == []
    assert status(text) == "PASS"


def test_the_screen_keeps_its_own_bullets():
    # The loose bullets are for finding entries only: the screen's verdict on
    # a bank lien and a private one is what it was.
    assert [b for _, b in liens(lv(BANK_LIEN))] == [False, False]
    assert status(lv("  o Zástavní právo smluvní\n   Oprávnění pro Osoba X, RČ: 0\n")) \
        == "REJECT"


# ── #46 and h2: part B as CUZK's "Jednotky" table ────────────────────────────
def head_with_units(*rows, header="Č.p./\nČ.jednotky        Způsob využití       Způsob ochrany"):
    body = "".join(f"{no}            {use}\n   Vymezena v:\n"
                   f"   Budova Testov, č.p. 1234, bytový dům, LV 777\n"
                   f"   Podíl na společných částech domu a pozemku\n   6543/123456\n"
                   for no, use in rows)
    return ("Výpis z katastru nemovitostí\nLIST VLASTNICTVÍ: 1234\n"
            "Katastrální území: Testov\nA Vlastník, jiný oprávněný\n"
            "  Vlastník Testovací, Testovací 1, Testov\n"
            f"B Nemovitosti\nJednotky\n{header}\n{body}"
            "B1 Věcná práva sloužící ve prospěch nemovitostí v části B - Bez zápisu\n")


def test_unit_numbers_reads_the_units_table():
    head = head_with_units(("1234/5", "byt"), ("1234/25", "garáž"))
    assert unit_numbers(head) == {"1234/5", "1234/25"}


@pytest.mark.parametrize("header", [
    "Č.p./\nČ.jednotky        Způsob využití       Způsob ochrany",
    "Č.p./Č.jednotky  Způsob využití  Způsob ochrany",
    "Číslo jednotky  Způsob využití  Způsob ochrany",
])
def test_a_share_alone_on_its_line_is_no_unit(header):
    assert unit_numbers(head_with_units(("1234/5", "byt"), header=header)) == {"1234/5"}


def test_a_private_lien_on_the_owners_garage_is_unverified_not_rejected():
    head = head_with_units(("1234/5", "byt"), ("1234/25", "garáž"))
    garage = ("  o Zástavní právo smluvní\n      Oprávnění pro Osoba Testovací, RČ/IČO: 0\n"
              "      Povinnost k Jednotka: 1234/25\n"
              "      Listina Smlouva o zřízení zástavního práva V-1/2020-101\n")
    r = lv_cz.check_text(lv(garage, head=head), "1234")
    assert r["status"] == "UNVERIFIED" and "2 units" in r["detail"]


@pytest.mark.parametrize("header", [
    "Č.p./\nČ.jednotky        Způsob využití       Způsob ochrany",
    "Číslo jednotky  Způsob využití  Způsob ochrany",
])
def test_a_clean_vypis_with_the_units_table_passes(header):
    head = head_with_units(("1234/5", "byt"), header=header)
    assert status(lv(head=head)) == "PASS"
    assert status(lv(BANK_LIEN, head=head)) == "PASS"


def test_the_buildings_lv_still_lists_no_unit():
    from tests.test_audit2_fixes import BUILDING_LV
    assert unit_numbers(BUILDING_LV) == set()
    assert status(BUILDING_LV, None) == "UNVERIFIED"
    assert status(BUILDING_LV, "777", building_lv="777") == "UNVERIFIED"


# ── h1: a company holder's name says what an easement is for ─────────────────
@pytest.mark.parametrize("holder", [
    "Testovací Distribuce, a. s., Testovací 8, 40502 Testov, RČ/IČO: 00000000",
    "Testovací plynárenská Distribuce, a.s., Testovací 5, Testov, RČ/IČO: 0",
    "TESTdistribuce, a.s., Testovací 3, Testov, RČ/IČO: 0",
    "Testovací energetika s.r.o., Testovací 9, Testov",
])
def test_an_easement_by_deed_held_by_a_utility_company_is_soft(holder):
    text = lv(easement("Věcné břemeno (podle listiny)", holder))
    found = screen_lv_cz(text)
    assert [(e["flag"], e["tier"]) for e in found] == [("věcné břemeno", "soft")]
    assert status(text) == "PASS"


@pytest.mark.parametrize("holder", [
    "Kabelková Marie, Testovací 1, Testov",                 # a surname
    "Nováková Marie, Plynární 1096/23, Testov",             # a street
    "Testovací a.s. Plynární 5, Testov",                     # a company's street
    "Testovací s.r.o., Elektrárenská 5, Testov",
])
def test_a_person_or_an_address_never_makes_an_easement_by_deed_soft(holder):
    text = lv(easement("Věcné břemeno (podle listiny)", holder))
    assert [(e["tier"], e["note"]) for e in screen_lv_cz(text)] == [
        ("hard", "kind of easement not recognised")]
    assert status(text) == "REJECT"


# ── h5: "Věcné břemeno užívání" is not by itself a right to live ─────────────
def test_a_use_easement_for_a_cable_is_soft():
    text = lv(easement("Věcné břemeno užívání", "Testovací Distribuce, a. s., Testovací 8",
                       "umístění a provozování kabelového vedení NN"))
    assert [(e["tier"], e["note"]) for e in screen_lv_cz(text)] == [
        ("soft", "utility / access easement")]
    assert status(text) == "PASS"


def test_a_use_easement_of_a_distribution_company_is_soft():
    text = lv(easement("Věcné břemeno užívání", "TESTdistribuce, a.s., Testovací 3, Testov"))
    assert status(text) == "PASS"


@pytest.mark.parametrize("kind,description,note", [
    ("Věcné břemeno užívání", "", "kind of easement not recognised"),
    ("Věcné břemeno užívání bytu", "", "lifetime right to use or live in it"),
    ("Věcné břemeno užívání", "užívání bytu č. 101/5", "lifetime right to use or live in it"),
    ("Služebnost bytu", "", "lifetime right to use or live in it"),
    ("Věcné břemeno bytu", "", "lifetime right to use or live in it"),
])
def test_a_use_easement_held_by_a_person_still_rejects(kind, description, note):
    text = lv(easement(kind, "Kabelková Marie, Plynární 1, Testov", description))
    assert [(e["tier"], e["note"]) for e in screen_lv_cz(text)] == [("hard", note)]
    assert status(text) == "REJECT"


# ── h9: a register number inside a recognised entry ──────────────────────────
NOTE_D = ("  o Poznámka o podání žádosti o změnu zápisu dle V-3333/2026-101\n"
          "      Povinnost k\n      Jednotka: 101/5\n"
          "      Listina Žádost o změnu zápisu ze dne 01.10.2026.\n"
          "      Z-4444/2026-101\n")


def test_a_note_citing_a_register_number_is_no_unknown_entry():
    text = lv(BANK_LIEN, NOTE_D)
    assert unrecognised_entries(text) == []
    r = lv_cz.check_text(text, "1234")
    assert r["status"] == "PASS" and "poznámka" in str(r.get("soft_flags"))


def test_a_second_deed_and_unit_of_one_lien_are_no_unknown_entry():
    amended = BANK_LIEN.replace(
        "V-1234/2020-101\n",
        "V-1234/2020-101\n      Pořadí k 16.03.2020 10:15\n"
        "      Listina Smlouva o zřízení zástavního práva - dodatek č. 1 V-3333/2022-101\n"
        "      Povinnost k\n      Jednotka: 101/5\n")
    assert unrecognised_entries(lv(amended)) == []
    assert status(lv(amended)) == "PASS"


@pytest.mark.parametrize("before", ["", "      Pořadí k 16.03.2020 10:15\n"])
def test_an_unknown_entry_after_a_register_number_is_still_found(before):
    # Its bullet lost, right after a recognised entry's register number (and
    # its "Pořadí k …" stamp): a type line of its own, so a new entry.
    utility = easement("Věcné břemeno zřizování a provozování vedení",
                       "Testovací Distribuce, a. s., Testovací 8")
    unknown = ("  Reálné břemeno\n      Oprávnění pro Osoba Testovací\n"
               "      Povinnost k Jednotka: 101/5\n      Listina Smlouva V-88/2018-101\n")
    text = lv(utility + before + unknown)
    assert unrecognised_entries(text) == ["Reálné břemeno"]
    assert status(text) == "UNVERIFIED"


# ── #47: the Czech prompt names the screen's hard stops ──────────────────────
@pytest.mark.parametrize("entry", [
    "  o Nájemní právo\n      do 31.12.2060\n      Oprávnění pro Osoba Testovací\n",
    "  o Výhrada zpětné koupě\n      Oprávnění pro Osoba Testovací\n",
    "  o Zajišťovací převod práva\n      Oprávnění pro Osoba Testovací\n",
    "  o Užívací právo\n      Oprávnění pro Osoba Testovací\n",
])
def test_a_hard_stop_claude_may_clear_is_named_in_the_czech_prompt(entry):
    r = lv_cz.check_text(lv(entry), "1234")
    assert r["status"] == "REJECT" and r["claude_may_clear"] is True
    prompt = fold(llm._LV_SYSTEM_CZ)
    flags = [e["flag"] for e in screen_lv_cz(lv(entry))]
    assert flags and all(fold(f) in prompt for f in flags)


@pytest.mark.parametrize("term", [
    "nájem", "pacht", "výhrada zpětné koupě", "výhrada vlastnického práva",
    "práva lepšího kupce", "koupě na zkoušku", "užívací právo",
    "zajišťovací převod práva", "zákaz zcizení nebo zatížení not in favour of a bank",
])
def test_the_czech_prompt_names_every_hard_kind(term):
    assert term in llm._LV_SYSTEM_CZ
    assert term not in llm._LV_SYSTEM                     # the Slovak prompt is its own


def test_the_answer_the_prompt_now_asks_for_keeps_a_lease_rejected(monkeypatch):
    # The decision path is unchanged: the prompt now asks for HIGH on a
    # registered nájem, and a HIGH / unsafe answer keeps the REJECT.
    r = lv_cz.check_text(lv("  o Nájemní právo\n      Oprávnění pro Osoba Testovací\n"), "1234")
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda t, market="sk": {
        "risk_level": "HIGH", "is_safe_to_proceed": False, "summary": "lease", "flags": ["nájem"]})
    assert debt_bot._decide_lv(r)["status"] == "REJECT"


# ── #57: banks whose name glues "bank" to another word ───────────────────────
@pytest.mark.parametrize("creditor", [
    "Sberbank CZ, a.s. v likvidaci", "Volksbank CZ, a.s.", "eBanka, a.s.",
    "Expobank CZ a.s.", "Citibank Europe plc", "Commerzbank Aktiengesellschaft, pobočka Praha",
])
def test_more_banks_by_name(creditor):
    part_c = f"  o Zástavní právo smluvní\n      Oprávnění pro {creditor}, RČ/IČO: 0\n"
    assert [(e["flag"], e["blocking"]) for e in screen_lv_cz(lv(part_c))] == [
        ("zástavní právo", False)]


def test_a_name_only_containing_a_bank_name_is_no_bank():
    part_c = ("  o Zástavní právo smluvní\n      Oprávnění pro Citibankovní Testovací s.r.o., "
              "RČ/IČO: 0\n")
    assert [e["blocking"] for e in screen_lv_cz(lv(part_c))] == [True]


def test_the_slovak_bank_list_is_untouched():
    import config
    import markets
    assert markets.SK.lv_bank_names == tuple(config.LV_BANK_NAMES)
    assert "sberbank" not in markets.SK.lv_bank_names
