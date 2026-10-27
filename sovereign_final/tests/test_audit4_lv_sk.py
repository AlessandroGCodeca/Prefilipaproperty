"""Regression tests for the fourth review, Slovak LV screen (modules/lv_screen):
one or more per finding (C1, C2, C3, C4, C6), on synthetic text only — no real
LV, no personal data, no request leaves the test.

Names are placeholders ("Peter Vzorový", "Jana Kabelková", "[OSOBA1]"); banks
and utilities appear by name only because the screen reads creditors by name."""

import pytest

import modules.debt_bot as debt_bot
from modules import lv_screen
from modules.debt_bot import _parse_lv
from modules.lv_screen import screen_lv

C = "ČASŤ C: ŤARCHY "
BANK = "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s., IČO 12345678 na byt č. 12 "
PART_B = ("LIST VLASTNÍCTVA č. 4321 ČASŤ A: MAJETKOVÁ PODSTATA Byt č. 12 "
          "ČASŤ B: VLASTNÍCI A INÉ OPRÁVNENÉ OSOBY 1 [OSOBA1] Spoluvlastnícky podiel: 1/1 "
          "Titul nadobudnutia: {title} ")


def _status(text):
    return _parse_lv(text)["status"]


# ── C1: a court's ruling on ownership as part B's title of acquisition ──────
RULING_TITLES = [
    "Rozsudok Okresného súdu sp. zn. 12C/45/2010 o určení vlastníckeho práva, "
    "právoplatný dňa 1.2.2011, Z 300/2011",
    "Rozsudok Okresného súdu sp. zn. 12C/45/2010 vo veci určenia vlastníckeho práva, "
    "Z 300/2011",
    "Rozsudok Okresného súdu sp. zn. 12C/45/2010 - určenie vlastníckeho práva, Z 300/2011",
]


@pytest.mark.parametrize("title", RULING_TITLES)
@pytest.mark.parametrize("part_c", [
    "Bez zápisu.",
    BANK,
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská distribučná, a.s. na uloženie "
    "elektrického vedenia",
    "1 Z 100/1996 - Predkupné právo v prospech Mesto Vzorovo",
])
def test_a_court_ruling_as_the_title_of_acquisition_burdens_nothing(title, part_c):
    res = _parse_lv(PART_B.format(title=title) + C + part_c)
    assert res["status"] == "PASS"
    assert all(e["flag"] != "súdny spor" for e in res["entries"])


def test_the_flat_check_passes_a_title_won_in_court_with_or_without_claude(monkeypatch):
    text = PART_B.format(title=RULING_TITLES[0]) + C + BANK
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv, **kw: {
        "status": "OK", "detail": "", "lv_text": text})
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    res = debt_bot.check_flat_lv("Vzorovo", 4321)
    assert res["status"] == "PASS" and "Tatra banka" in res["detail"]

    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda text, **kw: {
        "risk_level": "LOW", "is_safe_to_proceed": True, "flags": [],
        "summary": "The owner holds by a court ruling; only a bank mortgage."})
    assert debt_bot._decide_lv(debt_bot.check_flat_lv("Vzorovo", 4321))["status"] == "PASS"


@pytest.mark.parametrize("text", [
    # Proceedings still pending, noted in part C …
    C + "1 P 14/2023 - Poznámka o začatí konania vo veci určenia vlastníckeho práva k bytu "
        "č. 12",
    # … or in part B: proceedings block wherever they are noted.
    PART_B.format(title="Kúpna zmluva V 1000/2012 Poznámka: začatie konania o určenie "
                        "vlastníckeho práva") + C + BANK,
    # From part C on, any wording of it blocks.
    PART_B.format(title="Kúpna zmluva V 1000/2012") + C
    + "1 P 14/2023 - Poznámka o určení vlastníckeho práva k bytu č. 12",
    PART_B.format(title=RULING_TITLES[0]) + C
    + "1 P 14/2023 - Poznámka o určení vlastníckeho práva k bytu č. 12",
    # The rest of "súdny spor" still reads the whole LV.
    PART_B.format(title="Kúpna zmluva V 1000/2012 Poznámka: prebieha súdne konanie") + C
    + "Bez zápisu.",
    # With no part C heading to go by, a ruling blocks anywhere, like an auction.
    "Titul nadobudnutia: " + RULING_TITLES[0],
])
def test_ownership_proceedings_and_rulings_in_part_c_still_reject(text):
    res = _parse_lv(text)
    assert res["status"] == "REJECT" and res["flag"] == "súdny spor"
    assert res["claude_may_clear"] is False


def test_a_part_c_note_of_proceedings_is_one_entry():
    entries = screen_lv(C + "1 P 14/2023 - Poznámka: začatie konania o určenie vlastníckeho "
                            "práva k bytu č. 12")
    assert [e["flag"] for e in entries] == ["súdny spor"]


# ── C2: the company form must belong to the holder's own name ──────────────
@pytest.mark.parametrize("entry", [
    "1 V 512/2019 - Vecné bremeno in personam v prospech Jana Kabelková, IČO 12345678, "
    "Skúšobná 1, Vzorovo",
    "1 V 512/2019 - Vecné bremeno in personam v prospech Jana Prechodská, bytom v areáli "
    "Vzor Chemika, a.s., Skúšobná 1",
    "1 V 512/2019 - Vecné bremeno in personam v prospech Eva Plynárová, budova Vzor Tower, "
    "s.r.o., Skúšobná 1",
    "1 V 512/2019 - Vecné bremeno in personam v prospech Jana Kabelková, doručovacia adresa: "
    "Vzor Reality s.r.o., Skúšobná 1",
    "1 V 512/2019 - Vecné bremeno in personam v prospech Ján Elektrický, Skúšobná 1, Vzorovo "
    "a Vzor s.r.o., IČO 12345678",
    "1 V 512/2019 - Vecné bremeno spočívajúce v práve užívania záhrady v prospech Peter "
    "Kabela, nar. 1.1.1960, Skúšobná 1, Vzorovo a Vzor s.r.o., IČO 12345678, Vzorovo",
    # An IČO with no legal form can't tell a utility from a sole trader: the
    # kind stays unread, as before audit 3.
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská distribučná, IČO 12345678",
])
def test_a_form_or_ico_after_a_persons_name_does_not_make_an_easement_soft(entry):
    text = "LIST VLASTNÍCTVA č. 4321 " + C + entry
    assert [(e["flag"], e["tier"], e["note"]) for e in screen_lv(text)] == [
        ("vecné bremeno", "hard", "kind of easement not recognised")]
    assert _status(text) == "REJECT"


@pytest.mark.parametrize("entry", [
    "1 Z 1234/2005 - Vecné bremeno v prospech Stredoslovenská distribučná, a. s., IČO 12345678",
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská distribučná a.s.",
    "1 Z 1234/2005 - Vecné bremeno v prospech Slovak Telekom,\na.s., Skúšobná 1",
])
def test_a_utilitys_own_name_and_form_still_make_its_easement_soft(entry):
    assert [(e["flag"], e["tier"]) for e in screen_lv(C + entry)] == [("vecné bremeno", "soft")]
    assert _status(C + entry) == "PASS"


@pytest.mark.parametrize("folded,company", [
    ("vecne bremeno v prospech zapadoslovenska energetika, a.s., skusobna 6", True),
    ("vecne bremeno v prospech slovak telekom a.s. na umiestnenie siete", True),
    ("vecne bremeno v prospech vzor teplo, s. r. o.", True),
    # A sole trader has an IČO too: an IČO alone is no company form.
    ("vecne bremeno v prospech jana kabelkova, ico 12345678", False),
    ("vecne bremeno v prospech jan elektricky, skusobna 1 a vzor s.r.o.", False),
    ("vecne bremeno - pravo prechodu", False),
])
def test_the_holders_form_is_read_in_its_name_or_right_after_it(folded, company):
    assert lv_screen._holder_is_company(folded) is company


# ── C3: a private lien in its own entry, worded as a contract, after a bank's
@pytest.mark.parametrize("second", [
    "2 V 200/2021 - Zmluva o zriadení záložného práva pre Peter Vzorový, nar. 1.1.1960, "
    "Skúšobná 1, Vzorovo na byt č. 12",
    "2 V 200/2021 - Zmluva o zriadení záložného práva: Peter Vzorový, nar. 1.1.1960, "
    "Skúšobná 1, Vzorovo na byt č. 12",
    "2 V 200/2021 - Zriadenie záložného práva pre Peter Vzorový",
    "2. V 200/2021 - Zmluva o zriadení záložného práva pre Peter Vzorový",
])
def test_a_private_lien_in_its_own_entry_after_a_bank_lien_rejects(second):
    res = _parse_lv(C + BANK + second)
    assert res["status"] == "REJECT"
    assert "Peter Vzorový" in res["detail"] and "NOT a bank" in res["detail"]


def test_a_lien_in_its_own_entry_with_no_creditor_to_read_rejects():
    res = _parse_lv(C + BANK + "2 V 200/2021 - Zmluva o zriadení záložného práva na byt č. 12")
    assert res["status"] == "REJECT" and "unreadable creditor" in res["detail"]


@pytest.mark.parametrize("text", [
    # A register number inside the bank's own entry opens no new entry.
    C + BANK + "V 100/2015 - zmluva o zriadení záložného práva",
    C + "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s., IČO 12345678 "
        "V 100/2015 - zmluva o zriadení záložného práva",
    C + BANK + "zo dňa 12.05.2015 V 100/2015 - zmluva o zriadení záložného práva",
    # A second bank's lien in its own entry still clears.
    C + BANK + "2 V 200/2021 - Zmluva o zriadení záložného práva pre VÚB banka, a.s.",
    C + BANK + "2 V 200/2021 - Zmluva o zriadení záložného práva v prospech VÚB banka, a.s.",
])
def test_same_entry_references_and_a_second_bank_lien_still_pass(text):
    assert _status(text) == "PASS"


# ── C4: a personal right of use worded with words between, or for a room ────
@pytest.mark.parametrize("entry", [
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová spočívajúce v práve bezodplatne "
    "užívať celý byt č. 5 a v práve prístupu k nemu",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová - právo užívania jednej izby v byte "
    "č. 5 a právo prístupu k nej",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová spočívajúce v práve užívať izbu v "
    "byte č. 5 a v práve prechodu",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová spočívajúce v práve bezodplatne "
    "užívať predmetný byt a v práve prístupu k nemu",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová - právo bezplatného užívania celého "
    "bytu a právo prístupu k nemu",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová - právo užívania kuchyne v byte č. 5 "
    "a právo prechodu",
])
def test_a_right_to_use_the_flat_or_a_room_beside_an_access_word_is_hard(entry):
    res = _parse_lv(C + entry)
    assert res["status"] == "REJECT"
    assert "lifetime right to use or live in it" in res["detail"]


@pytest.mark.parametrize("entry", [
    "1 V 300/2014 - Vecné bremeno - právo zriadenia, prevádzkovania a užívania "
    "elektroenergetickej stavby a prístupu k nej v prospech Západoslovenská distribučná, a.s.",
    "1 V 300/2014 - Vecné bremeno - právo užívania vodnej stavby - vodovodnej prípojky a "
    "prístupu k nej",
    "1 V 300/2014 - Vecné bremeno - právo užívania plynárenskej líniovej stavby a prístupu "
    "k nej",
    "1 V 300/2014 - Vecné bremeno - právo užívania časti nehnuteľnosti na uloženie "
    "telekomunikačného kábla v prospech Slovak Telekom, a.s.",
])
def test_a_utilitys_right_to_use_its_structure_stays_soft(entry):
    res = _parse_lv(C + entry)
    assert res["status"] == "PASS" and res["soft_flags"]


# ── C6: a bank named after a long claim line or the contract it names ───────
LONG_CLAIM = ("na zabezpečenie pohľadávky vo výške 120 000 EUR s príslušenstvom a budúcich "
              "pohľadávok do výšky 50 000 EUR zo zmluvy o úvere č. 123/2013 ")
SPORITELNA = "Slovenská sporiteľňa, a.s., IČO 12345678 na byt č. 12"


@pytest.mark.parametrize("entry", [
    "1 V 2797/2013 - Záložné právo " + LONG_CLAIM + "v prospech " + SPORITELNA,
    "1 V 2797/2013 - Záložné právo podľa zmluvy o zriadení záložného práva V 2797/2013 "
    "v prospech " + SPORITELNA,
    "1 V 2797/2013 - Záložné právo podľa zmluvy o zriadení záložného práva č. V 2797/2013 "
    "v prospech " + SPORITELNA,
    "1 V 2797/2013 - Zmluva o zriadení záložného práva - záložné právo v prospech "
    + SPORITELNA,
])
def test_a_bank_named_after_a_long_claim_or_its_contract_clears_its_lien(entry):
    res = _parse_lv(C + entry)
    assert res["status"] == "PASS" and "Slovenská sporiteľňa" in res["detail"]


@pytest.mark.parametrize("text", [
    # A private creditor after the claim line …
    C + "1 V 2797/2013 - Záložné právo " + LONG_CLAIM + "v prospech Peter Vzorový, "
        "nar. 1.1.1960",
    # … or after the contract it names, alone or after a bank's lien.
    C + "1 V 2797/2013 - Záložné právo podľa zmluvy o zriadení záložného práva V 2797/2013 "
        "v prospech Peter Vzorový",
    C + BANK + "2 V 300/2021 - Záložné právo podľa zmluvy o zriadení záložného práva "
               "V 300/2021 v prospech Peter Vzorový",
    # A creditor the entry names first is not cleared by a bank named later.
    C + "1 V 100/2015 - Záložné právo, veriteľ: Peter Vzorový, podľa zmluvy o zriadení "
        "záložného práva v prospech Tatra banka, a.s.",
])
def test_a_private_creditor_after_a_claim_or_contract_still_rejects(text):
    res = _parse_lv(text)
    assert res["status"] == "REJECT"
    assert "Peter Vzorový" in res["detail"] and res["claude_may_clear"] is True


@pytest.mark.parametrize("text", [
    C + "1 V 2797/2013 - Záložné právo " + LONG_CLAIM + "2 P 55/2022 - Poznámka v prospech "
        "Tatra banka, a.s.",
    C + "1 V 2797/2013 - Záložné právo " + LONG_CLAIM + "P 55/2022 - Poznámka v prospech "
        "Tatra banka, a.s.",
    C + "1 V 2797/2013 - Záložné právo podľa zmluvy o zriadení záložného práva V 200/2021 - "
        "Poznámka v prospech Tatra banka, a.s.",
    # The next entry's type line, its number lost: a capital opens it.
    C + "1 V 2797/2013 - Záložné právo " + LONG_CLAIM + "Záložné právo v prospech "
        "Tatra banka, a.s.",
])
def test_a_bank_named_in_the_next_entry_clears_nothing(text):
    res = _parse_lv(text)
    assert res["status"] == "REJECT" and "NOT a bank" in res["detail"]


# ── A lien's creditor and its back-reference stop at the next entry ─────────
_HEAD_C = ("ČASŤ A: MAJETKOVÁ PODSTATA\nByt č. 12\nČASŤ B: VLASTNÍCI\n1 Novák Ján\n"
           "ČASŤ C: ŤARCHY\n")


def _blocks(part_c):
    from modules import lv_screen
    return any(e["blocking"] for e in lv_screen.screen_lv(_HEAD_C + part_c))


@pytest.mark.parametrize("part_c", [
    # A private lien with no marker does not borrow the next entry's bank.
    "1 V 100/2015 - Záložné právo: Kováč Peter, Hlavná 1, Testov\n"
    "2 P 55/2022 - Poznámka v prospech Tatra banka, a.s.\n",
    "1 V 100/2015 - Záložné právo Kováč Peter\n2 P 55/2022 - Poznámka v prospech Tatra banka, a.s.\n",
    "1 V 100/2015 - Záložné právo: Kováč Peter, Hlavná 1, Testov 2 P 55/2022 - Poznámka "
    "v prospech Tatra banka, a.s.\n",
    # A second lien on its own numbered line is no back-reference.
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s.\n"
    "2 V 200/2021 Zmluva o zriadení záložného práva pre Kováč Peter\n",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s.\n"
    "2 Zmluva o zriadení záložného práva pre Kováč Peter\n",
    # A long claim's search for "v prospech" stops at the next entry too.
    "1 V 100/2015 - Záložné právo na zabezpečenie pohľadávky z úveru\n"
    "2 Zmluva o zriadení záložného práva v prospech Tatra banka, a.s.\n",
])
def test_a_lien_reads_nothing_of_the_next_entry(part_c):
    assert _blocks(part_c)


@pytest.mark.parametrize("part_c", [
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s.\n",
    "1 V 100/2015 - Záložné právo podľa V 512/2019 v prospech Tatra banka, a.s.\n",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s. podľa zmluvy o zriadení "
    "záložného práva V 100/2015\n",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s.\n Zmluva o zriadení záložného "
    "práva V 100/2015 zo dňa 1.1.2015\n",
    "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s., IČO 12345678 V 100/2015 - "
    "zmluva o zriadení záložného práva\n",
    "1 V 100/2015 - Záložné právo na zabezpečenie pohľadávky zo zmluvy o úvere č. 123 "
    "v prospech Tatra banka, a.s.\n",
])
def test_a_bank_lien_and_its_own_references_still_pass(part_c):
    assert not _blocks(part_c)
