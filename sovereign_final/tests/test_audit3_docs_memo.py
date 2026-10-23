"""Audit 3 — documents and memo (ONE-CLICK CLOSE, the PDF memo, .env numbers).

#33 the internal note printed the asking-price score next to the agreed price
#34 the card's MEMO PDF was built once per session and never rebuilt
#35 a blank numeric key in .env meant 0, not the documented default
#36 the draft, EARLIER DRAFTS and the memo used three different clocks

Synthetic rows only.
"""

import ast
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytz

import engine.financial as fin
from modules import contract_draft as cd
from modules.contract_draft import (
    build_contract_draft, build_internal_analysis, doc_stamp, figures_at_price,
    local_now, note_figures, sk_eur, sk_number, to_local,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB = "\u00a0"
BRATISLAVA = pytz.timezone("Europe/Bratislava")


def _sk_row(price=120_000, **over):
    r = fin.analyse(price, 55, "Žilina", rooms=2)
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    row.update(id="sktest01", title="2-izbový byt, Testovacia", district="Žilina",
               price_eur=float(price), size_m2=55.0, rooms=2, lv_status="PASS")
    row.update(over)
    return row


def _cz_row(price=4_500_000, **over):
    r = fin.analyse(price, 55, "Praha 2", rent_override=22_000, market="cz")
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    row.update(id="cztest01", title="Prodej bytu 2+kk 55 m²", district="Praha 2",
               price_eur=float(price), size_m2=55.0, market="cz", currency="CZK",
               estimated_rent_eur=22_000, lv_status="UNVERIFIED")
    row.update(over)
    return row


def _sk_yield(v):
    return f"{'−' if v < 0 else ''}{sk_number(abs(v) * 100, 2)}{NB}%"


# ── #33 the note's figures belong to the price it prints ─────────────────────
def test_note_figures_are_reworked_at_the_agreed_price():
    row = _sk_row()
    text = build_internal_analysis(row, agreed_price=96_000)
    at = fin.analyse(96_000, 55, "Žilina", rooms=2, rent_override=row["estimated_rent_eur"])
    assert f"Cena v návrhu:       {sk_eur(96_000)}" in text
    assert f"s.r.o. surplus/mes.: {sk_eur(at.surplus_sro, 0, signed=True)}" in text
    assert f"Ročná úspora s.r.o.: {sk_eur(at.annual_sro_saving, 0)}" in text
    assert f"Net Yield:           {_sk_yield(at.net_rental_yield)}" in text
    assert (f"Ponuková cena:       {sk_eur(120_000)} — čísla nižšie sú prepočítané "
            "na cenu v návrhu") in text
    # The asking-price figures are gone from the note.
    assert sk_eur(row["surplus_sro"], 0, signed=True) not in text


def test_note_at_the_asking_price_reads_as_before():
    row = _sk_row()
    text = build_internal_analysis(row, agreed_price=120_000,
                                   generated_at=datetime(2026, 10, 8, 9, 30))
    assert text.splitlines()[3:] == [
        "",
        f"Cena v návrhu:       {sk_eur(120_000)}",
        f"s.r.o. surplus/mes.: {sk_eur(row['surplus_sro'], 0, signed=True)}",
        f"Ročná úspora s.r.o.: {sk_eur(row['annual_sro_saving'], 0)}",
        f"Net Yield:           {_sk_yield(row['net_rental_yield'])}",
        "LV overenie:         PASS — OVERIŤ 48H PRED PODPISOM",
    ]
    # The app's default is int(price): a fraction of a euro is the same price.
    assert "Ponuková cena" not in build_internal_analysis(
        _sk_row(price=99_999.6), agreed_price=99_999)


def test_reworking_at_the_asking_price_gives_the_stored_score():
    for row in (_sk_row(), _cz_row()):
        at = figures_at_price(row, row["price_eur"])
        for k in ("surplus_sro", "annual_sro_saving", "net_rental_yield"):
            assert at[k] == pytest.approx(row[k], abs=0.1), k


def test_note_keeps_the_scores_financing_and_tax_year():
    # A score made with other financing (a 3rd+ property's LTV, a bank's
    # rate, its own s.r.o. terms) is reworked on those, not on the defaults.
    kw = dict(ltv=0.70, rate=0.045, term_years=30, sro_ltv=0.6, sro_rate_premium=0.015,
              sro_running_cost=1_800.0)
    r = fin.analyse(120_000, 55, "Žilina", rooms=2, **kw)
    row = {**fin.result_to_db_dict(r), **fin.deal_extras(r), "price_eur": 120_000.0,
           "size_m2": 55.0, "district": "Žilina", "rooms": 2}
    at = figures_at_price(row, 100_000)
    want = fin.analyse(100_000, 55, "Žilina", rooms=2, rent_override=r.estimated_rent, **kw)
    assert at["surplus_sro"] == pytest.approx(want.surplus_sro, abs=0.05)
    assert at["annual_sro_saving"] == pytest.approx(want.annual_sro_saving, abs=0.5)
    assert at["net_rental_yield"] == pytest.approx(want.net_rental_yield, abs=1e-4)


def test_slovak_rework_passes_no_market_kwarg(monkeypatch):
    sk, cz = _sk_row(), _cz_row()
    seen = []
    real = fin.analyse
    monkeypatch.setattr(fin, "analyse", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    figures_at_price(sk, 96_000)
    figures_at_price(cz, 4_000_000)
    assert len(seen) == 2
    assert "market" not in seen[0]
    assert seen[1]["market"] == "cz"


def test_note_says_the_figures_are_the_asking_prices_when_it_cannot_rework(monkeypatch):
    # No rent to rework on: the stored figures stay, labelled.
    row = _sk_row(estimated_rent_eur=None)
    text = build_internal_analysis(row, agreed_price=96_000)
    assert f"Ponuková cena:       {sk_eur(120_000)} — čísla nižšie sú pri ponukovej cene" in text
    assert f"s.r.o. surplus/mes.: {sk_eur(row['surplus_sro'], 0, signed=True)}" in text
    # The engine cannot price it (a Czech place with no market figure, say).
    scored = _sk_row()
    monkeypatch.setattr(fin, "analyse", lambda *a, **k: (_ for _ in ()).throw(LookupError("x")))
    assert note_figures(scored, 96_000) == (scored, "asking")


def test_an_unscored_listing_gets_no_asking_price_line():
    row = {"id": "u1", "title": "Byt", "district": "Žilina", "price_eur": 90_000.0,
           "size_m2": 50.0, "surplus_sro": None, "annual_sro_saving": None,
           "net_rental_yield": None}
    text = build_internal_analysis(row, agreed_price=80_000)
    assert "Ponuková cena" not in text and "None" not in text


def test_czech_note_figures_are_reworked_at_the_agreed_price():
    from modules.contract_draft_cz import build_internal_analysis_cz, czk
    row = _cz_row()
    text = build_internal_analysis_cz(row, agreed_price=4_000_000)
    at = fin.analyse(4_000_000, 55, "Praha 2", rent_override=22_000, market="cz")
    assert f"Cena v návrhu:       {czk(4_000_000)}" in text
    assert f"Přebytek s.r.o./měs.: {czk(at.surplus_sro, signed=True)}" in text
    assert f"Roční rozdíl s.r.o.: {czk(at.annual_sro_saving, signed=True)}" in text
    assert (f"Nabídková cena:      {czk(4_500_000)} — čísla níže jsou přepočtena "
            "na cenu v návrhu") in text
    same = build_internal_analysis_cz(row, agreed_price=4_500_000)
    assert "Nabídková cena" not in same
    assert f"Přebytek s.r.o./měs.: {czk(row['surplus_sro'], signed=True)}" in same
    unpriced = build_internal_analysis_cz(_cz_row(estimated_rent_eur=None), agreed_price=4_000_000)
    assert "čísla níže jsou při nabídkové ceně" in unpriced


# ── #34 a kept memo is dropped once what it prints changes ───────────────────
def test_memo_fingerprint_follows_what_the_memo_prints():
    from modules.memo import memo_fingerprint
    base = _sk_row(_stage={"stage": "VIEWING", "note": "", "updated_at": "2026-10-01"},
                   _vibe=(7, "ok", 1), _ph=None, lv_detail="clean", _copies=[])
    base["_copies"] = [base, {"id": "other", "source": "nehnutelnosti", "price_eur": 121_000.0,
                              "url": "https://example.test/x", "scraped_at": "2026-09-01"}]
    sig = memo_fingerprint(base)
    assert memo_fingerprint(dict(base)) == sig           # the same row on the next rerun
    changes = [
        {"price_eur": 110_000.0},                          # price cut
        {"surplus_sro": base["surplus_sro"] + 10},          # rescore
        {"lv_status": "REJECTED", "lv_detail": "záložné právo"},
        {"_vibe": (9, "new note", 2)},                     # a note added
        {"_stage": {"stage": "OFFER", "note": "", "updated_at": "2026-10-02"}},
        {"_ph": {"history": [("2026-09-01", 125_000.0), ("2026-10-01", 120_000.0)],
                 "change_pct": -0.04}},
        {"_copies": [base, {**base["_copies"][1], "price_eur": 118_000.0}]},
    ]
    for ch in changes:
        assert memo_fingerprint({**base, **ch}) != sig, ch


@pytest.fixture
def app_db(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    import database
    from tests.conftest import make_listing

    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    now = datetime.now(timezone.utc)
    seen = dict(last_seen_at=now.isoformat(), scraped_at=(now - timedelta(days=9)).isoformat())

    def add(price):
        database.upsert_listing(make_listing("sk1", district="Žilina", price_eur=float(price),
                                             size_m2=55.0, **seen))
        from modules.cashflow_runner import run_scoring
        run_scoring()

    add(100_000)
    database.set_lv_status("sk1", "PASS", "", "clean")
    return database, add


def _run_app(open_cards=()):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_a_kept_memo_is_rebuilt_once_the_listing_changes(app_db):
    db, add = app_db
    at = _run_app(open_cards=("sk1",))
    next(b for b in at.button if b.key == "memo_sk1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    first = at.session_state["memo_ready"]["memo_sk1"]
    at.run()                                       # nothing changed: the download stays
    assert at.session_state["memo_ready"].get("memo_sk1") == first
    assert not any(b.key == "memo_sk1" for b in at.button)

    add(80_000)                                    # a price cut and a rescore …
    db.add_annotation("sk1", "synthetic note after the memo", 9)   # … and a note
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(b.key == "memo_sk1" for b in at.button)          # 📄 MEMO again
    assert "memo_sk1" not in at.session_state["memo_ready"]
    next(b for b in at.button if b.key == "memo_sk1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    again = at.session_state["memo_ready"]["memo_sk1"]
    assert again != first
    sig, pdf, made = again                         # kept with its fingerprint and time
    assert pdf[:4] == b"%PDF" and made.tzinfo.zone == "Europe/Bratislava"


# ── #35 a blank numeric key in .env means the default ───────────────────────
def test_env_helpers_treat_blank_as_unset(monkeypatch):
    import config
    monkeypatch.delenv("AUDIT3_TEST_NUM", raising=False)
    assert config._env_float("AUDIT3_TEST_NUM", 1200) == 1200.0
    assert config._env_int("AUDIT3_TEST_NUM", 14) == 14
    for blank in ("", "   "):
        monkeypatch.setenv("AUDIT3_TEST_NUM", blank)
        assert config._env_float("AUDIT3_TEST_NUM", 0.01) == 0.01
        assert config._env_int("AUDIT3_TEST_NUM", 14) == 14
    monkeypatch.setenv("AUDIT3_TEST_NUM", "0")            # an explicit 0 stays 0
    assert config._env_float("AUDIT3_TEST_NUM", 1200) == 0.0
    assert config._env_int("AUDIT3_TEST_NUM", 14) == 0
    monkeypatch.setenv("AUDIT3_TEST_NUM", " 1500 ")
    assert config._env_float("AUDIT3_TEST_NUM", 1200) == 1500.0
    monkeypatch.setenv("AUDIT3_TEST_NUM", "abc")          # a typo still stops the app
    with pytest.raises(ValueError):
        config._env_float("AUDIT3_TEST_NUM", 1200)


_NUMERIC_KEYS = ("PROPERTIES_OWNED", "TAX_YEAR", "SRO_ANNUAL_RUNNING_COST",
                 "SRO_RATE_PREMIUM_PP", "SRO_LTV_RATIO", "CASHFLOW_MIN_SURPLUS",
                 "SALE_PRICE_MIN_EUR", "CZK_PER_EUR", "BACKUP_KEEP")


def _config_in_subprocess(env_over: dict) -> list:
    code = ("import sys; sys.path.insert(0, '.'); import config; "
            "from engine.financial import analyse; "
            "r = analyse(98000, 58, 'Žilina'); "
            f"print(repr([getattr(config, k) for k in {_NUMERIC_KEYS!r}] "
            "+ [round(r.surplus_sro, 2), r.optimal_structure]))")
    env = {**os.environ, **env_over}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return ast.literal_eval(out.stdout.strip().splitlines()[-1])


def test_blank_numeric_settings_get_their_defaults():
    from datetime import date
    # Blank keys are present, so a developer's own .env cannot fill them.
    blank = _config_in_subprocess({k: "" for k in _NUMERIC_KEYS})
    assert blank[:9] == [0, date.today().year, 1200.0, 0.01, 0.70, 0.0, 15000, 24.355, 14]
    explicit = _config_in_subprocess({**{k: "" for k in _NUMERIC_KEYS},
                                      "SRO_ANNUAL_RUNNING_COST": "1200",
                                      "SRO_RATE_PREMIUM_PP": "0.01"})
    assert blank[9:] == explicit[9:]                # the s.r.o. is not made cheaper
    zero = _config_in_subprocess({**{k: "" for k in _NUMERIC_KEYS},
                                  "SRO_ANNUAL_RUNNING_COST": "0", "SRO_RATE_PREMIUM_PP": "0"})
    assert zero[2:4] == [0.0, 0.0]                  # an explicit 0 still means 0


# ── #36 one clock (Bratislava) for every document ────────────────────────────
@pytest.fixture
def new_york_host(monkeypatch):
    """The host's own clock set to a zone that is neither UTC nor Bratislava."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is Unix-only")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_stored_utc_is_shown_in_bratislava_time(new_york_host):
    assert to_local("2026-10-21T17:16:00.123456+00:00").strftime("%Y-%m-%d %H:%M") \
        == "2026-10-21 19:16"                                  # CEST, +2
    assert to_local("2026-12-01T23:30:00+00:00").strftime("%Y-%m-%d %H:%M") \
        == "2026-12-02 00:30"                                  # CET, +1, next day
    assert to_local("2026-10-21T17:16:00").strftime("%H:%M") == "19:16"   # naive = UTC
    assert to_local(None) is None and to_local("") is None and to_local("garbage") is None


def test_documents_print_bratislava_time(new_york_host, monkeypatch):
    utc = datetime(2026, 10, 21, 17, 16, tzinfo=timezone.utc)
    assert doc_stamp(utc) == "2026-10-21 19:16"
    assert doc_stamp(datetime(2026, 10, 8, 9, 30)) == "2026-10-08 09:30"   # naive: as given
    n = local_now()
    assert n.tzinfo.zone == "Europe/Bratislava"
    assert abs(n - datetime.now(timezone.utc)) < timedelta(seconds=5)
    # No time given: every document reads the same Bratislava clock.
    fixed = BRATISLAVA.localize(datetime(2026, 10, 21, 19, 16))
    monkeypatch.setattr(cd, "local_now", lambda: fixed)
    from modules.contract_draft_cz import build_contract_draft_cz, build_internal_analysis_cz
    row = _sk_row()
    assert "Vygenerované:  2026-10-21 19:16" in build_contract_draft(
        row, buyer_name="Kupujúci Test", agreed_price=120_000)
    assert "Vygenerované:        2026-10-21 19:16" in build_internal_analysis(row)
    cz = _cz_row()
    assert "Vygenerováno:  2026-10-21 19:16" in build_contract_draft_cz(
        cz, buyer_name="Kupující Test", agreed_price=4_500_000)
    assert "Vygenerováno:        2026-10-21 19:16" in build_internal_analysis_cz(cz)


def test_the_memo_prints_bratislava_time(monkeypatch):
    from modules import memo
    seen = []
    orig = memo._Memo.txt
    monkeypatch.setattr(memo._Memo, "txt", lambda self, s: (seen.append(str(s)), orig(self, s))[1])
    memo.build_memo_pdf(_sk_row(), generated_at=datetime(2026, 10, 21, 17, 16, tzinfo=timezone.utc))
    assert any("Memo generated 2026-10-21 19:16" in s for s in seen)
    seen.clear()
    monkeypatch.setattr(cd, "local_now", lambda: BRATISLAVA.localize(datetime(2026, 12, 2, 0, 30)))
    memo.build_memo_pdf(_sk_row())
    assert any("Memo generated 2026-12-02 00:30" in s for s in seen)


def _stamp_of(text, label):
    m = re.search(label + r":\s+(\d{4}-\d\d-\d\d \d\d:\d\d)", text)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")


def test_close_tab_draft_and_earlier_drafts_show_one_time(app_db, new_york_host):
    at = _run_app()
    sb = at.selectbox(key="close_sel")
    sb.select(next(o for o in sb.options if "[sk1]" in o)).run()
    next(t for t in at.text_input if t.label == "Full Name / s.r.o. Name") \
        .set_value("Kupujúci Test").run()
    next(n for n in at.number_input if n.label == "Agreed Price €").set_value(90_000).run()
    next(b for b in at.button if b.label == "GENERATE CONTRACT DRAFT").click().run()
    assert not at.exception, [e.value for e in at.exception]
    draft = next(t.value for t in at.text_area if t.label == "CONTRACT DRAFT")
    analysis = next(c.value for c in at.code if "FINANČNÁ ANALÝZA" in c.value)
    stored = app_db[0].get_contract_drafts("sk1")[0]["generated_at"]
    want = datetime.fromisoformat(stored).astimezone(BRATISLAVA).replace(tzinfo=None)
    drafted = _stamp_of(draft, "Vygenerované")
    assert abs(drafted - want.replace(second=0, microsecond=0)) <= timedelta(minutes=1)
    assert _stamp_of(analysis, "Vygenerované") == drafted
    caption = next(c.value for c in at.caption if "Kupujúci Test" in c.value)
    assert caption.startswith(want.strftime("%Y-%m-%d %H:%M") + " · ")
    # #33 through the tab: the note is at the typed price, the asking price named.
    assert f"Cena v návrhu:       {sk_eur(90_000)}" in analysis
    assert f"Ponuková cena:       {sk_eur(100_000)}" in analysis
