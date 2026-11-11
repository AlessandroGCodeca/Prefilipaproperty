"""High and medium findings of the 6 November 2026 audit
(docs/AUDIT_REVIEW_2026-11-06.pdf): 1 (transfer bans on Slovak title deeds),
2 (the 2026 Slovak income-tax bands, and the rental taxed on top of your
other income), 5 (s.r.o. and personal compared at the same equity)."""

import pytest

from modules.lv_screen import screen_lv

HEAD = "LIST VLASTNÍCTVA č. 1234\nČASŤ A: MAJETKOVÁ PODSTATA\nČASŤ B: VLASTNÍCI\n1 Novák Ján\nČASŤ C: ŤARCHY\n"


def _hits(part_c: str) -> list[tuple]:
    return [(h["flag"], h["tier"], h["blocking"]) for h in screen_lv(HEAD + part_c)]


# ── 1 · A ban on transferring the flat is no longer screened clean ────────────
@pytest.mark.parametrize("entry", [
    "1 Zákaz prevodu a zaťaženia v prospech Mesto Žilina, V 22/2019",
    "1 Zákaz scudzenia v prospech Ján Novák, V 1/2020",
    "1 Zákaz scudzenia a zaťaženia nehnuteľnosti v prospech XY Development s.r.o.",
    "1 Obmedzenie prevodu nehnuteľnosti v prospech Štátny fond rozvoja bývania",
    "1 Obmedzenie scudzenia bytu v prospech Obec Rača",
    "1 ZAKAZ PREVODU v prospech Mesto Trnava",           # typed without diacritics
])
def test_a_transfer_ban_blocks(entry):
    assert _hits(entry) == [("zákaz prevodu", "hard", True)]


@pytest.mark.parametrize("bank", ["Tatra banka, a.s.", "Slovenská sporiteľňa, a.s.",
                                  "Všeobecná úverová banka, a.s."])
def test_a_banks_ban_with_its_mortgage_is_a_soft_flag(bank):
    # A bank registers one with its mortgage; it goes when the loan is repaid.
    hits = _hits(f"1 Záložné právo v prospech {bank} V 5/2021\n"
                 f"2 Zákaz scudzenia a zaťaženia v prospech {bank}, V 5/2021")
    assert ("zákaz prevodu", "soft", False) in hits
    assert not any(blocking for _f, _t, blocking in hits)


def test_the_state_housing_funds_ban_is_not_a_banks():
    # ŠFRB counts as a lender for its liens, but its ban on a subsidised flat
    # is a real restriction.
    assert _hits("1 Zákaz prevodu v prospech ŠFRB") == [("zákaz prevodu", "hard", True)]


def test_soft_bans_reject_when_asked(monkeypatch):
    from modules import lv_screen
    monkeypatch.setattr(lv_screen, "LV_SOFT_FLAGS_REJECT", True)
    assert _hits("1 Zákaz zaťaženia v prospech Tatra banka, a.s.") == [
        ("zákaz prevodu", "soft", True)]


def test_a_court_ban_on_disposal_is_still_distress_not_a_transfer_ban():
    assert [f for f, _t, _b in _hits("1 Zákaz nakladania s nehnuteľnosťou, uznesenie súdu")] \
        == ["predbežné opatrenie"]


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    return database


def test_passes_from_the_older_rules_are_checked_again_once(db):
    from database.schema import _rescreen_lv_passes
    from tests.conftest import make_listing
    for lid, market in (("sk1", "sk"), ("sk2", "sk"), ("cz1", "cz")):
        db.upsert_listing(make_listing(lid, market=market))
        db.set_lv_status(lid, "PASS", "", "clean")
    db.set_lv_status("sk2", "REJECTED", "záložné právo", "private lien")
    conn = db.get_conn()
    try:
        # A database screened under version 1 (before transfer bans).
        conn.execute("UPDATE app_state SET value = '1' WHERE key = 'lv_rules_sk'")
        conn.commit()
        assert _rescreen_lv_passes(conn) == 1
        conn.commit()
        assert _rescreen_lv_passes(conn) == 0                # once per version
    finally:
        conn.close()
    assert _lv_status(db) == {"sk1": "PENDING", "sk2": "REJECTED", "cz1": "PASS"}
    assert any(r["id"] == "sk1" for r in db.get_pending_lv())  # queued for the check
    # Checked again and clean: it stays PASS on the next start.
    db.set_lv_status("sk1", "PASS", "", "clean")
    db.init_db()
    assert _lv_status(db)["sk1"] == "PASS"


def _lv_status(db) -> dict:
    conn = db.get_conn()
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT id, lv_status FROM listings")}
    finally:
        conn.close()


def test_a_new_database_has_nothing_to_check_again(db):
    conn = db.get_conn()
    try:
        from modules.lv_screen import RULES_VERSION
        row = conn.execute("SELECT value FROM app_state WHERE key = 'lv_rules_sk'").fetchone()
        assert int(row[0]) == RULES_VERSION
    finally:
        conn.close()
