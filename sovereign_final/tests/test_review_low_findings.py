"""The low-severity findings of the 6 November 2026 audit
(docs/AUDIT_REVIEW_2026-11-06.pdf, findings 14–27)."""

import os
import subprocess
import sys
import time

import pytest


# ── 14 · A scraper stopped at its time limit takes what it started with it ────
def _alive(pid: int) -> bool:
    """The process runs (a zombie waiting to be reaped does not count)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        # Gone: no /proc entry (FileNotFoundError), or it went between the
        # open and the read (ProcessLookupError, as CI hit).
        return False


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="reads /proc to see the process")
def test_a_timeout_stops_the_whole_process_tree(tmp_path):
    from dashboard.actions import run_killing_tree
    pid_file = tmp_path / "grandchild.pid"
    # The child starts a grandchild that never looks at a pipe (as a hung
    # browser would not), then waits for ever.
    child = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"open({str(pid_file)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(120)\n")
    with pytest.raises(subprocess.TimeoutExpired):
        run_killing_tree([sys.executable, "-c", child], timeout=3)
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        if not _alive(grandchild):
            break
        time.sleep(0.1)
    assert not _alive(grandchild)


def test_a_finished_run_returns_its_output():
    from dashboard.actions import run_killing_tree
    out, err = run_killing_tree(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"], 30)
    assert out.strip() == "out" and err.strip() == "err"


# ── 15 · An interest-free loan, and a loan with no term ───────────────────────
def test_an_interest_free_loan_repays_evenly():
    from engine.financial import amortization_schedule, calc_mortgage, first_year_amortization
    assert calc_mortgage(120_000, 0.0, 10) == pytest.approx(1_000)
    assert first_year_amortization(120_000, 0.0, 10) == (pytest.approx(0), pytest.approx(1_000))
    years = amortization_schedule(120_000, 0.0, 10)
    assert years[-1][2] == pytest.approx(0, abs=1e-6)
    assert sum(y[0] for y in years) == pytest.approx(0)


def test_an_interest_free_deal_scores(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "t.db"))
    from engine.financial import analyse
    r = analyse(150_000, 55, "Žilina", rate=0.0)
    assert r.mortgage_monthly == pytest.approx(150_000 * r.ltv / (25 * 12), rel=1e-3)


def test_a_loan_with_no_term_is_refused_plainly():
    from engine.financial import calc_mortgage
    with pytest.raises(ValueError, match="at least 1 year"):
        calc_mortgage(100_000, 0.04, 0)
    assert calc_mortgage(0, 0.04, 0) == 0.0      # no loan: no term needed


# ── 16, 17 · A value that can't be worked out is "—" or left out, not 0 or "None" ─
pytest.importorskip("streamlit")


def _app(tmp_path, monkeypatch):
    import database
    from tests.test_app_smoke import run_app
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_an_irr_that_cant_be_worked_out_shows_a_dash(tmp_path, monkeypatch):
    import dataclasses
    from engine import financial
    real = financial.project_irr

    def no_irr(*a, **k):
        return dataclasses.replace(real(*a, **k), irr=None, equity_multiple=None)
    monkeypatch.setattr(financial, "project_irr", no_irr)
    at = _app(tmp_path, monkeypatch)
    cmp = next(d.value for d in at.dataframe if "Personal (FO)" in d.value.columns)
    irr_row = cmp[cmp.iloc[:, 0].str.startswith("IRR over")].iloc[0]
    assert (irr_row["Personal (FO)"], irr_row["s.r.o."]) == ("—", "—")
    rent = cmp[cmp.iloc[:, 0] == "Rent"].iloc[0]
    assert rent["Personal (FO)"] not in ("—", "0.00")   # the other rows still show numbers


def test_triage_drops_benchmark_columns_no_row_has(tmp_path, monkeypatch):
    # The demo rows carry no max offers: the columns used to be full of "None".
    at = _app(tmp_path, monkeypatch)
    triage = next(d.value for d in at.dataframe if "Grade" in d.value.columns)
    assert not {"Max 🟡", "Max 🟢", "To 🟡"} & set(triage.columns)
    assert "Below%" in triage.columns              # the demo rows have a discount


# ── 18 · No Deploy button ─────────────────────────────────────────────────────
def test_the_toolbar_has_no_deploy_button():
    import tomllib
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".streamlit", "config.toml")
    with open(path, "rb") as f:
        assert tomllib.load(f)["client"]["toolbarMode"] == "minimal"


# ── 19 · The scheduler's log rotates ──────────────────────────────────────────
def test_the_scheduler_log_rotates(tmp_path, monkeypatch):
    import logging
    from logging.handlers import RotatingFileHandler
    import scheduler
    got = {}
    monkeypatch.setattr(scheduler, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(scheduler, "LOG_MAX_BYTES", 2_000)
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: got.update(kw))
    scheduler._setup_logging()
    fh = next(h for h in got["handlers"] if isinstance(h, RotatingFileHandler))
    try:
        assert fh.backupCount == scheduler.LOG_BACKUPS >= 1
        fh.setFormatter(logging.Formatter("%(message)s"))
        for _ in range(100):
            fh.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "x" * 60, None, None))
        assert (tmp_path / "scheduler.log.1").exists()
        assert (tmp_path / "scheduler.log").stat().st_size <= 2_000
    finally:
        fh.close()


# ── 20 · The image runs the app as an unprivileged user, without a compiler ───
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts) -> bytes:
    with open(os.path.join(_ROOT, *parts), "rb") as f:
        return f.read()


def test_the_image_has_no_compiler_and_drops_root():
    df = _read("docker", "Dockerfile").decode()
    assert "gcc" not in df
    assert "useradd" in df and "sovereign" in df
    assert 'ENTRYPOINT ["/app/docker/entrypoint.sh"]' in df
    # Chromium outside /root, where the unprivileged user can run it.
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in df


def test_the_entrypoint_hands_over_the_folders_and_drops_root():
    ep = _read("docker", "entrypoint.sh")
    assert b"\r\n" not in ep                      # CRLF breaks /bin/sh in the image
    text = ep.decode()
    for folder in ("/app/data", "/app/logs", "/app/backups"):
        assert folder in text                     # a root-owned volume from before
    assert "setpriv --reuid=sovereign" in text
    assert "--reset-env" not in text              # would drop the .env settings
    assert "HOME=/home/sovereign" in text         # Streamlit reads $HOME/.streamlit


def test_shell_scripts_stay_lf_in_a_windows_checkout():
    attrs = _read("..", ".gitattributes").decode()
    assert "*.sh" in attrs and "eol=lf" in attrs


# ── 22 · "banka" in a limited company's name clears nothing ───────────────────
@pytest.mark.parametrize("creditor, bank", [
    ("Tatra banka, a.s.", True),
    ("Slovenská sporiteľňa, a.s.", True),
    ("Všeobecná úverová banka, a.s.", True),
    ("BANKA PLUS s.r.o.", False),
    ("Banka Invest spol. s r. o.", False),
    ("Prima Banka Servis, s. r. o.", False),
])
def test_a_slovak_bank_is_a_joint_stock_company(creditor, bank):
    from modules.lv_screen import is_bank
    assert is_bank(creditor) is bank


@pytest.mark.parametrize("creditor, bank", [
    ("Komerční banka, a.s.", True),
    ("Česká spořitelna, a.s.", True),
    ("Banka Domů s.r.o.", False),
])
def test_a_czech_bank_is_a_joint_stock_company(creditor, bank):
    from modules import lv_screen_cz
    from modules.lv_screen import is_bank
    assert is_bank(creditor, lv_screen_cz._BANK_RE) is bank


def test_a_lien_for_a_limited_company_named_banka_blocks():
    from modules.lv_screen import screen_lv
    hits = screen_lv("LIST VLASTNÍCTVA č. 1\nČASŤ C: ŤARCHY\n"
                     "1 Záložné právo v prospech BANKA PLUS s.r.o. podľa V 1234/2020\n")
    assert [h["blocking"] for h in hits] == [True]


# ── 23 · The schema is checked once per database, not for every saved listing ─
def test_upsert_checks_the_schema_once_per_database(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import database
    from database import listings
    from tests.conftest import make_listing
    calls = []
    real = listings._ensure_market_columns
    monkeypatch.setattr(listings, "_ensure_market_columns",
                        lambda conn: calls.append(1) or real(conn))
    now = datetime.now(timezone.utc).isoformat()
    for db_name in ("a.db", "b.db"):
        monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / db_name))
        database.init_db()
        for i in range(5):
            database.upsert_listing(make_listing(f"x{i}", last_seen_at=now, scraped_at=now))
        assert len(database.get_all_active()) == 5
    assert len(calls) == 2                          # once for each database


# ── 24 · Price history for many listings is read in chunks ────────────────────
def test_price_history_for_many_listings_reads_in_chunks(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import database
    from database import prices
    from tests.conftest import make_listing
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(prices, "_IN_CHUNK", 3)
    database.init_db()
    t0 = datetime.now(timezone.utc)
    for i in range(7):
        for k, price in enumerate((100_000.0, 95_000.0)):
            seen = (t0 + timedelta(minutes=k)).isoformat()
            database.upsert_listing(make_listing(f"p{i}", price_eur=price,
                                                 last_seen_at=seen, scraped_at=t0.isoformat()))
    ids = [f"p{i}" for i in range(7)] + ["p0", "missing"]
    hist = database.get_price_history(ids)
    assert set(hist) == {f"p{i}" for i in range(7)}
    assert all(h["change_pct"] == pytest.approx(-0.05) for h in hist.values())
    assert hist == {k: v for k, v in database.get_price_history().items() if k in hist}


# ── 25 · A rent override of 0 is a figure, not "no override" ──────────────────
def test_a_zero_rent_override_is_modelled(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "t.db"))
    from engine.financial import analyse
    empty = analyse(120_000, 55, "Žilina", rent_override=0)
    assert empty.estimated_rent == 0
    assert empty.surplus_personal == pytest.approx(-empty.total_costs_personal)
    assert analyse(120_000, 55, "Žilina", rent_override=None).estimated_rent > 0


# ── 26 · The password gate locks after repeated wrong passwords ───────────────
def test_the_gate_locks_after_too_many_wrong_passwords(tmp_path, monkeypatch):
    import config
    import database
    from dashboard import login
    from tests.test_app_smoke import run_app
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    monkeypatch.setattr(config, "DASHBOARD_PASSWORD", "s3cret")
    monkeypatch.setattr(login, "WRONG_PASSWORD_DELAY_S", 0)
    login.reset_attempts()
    try:
        at = run_app()

        def enter(pw):
            at.text_input(key="login_pw").input(pw)
            at.button[0].click().run()
            assert not at.exception, [e.value for e in at.exception]
            return " ".join(e.value for e in at.error)

        for _ in range(login.MAX_TRIES - 1):
            assert enter("guess") == "Wrong password."
        assert "locked for 15 min" in enter("guess")
        # Locked: even the right password waits, in a new session too.
        assert "Try again in" in enter("s3cret") and not at.tabs
        at = run_app()
        assert "Try again in" in enter("s3cret") and not at.tabs
        # Once the lock has run out, the right password opens the page.
        monkeypatch.setattr(login, "_now", lambda: 10**10)
        enter("s3cret")
        assert at.tabs
    finally:
        login.reset_attempts()


def test_a_right_password_forgets_earlier_mistakes(monkeypatch):
    from dashboard import login
    login.reset_attempts()
    try:
        for t in range(login.MAX_TRIES - 1):
            login._record_failure(1000.0 + t)
        with login._lock:
            login._fails.clear()               # what the right password does
        login._record_failure(1010.0)
        assert login._locked_for(1010.0) == 0
        # Mistakes older than the window don't count towards a lockout.
        for t in range(login.MAX_TRIES - 1):
            login._record_failure(2000.0 + t)
        login._record_failure(2000.0 + login.LOCKOUT_S + 10)
        assert login._locked_for(2000.0 + login.LOCKOUT_S + 10) == 0
    finally:
        login.reset_attempts()
