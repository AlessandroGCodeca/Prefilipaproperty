"""The fixes from the audit of 12 November 2026 (docs/AUDIT_REVIEW_2026-11-12.pdf):
findings 1, 4, 5, 8 and 9 and suggestion S2 here; the alerts (finding 2,
S1) in test_alerts.py."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import make_listing

HEAD = ("LIST VLASTNÍCTVA č. 4521\nČASŤ A: MAJETKOVÁ PODSTATA\nByt č. 23\n"
        "ČASŤ B: VLASTNÍCI\n1 Novák Ján, nar. 1.1.1975\nČASŤ C: ŤARCHY\n")
# A deed the way the cadastre's report reads once its HTML is stripped: one line.
REAL = ("VÝPIS Z LISTU VLASTNÍCTVA č. 4521 Okres: Bratislava V Katastrálne územie: Petržalka "
        "ČASŤ A: MAJETKOVÁ PODSTATA Byty a nebytové priestory Vchod: Hálova 12 Byt č. 23 "
        "ČASŤ B: VLASTNÍCI A INÉ OPRÁVNENÉ OSOBY 5 Novák Ján, Hálova 12, Bratislava "
        "Titul nadobudnutia Kúpna zmluva V 12345/2015 Poznámka Bez zápisu. "
        "ČASŤ C: ŤARCHY Por.č.: 5 Na byt č. 23 Záložné právo v prospech Slovenská sporiteľňa, "
        "a.s., Tomášikova 48, Bratislava, IČO: 00151653 na zabezpečenie pohľadávky podľa "
        "zmluvy o zriadení záložného práva - V 12346/2015 5 Záložné právo v zmysle § 15 "
        "zákona č. 182/1993 Z.z. v prospech ostatných vlastníkov bytov a nebytových "
        "priestorov v dome Iné údaje: 5 Žiadosť o zápis zmeny priezviska R 1234/2018 "
        "Poznámka: Bez zápisu. Údaje platné k 10.11.2026.")


def status(text):
    from modules.debt_bot import _parse_lv
    return _parse_lv(text)["status"]


# ── Finding 1: entries the screen used to pass ───────────────────────────────
@pytest.mark.parametrize("entry, flag, outcome", [
    ("Právo doživotného bývania a užívania bytu v prospech: Mária Nováková",
     "doživotné užívanie", "REJECT"),
    ("PLOMBA VYZNAČENÁ NA ZÁKLADE V-1234/2026", "plomba", "PASS"),
    ("Na nehnuteľnosti prebieha konanie V 5521/2026 - návrh na vklad kúpnej zmluvy",
     "prebiehajúce konanie", "PASS"),
    ("Poznámka: Duplicitné vlastníctvo k nehnuteľnosti s LV č. 2211",
     "duplicitné vlastníctvo", "REJECT"),
    ("Poznámka: Hodnovernosť údajov katastra o práve k nehnuteľnosti bola spochybnená",
     "spochybnená hodnovernosť", "REJECT"),
    ("Poznámka: Obmedzenie nakladania s nehnuteľnosťou na základe rozhodnutia správcu dane",
     "obmedzenie nakladania", "REJECT"),
    ("Poznámka: Nútená správa nehnuteľnosti", "nútená správa", "REJECT"),
    ("Poznámka: P 12/2026 Začaté vyvlastňovacie konanie", "vyvlastnenie", "REJECT"),
    ("Poznámka: Povolená reštrukturalizácia vlastníka", "reštrukturalizácia", "REJECT"),
    ("Vlastníkovi bola poskytnutá ochrana pred veriteľmi - splátkový kalendár",
     "reštrukturalizácia", "REJECT"),
    ("2 V 44/2021 - Právo spätnej kúpy v prospech DEVELOP s.r.o.", "právo spätnej kúpy", "REJECT"),
    ("3 Z 9/2019 - Nájomné právo v prospech Peter Malý na dobu 10 rokov", "nájomné právo", "REJECT"),
    ("Zádržné právo v prospech STAVMONT a.s.", "zádržné právo", "REJECT"),
])
def test_each_wording_is_read(entry, flag, outcome):
    from modules.lv_screen import screen_lv
    text = HEAD + entry
    assert flag in [e["flag"] for e in screen_lv(text)]
    assert status(text) == outcome


def test_a_soft_entry_says_what_to_do():
    from modules.debt_bot import _parse_lv
    d = _parse_lv(HEAD + "PLOMBA V-1234/2026")
    assert d["status"] == "PASS" and "plomba" in d["detail"] and "before an offer" in d["detail"]


def test_an_easement_for_life_is_one_entry_not_two():
    from modules.lv_screen import screen_lv
    entries = screen_lv(HEAD + "1 V 5/2010 - Vecné bremeno - právo doživotného užívania bytu "
                               "v prospech Mária Nováková")
    assert [e["flag"] for e in entries] == ["vecné bremeno"]
    assert entries[0]["blocking"]


def test_a_plomba_in_part_b_still_counts_and_a_proposal_there_does_not():
    from modules.lv_screen import screen_lv
    text = HEAD.replace("ČASŤ C", "PLOMBA V-1/2026 návrh na vklad V 2/2026 ČASŤ C") + "Bez zápisu."
    assert [e["flag"] for e in screen_lv(text)] == ["plomba"]


# ── Finding 1 (b): the safety net ────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    REAL,
    REAL.split("ČASŤ C")[0] + "ČASŤ C: ŤARCHY Bez zápisu. Iné údaje: Bez zápisu.",
    REAL.split("ČASŤ C")[0] + "ČASŤ C: ŤARCHY Bez tiarch.",
    REAL.split("ČASŤ C")[0] + ("ČASŤ C: ŤARCHY 1 Vecné bremeno - právo prechodu a prejazdu "
                               "cez pozemok parc. č. 55/2 v prospech vlastníka pozemku parc. "
                               "č. 55/3 - Z 44/2010 Poznámka: Bez zápisu."),
    REAL.split("ČASŤ C")[0] + ("ČASŤ C: ŤARCHY 1 Záložné právo v prospech Tatra banka, a.s., "
                               "IČO 00686930, na zabezpečenie pohľadávky vrátane všetkých "
                               "nárokov z úverovej zmluvy, Zmluva o zriadení záložného práva "
                               "V 5555/2019 Poznámka: Bez zápisu."),
])
def test_a_deed_the_screen_fully_reads_has_nothing_unknown(text):
    from modules.lv_screen import unrecognised_entries
    assert unrecognised_entries(text) == []


@pytest.mark.parametrize("added", [
    ("Poznámka: Bez zápisu.", "Poznámka: Na byt sa vedie dedičské konanie 12D/55/2026."),
    ("Iné údaje: 5 Žiadosť", "6 Z 88/2020 - Právo stavby v prospech Stavby s.r.o. Iné údaje: 5 Žiadosť"),
    ("Iné údaje: 5 Žiadosť", "6 Právo stavby v prospech Stavby s.r.o. Iné údaje: 5 Žiadosť"),
    ("Iné údaje: 5 Žiadosť", "6 Zákaz zriadenia ďalšieho záložného práva bez súhlasu banky "
                             "Iné údaje: 5 Žiadosť"),
])
def test_an_entry_no_rule_names_is_found(added):
    from modules.lv_screen import unrecognised_entries
    text = REAL.replace(*added)
    assert status(text) == "PASS"                 # the rules alone see nothing
    found = unrecognised_entries(text)
    assert len(found) == 1


def test_check_flat_lv_does_not_pass_a_deed_with_an_unknown_entry(monkeypatch):
    from modules import debt_bot
    text = REAL.replace("Poznámka: Bez zápisu.", "Poznámka: Na byt sa vedie dedičské konanie.")
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda *a, **k: {"status": "OK", "lv_text": text})
    r = debt_bot.check_flat_lv("Petržalka", "4521")
    assert r["status"] == "UNVERIFIED"
    assert "no rule" in r["detail"] and "dedičské konanie" in r["detail"]
    assert r["raw"] == text and r["unknown_entries"]
    monkeypatch.setattr(debt_bot, "enrich_lv", lambda *a, **k: {"status": "OK", "lv_text": REAL})
    assert debt_bot.check_flat_lv("Petržalka", "4521")["status"] == "PASS"


def test_claude_decides_a_deed_the_screen_held_back(monkeypatch):
    from modules import debt_bot
    held = {"status": "UNVERIFIED", "detail": "…no rule…", "raw": REAL,
            "unknown_entries": ["Poznámka: Na byt sa vedie dedičské konanie"], "soft_flags": []}
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "lv_text_for_claude", lambda *a, **k: (REAL, True))
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda *a, **k: {
        "risk_level": "LOW", "is_safe_to_proceed": True, "flags": [],
        "summary": "Inheritance note only."})
    d = debt_bot._decide_lv(held)
    assert d["status"] == "PASS"
    assert any("dedičské konanie" in f and "LOW" in f for f in d["soft_flags"])
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", lambda *a, **k: {
        "risk_level": "HIGH", "is_safe_to_proceed": False, "flags": ["probate"], "summary": "No."})
    assert debt_bot._decide_lv(held)["status"] == "REJECT"
    # Without a key the screen's UNVERIFIED stands.
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: False)
    assert debt_bot._decide_lv(held)["status"] == "UNVERIFIED"


# ── Finding 9: banks ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("creditor", [
    "Privatbanka, a.s.", "ISTROBANKA, a.s.", "VOLKSBANK Slovensko, a.s.",
    "Sberbank Slovensko, a.s.", "Citibank Europe plc, pobočka zahraničnej banky",
    "SLSP, a.s.", "Prvá stavebná sporiteľňa, a.s.", "Tatra banka, a.s.", "365.bank, a. s.",
])
def test_a_bank_is_a_bank(creditor):
    assert status(HEAD + f"1 V 10/2019 - Záložné právo v prospech {creditor}") == "PASS"


@pytest.mark.parametrize("creditor", [
    "Tatra-Leasing, s.r.o.", "BANKA PLUS s.r.o.", "Daňový úrad Bratislava",
    "Bankové družstvo Morava",
])
def test_no_bank_is_still_no_bank(creditor):
    assert status(HEAD + f"1 V 10/2019 - Záložné právo v prospech {creditor}") == "REJECT"


def test_a_czech_bank_glued_to_its_name_is_a_bank():
    from modules.lv_screen_cz import _BANK_RE
    from modules.lv_screen import is_bank
    assert is_bank("Expobank CZ a.s.", _BANK_RE)
    assert not is_bank("ČSOB Leasing, a.s.", _BANK_RE)


# ── The re-check of stored verdicts ──────────────────────────────────────────
def test_version_4_reads_pass_verdicts_and_lien_rejections_again(full_db):
    import database
    from database.schema import _rescreen_lv_passes
    for lid, st in (("p", "PASS"), ("r", "REJECTED"), ("x", "REJECTED"), ("c", "PASS")):
        database.upsert_listing(make_listing(lid, market="cz" if lid == "c" else "sk"))
        database.set_lv_status(lid, st, "záložné právo" if lid == "r" else "exekúcia", "d")
    conn = database.get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('lv_rules_sk', '3')")
    assert _rescreen_lv_passes(conn) == 2
    conn.commit()
    got = dict(conn.execute("SELECT id, lv_status FROM listings").fetchall())
    conn.close()
    assert got == {"p": "PENDING", "r": "PENDING", "x": "REJECTED", "c": "PASS"}


# ── Finding 8: a PASS is read again, and its date is shown ───────────────────
def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def test_an_old_pass_and_a_deals_week_old_pass_are_due_again(full_db):
    import database
    for lid, age, stage in (("old", 40, None), ("fresh", 3, None), ("deal", 9, "OFFER"),
                            ("watch", 9, "WATCHING"), ("nolv", 40, None)):
        database.upsert_listing(make_listing(lid))
        database.set_lv_status(lid, "PASS", "", "clean")
        if lid != "nolv":
            database.set_flat_lv(lid, "4521", "Petržalka")
            database.set_lv_status(lid, "PASS", "", "clean")
        conn = database.get_conn()
        conn.execute("UPDATE listings SET lv_checked_at=? WHERE id=?", (_days_ago(age), lid))
        conn.commit()
        conn.close()
        if stage:
            database.set_deal_stage(lid, stage)
    ids = lambda **kw: sorted(r["id"] for r in database.get_pending_lv(**kw))  # noqa: E731
    assert ids() == []
    assert ids(pass_days=30, deal_days=7) == ["deal", "old"]
    assert ids(pass_days=0, deal_days=7) == ["deal"]


def test_the_card_says_when_the_deed_was_checked():
    from dashboard.fmt import lv_checked_label
    assert lv_checked_label({}) == ""
    fresh = lv_checked_label({"lv_status": "PASS", "lv_checked_at": _days_ago(2)})
    assert fresh.startswith("checked ") and "2 days ago" in fresh and "⚠" not in fresh
    old = lv_checked_label({"lv_status": "PASS", "lv_checked_at": _days_ago(45)})
    assert "⚠" in old and "re-verify" in old
    # An old REJECTED is not a stale clean bill.
    assert "⚠" not in lv_checked_label({"lv_status": "REJECTED", "lv_checked_at": _days_ago(45)})
    assert "před 2 dny" in lv_checked_label({"lv_status": "PASS",
                                              "lv_checked_at": _days_ago(2)}, cz=True)


# ── S2: Read part C ──────────────────────────────────────────────────────────
def test_part_c_is_shown_with_the_screens_reading_and_escaped():
    from dashboard.lv_view import part_c_html
    text = (REAL.split("ČASŤ C")[0] + "ČASŤ C: ŤARCHY 1 Záložné právo v prospech Tatra banka, a.s. "
            "2 Z 5/2020 - Právo stavby v prospech <b>X</b> 3 Exekučný príkaz EX 1/2026 "
            "Poznámka: Bez zápisu.")
    html = part_c_html(text)
    assert html.startswith('<div class="lvc">ČASŤ C')
    assert '<span class="lvb">Záložné právo' in html
    assert '<span class="lvu">Právo stavby' in html
    assert '<span class="lvh">Exekučný' in html
    assert "<b>X</b>" not in html and "&lt;b&gt;X&lt;/b&gt;" in html
    assert "Novák" not in html                     # part C only
    assert part_c_html("no headings here") == ""


def test_the_deed_on_file_comes_from_the_cache_whatever_its_age(full_db):
    import database
    from kataster_scraper import _cache_put, _new_result
    from dashboard.lv_view import deed_text
    r = _new_result({"cadastral_area": "Petržalka", "lv_no": "4521", "register": "LV"})
    r.update(status="OK", lv_text=REAL, fetched_at=_days_ago(90))
    _cache_put("lv|petrzalka|4521", r)
    got = deed_text({"lv_number": "4521", "cadastral_area": "Petržalka"})
    assert got and got[0] == REAL
    assert deed_text({"lv_number": "", "cadastral_area": "Petržalka"}) is None
    assert deed_text({"_market": "cz", "id": "c"}, {"c": "výpis"}) == ("výpis", "")
    assert database  # the full_db fixture's database


# ── Finding 4: the s.r.o.'s tax ──────────────────────────────────────────────
def test_the_company_depreciates_the_flat_up_to_its_rent():
    from engine.financial import sro_depreciation
    assert sro_depreciation(150_000, 9_000) == 3_750
    assert sro_depreciation(150_000, 2_000) == 2_000          # capped at the rent
    import markets
    assert sro_depreciation(150_000, 9_000, markets.tax_rules(market="cz")) == 0


def test_depreciation_lowers_the_companys_tax_until_the_minimum():
    from engine import financial
    with_dep = financial.analyse(60_000, 50, "Nitra", ltv=0.0)
    financial.SRO_DEPRECIATION, keep = False, financial.SRO_DEPRECIATION
    try:
        without = financial.analyse(60_000, 50, "Nitra", ltv=0.0)
    finally:
        financial.SRO_DEPRECIATION = keep
    assert with_dep.income_tax_sro < without.income_tax_sro
    assert with_dep.income_tax_sro * 12 >= 340 - 0.01        # never below the minimum


# ── Finding 5: the structure shown ───────────────────────────────────────────
def test_the_structure_shown_is_the_recommended_one_by_default():
    from engine.financial import shown_surplus, shows_sro
    personal = {"optimal_structure": "PERSONAL", "surplus_personal": -50, "surplus_sro": 20}
    company = {"optimal_structure": "SRO", "surplus_personal": -50, "surplus_sro": 20}
    assert shown_surplus(personal) == -50 and shown_surplus(company) == 20
    assert shown_surplus(personal, "sro") == 20 and shown_surplus(company, "personal") == -50
    assert not shows_sro({}) and shows_sro({}, "sro")


def test_the_cash_flow_flag_follows_the_recommended_structure():
    from engine.financial import analyse
    r = analyse(150_000, 55, "Petržalka")
    assert r.optimal_structure == "PERSONAL"
    assert r.cashflow_negative == (r.surplus_personal < 0)
    assert "under the recommended structure" in r.recommendation


def test_the_stress_test_is_kept_for_both_structures(full_db):
    import database
    from modules.cashflow_runner import run_scoring
    database.upsert_listing(make_listing("s1", price_eur=120_000.0, size_m2=55.0))
    run_scoring()
    row = next(r for r in database.get_all_active() if r["id"] == "s1")
    assert row["stress_surplus_personal"] is not None and row["stress_surplus_sro"] is not None
    assert row["stress_surplus_personal"] != row["stress_surplus_sro"]


# ── Your situation (S5, finding 23 of the audit) ─────────────────────────────
@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    import config
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", str(path))
    from engine import financial
    import markets
    for mod in (config, financial):
        for k in ("OTHER_ANNUAL_INCOME", "PROPERTIES_OWNED", "MORTGAGE_RATE_PA",
                  "LOAN_TERM_YEARS", "LTV_RATIO"):
            monkeypatch.setattr(mod, k, getattr(mod, k))
    monkeypatch.setattr(markets, "SK", markets.SK)
    monkeypatch.setattr(markets, "CZ", markets.CZ)
    monkeypatch.setitem(markets.MARKETS, "sk", markets.SK)
    monkeypatch.setitem(markets.MARKETS, "cz", markets.CZ)
    return path


def test_saved_settings_reach_the_engine_and_both_markets(settings_file):
    import config
    import markets
    from engine import financial
    from modules import settings
    base = financial.analyse(150_000, 55, "Petržalka")
    saved = settings.save({"MORTGAGE_RATE_PA": 0.045, "LOAN_TERM_YEARS": 30,
                           "OTHER_ANNUAL_INCOME": 50_000, "CZ_MORTGAGE_RATE_PA": 0.049,
                           "UNKNOWN": 1, "LTV_RATIO": "abc"})
    assert saved == {"MORTGAGE_RATE_PA": 0.045, "LOAN_TERM_YEARS": 30,
                     "OTHER_ANNUAL_INCOME": 50_000.0, "CZ_MORTGAGE_RATE_PA": 0.049}
    assert json.loads(settings_file.read_text())["LOAN_TERM_YEARS"] == 30
    assert config.MORTGAGE_RATE_PA == 0.045 and financial.LOAN_TERM_YEARS == 30
    assert markets.get("cz").mortgage_rate_pa == 0.049
    after = financial.analyse(150_000, 55, "Petržalka")
    assert after.mortgage_rate == 0.045 and after.loan_term_years == 30
    assert after.income_tax_personal > base.income_tax_personal      # taxed at 25 %


def test_values_are_kept_inside_their_ranges(settings_file):
    from modules import settings
    assert settings.clean({"LOAN_TERM_YEARS": 99, "LTV_RATIO": 1.5, "PROPERTIES_OWNED": -3}) == {
        "LOAN_TERM_YEARS": 40, "LTV_RATIO": 0.9, "PROPERTIES_OWNED": 0}


def test_another_process_picks_a_change_up(settings_file):
    import config
    from modules import settings
    settings.sync()
    settings_file.write_text(json.dumps({"PROPERTIES_OWNED": 3}))
    os.utime(settings_file, (1, 1))
    assert settings.sync() == ["PROPERTIES_OWNED"]
    assert config.PROPERTIES_OWNED == 3
    assert settings.sync() == []                  # unchanged since


def test_a_saved_value_outranks_the_env(settings_file, monkeypatch):
    import config
    monkeypatch.setenv("LOAN_TERM_YEARS", "20")
    settings_file.write_text(json.dumps({"LOAN_TERM_YEARS": 30}))
    monkeypatch.setattr(config, "_SAVED", config.saved_settings())
    assert config._env_int("LOAN_TERM_YEARS", 25) == 30
    monkeypatch.setattr(config, "_SAVED", {})
    assert config._env_int("LOAN_TERM_YEARS", 25) == 20
