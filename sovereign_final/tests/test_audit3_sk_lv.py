"""Regression tests for the third review, Slovak LV area (modules/lv_screen,
modules/debt_bot): one or more per finding, on synthetic text and synthetic
listings only — no real LV, no personal data, no request leaves the test.

Names are placeholders ("Peter Vzorový", "Jana Vzorová"); banks and utilities
appear by name only because the screen reads creditors by name."""

import pytest

import kataster_scraper as ks
import modules.debt_bot as debt_bot
from modules import lv_screen
from modules.debt_bot import _parse_lv
from modules.lv_screen import is_bank, screen_lv
from tests.conftest import make_listing

C = "ČASŤ C: ŤARCHY "
BANK = "1 V 100/2015 - Záložné právo v prospech Tatra banka, a.s., IČO 12345678 na byt č. 12 "


def _status(text):
    return _parse_lv(text)["status"]


# ── #9: foreclosure, auction, injunction, seizure, ownership dispute ─────────
@pytest.mark.parametrize("entry,flag", [
    (BANK + "2 P 55/2022 - Poznámka o začatí výkonu záložného práva v prospech "
     "Tatra banka, a.s.", "výkon záložného práva"),
    (BANK + "2 P 77/2023 - Oznámenie o dražbe nehnuteľnosti", "dražba"),
    ("1 P 12/2023 - Predbežné opatrenie Okresného súdu, ktorým sa zakazuje nakladať "
     "s bytom č. 12", "predbežné opatrenie"),
    ("1 P 13/2023 - Uznesenie o zaistení nehnuteľnosti podľa Trestného poriadku",
     "zaistenie"),
    ("1 P 14/2023 - Poznámka: začatie konania o určenie vlastníckeho práva k bytu č. 12",
     "súdny spor"),
    ("1 P 15/2023 - Poznámka o spornosti zápisu vlastníckeho práva", "súdny spor"),
])
def test_slovak_distress_notes_reject_and_claude_cannot_clear_them(entry, flag):
    res = _parse_lv(C + entry)
    assert res["status"] == "REJECT"
    assert res["flag"] == flag
    assert res["claude_may_clear"] is False


def test_a_pledgees_enforcement_note_is_not_a_second_bank_lien():
    res = _parse_lv(C + BANK + "2 P 55/2022 - Poznámka o začatí výkonu záložného práva "
                    "v prospech Tatra banka, a.s.")
    assert res["status"] == "REJECT" and "výkon záložného práva" in res["detail"]


def test_an_auction_counts_from_part_c_on():
    # Before part C (part B's title of acquisition) the word burdens nothing;
    # in part C it blocks; with no part C heading to go by, it blocks anywhere.
    head = ("LIST VLASTNÍCTVA č. 4321 ČASŤ B: VLASTNÍCI A INÉ OPRÁVNENÉ OSOBY 1 [OSOBA1] "
            "Spoluvlastnícky podiel: 1/1 Titul nadobudnutia: dražba N 12/2015 ")
    assert _status(head + C + "Bez zápisu.") == "PASS"
    assert _status(head + C + "1 P 77/2023 - Oznámenie o dražbe nehnuteľnosti") == "REJECT"
    assert _status("Titul nadobudnutia: dražba N 12/2015") == "REJECT"


def test_other_distress_and_an_auction_heading_variant():
    assert _status("LIST VLASTNÍCTVA C. ŤARCHY 1 P 77/2023 - Dražobná vyhláška") == "REJECT"
    # The Czech vocabulary reads parts C–D itself and keeps no part-C-only rule.
    from modules.lv_screen_cz import VOCABULARY
    assert VOCABULARY.part_c_only == frozenset()


# ── #11: "Zmluva o zriadení / Zriadenie záložného práva" as a new entry ──────
@pytest.mark.parametrize("second", [
    "2 V 200/2021 - Zmluva o zriadení záložného práva, záložný veriteľ Peter Vzorový, "
    "nar. 1.1.1960, na byt č. 12",
    "2 V 200/2021 - Zriadenie záložného práva, oprávnený: Peter Vzorový",
])
def test_a_private_lien_worded_as_a_contract_after_a_bank_lien_rejects(second):
    res = _parse_lv(C + BANK + second)
    assert res["status"] == "REJECT"
    assert "Peter Vzorový" in res["detail"] and "NOT a bank" in res["detail"]


@pytest.mark.parametrize("ref", [
    "podľa zmluvy o zriadení záložného práva č. 77/2015",
    "podľa V 100/2015 zmluvy o zriadení záložného práva",
    "podľa zmluvy o zriadení záložného práva, záložný veriteľ Tatra banka, a.s.",
])
def test_a_same_entry_reference_to_the_bank_lien_still_passes(ref):
    res = _parse_lv(C + BANK + ref)
    assert res["status"] == "PASS"


# ── #12: a personal right worded with a verb ─────────────────────────────────
@pytest.mark.parametrize("entry", [
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová spočívajúce v práve užívať byt "
    "č. 5 a v práve prístupu k nemu",
    "1 V 50/2018 - Vecné bremeno - právo užívať byt do smrti a právo prechodu v prospech "
    "Jana Vzorová",
    "1 V 50/2018 - Vecné bremeno v prospech Jana Vzorová spočívajúce v práve bývať v byte "
    "č. 5 a práve prechodu cez pozemok",
])
def test_a_right_to_use_or_live_in_the_flat_beside_an_access_word_is_hard(entry):
    res = _parse_lv(C + entry)
    assert res["status"] == "REJECT"
    assert "lifetime right to use or live in it" in res["detail"]


def test_a_utility_easement_stays_soft_beside_the_wider_personal_rule():
    res = _parse_lv(C + "1 V 300/2014 - Vecné bremeno - právo uloženia plynovej prípojky "
                        "a právo prístupu k nej")
    assert res["status"] == "PASS" and res["soft_flags"]


# ── #13: leasing / insurance companies of a banking group ────────────────────
@pytest.mark.parametrize("creditor", [
    "VÚB Leasing, a.s.", "ČSOB Leasing, a.s.", "UniCredit Leasing Slovakia, a.s.",
    "ČSOB Poisťovňa, a.s.", "mBank Leasing s.r.o.",
])
def test_a_banking_groups_leasing_or_insurance_company_is_no_bank(creditor):
    assert not is_bank(creditor)
    text = C + f"1 V 10/2024 - Záložné právo v prospech {creditor}, IČO 12345678 na byt č. 12"
    assert _status(text) == "REJECT"


@pytest.mark.parametrize("creditor", [
    "VÚB, a.s.", "VÚB banka", "Všeobecná úverová banka, a.s.", "ČSOB banka",
    "Československá obchodná banka, a.s.", "UniCredit Bank Czech Republic and Slovakia",
    "Prima banka Slovensko, a.s.", "Prvá stavebná sporiteľňa, a.s.",
    "Wüstenrot stavebná sporiteľňa, a.s.", "Oberbank AG", "mBank S.A.", "365.bank, a. s.",
    "Tatra banka, a.s.", "Štátny fond rozvoja bývania", "ŠFRB",
])
def test_banks_still_clear_their_own_lien(creditor):
    assert is_bank(creditor)
    assert _status(C + f"1 V 10/2024 - Záložné právo v prospech {creditor} na byt č. 12") \
        == "PASS"


# ── #43: a contract word before the next entry's register number ────────────
@pytest.mark.parametrize("second", [
    "2 V 512/2019 - Záložné právo pre Peter Vzorový, nar. 1.1.1970, Skúšobná 1, Nitra na "
    "byt č. 12",
    "2 V 512/2019 - Záložné právo: Peter Vzorový, nar. 1.1.1970, Skúšobná 1, Nitra",
    "2 V 512/2019 - Záložné právo, oprávnený: Peter Vzorový, Skúšobná 1, Nitra",
    "2 V 512/2019 - Záložné právo, veriteľ: Peter Vzorový, Skúšobná 1, Nitra",
    "\n2 V 512/2019 - Záložné právo pre Peter Vzorový, Skúšobná 1, Nitra",
])
@pytest.mark.parametrize("end_of_first", ["podľa zmluvy V 100/2015 ", ", zriadené zmluvou "])
def test_a_private_lien_after_an_entry_ending_in_its_contract_rejects(second, end_of_first):
    text = C + BANK.rstrip() + end_of_first + second
    res = _parse_lv(text)
    assert res["status"] == "REJECT"
    assert "Peter Vzorový" in res["detail"]


# ── #10: RE-VERIFY reads the cadastre now ────────────────────────────────────
@pytest.fixture
def portal(full_db, monkeypatch):
    """The real enrich_lv and cadastre cache over a temp DB; the portal is a
    list of LV texts served in turn (None: unreachable), counting requests."""
    import database as db
    db.upsert_listing(make_listing("l1", district="Nitra"))
    db.set_flat_lv("l1", "4321", "Nitra")
    served = {"texts": [], "requests": 0}

    def fetch(lv_no, ku_code):
        served["requests"] += 1
        text = served["texts"].pop(0) if len(served["texts"]) > 1 else served["texts"][0]
        if text is None:
            raise ks.CadastreError("portal down")
        return text

    monkeypatch.setattr(ks, "resolve_cadastral_unit",
                        lambda area: {"code": 838365, "name": "Nitra"})
    monkeypatch.setattr(ks, "fetch_lv_text", fetch)
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    return served


def _lv_status(full_db):
    c = full_db()
    row = c.execute("SELECT lv_status, lv_detail FROM listings WHERE id='l1'").fetchone()
    c.close()
    return row["lv_status"], row["lv_detail"]


def test_reverify_reads_the_cadastre_not_the_cached_copy(portal, full_db):
    exekucia = C + "1 Z 55/2026 - Exekučný príkaz EX 55/2026 na byt č. 12"
    clean = C + "Bez zápisu."
    portal["texts"] = [exekucia, clean]
    assert debt_bot.reverify("l1")["status"] == "REJECT"
    assert portal["requests"] == 1
    # The lien is struck off: the re-check sees it.
    assert debt_bot.reverify("l1")["status"] == "PASS"
    assert portal["requests"] == 2
    assert _lv_status(full_db)[0] == "PASS"


def test_reverify_sees_a_lien_entered_since_the_last_read(portal, full_db):
    portal["texts"] = [C + "Bez zápisu.", C + "1 Z 55/2026 - Exekučný príkaz EX 55/2026"]
    assert debt_bot.reverify("l1")["status"] == "PASS"
    assert debt_bot.reverify("l1")["status"] == "REJECT"
    assert _lv_status(full_db)[0] == "REJECTED"


def test_the_background_run_keeps_the_cache(portal, full_db):
    portal["texts"] = [C + "Bez zápisu."]
    import database as db
    row = db.get_lv_row("l1")
    assert debt_bot.check_listing(row)["status"] == "PASS"
    assert debt_bot.check_listing(row)["status"] == "PASS"
    assert portal["requests"] == 1          # the second read came from the cache


def test_a_re_check_that_cannot_reach_the_cadastre_is_not_the_old_verdict(portal, full_db):
    portal["texts"] = [C + "Bez zápisu.", None]
    assert debt_bot.reverify("l1")["status"] == "PASS"
    res = debt_bot.reverify("l1")
    assert res["status"] == "UNVERIFIED" and "portal down" in res["detail"]
    assert _lv_status(full_db)[0] == "UNVERIFIED"


# ── #14 / #44: an earlier Claude read never outlives its check ───────────────
def _analysis(full_db, lid):
    c = full_db()
    row = c.execute("SELECT lv_status, lv_risk_level, lv_summary FROM listings WHERE id=?",
                    (lid,)).fetchone()
    c.close()
    return tuple(row)


def test_a_slovak_re_check_clears_the_last_claude_read(full_db, monkeypatch):
    import database as db
    db.upsert_listing(make_listing("s1", district="Nitra"))
    db.set_flat_lv("s1", "4321", "Nitra")
    answers = {"lv": None, "claude": None}
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv, **kw: answers["lv"])
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda text, **kw: answers["claude"])

    answers["lv"] = {"status": "OK", "detail": "", "lv_text": C + BANK}
    answers["claude"] = {"risk_level": "LOW", "is_safe_to_proceed": True, "flags": [],
                         "summary": "Only a bank mortgage; clean."}
    assert debt_bot.reverify("s1")["status"] == "PASS"
    assert _analysis(full_db, "s1") == ("PASS", "LOW", "Only a bank mortgage; clean.")

    # The lookup fails: UNVERIFIED, and no Claude read of it.
    answers["lv"] = {"status": "ERROR", "detail": "portal down", "lv_text": None}
    assert debt_bot.reverify("s1")["status"] == "UNVERIFIED"
    assert _analysis(full_db, "s1") == ("UNVERIFIED", None, None)

    # An exekúcia with the Claude call failing: the screen decides.
    answers["lv"] = {"status": "OK", "detail": "",
                     "lv_text": C + "1 Z 55/2026 - Exekučný príkaz EX 55/2026"}
    answers["claude"] = None
    assert debt_bot.reverify("s1")["status"] == "REJECT"
    assert _analysis(full_db, "s1") == ("REJECTED", None, None)

    # Claude switched off.
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    answers["lv"] = {"status": "OK", "detail": "", "lv_text": C + BANK}
    assert debt_bot.reverify("s1")["status"] == "PASS"
    assert _analysis(full_db, "s1") == ("PASS", None, None)


def test_a_czech_re_check_clears_the_last_claude_read(full_db, monkeypatch):
    import database as db
    from tests.test_lv_cz import BANK_LIEN, lv
    db.upsert_listing(make_listing("cz1", market="cz", currency="CZK", district="Praha 2",
                                   description="Vlastnictví: osobní."))
    monkeypatch.delenv("CZ_CUZK_API_KEY", raising=False)
    claude = {"answer": {"risk_level": "LOW", "is_safe_to_proceed": True, "flags": [],
                         "summary": "Only a bank mortgage; clean."}}
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda text, **kw: claude["answer"])

    db.set_lv_document("cz1", lv(BANK_LIEN))
    assert debt_bot.reverify("cz1")["status"] == "PASS"
    assert _analysis(full_db, "cz1") == ("PASS", "LOW", "Only a bank mortgage; clean.")

    claude["answer"] = None
    db.set_lv_document("cz1", lv(BANK_LIEN, part_d="  o Zahájení exekuce\n"))
    assert debt_bot.reverify("cz1")["status"] == "REJECT"
    assert _analysis(full_db, "cz1") == ("REJECTED", None, None)

    db.set_lv_document("cz1", "  ")                        # the výpis removed
    assert debt_bot.reverify("cz1")["status"] == "UNVERIFIED"
    assert _analysis(full_db, "cz1") == ("UNVERIFIED", None, None)


def test_a_claude_read_of_this_check_is_still_stored(full_db, monkeypatch):
    import database as db
    db.upsert_listing(make_listing("s2", district="Nitra"))
    db.set_flat_lv("s2", "4321", "Nitra")
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv, **kw: {
        "status": "OK", "detail": "", "lv_text": C + "1 Z 55/2026 - Exekučný príkaz EX 55/2026"})
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda text, **kw: {
        "risk_level": "HIGH", "is_safe_to_proceed": False, "flags": ["EXEKUCIA"],
        "summary": "An exekúcia is registered."})
    assert debt_bot.reverify("s2")["status"] == "REJECT"
    assert _analysis(full_db, "s2") == ("REJECTED", "HIGH", "An exekúcia is registered.")


# ── h0: a utility's own name still marks its easement as a utility one ───────
UTILITY_EASEMENTS = [
    # Statutory, the holder followed by its address and the law.
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská energetika, a.s., Skúšobná 6, "
    "Bratislava, IČO 12345678 v zmysle § 22 zák. č. 79/1957 Zb. o výrobe, rozvode a "
    "spotrebe elektriny.",
    "1 Z 1234/2005 - Vecné bremeno v prospech Slovenský plynárenský priemysel, a.s. v zmysle "
    "zák. č. 656/2004 Z.z. o energetike",
    # The description straight after the holder.
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská distribučná, a.s. na uloženie "
    "elektrického vedenia",
    "1 Z 1234/2005 - Vecné bremeno v prospech Slovak Telekom, a.s. na umiestnenie "
    "telekomunikačnej siete",
    # Nothing but the holder: its name is the only evidence.
    "1 Z 1234/2005 - Vecné bremeno v prospech Západoslovenská distribučná, a.s., IČO 12345678",
    "1 Z 1234/2005 - Vecné bremeno v prospech Slovenský plynárenský priemysel, a.s.",
]


@pytest.mark.parametrize("entry", UTILITY_EASEMENTS)
def test_a_utility_or_statutory_easement_is_soft_and_passes(entry):
    text = "LIST VLASTNÍCTVA č. 4321 " + C + entry
    assert [(e["flag"], e["tier"]) for e in screen_lv(text)] == [("vecné bremeno", "soft")]
    res = _parse_lv(text)
    assert res["status"] == "PASS" and res["soft_flags"]


@pytest.mark.parametrize("entry", UTILITY_EASEMENTS[:4])
def test_a_utility_easement_passes_the_flat_check(entry, monkeypatch):
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv, **kw: {
        "status": "OK", "detail": "", "lv_text": "LIST VLASTNÍCTVA č. 4321 " + C + entry})
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    res = debt_bot.check_flat_lv("Petržalka", 4321)
    assert res["status"] == "PASS" and "utility / access easement" in res["detail"]


@pytest.mark.parametrize("entry", [
    # A person's address is no utility line …
    "1 V 512/2019 - Vecné bremeno in personam v prospech Jana Vzorová, Plynárenská 7, "
    "Bratislava podľa V 512/2019",
    "1 V 512/2019 - Vecné bremeno v prospech Jana Vzorová, Elektrárenská ulica 7, Bratislava",
    # … nor is a person's surname …
    "1 V 512/2019 - Vecné bremeno v prospech Peter Kabela, nar. 1.1.1960, Skúšobná 1, Nitra",
    # … nor a company's address when its name says nothing.
    "1 V 512/2019 - Vecné bremeno v prospech Vzor Reality, s.r.o., Plynárenská 7, Bratislava",
])
def test_a_holders_address_or_surname_does_not_make_an_easement_soft(entry):
    assert [(e["flag"], e["tier"]) for e in screen_lv(C + entry)] == [("vecné bremeno", "hard")]
    assert _status(C + entry) == "REJECT"


def test_the_holder_block_ends_where_the_description_starts():
    blocked = lv_screen._HOLDER_BLOCK_RE.sub(
        " ", lv_screen.fold("v prospech X, a.s., Elektrárenská 1 v zmysle zák. o energetike"))
    assert "energet" in blocked and "elektraren" not in blocked


# ── h8: a "C. ŤARCHY" heading is a part C ────────────────────────────────────
@pytest.mark.parametrize("text,want", [
    ("LIST VLASTNÍCTVA č. 4321 A. MAJETKOVÁ PODSTATA Byt č. 12 B. VLASTNÍCI 1 [OSOBA1] "
     "C. ŤARCHY Bez zápisu.", "PASS"),
    ("Výpis z LV 4321. ČASŤ C: ŤARCHY: Bez zápisu.", "PASS"),
    ("ČASŤ C: Záložné právo v prospech Tatra banka, a.s. na byt č. 12", "PASS"),
    ("Služba je momentálne nedostupná z dôvodu údržby. Skúste to neskôr, prosím.",
     "UNVERIFIED"),
])
def test_every_part_c_heading_the_screen_knows_counts(text, want, monkeypatch):
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda area, lv, **kw: {
        "status": "OK", "detail": "", "lv_text": text})
    assert debt_bot.check_flat_lv("Petržalka", 4321)["status"] == want
