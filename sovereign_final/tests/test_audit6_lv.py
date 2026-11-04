"""Audit 6: what a regression hunt found in the audit-5 title-deed changes,
each case reproduced on the pushed code first. Slovak reports are one line,
as kataster_scraper gives them; synthetic data only."""
import pytest

from modules import lv_cz
from tests.test_audit5_fixes import SK_HEAD, SPOR, TATRA, sk, status
from tests.test_lv_cz import BANK_LIEN, lv as cz_lv


# ── D1: a private lien in its own entry, under a number seen before ─────────
@pytest.mark.parametrize("part_c", [
    f"1 V 2797/2013 - Záložné právo v prospech {TATRA} 2 V 2797/2013 - Zmluva o zriadení "
    "záložného práva pre Kováč Peter, Hlavná 2, Testov",
    f"1 V 2797/2013 - Záložné právo v prospech {TATRA} 2 V 2797/2013 - Zmluva o zriadení "
    "záložného práva: Kováč Peter, Hlavná 2, Testov",
    # A seller's lien under the purchase's own number (part B: V 1000/2012).
    f"1 V 2797/2013 - Záložné právo v prospech {TATRA} 2 V 1000/2012 - Zmluva o zriadení "
    "záložného práva pre predávajúceho Kováč Peter, Hlavná 2, Testov",
])
def test_a_private_lien_under_a_known_number_is_its_own_entry(part_c):
    assert status(sk(part_c)) == "REJECT"


# ── D2: an address number before the bank lien's own deed opens no entry ─────
@pytest.mark.parametrize("part_c", [
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., Testovacia 3, 811 06 "
    "Bratislava 1 Zmluva o zriadení záložného práva zo dňa 15.05.2013",
    "1 Záložné právo v prospech Tatra banka, a.s., Testovacia 3, 811 06 Bratislava 1, "
    "IČO: 12 345 678 Zmluva o zriadení záložného práva zo dňa 15.05.2013",
    "1 Záložné právo v prospech Všeobecná úverová banka, a.s., Testovacia 1, 829 90 "
    "Bratislava 25 Zmluva o zriadení záložného práva V 2797/2013",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., Testovacia 3, 811 06 "
    "Bratislava 1 Zriadenie záložného práva V 2797/2013",
    "1 V 2797/2013 - Záložné právo v prospech Tatra banka, a.s., na byt číslo 12 Zmluva o "
    "zriadení záložného práva",
    # The creditor written after the deed, past an address-like number.
    "1 Záložné právo na byt č. 12, vchod 1 Zmluva o zriadení záložného práva V 2797/2013 "
    f"v prospech {SPOR}",
])
def test_an_address_number_before_the_banks_own_deed_passes(part_c):
    assert status(sk(part_c)) == "PASS"


@pytest.mark.parametrize("part_c", [
    # The next ordinal still opens the next entry.
    "1 V 100/2015 - Záložné právo: Kováč Peter, Hlavná 1, Testov 2 Zmluva o zriadení "
    "záložného práva v prospech Tatra banka, a.s.",
    f"1 V 100/2015 - Záložné právo v prospech {TATRA} 2 Zmluva o zriadení záložného práva "
    "pre Kováč Peter",
])
def test_the_next_ordinal_still_opens_the_next_entry(part_c):
    assert status(sk(part_c)) == "REJECT"


# ── D3: an all-caps report opens its entries too ─────────────────────────────
@pytest.mark.parametrize("part_c", [
    "1 V 2797/2013 - ZÁLOŽNÉ PRÁVO V PROSPECH TATRA BANKA, A.S., IČO: 12345678 2 ZMLUVA O "
    "ZRIADENÍ ZÁLOŽNÉHO PRÁVA PRE KOVÁČ PETER",
    "1 V 2797/2013 - ZÁLOŽNÉ PRÁVO V PROSPECH TATRA BANKA, A.S., IČO: 12345678 2 V 3000/2019 "
    "ZMLUVA O ZRIADENÍ ZÁLOŽNÉHO PRÁVA PRE KOVÁČ PETER",
])
def test_an_all_caps_report_keeps_each_lien_in_its_entry(part_c):
    assert status(sk(part_c).upper()) == "REJECT"


# ── D4: a title won in court, whatever its wording ───────────────────────────
@pytest.mark.parametrize("title", [
    "Rozsudok Okresného súdu Testov v spore o určenie vlastníckeho práva sp. zn. 12C/1/2010 "
    "zo dňa 01.02.2011, právoplatný dňa 05.03.2011",
    "Rozsudok Okresného súdu Testov o určení vlastníckeho práva v konaní sp. zn. 12C/1/2010",
    "Rozsudok Okresného súdu Testov, ktorým súd vyhovel návrhu na určenie vlastníckeho práva",
    "Rozsudok Okresného súdu Testov na návrh Novák Ján o určenie vlastníckeho práva",
    "Rozsudok Okresného súdu Testov o určení vlastníckeho práva, konanie skončené dňa 05.03.2011",
])
def test_a_title_won_in_court_passes_whatever_its_wording(title):
    head = SK_HEAD.replace("Kúpna zmluva V 1000/2012", title)
    assert status(head + f"ČASŤ C: ŤARCHY 1 V 100/2015 - Záložné právo v prospech {SPOR}") \
        == "PASS"


def test_a_pending_dispute_noted_in_part_b_still_rejects():
    assert status(sk(f"1 V 100/2015 - Záložné právo v prospech {TATRA}",
                     part_b_note="Poznámka: spor o určenie vlastníckeho práva k bytu č. 12 ")) \
        == "REJECT"


# ── D5: a person's right to use the property is hard ─────────────────────────
def _use(desc, holder):
    return (f"  o Věcné břemeno užívání\n      {desc}\n      Oprávnění pro {holder}\n"
            "      Povinnost k Jednotka: č. 101/5\n"
            "      Listina Smlouva o zřízení věcného břemene V-1234/2015-101\n")


@pytest.mark.parametrize("desc", [
    "právo užívat nemovitost a právo přístupu ke sklepu",
    "právo užívat nemovitost včetně cesty k domu",
    "právo užívat stavbu a povinnost údržby",
])
def test_a_persons_right_to_use_the_property_is_hard(desc):
    text = cz_lv(BANK_LIEN + _use(desc, "Nováková Marie, Testovací 1, Testov, "
                                        "RČ/IČO: 000000/0000"))
    assert lv_cz.check_text(text, "1234")["status"] == "REJECT"


def test_a_utilitys_right_to_use_its_structure_stays_soft():
    text = cz_lv(BANK_LIEN + _use("právo zřídit, provozovat a užívat stavbu vodovodní přípojky",
                                  "Testovací vodárny, a.s., Testovací 1, Testov, "
                                  "RČ/IČO: 00000000"))
    assert lv_cz.check_text(text, "1234")["status"] == "PASS"


# ── D6: a dash-bulleted entry after a claim list is still an entry ───────────
def _dash_bank(tail=""):
    return ("  - Zástavní právo smluvní\n"
            "      k zajištění pohledávek:\n"
            "      - Pohledávka z úvěru ve výši 2 400 000 Kč\n"
            "      Oprávnění pro Testovací banka, a.s., Testovací 33, Testov, RČ/IČO: 00000000\n"
            "      Povinnost k Jednotka: č. 101/5\n"
            "      Listina Smlouva o zřízení zástavního práva V-1234/2020-101\n" + tail)


def test_an_unknown_entry_after_a_claim_list_is_seen():
    text = cz_lv(_dash_bank("  - Reálné břemeno\n"))
    assert lv_cz.check_text(text, "1234")["status"] == "UNVERIFIED"


def test_a_claim_list_alone_is_no_entry():
    assert lv_cz.check_text(cz_lv(_dash_bank()), "1234")["status"] == "PASS"
