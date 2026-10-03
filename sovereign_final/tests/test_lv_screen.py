"""Tests for modules/lv_screen.py and debt_bot._parse_lv — the entry-by-entry
LV screen.

The old screen cleared every reject keyword whenever any bank name appeared
anywhere in the document, and only matched nominative phrases. The reported
failures — a private lien beside a bank mortgage, an exekúcia beside a bank
mortgage, "začatie exekúcie" — are the first three tests."""

import pytest

import modules.debt_bot as debt_bot
from modules.lv_screen import screen_lv, is_bank, fold


def _status(text):
    return debt_bot._parse_lv(text)["status"]


class TestReportedFalsePasses:
    def test_private_lien_beside_bank_mortgage_rejects(self):
        text = ("ČASŤ C: ŤARCHY 1 V 2797/2013 - Záložné právo v prospech "
                "Slovenská sporiteľňa, a.s., Tomášikova 48, IČO 00151653 na byt "
                "č. 12 - č.z. 2345/2013 2 V 512/2019 - Záložné právo v prospech "
                "Ján Novák, nar. 1.1.1970, Hlavná 1, Nitra na byt č. 12")
        res = debt_bot._parse_lv(text)
        assert res["status"] == "REJECT"
        assert res["flag"] == "záložné právo"
        assert "Ján Novák" in res["detail"]

    def test_exekucia_beside_bank_mortgage_rejects(self):
        text = ("Záložné právo v prospech Tatra banka, a.s. "
                "Z 55/2021 - Exekučný príkaz EX 55/2021 na zriadenie "
                "exekučného záložného práva")
        res = debt_bot._parse_lv(text)
        assert res["status"] == "REJECT"
        assert res["flag"] == "exekúcia"

    def test_inflected_zacatie_exekucie_rejects(self):
        res = debt_bot._parse_lv("Poznámka: Upovedomenie o začatí exekúcie EX 123/2022")
        assert res["status"] == "REJECT" and res["flag"] == "exekúcia"


class TestInflectionAndSpelling:
    @pytest.mark.parametrize("text,flag", [
        ("byt je zaťažený záložným právom v prospech Peter Kováč", "záložné právo"),
        ("Zalozne pravo v prospech Jozef Mrkva", "záložné právo"),
        ("Poznámka o vyhlásení konkurzu na majetok vlastníka", "konkurz"),
        ("podaná žaloba o určenie vlastníctva", "súdny spor"),
        ("začaté súdne konanie o vypratanie", "súdny spor"),
        ("Zriadenie vecného bremena — právo prechodu", "vecné bremeno"),
        ("Predkupné právo v prospech Mesto Nitra", "predkupné právo"),
        ("EXEKÚCIA EX 1/2020", "exekúcia"),
    ])
    def test_rejects(self, text, flag):
        res = debt_bot._parse_lv(text)
        assert res["status"] == "REJECT" and res["flag"] == flag

    def test_deposits_are_not_a_lawsuit(self):
        # "zálohy" (advance payments) must not read as "žaloba".
        assert _status("Mesačné zálohy za služby 120 €") == "PASS"


class TestBankLiens:
    @pytest.mark.parametrize("creditor", [
        "Tatra banka, a.s.",
        "Všeobecná úverová banka, a.s.",   # VÚB's legal name, as the LV prints it
        "VÚB, a.s.",
        "Československá obchodná banka, a.s.",
        "UniCredit Bank Czech Republic and Slovakia, a.s.",
        "Prvá stavebná sporiteľňa, a.s.",
        "365.bank, a. s.",
        "mBank S.A., pobočka zahraničnej banky",
        "Štátny fond rozvoja bývania",
    ])
    def test_bank_creditor_passes(self, creditor):
        assert _status(f"Záložné právo v prospech {creditor} na byt č. 12") == "PASS"

    def test_back_reference_to_the_same_lien_is_not_a_second_lien(self):
        text = ("V 2797/2013-Záložné právo v prospech Všeobecná úverová banka, "
                "a.s., Mlynské nivy 1, IČO: 31320155 na byt č.12 podľa zmluvy o "
                "zriadení záložného práva č. 1234/2013 - č.z. 2345/2013")
        assert _status(text) == "PASS"

    def test_two_bank_liens_pass(self):
        text = ("1 Záložné právo v prospech Prima banka Slovensko, a.s. "
                "2 Záložné právo v prospech Prvá stavebná sporiteľňa, a.s.")
        res = debt_bot._parse_lv(text)
        assert res["status"] == "PASS"
        assert "2 bank lien(s)" in res["detail"]

    def test_bank_elsewhere_in_document_clears_nothing(self):
        # A bank as an OWNER in part B, or in the next sentence, is not the
        # lien's creditor.
        assert _status("ČASŤ B: vlastník Tatra banka a.s. "
                       "ČASŤ C: Záložné právo v prospech Ján Novák") == "REJECT"
        assert _status("Záložné právo v prospech Ján Novák. "
                       "Iné údaje: úver Tatra banka") == "REJECT"

    def test_state_and_tax_liens_are_not_banks(self):
        assert _status("Zákonné záložné právo v prospech Daňový úrad Bratislava") == "REJECT"

    def test_unattributable_lien_blocks(self):
        assert _status("Záložné právo zapísané V 12/2010.") == "REJECT"

    def test_creditor_named_without_marker(self):
        assert _status("Záložné právo: Tatra banka, a.s.") == "PASS"

    def test_titled_private_creditor_blocks(self):
        res = debt_bot._parse_lv("Záložné právo v prospech Ing. Ján Novák, Hlavná 1")
        assert res["status"] == "REJECT"
        assert "Ing. Ján Novák" in res["detail"]


class TestCleanAndShape:
    def test_clean_lv(self):
        res = debt_bot._parse_lv("ČASŤ C: ŤARCHY: Bez zápisu.")
        assert res["status"] == "PASS" and res["raw"] == "ČASŤ C: ŤARCHY: Bez zápisu."

    def test_one_exekucia_entry_reported_once(self):
        entries = screen_lv("Exekúcia EX 123/2020, exekučné záložné právo")
        assert [e["flag"] for e in entries] == ["exekúcia"]

    def test_distress_cannot_be_cleared_by_claude_but_liens_can(self):
        assert debt_bot._parse_lv("Exekúcia EX 1/2020")["claude_may_clear"] is False
        assert debt_bot._parse_lv(
            "Záložné právo v prospech Ján Novák")["claude_may_clear"] is True

    def test_fold_keeps_positions(self):
        text = "Záložné právo — Ľubovňa"
        assert len(fold(text)) == len(text)
        assert fold(text) == "zalozne pravo — lubovna"

    def test_is_bank(self):
        assert is_bank("Tatra banka") and is_bank("Slovenská sporiteľňa")
        assert not is_bank("Ján Novák") and not is_bank("Nebank s.r.o.")
