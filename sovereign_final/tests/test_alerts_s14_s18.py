"""S18: flats you follow that leave the portals (sold or withdrawn?), on
Telegram and on TODAY, and days on the market per district. S14: the weekly
digest. Also: "gone" is judged against each market's own newest sighting.
Telegram is faked (tests/test_alerts.py)."""

from datetime import datetime, timedelta, timezone

import config
from tests.conftest import make_listing
import tests.test_alerts as ta
from tests.test_alerts import _add, _now

db, tg, every_deal_pays = ta.db, ta.tg, ta.every_deal_pays


def _gone_flat(db, lid, days_ago_seen=10, market="sk", **over):
    db.upsert_listing(make_listing(lid, price_eur=120_000.0, scraped_at=_now(40),
                                   last_seen_at=_now(days_ago_seen), market=market, **over))


def _retire(db, lid):
    """The dashboard retires it (its page said it's gone, or 21 days unseen)."""
    db.deactivate_listings([f"https://example.sk/{lid}"])


def _fresh(db, lid, market="sk"):
    db.upsert_listing(make_listing(lid, price_eur=100_000.0, scraped_at=_now(2),
                                   last_seen_at=_now(), market=market))


# ── "gone" against its own market ────────────────────────────────────────────
def test_a_market_whose_runs_stopped_doesnt_look_sold(db):
    """Czech flats last seen 10 days ago, Slovak ones today: the Czech ones
    are not gone just because Slovakia's run went on."""
    from engine import backtest
    _fresh(db, "sk1")
    db.upsert_listing(make_listing("cz1", price_eur=3_000_000.0, scraped_at=_now(40),
                                   last_seen_at=_now(10), market="cz"))
    db.upsert_listing(make_listing("cz2", price_eur=3_100_000.0, scraped_at=_now(40),
                                   last_seen_at=_now(10), market="cz"))
    out = backtest.outcomes(["cz1", "cz2", "sk1"])
    assert not out["cz1"]["gone"] and not out["cz2"]["gone"] and not out["sk1"]["gone"]
    # In its own market, a flat unseen for days before the newest sighting is gone.
    _fresh(db, "cz3", market="cz")
    assert backtest.outcomes(["cz1"])["cz1"]["gone"]


# ── S18 ───────────────────────────────────────────────────────────────────────
def test_only_followed_flats_count(db):
    from engine import backtest
    _fresh(db, "x")
    _gone_flat(db, "starred")
    _gone_flat(db, "viewing")
    _gone_flat(db, "passed")
    _gone_flat(db, "nobody")
    db.set_starred("starred", True)
    db.set_deal_stage("viewing", "VIEWING", "")
    db.set_deal_stage("passed", "PASSED", "")
    gone = backtest.gone_followed()
    assert {g["id"] for g in gone} == {"starred", "viewing"}
    g = next(g for g in gone if g["id"] == "viewing")
    assert g["stage"] == "VIEWING" and g["_days_listed"] == 30
    assert not g["_retired"] and g["_unseen_days"] == 10
    # Retired only: the flats the dashboard itself took off.
    assert backtest.gone_followed(retired_only=True) == []
    _retire(db, "viewing")
    assert [g["id"] for g in backtest.gone_followed(retired_only=True)] == ["viewing"]


def test_a_followed_flat_that_left_is_announced_once(db, tg):
    from modules import alerts
    _fresh(db, "x")
    _gone_flat(db, "old")
    db.set_starred("old", True)
    _retire(db, "old")
    alerts.run()                                   # first run: noted, not messaged
    alerts.run()
    assert not any("old" in m and "Gone from the portals" in m for m in tg.sent)
    _gone_flat(db, "v1", days_ago_seen=5, title="Byt na Vlčincoch")
    db.set_deal_stage("v1", "OFFER", "")
    # Only unseen for 5 days: maybe further down the results than the
    # scrapers read. No message for that.
    assert alerts.run() == "nothing new"
    _retire(db, "v1")
    assert "1 gone" in alerts.run()
    msg = tg.sent[-1]
    assert "Gone from the portals" in msg and "Byt na Vlčincoch" in msg and "[OFFER]" in msg
    assert "up 35 days" in msg
    assert alerts.run() == "nothing new"           # once


def test_today_lists_followed_flats_that_left(db, monkeypatch):
    import tests.test_app_smoke as smoke
    _fresh(db, "x")
    _gone_flat(db, "s1", days_ago_seen=6, title="Starred flat that went")
    db.set_starred("s1", True)
    at = smoke.run_app()
    assert not at.exception, [e.value for e in at.exception]
    md = " ".join(m.value for m in at.markdown)
    assert "Gone from the portals" in md and "Starred flat that went" in md
    assert "up 34 days" in md and "not seen for 6 days: still listed?" in md
    # Shown once: not again under Starred.
    assert md.count("Starred flat that went") == 1


def test_days_on_market_per_district(db):
    from engine import backtest
    _fresh(db, "now")
    for i, (seen, first) in enumerate(((10, 40), (8, 20), (5, 35))):
        db.upsert_listing(make_listing(f"g{i}", price_eur=100_000.0, scraped_at=_now(first),
                                       last_seen_at=_now(seen)))
        _retire(db, f"g{i}")
    # Only unseen for 6 days, not retired: in neither column.
    db.upsert_listing(make_listing("u1", price_eur=100_000.0, scraped_at=_now(50),
                                   last_seen_at=_now(6)))
    rows = backtest.days_on_market("sk")
    row = rows[0]
    assert row["Left"] == 3 and row["Median days to go"] == 30
    assert row["Still listed"] == 1 and row["Median days listed so far"] == 2


# ── S14 ───────────────────────────────────────────────────────────────────────
def test_the_digest_goes_once_a_week_from_the_chosen_day(db, tg, monkeypatch, every_deal_pays):
    from modules import alerts
    monkeypatch.setattr(config, "ALERT_DIGEST", True)
    monkeypatch.setattr(config, "ALERT_DIGEST_DAY", 0)
    monday = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    assert alerts.digest_key(monday) == "2026-W48"
    assert alerts.send_digest_if_due(monday) is True
    assert alerts.send_digest_if_due(monday + timedelta(days=2)) is False   # same week
    assert alerts.digest_key(monday + timedelta(days=7)) == "2026-W49"
    # A later day: nothing before it in the week.
    monkeypatch.setattr(config, "ALERT_DIGEST_DAY", 4)
    assert alerts.digest_key(monday + timedelta(days=7)) is None           # Monday < Friday
    monkeypatch.setattr(config, "ALERT_DIGEST", False)
    assert alerts.digest_key(monday + timedelta(days=11)) is None          # off


def test_the_digest_says_what_is_there_and_what_changed(db, tg, monkeypatch, every_deal_pays):
    from modules import alerts
    monkeypatch.setattr(config, "ALERT_DIGEST", True)
    _add(db, "g1", title="A cheap flat")
    _gone_flat(db, "s1", days_ago_seen=4)
    db.set_starred("s1", True)
    _retire(db, "s1")
    db.set_deal_stage("g1", "VIEWING", "")
    now = datetime.now(timezone.utc)
    text = alerts.build_digest(now, alerts.digest_figures(now))
    assert "your week" in text and "On the dashboard:" in text and "New this week:" in text
    assert "★ 1 starred · 1 in a deal stage" in text and "1 gone from the portals" in text
    assert "Best new deals this week" in text and "A cheap flat" in text
    assert len(text) <= alerts.MESSAGE_MAX


def test_a_run_sends_the_digest_when_due(db, tg, monkeypatch):
    from modules import alerts
    monkeypatch.setattr(config, "ALERT_DIGEST", True)
    assert alerts.run().endswith("; weekly digest sent")
    assert "your week" in tg.sent[-1]
    assert not alerts.run().endswith("weekly digest sent")


def test_followed_flats_on_a_database_from_before_markets(monkeypatch, tmp_path):
    """A database whose listings table predates the market column: the
    followed flats still read (and the alert run doesn't fall over)."""
    import sqlite3
    import database
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE listings (id TEXT PRIMARY KEY, title TEXT, district TEXT,
        url TEXT, price_eur REAL, scraped_at TEXT, last_seen_at TEXT, is_active INTEGER)""")
    conn.execute("INSERT INTO listings VALUES ('o1', 'Old flat', 'Žilina', 'https://x', "
                 "90000, ?, ?, 0)", (_now(40), _now(9)))
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "SQLITE_PATH", path)
    database.set_starred("o1", True)
    rows = database.get_followed()
    assert rows[0]["id"] == "o1" and rows[0]["market"] == "sk" and rows[0]["starred"] == 1


def test_a_long_digest_is_cut_between_lines_not_inside_a_tag(db, monkeypatch):
    from modules import alerts
    monkeypatch.setattr(alerts, "MESSAGE_MAX", 300)
    long_deal = {"_class": "GREEN", "title": "x" * 80, "url": "https://example.sk/" + "y" * 120,
                 "district": "Žilina", "price_eur": 90000.0, "_best": 50.0, "market_discount": 0.3,
                 "lv_status": "PASS"}
    f = {"by_class": {}, "new_by_class": {}, "by_market": {}, "cuts": 0, "starred": 0,
         "staged": 0, "gone": [], "failed": [], "best": [long_deal] * 3}
    text = alerts.build_digest(datetime.now(timezone.utc), f)
    assert len(text) <= 300
    assert text.count("<a ") == text.count("</a>") and text.count("<b>") == text.count("</b>")
