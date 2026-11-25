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
    monkeypatch.setattr(config, "ALERT_GRADES", [])
    monkeypatch.setattr(config, "ALERT_MIN_SURPLUS", None)
    monkeypatch.setattr(config, "ALERT_FAILURES", True)
    # The weekly digest has tests of its own (test_alerts_s14_s18.py).
    monkeypatch.setattr(config, "ALERT_DIGEST", False)
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


def test_the_built_in_rule_is_green_and_yellow_whatever_the_cash_flow(db, tg, monkeypatch):
    # Audit of 12 Nov 2026, finding 2: asking for break-even silenced the
    # alerts, since at ordinary financing almost no GREEN flat breaks even.
    from engine import financial
    from modules import alerts
    alerts.run()                                 # baseline on an empty database
    _add(db, "white", ratio=1.0)                 # at market: WHITE
    monkeypatch.setattr(financial, "CASHFLOW_MIN_SURPLUS", 1e9)   # nothing "pays"
    _add(db, "green_loses")
    assert alerts.run().startswith("sent: 1 deal")
    assert "green_loses" in tg.sent[-1] and "white" not in tg.sent[-1]


def test_a_least_surplus_from_env_keeps_out_what_costs_more(db, tg, monkeypatch):
    from modules import alerts
    alerts.run()
    _add(db, "g1")
    surplus = alerts.qualifying_deals()[0]["_best"]
    monkeypatch.setattr(config, "ALERT_MIN_SURPLUS", surplus + 1)
    assert alerts.run() == "nothing new"
    monkeypatch.setattr(config, "ALERT_MIN_SURPLUS", surplus - 1)
    assert alerts.run().startswith("sent: 1 deal")


def test_saved_rules_replace_the_built_in_one(db, tg):
    from modules import alerts
    alerts.run()
    _add(db, "zilina")
    _add(db, "nitra", district="Nitra", address_raw="Nitra")
    db.save_alert_rules([{"name": "Nitra watch", "district": "nitra", "classes": "GREEN, yellow"},
                         {"name": "off", "enabled": False, "classes": "GREEN"},
                         {"name": "", "classes": "GREEN"}])          # no name: dropped
    assert [r["name"] for r in db.get_alert_rules()] == ["Nitra watch", "off"]
    assert alerts.run().startswith("sent: 1 deal")
    msg = tg.sent[-1]
    assert "nitra" in msg and "zilina" not in msg and "🔎 Nitra watch" in msg


def test_a_rule_reads_grade_size_price_and_market(db):
    from modules import alerts
    row = {"id": "x", "cf_class": "GREEN", "district": "Bratislava - Petržalka", "size_m2": 55,
           "price_eur": 150_000, "currency": "EUR", "market": "sk", "optimal_structure": "PERSONAL",
           "surplus_personal": -120, "surplus_sro": 50, "cap_rate": 0.05, "market_discount": 0.25}
    rule = alerts.builtin_rule()
    assert alerts.matches(row, rule)
    assert not alerts.matches(row, {**rule, "market": "cz"})
    assert not alerts.matches(row, {**rule, "min_size": 60})
    assert not alerts.matches(row, {**rule, "max_price_eur": 140_000})
    assert alerts.matches(row, {**rule, "district": "petrzalka"})          # without diacritics
    # The surplus is the recommended structure's (personal here), not the better one.
    assert not alerts.matches(row, {**rule, "min_surplus": -100})
    assert alerts.matches(row, {**rule, "min_surplus": -150})
    assert alerts.matches(row, {**rule, "grades": "A,B"}, grade="A")
    assert not alerts.matches(row, {**rule, "grades": "A,B"}, grade="C")


def test_a_deal_you_were_told_about_comes_back_when_it_turns_green_or_is_cut(db, tg):
    from modules import alerts
    alerts.run()
    _add(db, "y1", ratio=0.86)                   # YELLOW
    assert alerts.run().startswith("sent: 1 deal")
    assert alerts.run() == "nothing new"
    # Cut to GREEN: one message saying both.
    from engine.regional_prices import regional_median_price
    db.upsert_listing(make_listing("y1", price_eur=float(round(regional_median_price("Žilina")
                                                               * 55 * 0.7)),
                                   size_m2=55.0, scraped_at=_now(5), last_seen_at=_now()))
    from modules.cashflow_runner import run_scoring
    run_scoring()
    out = alerts.run()
    assert "1 now GREEN" in out and "1 cut again" in out
    assert "Now GREEN" in tg.sent[-1] and "Cut since you were told" in tg.sent[-1]
    assert alerts.run() == "nothing new"          # each once


def test_saving_rules_can_note_what_fits_now(db, tg):
    from modules import alerts
    alerts.run()
    _add(db, "g1")
    db.save_alert_rules([{"name": "all", "classes": "GREEN,YELLOW"}])
    assert alerts.note_existing() == 1
    assert alerts.run() == "nothing new"


def test_a_message_never_passes_telegrams_limit(db):
    from modules import alerts
    issues = [(f"k{i}", "⚠ " + "x" * 300) for i in range(40)]
    cuts = [{"title": "t" * 60, "url": "https://e.sk", "_stage": "OFFER", "price_eur": 1,
             "_cut": -0.1, "currency": "EUR"} for _ in range(40)]
    msg = alerts.build_message([], cuts, issues)
    assert len(msg) <= alerts.MESSAGE_MAX
    assert "more on the dashboard" in msg


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
    assert alerts.run().endswith("1 tracked cut(s), 0 issue(s)")
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
