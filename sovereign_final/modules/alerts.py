"""
modules/alerts.py — Telegram alerts after each full run.

After ▶ RUN EVERYTHING or the scheduler's run, one message to your Telegram
chat with what is new since the last one:

  - deals: an active listing of a class in config.ALERT_CLASSES (GREEN and
    YELLOW by default), not rejected on its title deed, and not cash-flow
    negative under its better structure (CASHFLOW_MIN_SURPLUS) — the first
    time it qualifies, one message per flat across its portal copies;
  - price cuts on the deals you track in DEAL PIPELINE (not CLOSED or
    PASSED), each cut once;
  - with config.ALERT_FAILURES: a market whose run failed with no retry left,
    and a portal gone quiet (database.quiet_portals), each once.

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
# Telegram refuses a message over 4,096 characters: at most this many deals
# are listed, the rest counted.
DEALS_SHOWN = 10
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
    values = [v for v in (l.get("surplus_personal"), l.get("surplus_sro")) if v is not None]
    return max(values) if values else None


def qualifying_deals() -> list[dict]:
    """The active listings an alert is for, best discount first, one per flat."""
    from engine.duplicates import one_per_flat
    from engine.financial import is_cashflow_negative
    out = []
    for l in _db.get_all_active():           # LV-rejected listings are left out
        cls = (l.get("cf_class") or l.get("classification") or "").upper()
        best = _best_surplus(l)
        if cls not in config.ALERT_CLASSES or best is None or l.get("is_dev_project"):
            continue
        if is_cashflow_negative(best, markets.of_row(l)):
            continue
        out.append({**l, "_class": cls, "_best": best})
    out = one_per_flat(out)
    out.sort(key=lambda l: l.get("market_discount") or 0, reverse=True)
    return out


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
    return (f"{emoji} <a href=\"{html.escape(l.get('url') or '', quote=True)}\">{title}</a>"
            f"{f' · {district}' if district and district not in title else ''}\n"
            f"    {_money(l, l.get('price_eur'))}{below} · "
            f"{_money(l, l['_best'], '/mo')} · {_lv(l)}")


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


def build_message(deals, cuts, issues, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    from modules.contract_draft import to_local
    parts = [f"🏛 <b>Sovereign</b> · {to_local(now.isoformat()):%d.%m. %H:%M}"]
    if deals:
        parts.append(f"<b>{len(deals)} new deal{'s' if len(deals) != 1 else ''}</b>")
        parts += [_deal_line(l) for l in deals[:DEALS_SHOWN]]
        if len(deals) > DEALS_SHOWN:
            parts.append(f"…and {len(deals) - DEALS_SHOWN} more on the dashboard.")
    if cuts:
        parts.append("<b>Price cuts on deals you track</b>")
        parts += [_cut_line(t) for t in cuts]
    if issues:
        parts.append("<b>Needs a look</b>")
        parts += [line for _key, line in issues]
    return "\n".join(parts)


# ── The pipeline's step ───────────────────────────────────────────────────────
def run() -> str:
    """Send what is new since the last message. Returns a summary for the log;
    raises TelegramError when Telegram refused or couldn't be reached."""
    if not enabled():
        return "off (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"
    deals = qualifying_deals()
    sent_deals = _sent("deal")
    if not sent_deals:
        # First run with alerts on: today's deals are already on the
        # dashboard. Say how many, and alert only new ones from now on.
        send(f"🏛 <b>Sovereign alerts are on.</b>\n{len(deals)} deal(s) matching your "
             f"alert settings are already on the dashboard; from now on you'll hear "
             f"about each new one, price cuts on the deals you track"
             + (", and failed runs or quiet portals." if config.ALERT_FAILURES else "."))
        # A marker row, so a dashboard with no deal yet isn't "first" forever.
        _mark_sent([("deal", "__baseline__")] + [("deal", _deal_key(l)) for l in deals])
        return f"alerts on: {len(deals)} existing deal(s) noted, none messaged"
    new = [l for l in deals if _deal_key(l) not in sent_deals]
    cuts = [t for t in tracked_cuts() if t["_key"] not in _sent("cut")]
    issues = []
    if config.ALERT_FAILURES:
        done = _sent("issue")
        issues = [(k, line) for k, line in problems() if k not in done]
    if not (new or cuts or issues):
        return "nothing new"
    send(build_message(new, cuts, issues))
    _mark_sent([("deal", _deal_key(l)) for l in new]
               + [("cut", t["_key"]) for t in cuts]
               + [("issue", k) for k, _line in issues])
    return f"sent: {len(new)} deal(s), {len(cuts)} cut(s), {len(issues)} issue(s)"


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
