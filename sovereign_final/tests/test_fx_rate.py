"""modules/fx_rate: the ČNB EUR/CZK rate, saved, shared and dated (review L6)."""

import json
import os
from datetime import date

import pytest

import config
import markets
from modules import fx_rate

CNB = """05.11.2026 #213
země|měna|množství|kód|kurz
Austrálie|dolar|1|AUD|15,159
EMU|euro|1|EUR|24,290
Filipíny|peso|100|PHP|34,360
"""


@pytest.fixture(autouse=True)
def _rate(monkeypatch):
    """Each test starts from the config fallback and leaves config as it was."""
    monkeypatch.delenv("CZK_PER_EUR", raising=False)
    monkeypatch.setattr(config, "CZK_PER_EUR", 24.355)  # the old fallback, ≠ the file below
    monkeypatch.setattr(config, "FX_RATE_DATE", "2026-10-14")
    monkeypatch.setattr(config, "FX_RATE_SOURCE", "ČNB kurzy devizového trhu")
    monkeypatch.setattr(fx_rate, "_seen_mtime", None)
    monkeypatch.setattr(fx_rate, "_next_sync", 0.0)


def test_parse_cnb_reads_the_euro_row_and_date():
    rate, fixed = fx_rate.parse_cnb(CNB)
    assert rate == pytest.approx(24.29)
    assert fixed == date(2026, 11, 5)


def test_parse_cnb_divides_by_the_amount():
    rate, _ = fx_rate.parse_cnb(CNB, "PHP")
    assert rate == pytest.approx(0.3436)


@pytest.mark.parametrize("text", ["", "05.11.2026 #213\nzemě|měna\n",
                                  "garbage\nzemě|měna|množství|kód|kurz\nEMU|euro|1|EUR|24,290",
                                  "05.11.2026 #1\nzemě|měna|množství|kód|kurz\nEMU|euro|1|EUR|abc",
                                  "05.11.2026 #1\nzemě|měna|množství|kód|kurz\nEMU|euro|1|EUR|243,55"])
def test_parse_cnb_refuses_bad_files(text):
    with pytest.raises(fx_rate.FxError):
        fx_rate.parse_cnb(text)


def test_refresh_saves_and_uses_the_rate(monkeypatch):
    monkeypatch.setattr(fx_rate, "_fetch", lambda timeout=15: CNB)
    assert fx_rate.refresh() is True
    assert config.CZK_PER_EUR == pytest.approx(24.29)
    assert config.FX_RATE_DATE == "2026-11-05"
    with open(fx_rate.CACHE_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["czk_per_eur"] == pytest.approx(24.29) and saved["fetched_at"]
    assert markets.to_eur(24_290, "CZK") == pytest.approx(1000)
    assert "24.290" in markets.fx_note() and "2026-11-05" in markets.fx_note()


def test_refresh_failure_keeps_the_last_rate():
    # conftest's _fetch raises: no network.
    assert fx_rate.refresh() is False
    assert config.CZK_PER_EUR == 24.355
    assert not os.path.exists(fx_rate.CACHE_PATH)


def test_sync_loads_a_rate_another_process_saved():
    with open(fx_rate.CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"czk_per_eur": 25.1, "date": "2026-11-04", "source": "ČNB"}, f)
    fx_rate.sync()
    assert config.CZK_PER_EUR == 25.1 and config.FX_RATE_DATE == "2026-11-04"


def test_sync_ignores_a_broken_file():
    with open(fx_rate.CACHE_PATH, "w", encoding="utf-8") as f:
        f.write("{not json")
    fx_rate.sync()
    assert config.CZK_PER_EUR == 24.355


def test_refresh_if_due_skips_a_recent_fetch(monkeypatch):
    monkeypatch.setattr(fx_rate, "_fetch", lambda timeout=15: CNB)
    assert fx_rate.refresh_if_due() is True
    calls = []
    monkeypatch.setattr(fx_rate, "_fetch", lambda timeout=15: calls.append(1) or CNB)
    assert fx_rate.refresh_if_due() is False
    assert calls == []


def test_a_rate_pinned_in_env_is_never_replaced(monkeypatch):
    monkeypatch.setenv("CZK_PER_EUR", "24.355")
    monkeypatch.setattr(fx_rate, "_fetch", lambda timeout=15: CNB)
    assert fx_rate.refresh() is False
    with open(fx_rate.CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"czk_per_eur": 25.1, "date": "2026-11-04"}, f)
    fx_rate.sync(force=True)
    assert config.CZK_PER_EUR == 24.355


def test_stale_warning_after_a_week():
    config.FX_RATE_DATE = "2026-10-29"
    assert fx_rate.stale_warning(today=date(2026, 11, 5)) is None      # 7 days: fine
    w = fx_rate.stale_warning(today=date(2026, 11, 6))                   # 8 days
    assert w and "8 days ago" in w and "ČNB" in w


def test_stale_warning_names_the_env_pin(monkeypatch):
    monkeypatch.setenv("CZK_PER_EUR", "24.355")
    w = fx_rate.stale_warning(today=date(2026, 11, 5))
    assert w and ".env" in w


def test_stale_warning_on_an_unreadable_date():
    config.FX_RATE_DATE = "October"
    assert "FX_RATE_DATE" in fx_rate.stale_warning()


def test_scheduler_refreshes_the_rate_before_the_markets(monkeypatch):
    import scheduler
    order = []
    monkeypatch.setattr(fx_rate, "refresh", lambda *a, **k: order.append("fx") or True)
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **k: order.append(k.get("market", "sk")) or True)
    monkeypatch.setattr(scheduler, "_record_failure", lambda *a, **k: None)
    scheduler.run_all_markets(holder="test", which=["sk", "cz"])
    assert order == ["fx", "sk", "cz"]


def test_scheduler_runs_when_the_refresh_raises(monkeypatch):
    import scheduler
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(fx_rate, "refresh", boom)
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **k: True)
    assert scheduler.run_all_markets(holder="test", which=["sk"]) == {"sk": True}
