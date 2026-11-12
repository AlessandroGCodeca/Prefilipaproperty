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


# ── 4 · The owners' statutory lien (§ 15 of Act 182/1993) is flagged, not rejected ─
@pytest.mark.parametrize("entry", [
    "1 Záložné právo v zmysle § 15 zák. č. 182/1993 Z.z. v prospech vlastníkov bytov a "
    "nebytových priestorov v dome súpisné číslo 1234, Z 1234/2005",
    "1 Zákonné záložné právo podľa § 15 zákona č. 182/1993 Z. z. v prospech ostatných "
    "vlastníkov bytov",
    "1 Zákonné záložné právo v zmysle § 15 zákona NR SR č. 182/93 Z.z. v znení neskorších "
    "predpisov",                                      # no creditor named: the act says it
    "1 Záložné právo v prospech Spoločenstvo vlastníkov bytov Mlynská 5, Z 77/2010",
])
def test_the_owners_statutory_lien_is_a_soft_flag(entry):
    from modules.debt_bot import _parse_lv
    assert _hits(entry) == [("záložné právo", "soft", False)]
    out = _parse_lv(HEAD + entry)
    assert out["status"] == "PASS" and "bank lien" not in out["detail"]
    assert "§ 15 of Act 182/1993" in out["soft_flags"][0]
    assert "správca" in out["soft_flags"][0]          # what to do about it


@pytest.mark.parametrize("entries, flags", [
    # A private lien beside it still rejects.
    ("1 Záložné právo v prospech Jozef Mrkvička podľa V 1234/2020\n"
     "2 Záložné právo podľa § 15 zák. 182/1993 Z.z. v prospech vlastníkov bytov",
     [("záložné právo", "hard", True), ("záložné právo", "soft", False)]),
    # The owners enforcing it is distress.
    ("1 Záložné právo § 15 zák. 182/1993 v prospech vlastníkov bytov\n"
     "2 Začatie výkonu záložného práva v prospech vlastníkov bytov",
     [("záložné právo", "soft", False), ("výkon záložného práva", "hard", True),
      ("záložné právo", "soft", False)]),
    # Another statutory lien (the tax office's) is no owners' lien.
    ("1 Zákonné záložné právo v prospech Daňový úrad Bratislava podľa § 81 zák. 563/2009",
     [("záložné právo", "hard", True)]),
    # Another act's § 15, or Act 182/1993 without § 15, with a private creditor.
    ("1 Záložné právo podľa § 15 zák. 40/1964 v prospech Ján Novák",
     [("záložné právo", "hard", True)]),
])
def test_only_the_owners_lien_is_softened(entries, flags):
    assert _hits(entries) == flags


def test_the_owners_lien_rejects_when_soft_flags_do(monkeypatch):
    from modules import lv_screen
    monkeypatch.setattr(lv_screen, "LV_SOFT_FLAGS_REJECT", True)
    assert _hits("1 Záložné právo § 15 zák. 182/1993 v prospech vlastníkov bytov") == [
        ("záložné právo", "soft", True)]


def test_a_czech_lien_for_owners_still_blocks():
    # The Czech register has no such statutory lien: the rule is Slovak.
    from modules import lv_screen_cz
    assert lv_screen_cz.VOCABULARY.statutory_lien is None
    hits = lv_screen_cz.screen_lv_cz(
        "Výpis z katastru nemovitostí\nC Omezení vlastnického práva\n"
        "  o Zástavní právo smluvní\n      Oprávnění pro Společenství vlastníků bytů Dlouhá 5\n"
        "      V-123/2020-101\n")
    assert [(h["flag"], h["blocking"]) for h in hits] == [("zástavní právo", True)]


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    return database


def test_passes_from_the_older_rules_are_checked_again_once(db):
    from database.schema import _rescreen_lv_passes
    from tests.conftest import make_listing
    for lid, market in (("sk1", "sk"), ("sk2", "sk"), ("sk3", "sk"), ("cz1", "cz"),
                        ("cz2", "cz")):
        db.upsert_listing(make_listing(lid, market=market))
        db.set_lv_status(lid, "PASS", "", "clean")
    db.set_lv_status("sk2", "REJECTED", "záložné právo", "lien: vlastníkov bytov")
    db.set_lv_status("sk3", "REJECTED", "exekúcia", "exekúcia EX 1/2024")
    db.set_lv_status("cz2", "REJECTED", "zástavní právo", "private lien")
    conn = db.get_conn()
    try:
        # A database screened under version 1: before transfer bans (2) and
        # before the owners' statutory lien became a soft flag (3).
        conn.execute("UPDATE app_state SET value = '1' WHERE key = 'lv_rules_sk'")
        conn.commit()
        assert _rescreen_lv_passes(conn) == 2
        conn.commit()
        assert _rescreen_lv_passes(conn) == 0                # once per version
    finally:
        conn.close()
    # The PASS (a ban may now reject it) and the lien rejection (the owners'
    # lien may now pass) are checked again; distress and Czech verdicts stay.
    assert _lv_status(db) == {"sk1": "PENDING", "sk2": "PENDING", "sk3": "REJECTED",
                              "cz1": "PASS", "cz2": "REJECTED"}
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


# ── 2 · The 2026 bands, and the rental taxed on top of your other income ──────
def test_2026_has_four_bands_from_the_subsistence_minimum():
    import config
    bands = config.tax_rules(2026)["personal_bands"]
    zm = 284.13
    assert [round(u, 2) if u else None for u, _r in bands] == [
        round(154.8 * zm, 2), round(212.4 * zm, 2), round(264 * zm, 2), None]
    assert [r for _u, r in bands] == [0.19, 0.25, 0.30, 0.35]


@pytest.mark.parametrize("base, tax", [
    (10_000, 1_900.0),
    (43_983.32, 0.19 * 43_983.32),
    (50_000, 0.19 * 43_983.32 + 0.25 * (50_000 - 43_983.32)),
    (100_000, 0.19 * 43_983.32 + 0.25 * (60_349.21 - 43_983.32)
              + 0.30 * (75_010.32 - 60_349.21) + 0.35 * (100_000 - 75_010.32)),
])
def test_each_part_of_the_base_is_taxed_at_its_own_band(base, tax):
    import config
    from engine.financial import calc_income_tax_personal
    assert calc_income_tax_personal(base, config.tax_rules(2026)) == pytest.approx(tax)


def test_the_rental_is_taxed_on_top_of_a_salary():
    import config
    from engine.financial import calc_income_tax_personal
    rules = config.tax_rules(2026)
    alone = calc_income_tax_personal(5_000, rules)
    assert alone == pytest.approx(950)                           # 19 %
    assert calc_income_tax_personal(5_000, rules, other_income=50_000) == pytest.approx(1_250)  # 25 %
    assert calc_income_tax_personal(5_000, rules, other_income=80_000) == pytest.approx(1_750)  # 35 %
    # Straddling a band: €2,000 at 19 %, €3,000 at 25 %.
    straddle = calc_income_tax_personal(5_000, rules, other_income=43_983.32 - 2_000)
    assert straddle == pytest.approx(2_000 * 0.19 + 3_000 * 0.25)


def test_czech_rules_keep_their_two_bands():
    import markets
    from engine.financial import calc_income_tax_personal, personal_bands
    t = markets.tax_rules(2026, "cz")
    assert personal_bands(t) == ((t["personal_threshold"], 0.15), (None, 0.23))
    over = t["personal_threshold"] + 100_000
    assert calc_income_tax_personal(over, t) == pytest.approx(
        t["personal_threshold"] * 0.15 + 100_000 * 0.23)


def test_a_salary_raises_the_personal_tax_in_the_analysis(db, monkeypatch):
    from engine import financial
    base = financial.analyse(100_000, 55, "Žilina", rent_override=900)
    monkeypatch.setattr(financial, "OTHER_ANNUAL_INCOME", 50_000)
    salaried = financial.analyse(100_000, 55, "Žilina", rent_override=900)
    assert base.income_tax_personal > 0
    # 25 % instead of 19 % on the same taxable rent.
    assert salaried.income_tax_personal == pytest.approx(base.income_tax_personal * 25 / 19, rel=1e-3)
    assert salaried.surplus_personal < base.surplus_personal
    assert salaried.income_tax_sro == base.income_tax_sro       # the company's tax is its own


def test_scores_from_before_the_bands_are_redone():
    from engine.financial import SCORING_MODEL_VERSION
    assert SCORING_MODEL_VERSION >= 7


# ── 5 · s.r.o. and personal compared at the same equity ───────────────────────
def test_the_sros_extra_cash_is_not_a_saving(db):
    from engine.financial import analyse
    r = analyse(150_000, 55, "Bratislava - Petržalka")          # s.r.o. at 70 %, personal 80 %
    extra = r.total_cash_invested_sro - r.total_cash_invested
    assert extra == pytest.approx(15_000, rel=0.01)
    assert r.annual_sro_saving == pytest.approx(
        (r.surplus_sro - r.surplus_personal) * 12 - extra * r.mortgage_rate, abs=0.15)  # surpluses are stored to the cent
    # The audit's case: +€104/yr before, from the extra cash alone.
    assert r.annual_sro_saving < 0 and r.optimal_structure == "PERSONAL"
    assert "more cash costs" in r.recommendation


def test_at_the_same_ltv_nothing_is_charged(db):
    from engine.financial import analyse
    r = analyse(150_000, 55, "Bratislava - Petržalka", sro_ltv=0.8)
    assert r.total_cash_invested_sro == r.total_cash_invested
    assert r.annual_sro_saving == pytest.approx((r.surplus_sro - r.surplus_personal) * 12, abs=0.15)


def _sro_wins(db, monkeypatch, **kw):
    """A case where the company pays: a high earner's 35 % against 10 % + 10 %,
    on the same loan and no running cost."""
    from engine import financial
    monkeypatch.setattr(financial, "OTHER_ANNUAL_INCOME", 120_000)
    return financial.analyse(100_000, 55, "Žilina", rent_override=900, sro_ltv=0.8,
                             sro_rate_premium=0, sro_running_cost=0, **kw)


# ── 7 · Headline returns are the recommended structure's ──────────────────────
def test_headline_returns_follow_the_recommended_structure(db, monkeypatch):
    from engine.financial import analyse
    p = analyse(150_000, 55, "Bratislava - Petržalka")
    assert p.optimal_structure == "PERSONAL"
    assert p.cash_on_cash == pytest.approx(p.surplus_personal * 12 / p.total_cash_invested, abs=1e-4)
    assert p.net_rental_yield == pytest.approx(p.surplus_personal * 12 / 150_000, abs=1e-4)
    assert p.principal_paydown_monthly == p.mortgage_principal_monthly
    s = _sro_wins(db, monkeypatch)
    assert s.optimal_structure == "SRO"
    assert s.cash_on_cash == pytest.approx(s.surplus_sro * 12 / s.total_cash_invested_sro, abs=1e-4)


# ── 8 · The hold period decides whether the s.r.o.'s setup pays back ──────────
def test_a_short_hold_keeps_the_setup_cost_from_paying_back(db, monkeypatch):
    import config
    ten = _sro_wins(db, monkeypatch)
    assert ten.optimal_structure == "SRO" and ten.annual_sro_saving > 0
    short = max(1, int(config.SRO_SETUP_COST // ten.annual_sro_saving))   # can't repay it
    assert ten.annual_sro_saving * short <= config.SRO_SETUP_COST
    held = _sro_wins(db, monkeypatch, hold_years=short)
    assert held.optimal_structure == "PERSONAL"
    assert f"beyond the {short}-year hold" in held.recommendation


def test_whatif_shows_the_recommended_structures_rate_shock(db):
    from tests.test_app_smoke import run_app
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    md = "\n".join(m.value for m in at.markdown)
    # The default custom flat: personal is recommended.
    assert "RATE SHOCK (personal)" in md and "EQUITY CASH FLOWS (personal)" in md
    at.slider(key="wi_hold").set_value(3).run()
    assert not at.exception, [e.value for e in at.exception]


# ── 9 · Czech towns outside the Deloitte index take the MF rent map's figure ──
def test_the_mf_rent_map_covers_the_towns_that_waited():
    from engine import rent_cz
    for town in ("kladno", "mladá boleslav", "opava", "frýdek-místek", "karviná",
                 "havířov", "teplice", "děčín", "chomutov", "most", "příbram", "kolín"):
        assert rent_cz.mf_rent(town), town
        assert rent_cz.rent_fallback_kind(town) == "mf"


def test_the_mf_rent_map_is_sane():
    from engine import rent_cz
    data = rent_cz._mf_map()
    assert len(data["rents"]) > 4000 and data["published"]
    assert "Cenová mapa nájemného" in data["source"]
    assert all(80 <= rent <= 700 and 1 <= coverage <= 5
               for rent, coverage in data["rents"].values())
    # Kladno the city (data coverage 5), not the Pardubický village.
    assert data["rents"]["kladno"][1] == 5
    # A name many municipalities share has no figure: it can't say which.
    assert rent_cz.mf_rent("nová ves") is None
    # Deloitte's figure wins where it has one.
    assert rent_cz.baseline_rent("brno") == rent_cz.RENT_PER_M2_CZ["brno"]
    assert rent_cz.rent_fallback_kind("brno") is None


def test_a_flat_priced_from_the_mf_map_says_so(db):
    from engine.financial import analyse
    r = analyse(2_500_000, 55, "Kladno - Kročehlavy", market="cz")
    assert r.rent_key == "kladno"
    assert "Ministry of Finance rent map" in r.recommendation


# ── 10 · Keyword-only LV checks say so ────────────────────────────────────────
@pytest.mark.parametrize("key_set", [False, True])
def test_the_lv_tabs_say_when_checks_are_keyword_only(db, monkeypatch, key_set):
    from modules import debt_bot
    from tests.test_app_smoke import run_app
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: key_set)
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    notes = [w.value for w in at.warning if "keyword rules only" in w.value]
    assert len(notes) == (0 if key_set else 2)          # LV TO-DO and REJECTED


def test_the_lv_step_says_when_checks_are_keyword_only(db, monkeypatch):
    from dashboard import actions
    from modules import debt_bot
    monkeypatch.setattr(debt_bot, "run_debt_filter", lambda **kw: (1, 0, 2))
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    level, msg = actions._lv_step(lambda *a: None)
    assert level == "warning" and "keyword rules only" in msg
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    level, msg = actions._lv_step(lambda *a: None)
    assert level == "success" and "keyword" not in msg


# ── 12 · Old title-deed texts are deleted, verdicts kept ──────────────────────
def test_old_lv_texts_are_purged_and_verdicts_kept(db):
    from datetime import datetime, timedelta, timezone
    from tests.conftest import make_listing
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    for lid, seen in (("gone", old), ("live", new), ("tracked", old), ("passed", old)):
        db.upsert_listing(make_listing(lid, market="cz", last_seen_at=seen, scraped_at=old))
        db.set_lv_document(lid, f"Vlastník: Jan Novák … {lid}")
        db.set_lv_status(lid, "REJECTED", "zástavní právo", "private lien")
    conn = db.get_conn()
    try:
        conn.execute("UPDATE listings SET is_active = 0, last_seen_at = ? "
                     "WHERE id IN ('gone', 'tracked', 'passed')", (old,))
        conn.commit()
    finally:
        conn.close()
    db.set_deal_stage("tracked", "OFFER", "")        # still yours: kept
    db.set_deal_stage("passed", "PASSED", "")        # given up: purged
    import kataster_scraper as ks
    conn = db.get_conn()
    try:
        ks._ensure_cache_table(conn)
        for key, when in (("old", old), ("fresh", new)):
            conn.execute("INSERT INTO cadastre_cache (cache_key, status, result_json, fetched_at) "
                         "VALUES (?, 'OK', '{\"lv_text\": \"Vlastník: …\"}', ?)", (key, when))
        conn.commit()
    finally:
        conn.close()

    out = db.purge_old_lv_texts(180)
    assert out["cadastre_cache"] == 1 and out["lv_documents"] == 2
    assert set(db.get_lv_documents(["gone", "live", "tracked", "passed"])) == {"live", "tracked"}
    conn = db.get_conn()
    try:
        assert [r[0] for r in conn.execute("SELECT cache_key FROM cadastre_cache")] == ["fresh"]
        verdicts = dict(conn.execute("SELECT id, lv_status FROM listings").fetchall())
    finally:
        conn.close()
    assert verdicts["gone"] == "REJECTED"           # the verdict stays
    assert db.purge_old_lv_texts(0) == {}            # 0 keeps everything


def test_housekeeping_purges_old_lv_texts(db, monkeypatch):
    import config
    import scheduler
    calls = []
    monkeypatch.setattr(db, "purge_old_lv_texts", lambda days: calls.append(days) or {"x": 3})
    monkeypatch.setattr(config, "LV_TEXT_RETENTION_DAYS", 90)
    step = next(fn for name, fn in scheduler._market_steps("sk", set())
                if "ousekeeping" in name)
    _result, msg = step()
    assert calls == [90] and "removed 3 LV text(s) older than 90 days" in msg


# ── 6 · Mortgage interest in the personal tax base: a switch, off by default ──
def test_interest_is_deducted_only_when_switched_on(db, monkeypatch):
    from engine import financial
    off = financial.analyse(100_000, 55, "Žilina", rent_override=900)
    monkeypatch.setattr(financial, "PERSONAL_INTEREST_DEDUCTIBLE", True)
    on = financial.analyse(100_000, 55, "Žilina", rent_override=900)
    interest = off.mortgage_interest_monthly * 12
    assert interest > 1_000
    # 19 % of a year's interest less tax, every month.
    assert off.income_tax_personal - on.income_tax_personal == pytest.approx(
        interest * 0.19 / 12, abs=0.02)
    assert on.surplus_personal > off.surplus_personal
    assert on.income_tax_sro == off.income_tax_sro      # the company always deducted it
    # The IRR's yearly tax uses the same base.
    kw = dict(structure="PERSONAL", rent=900)
    monkeypatch.setattr(financial, "PERSONAL_INTEREST_DEDUCTIBLE", False)
    irr_off = financial.project_irr(100_000, 55, "Žilina", **kw).irr
    monkeypatch.setattr(financial, "PERSONAL_INTEREST_DEDUCTIBLE", True)
    assert financial.project_irr(100_000, 55, "Žilina", **kw).irr > irr_off


def test_interest_is_left_out_by_default():
    import config
    assert config.PERSONAL_INTEREST_DEDUCTIBLE is False
