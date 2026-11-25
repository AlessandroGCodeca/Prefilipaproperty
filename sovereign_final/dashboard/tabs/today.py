"""
dashboard/tabs/today.py — TODAY, the first page (D1): what changed since you
last looked and what needs you, each line one tap from its card. Above it,
until everything is set up, the setup checklist (D11).

Flats you follow that left the portals in the last GONE_SHOWN_DAYS days are
listed too (S18): retired by the dashboard (sold or withdrawn?), or not seen
for a few days (worth checking it is still listed). They are left out of the
other sections.

"Since you last looked" is the time of the previous visit, kept in the
database (app_state 'last_visit'), so it holds across devices; a first visit
looks back a week.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import streamlit as st

from dashboard.fmt import amt, esc, sgn

SECTION_MAX = 8
GONE_SHOWN_DAYS = 30
LV_STALE_DAYS = 30
ACTIVE_STAGES = ("VIEWING", "OFFER", "NEGOTIATING", "DUE DILIGENCE", "NOTARY")


# ── Since your last visit ────────────────────────────────────────────────────
def since_last_visit(now: datetime | None = None) -> datetime:
    """When this browser session's user last opened the dashboard before now
    (once per session: later reruns keep the same answer)."""
    if "_since" in st.session_state:
        return st.session_state["_since"]
    import database
    now = now or datetime.now(timezone.utc)
    conn = database.get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
        row = conn.execute("SELECT value FROM app_state WHERE key = 'last_visit'").fetchone()
        try:
            since = datetime.fromisoformat(row[0]) if row else now - timedelta(days=7)
        except ValueError:
            since = now - timedelta(days=7)
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES ('last_visit', ?)",
                     (now.isoformat(),))
        conn.commit()
    finally:
        conn.close()
    st.session_state["_since"] = since
    return since


def _after(stamp, since: datetime) -> bool:
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t > since


# ── What needs you ───────────────────────────────────────────────────────────
def sections(listings, v, since: datetime, starred: set) -> list[tuple[str, str, list]]:
    """[(title, hint, listings)] — only the sections with something in them."""
    from dashboard.fmt import days_since
    deals = [l for l in listings
             if (l.get("cf_class") or l.get("classification")) in ("GREEN", "YELLOW")]
    stage = lambda l: (l.get("_stage") or {}).get("stage")  # noqa: E731
    followed = [l for l in listings if l.get("id") in starred or stage(l) in ACTIVE_STAGES]

    def cut_since(l):
        ph = l.get("_ph") or {}
        hist = ph.get("history") or []
        return (ph.get("change_pct") or 0) < 0 and hist and _after(hist[-1][0], since)

    def lv_needs_you(l):
        if stage(l) not in ACTIVE_STAGES:
            return False
        if (l.get("lv_status") or "").upper() not in ("PASS", "CLEAN"):
            return True
        age = days_since(l.get("lv_checked_at"))
        return age is None or age > LV_STALE_DAYS

    out = [
        ("Starred", "the flats you starred", [l for l in listings if l.get("id") in starred]),
        ("New deals", "green or yellow, first seen since your last visit",
         [l for l in deals if _after(l.get("scraped_at"), since)]),
        ("Price cuts on flats you follow", "starred or in a deal stage",
         [l for l in followed if cut_since(l)]),
        ("Title deed to check", f"a deal in progress whose LV isn't clean or is over "
                                f"{LV_STALE_DAYS} days old", [l for l in listings if lv_needs_you(l)]),
    ]
    return [(t, h, ls) for t, h, ls in out if ls]


def failed_portals(health: dict) -> list[str]:
    """Names of the portals whose latest run failed or returned nothing."""
    import scheduler
    names = {(m, scheduler.source_of(mod)): n
             for m, pairs in scheduler.SCRAPERS.items() for n, mod in pairs}
    out = []
    for key, h in health.items():
        last = (h or {}).get("last")
        if last and (last.get("error") or not last.get("listings")):
            out.append(names.get(key, key[1]))
    return sorted(out)


def open_card(lid: str) -> None:
    """Button callback: open the flat's card in DEALS → ACTIVE SNAG LIST and
    put it first in its section."""
    st.session_state[f"card_{lid}"] = True
    st.session_state["_pin"] = lid
    st.query_params["group"] = "deals"
    st.query_params["tab"] = "ACTIVE SNAG LIST"
    # New tab bars open on the tabs just put in the address (app.py).
    st.session_state["_tabgen"] = st.session_state.get("_tabgen", 0) + 1


def _row(l, v, section: str) -> None:
    lid = l.get("id")
    surplus = v.surplus(l)
    tone = "" if surplus is None else ("bad" if v.cf_negative(l) else "good")
    cls = (l.get("cf_class") or l.get("classification") or "").upper()
    cut = (l.get("_ph") or {}).get("change_pct")
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    with c1:
        st.markdown(
            f'<div class="td-row"><div class="td-t">{esc((l.get("title") or l.get("district") or "—")[:70])}</div>'
            f'<div class="td-m">{amt(l, l.get("price_eur") or 0)} · '
            f'<span class="td-{tone}">{sgn(l, surplus)}</span>'
            + (f" · {cls.title()}" if cls else "")
            + (f" · price {cut:+.0%}" if cut and cut < 0 else "") + "</div></div>",
            unsafe_allow_html=True)
    with c2:
        if cls in ("GREEN", "YELLOW"):
            st.button("Open", key=f"td_{section}_{lid}", on_click=open_card, args=(lid,),
                      width="stretch")
        elif l.get("url"):
            from dashboard.fmt import safe_url
            st.link_button("Listing", safe_url(l.get("url")), width="stretch")


def _gone_row(g: dict) -> None:
    from dashboard.fmt import amt, safe_url
    tag = g.get("stage") or "★ starred"
    days = f" · up {g['_days_listed']} days" if g.get("_days_listed") is not None else ""
    state = ("gone from its portal" if g.get("_retired") else
             f"not seen for {g['_unseen_days']} days: still listed?")
    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    with c1:
        st.markdown(
            f'<div class="td-row"><div class="td-t">{esc((g.get("title") or g.get("district") or "—")[:70])}'
            f' <span class="muted">· {esc(tag)}</span></div>'
            f'<div class="td-m">{esc(state)} · last asked {amt(g, g.get("price_eur") or 0)}'
            f'{esc(days)} · '
            f'last seen {g["_last_seen"].day} {g["_last_seen"]:%b}</div></div>',
            unsafe_allow_html=True)
    with c2:
        if g.get("url"):
            st.link_button("Listing", safe_url(g.get("url")), width="stretch")


# ── Setup checklist (D11) ────────────────────────────────────────────────────
def setup_items() -> list[tuple[str, bool, str]]:
    """(what, done, how) for each part of the setup."""
    from config import DASHBOARD_PASSWORD
    from dashboard import legal
    import config
    env = os.getenv
    situation = os.path.exists(getattr(config, "SETTINGS_PATH", ""))
    return [
        ("Your financing and income", situation,
         "YOUR SITUATION in the sidebar: your rate, loan share and income."),
        ("Telegram alerts", bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID")),
         "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."),
        ("Claude reads ads and scans", bool(env("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY in .env."),
        ("Google maps and places", bool(env("GOOGLE_PLACES_API_KEY")), "GOOGLE_PLACES_API_KEY in .env."),
        ("Mapy.com addresses", bool(env("MAPY_API_KEY")), "MAPY_API_KEY in .env (task V)."),
        ("Daily-run watcher", bool(env("HEALTHCHECK_URL")), "HEALTHCHECK_URL in .env (healthchecks.io)."),
        ("Backups copied off this computer", bool(env("BACKUP_COPY_DIR")),
         "BACKUP_COPY_DIR in .env: an iCloud or Dropbox folder."),
        ("A long dashboard password", len(DASHBOARD_PASSWORD or "") >= 12,
         "DASHBOARD_PASSWORD in .env, 12 characters or more."),
        ("Your details in the imprint", not legal.missing(), "OPERATOR_* lines in .env (task U)."),
    ]


def render_setup() -> None:
    items = setup_items()
    left = [i for i in items if not i[1]]
    if not left:
        return
    done = len(items) - len(left)
    with st.expander(f"Setup · {done} of {len(items)} done", expanded=done < 3):
        rows = "".join(
            f'<div class="brow"><span class="l">{"✓" if ok else "○"} {esc(what)}</span>'
            f'<span class="v" style="font-family:var(--sans)">{"" if ok else esc(how)}</span></div>'
            for what, ok, how in items)
        st.markdown(f'<div class="setup">{rows}</div>', unsafe_allow_html=True)
        st.caption("Change .env, then restart the dashboard. This box goes away once all is done.")


# ── The page ─────────────────────────────────────────────────────────────────
def render(v) -> None:
    """The TODAY tab."""
    render_setup()
    if v.using_demo:
        st.info("TODAY shows what changed since your last visit; it needs the database, "
                "not the demo data.")
        return
    from database import get_starred, portal_health
    from engine.backtest import gone_followed
    since = since_last_visit()
    try:
        gone = gone_followed(within_days=GONE_SHOWN_DAYS)
    except Exception:
        gone = []
    gone_ids = {g["id"] for g in gone}
    listings = [l for l in v.greens + v.yellows + v.whites if l.get("id") not in gone_ids]
    secs = sections(listings, v, since, get_starred())
    failed = failed_portals(portal_health(days=2))
    local = since.astimezone()
    # "23 Nov, 12:35". The day without its zero comes from .day: strftime's
    # no-padding flag is a Linux and Mac extension that Windows rejects.
    when = f"{local.day} {local:%b, %H:%M}"
    st.markdown(f'<div class="vd-head" style="margin:4px 0 2px">Since your last visit</div>'
                f'<div class="muted" style="margin-bottom:10px">{esc(when)}</div>',
                unsafe_allow_html=True)
    if failed:
        st.warning(f"{', '.join(failed)}: the latest run failed or found nothing. "
                   "Open DIAGNOSTICS → TEST SITES in the sidebar to see why.")
    # S18: flats you follow that left the portals, or may have.
    if gone:
        st.markdown(f'<div class="td-h">Gone from the portals? <span class="muted">· {len(gone)} · '
                    f'flats you follow, retired or not seen lately (last {GONE_SHOWN_DAYS} '
                    f'days)</span></div>', unsafe_allow_html=True)
        for g in gone[:SECTION_MAX]:
            _gone_row(g)
    if not secs:
        if not gone:
            st.success("Nothing new needs you. The full list is in DEALS → ACTIVE SNAG LIST.")
        return
    for title, hint, ls in secs:
        st.markdown(f'<div class="td-h">{esc(title)} <span class="muted">· {len(ls)} · '
                    f'{esc(hint)}</span></div>', unsafe_allow_html=True)
        for l in ls[:SECTION_MAX]:
            _row(l, v, title[:6])
        if len(ls) > SECTION_MAX:
            st.caption(f"and {len(ls) - SECTION_MAX} more in DEALS → ACTIVE SNAG LIST.")
