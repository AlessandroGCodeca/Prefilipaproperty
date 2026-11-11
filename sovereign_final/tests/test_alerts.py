"""modules/alerts.py — the Telegram message after each full run. Telegram is
faked: no test sends a real message."""

from datetime import datetime, timedelta, timezone

import pytest

import config
from tests.conftest import make_listing

TOKEN = "123456:TEST-TOKEN-never-real"


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    return database


@pytest.fixture
def tg(monkeypatch):
    """A fake Telegram: records each sendMessage; `fail` makes it refuse."""
    import requests

    class Fake:
        sent: list = []
        fail = False

        @staticmethod
        def post(url, data=None, timeout=None):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    if Fake.fail:
                        return {"ok": False, "description": "Bad Gateway"}
                    return {"ok": True, "result": {}}
            assert url.startswith("https://api.telegram.org/bot") and timeout
            if Fake.fail:
                R.status_code = 502
                return R
            Fake.sent.append(data["text"])
            return R
    Fake.sent = []
    monkeypatch.setattr(requests, "post", Fake.post)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(config, "ALERT_CLASSES", ["GREEN", "YELLOW"])
    monkeypatch.setattr(config, "ALERT_FAILURES", True)
    return Fake


def _now(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _add(db, lid, ratio=0.7, **over):
    """A Žilina flat at `ratio` × the regional median, scored."""
    from engine.regional_prices import regional_median_price
    from modules.cashflow_runner import run_scoring
    price = round(regional_median_price("Žilina") * 55 * ratio)
    db.upsert_listing(make_listing(lid, price_eur=float(price), size_m2=55.0,
                                   scraped_at=_now(5), last_seen_at=_now(), **over))
    db.set_lv_status(lid, "UNVERIFIED", "", "no flat LV yet")
    run_scoring()


@pytest.fixture
def every_deal_pays(monkeypatch):
    """Count every scored listing as cash-flow positive (the threshold the
    flag uses), so a test picks its deals by class alone."""
    from engine import financial
    monkeypatch.setattr(financial, "CASHFLOW_MIN_SURPLUS", -1e9)


def test_off_without_a_token_or_chat(db, monkeypatch):
    import requests
    from modules import alerts
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no request when off"))
    assert alerts.run().startswith("off")


def test_the_first_run_counts_the_deals_then_only_new_ones_are_sent(db, tg, every_deal_pays):
    from modules import alerts
    _add(db, "g1")
    assert alerts.run().startswith("alerts on: 1 existing")
    assert len(tg.sent) == 1 and "alerts are on" in tg.sent[0] and "g1" not in tg.sent[0]

    assert alerts.run() == "nothing new" and len(tg.sent) == 1     # no message

    _add(db, "g2", title="Nový 2-izbový byt")
    assert alerts.run().startswith("sent: 1 deal")
    msg = tg.sent[-1]
    assert "1 new deal" in msg and "Nový 2-izbový byt" in msg and "https://example.sk/g2" in msg
    assert "g1" not in msg                       # already known
    assert alerts.run() == "nothing new"         # each deal once


def test_only_green_and_yellow_deals_that_pay_are_alerted(db, tg, monkeypatch):
    from engine import financial
    from modules import alerts
    alerts.run()                                 # baseline on an empty database
    _add(db, "white", ratio=1.0)                 # at market: WHITE
    monkeypatch.setattr(financial, "CASHFLOW_MIN_SURPLUS", 1e9)   # nothing pays
    _add(db, "green_loses")
    assert alerts.run() == "nothing new"
    monkeypatch.setattr(financial, "CASHFLOW_MIN_SURPLUS", -1e9)  # everything pays
    assert alerts.run().startswith("sent: 1 deal")
    assert "green_loses" in tg.sent[-1] and "white" not in tg.sent[-1]


def test_a_rejected_flat_is_never_alerted(db, tg, every_deal_pays):
    from modules import alerts
    alerts.run()
    _add(db, "bad")
    db.set_lv_status("bad", "REJECTED", "záložné právo", "private lien")
    assert alerts.run() == "nothing new"


def test_an_alert_telegram_refused_goes_out_with_the_next_run(db, tg, every_deal_pays):
    from modules import alerts
    alerts.run()
    _add(db, "g1")
    tg.fail = True
    with pytest.raises(alerts.TelegramError) as e:
        alerts.run()
    assert TOKEN not in str(e.value)             # the token never reaches a log
    tg.fail = False
    assert alerts.run().startswith("sent: 1 deal") and "g1" in tg.sent[-1]


def test_a_price_cut_on_a_tracked_deal_is_alerted_once(db, tg):
    from modules import alerts
    alerts.run()
    db.upsert_listing(make_listing("t1", price_eur=150_000.0, scraped_at=_now(20),
                                   last_seen_at=_now(20)))
    db.set_deal_stage("t1", "VIEWING", "")
    db.upsert_listing(make_listing("t1", price_eur=141_000.0, scraped_at=_now(20),
                                   last_seen_at=_now(1)))
    assert alerts.run().startswith("sent: 0 deal(s), 1 cut")
    assert "−6.0%" in tg.sent[-1] or "-6.0%" in tg.sent[-1]
    assert "[VIEWING]" in tg.sent[-1]
    assert alerts.run() == "nothing new"
    # A deal you passed on is no longer news.
    db.set_deal_stage("t1", "PASSED", "")
    db.upsert_listing(make_listing("t1", price_eur=130_000.0, scraped_at=_now(20),
                                   last_seen_at=_now()))
    assert alerts.run() == "nothing new"


def test_a_failed_run_with_no_retry_left_is_alerted_once(db, tg, monkeypatch):
    from modules import alerts, pipeline_state
    alerts.run()
    status = {"state": "failed", "trigger": "06:00", "finished_at": _now(),
              "error": "all 3 scrapers failed", "next_retry_at": None}
    monkeypatch.setattr(pipeline_state, "read_status",
                        lambda m="sk": status if m == "sk" else None)
    assert alerts.run().endswith("1 issue(s)")
    assert "SK run failed: all 3 scrapers failed" in tg.sent[-1]
    assert alerts.run() == "nothing new"
    monkeypatch.setattr(config, "ALERT_FAILURES", False)
    status["finished_at"] = _now()               # a new failure, but they're off
    assert alerts.run() == "nothing new"


def test_a_failure_with_a_retry_coming_waits(db, tg, monkeypatch):
    from modules import alerts, pipeline_state
    alerts.run()
    monkeypatch.setattr(pipeline_state, "read_status", lambda m="sk": {
        "state": "failed", "trigger": "06:00", "finished_at": _now(),
        "next_retry_at": _now(-1 / 24)})
    assert alerts.run() == "nothing new"


def test_listing_text_is_escaped_and_long_lists_are_cut(db, tg, every_deal_pays, monkeypatch):
    from modules import alerts
    monkeypatch.setattr(alerts, "DEALS_SHOWN", 2)
    alerts.run()
    for i in range(3):
        _add(db, f"x{i}", title=f"<b>Byt</b> & co {i}")
    alerts.run()
    msg = tg.sent[-1]
    assert "<b>Byt</b>" not in msg and "&lt;b&gt;Byt&lt;/b&gt; &amp; co" in msg
    assert "…and 1 more on the dashboard." in msg


def test_a_full_run_sends_alerts_and_a_failure_never_breaks_it(db, monkeypatch):
    import scheduler
    from modules import alerts
    ran = []

    def boom():
        ran.append(1)
        raise alerts.TelegramError("sendMessage: HTTP 502")
    monkeypatch.setattr(alerts, "run", boom)
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **kw: True)
    monkeypatch.setattr(scheduler, "_refresh_fx", lambda: None)
    assert scheduler.run_all_markets(holder="test", which=["sk"]) == {"sk": True}
    assert ran == [1]


def test_chat_ids_lists_who_messaged_the_bot(monkeypatch):
    from modules import alerts
    monkeypatch.setattr(alerts, "_call", lambda method, **p: [
        {"message": {"chat": {"id": 6385, "first_name": "Alex"}}},
        {"message": {"chat": {"id": 6385, "first_name": "Alex"}}}])
    assert alerts.chat_ids() == [(6385, "Alex")]


def test_no_test_can_reach_a_real_chat():
    # tests/conftest.py blanks these whatever .env says.
    from modules import alerts
    assert not alerts.enabled()
