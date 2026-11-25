"""
modules/alerts.py — Telegram alerts after each full run.

After ▶ RUN EVERYTHING or the scheduler's run, one message to your Telegram
chat with what is new since the last one:

  - deals: an active listing, not rejected on its title deed, that matches
    one of your alert rules — the first time it does, one message per flat
    across its portal copies. Rules are saved searches from the dashboard's
    ALERTS tab (class, grade, district, size, price, least monthly surplus);
    with none saved, the built-in rule from .env applies: ALERT_CLASSES
    (GREEN and YELLOW), ALERT_GRADES and ALERT_MIN_SURPLUS, both off by
    default. A deal you were told about is announced again when it turns
    GREEN, and when its price is cut;
  - price cuts on the deals you track in DEAL PIPELINE (not CLOSED or
    PASSED), each cut once;
  - with config.ALERT_FAILURES: a market whose run failed with no retry left,
    and a portal gone quiet (database.quiet_portals), each once;
  - a flat you follow (starred, or in a deal stage that isn't CLOSED or
    PASSED) that the dashboard has retired as gone from its portal — sold or
    withdrawn? — once (S18).

Once a week, with the first run on or after ALERT_DIGEST_DAY (Monday by
default), a digest of its own: what is on the dashboard, what came and went
that week, the portals (S14). ALERT_DIGEST=0 turns it off.

Nothing new, no message. What was sent is kept in the sent_alerts table, and
recorded only once Telegram took the message: an alert lost to a network
error goes out with the next run. The first run with alerts on doesn't
message every deal already on the dashboard: it says how many there are and
alerts from then on.

Off while TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is blank.

  python -m modules.alerts test      send a test message
  python -m modules.alerts chat-id   the chats that have messaged your bot
  python -m modules.alerts run       send what is new now
"""

import html
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import database as _db
import markets

log = logging.getLogger("sovereign")

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_S = 20
# Telegram refuses a message over 4,096 characters: at most this many lines
# of each kind are listed, the rest counted — and the text is cut at
# MESSAGE_MAX whatever it holds, so one long run can't block every later one.
DEALS_SHOWN = 10
CUTS_SHOWN = 10
ISSUES_SHOWN = 8
MESSAGE_MAX = 3900
# A price cut on a tracked deal older than this isn't news any more.
CUT_MAX_AGE_DAYS = 14
_DONE_STAGES = ("CLOSED", "PASSED")


class TelegramError(Exception):
    pass


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _call(method: str, **params) -> dict:
    """One Bot API call. The token travels in the URL, so an error names the
    method and Telegram's answer, never the URL."""
    import requests
    try:
        r = requests.post(API.format(token=config.TELEGRAM_BOT_TOKEN, method=method),
                          data=params, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise TelegramError(f"{method}: {type(e).__name__}") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not body.get("ok"):
        raise TelegramError(f"{method}: HTTP {r.status_code} "
                            f"{body.get('description') or ''}".strip())
    return body.get("result") or {}


def send(text: str) -> None:
    """Send `text` (Telegram HTML) to TELEGRAM_CHAT_ID."""
    _call("sendMessage", chat_id=config.TELEGRAM_CHAT_ID, text=text, parse_mode="HTML",
          disable_web_page_preview="true")


# ── What was sent ─────────────────────────────────────────────────────────────
def _ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            kind    TEXT NOT NULL,
            key     TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (kind, key)
        )""")


def _sent(kind: str) -> set[str]:
    conn = _db.get_conn()
    try:
        _ensure_table(conn)
        return {r[0] for r in conn.execute("SELECT key FROM sent_alerts WHERE kind = ?", (kind,))}
    finally:
        conn.close()


def _mark_sent(items: list[tuple[str, str]]) -> None:
    if not items:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.get_conn()
    try:
        _ensure_table(conn)
        conn.executemany("INSERT OR IGNORE INTO sent_alerts (kind, key, sent_at) VALUES (?,?,?)",
                         [(k, key, now) for k, key in items])
        conn.commit()
    finally:
        conn.close()


# ── What is worth a message ───────────────────────────────────────────────────
def _deal_key(l: dict) -> str:
    # One message per flat: its portal copies share a dup_group.
    return f"group:{l['dup_group']}" if l.get("dup_group") else l["id"]


def _best_surplus(l: dict):
    """The monthly surplus under the structure recommended for the listing —
    the dashboard's own rule (engine.financial.shown_surplus)."""
    from engine.financial import shown_surplus
    return shown_surplus(l)


def builtin_rule() -> dict:
    """The rule in force while none is saved: .env's ALERT_CLASSES,
    ALERT_GRADES and ALERT_MIN_SURPLUS."""
    return {"name": "", "enabled": 1, "market": "",
            "classes": ",".join(config.ALERT_CLASSES), "grades": ",".join(config.ALERT_GRADES),
            "district": "", "min_size": None, "max_price_eur": None,
            "min_surplus": config.ALERT_MIN_SURPLUS}


def active_rules() -> list[dict]:
    """The rules a deal is matched against: the saved ones that are switched
    on, or the built-in one when none was ever saved."""
    saved = _db.get_alert_rules()
    return [r for r in saved if r.get("enabled")] if saved else [builtin_rule()]


def _fold(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def matches(l: dict, rule: dict, grade: str | None = None) -> bool:
    """Whether a scored listing row fits a rule. Money in the rule is in EUR
    (a Czech listing's is converted at the dated rate); a blank field of the
    rule asks for nothing."""
    cur = l.get("currency") or markets.get(markets.of_row(l)).currency
    cls = (l.get("cf_class") or l.get("classification") or "").upper()
    if rule.get("market") and markets.of_row(l) != rule["market"]:
        return False
    if rule.get("classes") and cls not in rule["classes"].split(","):
        return False
    if rule.get("grades"):
        if grade is None:
            from engine.financial import compute_deal_score
            grade = compute_deal_score(l)[1]
        if grade not in rule["grades"].split(","):
            return False
    if rule.get("district") and _fold(rule["district"]) not in _fold(l.get("district") or ""):
        return False
    if rule.get("min_size") is not None and (l.get("size_m2") or 0) < rule["min_size"]:
        return False
    if rule.get("max_price_eur") is not None and \
            (markets.to_eur(l.get("price_eur") or 0, cur) or 0) > rule["max_price_eur"]:
        return False
    if rule.get("min_surplus") is not None:
        surplus = _best_surplus(l)
        if surplus is None or markets.to_eur(surplus, cur) < rule["min_surplus"]:
            return False
    return True


def qualifying_deals(rules: list[dict] | None = None) -> list[dict]:
    """The active listings an alert is for, best discount first, one per
    flat: scored, not a developer project, and fitting at least one rule
    (`rules`, default active_rules()). Each carries "_class", "_best" (its
    recommended structure's surplus) and "_rules" (the names it fits)."""
    from engine.duplicates import one_per_flat
    from engine.financial import compute_deal_score
    rules = active_rules() if rules is None else rules
    need_grade = any(r.get("grades") for r in rules)
    out = []
    for l in _db.get_all_active():           # LV-rejected listings are left out
        cls = (l.get("cf_class") or l.get("classification") or "").upper()
        best = _best_surplus(l)
        if best is None or l.get("is_dev_project"):
            continue
        grade = compute_deal_score(l)[1] if need_grade else None
        fits = [r["name"] for r in rules if matches(l, r, grade)]
        if fits:
            out.append({**l, "_class": cls, "_best": best, "_rules": [n for n in fits if n]})
    out = one_per_flat(out)
    out.sort(key=lambda l: l.get("market_discount") or 0, reverse=True)
    return out


def note_existing(rules: list[dict] | None = None) -> int:
    """Record every deal that fits the rules now as already announced,
    without a message — after you change the rules, so you hear only about
    what comes in from here on. Returns how many were noted."""
    deals = qualifying_deals(rules)
    _mark_sent([("deal", "__baseline__")] + [("deal", _deal_key(l)) for l in deals]
               + [("deal-green", _deal_key(l)) for l in deals if l["_class"] == "GREEN"])
    return len(deals)


def _sent_at(kind: str) -> dict[str, str]:
    conn = _db.get_conn()
    try:
        _ensure_table(conn)
        return {r[0]: r[1] for r in conn.execute(
            "SELECT key, sent_at FROM sent_alerts WHERE kind = ?", (kind,))}
    finally:
        conn.close()


def follow_ups(deals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Of the deals you were already told about: (the ones that have turned
    GREEN since, the ones whose price was cut since) — each cut once."""
    told = _sent_at("deal")
    green_told, cut_told = _sent("deal-green"), _sent("deal-cut")
    known = [l for l in deals if _deal_key(l) in told]
    greens = [l for l in known if l["_class"] == "GREEN" and _deal_key(l) not in green_told]
    hist = _db.get_price_history({l["id"] for l in known}) if known else {}
    cuts = []
    for l in known:
        h = hist.get(l["id"]) or {}
        if (h.get("last_change_pct") or 0) < 0 and (h.get("last_change_at") or "") > told[_deal_key(l)]:
            key = f"{_deal_key(l)}@{h['last_change_at']}"
            if key not in cut_told:
                cuts.append({**l, "_cut": h["last_change_pct"], "_key": key})
    return greens, cuts


def tracked_cuts(now: datetime | None = None) -> list[dict]:
    """Price cuts on the deals you track: [{listing…, "_key", "_cut"}]."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=CUT_MAX_AGE_DAYS)).isoformat()
    stages = _db.get_deal_stages()
    live = {lid for lid, s in stages.items() if s.get("stage") not in _DONE_STAGES}
    if not live:
        return []
    hist = _db.get_price_history(live)
    out = []
    for t in _db.get_tracked_listings():
        h = hist.get(t["id"])
        if (t["id"] not in live or not t.get("is_active") or not h
                or (h.get("last_change_pct") or 0) >= 0 or h["last_change_at"] < cutoff):
            continue
        out.append({**t, "_stage": stages[t["id"]]["stage"], "_cut": h["last_change_pct"],
                    "_key": f"{t['id']}@{h['last_change_at']}"})
    return out


def problems() -> list[tuple[str, str]]:
    """(key, line) for each run that failed with no retry left and each
    portal gone quiet."""
    from modules.pipeline_state import read_status
    from scheduler import active_markets, portal_name
    out = []
    for m in active_markets():
        st = read_status(m) or {}
        # The scheduler's failure has a retry coming while next_retry_at is
        # set; a dashboard run's is final (nothing retries it).
        if st.get("state") == "failed" and (not st.get("next_retry_at")
                                             or st.get("trigger") == "dashboard"):
            out.append((f"run:{m}:{st.get('finished_at')}",
                        f"❌ {m.upper()} run failed: {html.escape(str(st.get('error') or 'unknown error'))[:200]}"))
    for q in _db.quiet_portals():
        since = (q.get("last_good_at") or "never")[:10]
        out.append((f"quiet:{q['market']}:{q['source']}:{q.get('last_good_at')}",
                    f"⚠ {html.escape(portal_name(q['market'], q['source']))} returned no "
                    f"listings on its last {len(q.get('runs') or [])} runs "
                    f"(last good: {since}) — its listings are kept."))
    return out


def _reminders() -> list[dict]:
    from modules import yearly
    try:
        return yearly.reminders()
    except Exception as e:
        log.warning(f"Yearly reminders skipped: {type(e).__name__}: {e}")
        return []


# ── The message ───────────────────────────────────────────────────────────────
def _money(l: dict, v, suffix: str = "") -> str:
    cur = l.get("currency") or markets.get(markets.of_row(l)).currency
    return markets.format_money(v, cur, suffix=suffix)


def _lv(l: dict) -> str:
    status = (l.get("lv_status") or "PENDING").upper()
    return "LV ✅" if status in ("PASS", "CLEAN") else "LV unverified"


def _deal_line(l: dict) -> str:
    emoji = {"GREEN": "🟢", "YELLOW": "🟡"}.get(l["_class"], "•")
    disc = l.get("market_discount")
    below = f" · {disc:.0%} below market" if disc is not None else ""
    title = html.escape((l.get("title") or l.get("district") or "—")[:60])
    district = html.escape(l.get("district") or "")
    rules = f" · 🔎 {html.escape(', '.join(l['_rules'])[:60])}" if l.get("_rules") else ""
    cut = f" · 🔻 {l['_cut']:+.1%}" if l.get("_cut") else ""
    return (f"{emoji} <a href=\"{html.escape(l.get('url') or '', quote=True)}\">{title}</a>"
            f"{f' · {district}' if district and district not in title else ''}\n"
            f"    {_money(l, l.get('price_eur'))}{cut}{below} · "
            f"{_money(l, l['_best'], '/mo')} · {_lv(l)}{rules}")


def _cut_line(t: dict) -> str:
    title = html.escape((t.get("title") or t.get("district") or "—")[:60])
    my = t.get("max_price_yellow")
    inside = ""
    if my:
        inside = (" · now inside max 🟡" if t["price_eur"] <= my
                  else f" · {t['price_eur'] / my - 1:+.0%} over max 🟡")
    return (f"🔻 <a href=\"{html.escape(t.get('url') or '', quote=True)}\">{title}</a> "
            f"[{html.escape(t['_stage'])}]\n"
            f"    now {_money(t, t['price_eur'])} ({t['_cut']:+.1%}){inside}")


def _gone_line(g: dict) -> str:
    title = html.escape((g.get("title") or g.get("district") or "—")[:60])
    tag = html.escape(g["stage"]) if g.get("stage") else "★"
    days = f" · up {g['_days_listed']} days" if g.get("_days_listed") is not None else ""
    return (f"📭 <a href=\"{html.escape(g.get('url') or '', quote=True)}\">{title}</a> [{tag}]\n"
            f"    last asked {_money(g, g.get('price_eur'))}{days} · "
            f"last seen {g['_last_seen']:%d.%m.}")


def _section(parts: list, title: str, lines: list, shown: int) -> None:
    if not lines:
        return
    parts.append(f"<b>{title}</b>")
    parts += lines[:shown]
    if len(lines) > shown:
        parts.append(f"…and {len(lines) - shown} more on the dashboard.")


def build_message(deals, cuts, issues, now: datetime | None = None,
                  now_green=(), recut=(), gone=()) -> str:
    """The message: new deals, deals that turned GREEN, deals cut again,
    price cuts on tracked deals, problems — each section capped, and the
    whole cut at MESSAGE_MAX (Telegram's limit is 4,096 characters)."""
    now = now or datetime.now(timezone.utc)
    from modules.contract_draft import to_local
    parts = [f"🏛 <b>Sovereign</b> · {to_local(now.isoformat()):%d.%m. %H:%M}"]
    _section(parts, f"{len(deals)} new deal{'s' if len(deals) != 1 else ''}",
             [_deal_line(l) for l in deals], DEALS_SHOWN)
    _section(parts, "Now GREEN", [_deal_line(l) for l in now_green], DEALS_SHOWN)
    _section(parts, "Cut since you were told", [_deal_line(l) for l in recut], DEALS_SHOWN)
    _section(parts, "Price cuts on deals you track", [_cut_line(t) for t in cuts], CUTS_SHOWN)
    _section(parts, "Gone from the portals: sold or withdrawn?", [_gone_line(g) for g in gone],
             CUTS_SHOWN)
    _section(parts, "Needs a look", [line for _key, line in issues], ISSUES_SHOWN)
    out, size = [], 0
    for part in parts:              # whole lines only: a cut tag would be refused
        if size + len(part) + 1 > MESSAGE_MAX:
            out.append("…more on the dashboard.")
            break
        out.append(part)
        size += len(part) + 1
    return "\n".join(out)


# ── The pipeline's step ───────────────────────────────────────────────────────
def gone_news() -> list[dict]:
    """Followed flats the dashboard has retired (gone from their portal) that
    weren't announced yet. Only retired ones: a flat merely unseen for a few
    days may be further down the results than the scrapers read. The first
    time, the ones already gone are noted, not messaged."""
    from engine.backtest import gone_followed
    gone, told = gone_followed(retired_only=True), _sent("gone")
    if not told:
        _mark_sent([("gone", "__baseline__")] + [("gone", g["id"]) for g in gone])
        return []
    return [g for g in gone if g["id"] not in told]


def run() -> str:
    """Send what is new since the last message, and the weekly digest when it
    is due. Returns a summary for the log; raises TelegramError when Telegram
    refused or couldn't be reached."""
    if not enabled():
        return "off (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"
    summary = _run_news()
    if send_digest_if_due():
        summary += "; weekly digest sent"
    return summary


def _run_news() -> str:
    deals = qualifying_deals()
    sent_deals = _sent("deal")
    if not sent_deals:
        # First run with alerts on: today's deals are already on the
        # dashboard. Say how many, and alert only new ones from now on.
        send(f"🏛 <b>Sovereign alerts are on.</b>\n{len(deals)} deal(s) matching your "
             f"alert rules are already on the dashboard; from now on you'll hear "
             f"about each new one, price cuts on the deals you track"
             + (", and failed runs or quiet portals." if config.ALERT_FAILURES else "."))
        # A marker row, so a dashboard with no deal yet isn't "first" forever.
        _mark_sent([("deal", "__baseline__")] + [("deal", _deal_key(l)) for l in deals]
                   + [("deal-green", _deal_key(l)) for l in deals if l["_class"] == "GREEN"])
        return f"alerts on: {len(deals)} existing deal(s) noted, none messaged"
    new = [l for l in deals if _deal_key(l) not in sent_deals]
    now_green, recut = follow_ups(deals)
    sent_cuts = _sent("cut")
    cuts = [t for t in tracked_cuts() if t["_key"] not in sent_cuts]
    done = _sent("issue")
    issues = [(k, line) for k, line in (problems() if config.ALERT_FAILURES else [])
              if k not in done]
    # The yearly tax-table reminder (modules/yearly), once each.
    issues += [(r["key"], r["text"]) for r in _reminders() if r["key"] not in done]
    gone = gone_news()
    if not (new or now_green or recut or cuts or issues or gone):
        return "nothing new"
    send(build_message(new, cuts, issues, now_green=now_green, recut=recut, gone=gone))
    _mark_sent([("deal", _deal_key(l)) for l in new]
               + [("deal-green", _deal_key(l)) for l in new + now_green if l["_class"] == "GREEN"]
               + [("deal-cut", l["_key"]) for l in recut]
               + [("cut", t["_key"]) for t in cuts]
               + [("issue", k) for k, _line in issues]
               + [("gone", g["id"]) for g in gone])
    return (f"sent: {len(new)} deal(s), {len(now_green)} now GREEN, {len(recut)} cut again, "
            f"{len(gone)} gone, {len(cuts)} tracked cut(s), {len(issues)} issue(s)")


# ── The weekly digest (S14) ───────────────────────────────────────────────────
def _local(now: datetime) -> datetime:
    from modules.pipeline_state import LOCAL_TZ
    return now.astimezone(LOCAL_TZ)


def digest_key(now: datetime) -> str | None:
    """This week's digest key when one is due now, else None: on or after
    ALERT_DIGEST_DAY in the local week, not sent yet."""
    if not config.ALERT_DIGEST:
        return None
    local = _local(now)
    if local.weekday() < config.ALERT_DIGEST_DAY:
        return None
    year, week, _ = local.isocalendar()
    key = f"{year}-W{week:02d}"
    return None if key in _sent("digest") else key


def digest_figures(now: datetime) -> dict:
    """The digest's numbers: active scored flats by market and class, the
    ones first seen in the last 7 days, price cuts in those days, what you
    follow and what of it went, and the portals whose latest run failed."""
    from engine.backtest import gone_followed
    week_ago = (now - timedelta(days=7)).isoformat()
    by_class: dict[str, int] = {}
    new_by_class: dict[str, int] = {}
    by_market: dict[str, int] = {}
    conn = _db.get_conn()
    try:
        if _db._has_table(conn, "cashflow_scores"):
            for market, cls, n, new in conn.execute("""
                    SELECT COALESCE(l.market, 'sk'), c.classification, COUNT(*),
                           SUM(CASE WHEN l.scraped_at >= ? THEN 1 ELSE 0 END)
                    FROM listings l JOIN cashflow_scores c ON c.listing_id = l.id
                    WHERE l.is_active = 1 GROUP BY 1, 2""", (week_ago,)):
                cls = (cls or "PENDING").upper()
                by_class[cls] = by_class.get(cls, 0) + n
                new_by_class[cls] = new_by_class.get(cls, 0) + (new or 0)
                by_market[market] = by_market.get(market, 0) + n
    finally:
        conn.close()
    followed = _db.get_followed()
    gone = [g for g in gone_followed(retired_only=True)
            if g["_last_seen"].isoformat() >= week_ago]
    failed = _failed_portals()
    best = sorted((l for l in qualifying_deals() if (l.get("scraped_at") or "") >= week_ago),
                  key=lambda l: -(l["_best"] if l.get("_best") is not None else -1e12))[:3]
    return {"by_class": by_class, "new_by_class": new_by_class, "by_market": by_market,
            "cuts": len(_db.get_price_drops(days=7)),
            "starred": sum(1 for f in followed if f.get("starred")),
            "staged": sum(1 for f in followed if f.get("stage")),
            "gone": gone, "failed": failed, "best": best}


def _failed_portals() -> list[str]:
    """Portals whose latest run (in the last two days) failed or found nothing."""
    import scheduler
    names = {(m, scheduler.source_of(mod)): n
             for m, pairs in scheduler.SCRAPERS.items() for n, mod in pairs}
    out = []
    for key, h in _db.portal_health(days=2).items():
        last = (h or {}).get("last")
        if last and (last.get("error") or not last.get("listings")):
            out.append(names.get(key, key[1]))
    return sorted(out)


def build_digest(now: datetime, f: dict) -> str:
    local = _local(now)
    start = local - timedelta(days=7)
    dots = (("GREEN", "🟢"), ("YELLOW", "🟡"), ("WHITE", "⚪"))

    def classes(counts: dict) -> str:
        return " · ".join(f"{dot} {counts.get(c, 0)}" for c, dot in dots)

    markets_line = " · ".join(f"{m.upper()} {n}" for m, n in sorted(f["by_market"].items()))
    parts = [f"🏛 <b>Sovereign · your week</b> ({start:%d.%m.}–{local:%d.%m.})",
             f"On the dashboard: {classes(f['by_class'])}"
             + (f" ({markets_line})" if markets_line else ""),
             f"New this week: {classes(f['new_by_class'])}",
             f"Price cuts this week: {f['cuts']}",
             f"You follow: ★ {f['starred']} starred · {f['staged']} in a deal stage"
             + (f" · 📭 {len(f['gone'])} gone from the portals this week" if f["gone"] else ""),
             ("Portals: all ran" if not f["failed"] else
              "Portals: ⚠ " + html.escape(", ".join(f["failed"])) + " failed or found nothing")]
    if f["best"]:
        parts.append("<b>Best new deals this week</b>")
        parts += [_deal_line(l) for l in f["best"]]
    out, size = [], 0
    for part in parts:              # whole lines only: a cut tag would be refused
        if size + len(part) + 1 > MESSAGE_MAX:
            break
        out.append(part)
        size += len(part) + 1
    return "\n".join(out)


def send_digest_if_due(now: datetime | None = None) -> bool:
    """Send this week's digest if it is due; True when it went out. Recorded
    only once Telegram took it."""
    now = now or datetime.now(timezone.utc)
    key = digest_key(now)
    if not key:
        return False
    send(build_digest(now, digest_figures(now)))
    _mark_sent([("digest", key)])
    return True


def run_quietly() -> None:
    """run(), for the end of a pipeline run: an alert never fails the run."""
    try:
        log.info(f"📨 Telegram alerts: {run()}")
    except Exception as e:
        log.error(f"📨 Telegram alerts not sent: {type(e).__name__}: {e}")


def send_test() -> None:
    send("🏛 <b>Sovereign</b> — test message. Alerts reach this chat.")


def chat_ids() -> list[tuple[int, str]]:
    """(chat id, name) of each chat that has messaged the bot lately —
    Telegram keeps a day of messages."""
    seen = {}
    for u in _call("getUpdates"):
        m = u.get("message") or u.get("edited_message") or u.get("my_chat_member") or {}
        c = m.get("chat") or {}
        if c.get("id") is not None:
            seen[c["id"]] = c.get("username") or c.get("first_name") or c.get("title") or ""
    return list(seen.items())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if not config.TELEGRAM_BOT_TOKEN:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env first.")
    if cmd == "chat-id":
        ids = chat_ids()
        if not ids:
            print("No messages yet: send your bot any message in Telegram, then run this again.")
        for cid, name in ids:
            print(f"TELEGRAM_CHAT_ID={cid}    ({name})")
    elif cmd == "test":
        send_test()
        print("Sent — check Telegram.")
    else:
        print(run())
