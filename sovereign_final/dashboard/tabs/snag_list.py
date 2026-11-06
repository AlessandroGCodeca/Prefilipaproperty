"""
dashboard/tabs/snag_list.py — ACTIVE SNAG LIST: a card per listing, GREEN
then YELLOW then WHITE, and the listings still waiting to be scored.
"""

import streamlit as st

from dashboard.cards import render_cards
from dashboard.fmt import amt, esc


def render(v) -> None:
    """The ACTIVE SNAG LIST tab."""
    _cf_negative = v.cf_negative
    greens = v.greens
    hidden_note = v.hidden_note
    n_hidden = v.n_hidden
    n_scored_loaded = v.n_scored_loaded
    pending = v.pending
    unscored_note = v.unscored_note
    whites = v.whites
    yellows = v.yellows
    if not greens and not yellows and not whites and not pending:
        st.info(hidden_note() if n_hidden else
                "No listings in DB yet — click ▶ RUN EVERYTHING (or a portal under "
                "📅 DAILY RUN) in the sidebar to scrape.")
    else:
        if not greens and not yellows and not whites and pending:
            st.info(hidden_note("scored listings") if n_scored_loaded else unscored_note())
        def _neg_note(group):
            # The class is price vs market; say how many still lose money.
            n = sum(1 for l in group if _cf_negative(l))
            return f" · ⛔ {n} CASH-FLOW NEGATIVE" if n else ""
        if greens:
            st.markdown(f'<div class="muted" style="margin:14px 0 8px">🟢 GREEN — ≥20% BELOW MARKET ({len(greens)}){_neg_note(greens)}</div>', unsafe_allow_html=True)
            render_cards(greens, "green", v)
        if yellows:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">🟡 YELLOW — 10–20% BELOW MARKET ({len(yellows)}){_neg_note(yellows)}</div>', unsafe_allow_html=True)
            render_cards(yellows, "yellow", v)
        if whites:
            st.markdown(f'<div class="muted" style="margin:18px 0 8px">⚪ WHITE — AT MARKET OR NO BENCHMARK ({len(whites)})</div>', unsafe_allow_html=True)
            render_cards(whites, "white", v)
        if pending:
            pend = st.expander(f"⏳ PENDING SCORING ({len(pending)} listings scraped, not yet classified)",
                               key="pending_list", on_change="rerun")
            if pend.open:
                rows = ""
                for l in pending:
                    title = l.get("title") or l.get("address_raw") or l.get("district") or "—"
                    price = l.get("price_eur") or 0
                    size  = l.get("size_m2") or 0
                    src   = (l.get("source") or "").upper()
                    rows += f'<div class="brow"><span class="l">{esc(title[:60])}</span><span class="v">{amt(l, price)} · {size:.0f}m² · {esc(src)}</span></div>'
                pend.markdown(rows, unsafe_allow_html=True)
