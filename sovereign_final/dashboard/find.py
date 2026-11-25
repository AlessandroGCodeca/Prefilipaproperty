"""
dashboard/find.py — one box above the tabs to find a flat (UX2): paste its
portal link, type its id (the six characters the pickers show) or words of
its title or street. The matches show with their summary; a tracked flat the
sidebar's filters hide is listed with a note.

A link no listing has yet can be read on the spot where a portal's own
reader can do it from the link alone: Topreality.sk and Bezrealitky.cz (the
others are read from their search pages, or with a browser, every morning).
Only those portals' own addresses are fetched, so a pasted link never makes
the server fetch anything else.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import streamlit as st

from dashboard.fmt import amt, esc

MAX_SHOWN = 8
_ID = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def _fold(text: str) -> str:
    from scraper.textparse import strip_diacritics
    return strip_diacritics(str(text or "")).lower()


def norm_url(url: str) -> str:
    """A link without its query, fragment, "www." and trailing slash, for
    comparing two links to one page."""
    p = urlsplit(str(url or "").strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, p.path.rstrip("/"), "", ""))


def is_link(query: str) -> bool:
    return bool(re.match(r"^https?://", query.strip(), re.I))


def find(query: str, rows: list[dict]) -> list[dict]:
    """The rows `query` names: by link, by id (whole or its first 6+
    characters), or by every word of it in the title, address or district
    (accents and case ignored)."""
    q = (query or "").strip()
    if not q:
        return []
    if is_link(q):
        want = norm_url(q)
        return [r for r in rows if r.get("url") and norm_url(r["url"]) == want]
    if _ID.match(q):
        hits = [r for r in rows if str(r.get("id") or "").startswith(q)]
        if hits:
            return hits
    words = _fold(q).split()
    return [r for r in rows
            if all(w in _fold(f"{r.get('title')} {r.get('address_raw')} {r.get('district')}")
                   for w in words)]


# ── Reading a flat no listing has yet ─────────────────────────────────────────
def _read_topreality(url: str) -> dict | None:
    from database.portal_runs import now_iso
    from scraper import topreality
    status, html = topreality._fetch(url)
    return topreality._build_listing_from_detail(url, html, now_iso()) if status == 200 else None


def _read_bezrealitky(url: str) -> dict | None:
    from scraper import bezrealitky
    from scraper._http import get
    flat = bezrealitky.flat_url(url)
    if not flat:
        return None
    r = get(flat, timeout=25)
    if r.status_code != 200:
        return None
    advert = bezrealitky.advert_from_html(r.text)
    return bezrealitky.listing_from_advert(advert, flat) if advert else None


READERS = {"topreality.sk": ("Topreality.sk", _read_topreality),
           "bezrealitky.cz": ("Bezrealitky.cz", _read_bezrealitky)}


def reader_for(url: str):
    """(portal name, reader) for a link one of READERS can read, else None."""
    host = (urlsplit(url.strip()).hostname or "").lower().removeprefix("www.")
    return READERS.get(host)


def read_now(url: str) -> str:
    """READ IT NOW: read the flat at `url` (a READERS portal's), store and
    score it. Returns what happened, in a sentence."""
    found = reader_for(url)
    if not found:
        return "That portal can't be read from a link alone."
    name, reader = found
    try:
        listing = reader(url)
    except Exception as e:
        return f"{name} couldn't be read ({type(e).__name__})."
    if not listing:
        return f"{name} didn't give a flat for sale on that page."
    from dashboard.listing_cache import clear_listing_cache
    from database import upsert_listing
    from modules.cashflow_runner import run_scoring
    upsert_listing(listing)
    run_scoring()
    clear_listing_cache()
    return f"Read from {name} and scored: {listing.get('title') or 'the flat'}."


def _read_clicked(url: str) -> None:
    st.session_state["find_said"] = read_now(url)


def _show(lid: str) -> None:
    st.session_state["find_open"] = None if st.session_state.get("find_open") == lid else lid


def render(v) -> None:
    """The box and what it finds."""
    q = st.text_input("Find a flat", key="find_q", label_visibility="collapsed",
                      placeholder="Find a flat: paste its portal link, its id or words of "
                                  "its title or street", icon=":material/search:")
    said = st.session_state.pop("find_said", None)
    if said:
        st.caption(said)
    if not q.strip():
        return
    from dashboard.listing_cache import load_active
    shown = {l.get("id"): l for l in v.data}
    every = {r.get("id"): r for r in load_active() + load_active(rejected=True)}
    hits = find(q, list(every.values()))
    if not hits:
        if is_link(q) and reader_for(q):
            name = reader_for(q)[0]
            st.info(f"No flat tracked from that link yet. It can be read from {name} now.")
            st.button("READ IT NOW", key="find_read", on_click=_read_clicked, args=(q.strip(),),
                      disabled=v.using_demo)
        elif is_link(q):
            st.info("No flat tracked from that link yet. Its portal is read every morning; "
                    "the flat appears then if it is among the pages the run reads.")
        else:
            st.info("No tracked flat matches.")
        return
    from dashboard.tabs.triage import render_summary
    st.markdown(f'<div class="muted">{len(hits)} FOUND'
                + (f" — THE FIRST {MAX_SHOWN}" if len(hits) > MAX_SHOWN else "") + "</div>",
                unsafe_allow_html=True)
    from dashboard.fmt import _tag_market
    for r in hits[:MAX_SHOWN]:
        l = shown.get(r.get("id"))
        r = _tag_market(dict(r))           # its currency, for a row the view doesn't hold
        with st.container(horizontal=True, vertical_alignment="center", key=f"findr_{r['id']}"):
            st.markdown(f'<div class="td-row"><div class="td-t">'
                        f'{esc((r.get("title") or r.get("district") or "—")[:80])}</div>'
                        f'<div class="td-m">{esc(amt(r, r.get("price_eur") or 0))}'
                        f' · {esc(r.get("district") or "—")}'
                        + ("" if l else " · hidden by the sidebar's filters")
                        + "</div></div>", unsafe_allow_html=True, width="stretch")
            if l:
                st.button("Close" if st.session_state.get("find_open") == r["id"] else "Show",
                          key=f"finds_{r['id']}", on_click=_show, args=(r["id"],))
        if l and st.session_state.get("find_open") == r["id"]:
            render_summary(l, v, ctx="find")
