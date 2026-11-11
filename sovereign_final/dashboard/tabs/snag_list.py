"""
dashboard/tabs/snag_list.py — ACTIVE SNAG LIST: a card per listing, GREEN
then YELLOW then WHITE, and the listings still waiting to be scored.
"""

import streamlit as st

from dashboard.cards import render_cards
from dashboard.fmt import amt, esc


def render_white_table(whites, v) -> None:
    """WHITE listings as one table, not cards. They are most of the listings
    and none is a deal, and a card each made every click slower; the triage
    table, WHAT-IF and DEAL PIPELINE still reach every one of them."""
    import pandas as pd
    rows = []
    for l in whites:
        surplus = l.get("surplus_sro") if v.show_sro else l.get("surplus_personal")
        disc = l.get("market_discount")
        rows.append({
            "Title":    (l.get("title") or l.get("district") or "—")[:60],
            "District": l.get("district") or "—",
            "Mkt":      "🇨🇿 CZ" if l.get("_market") == "cz" else "🇸🇰 SK",
            "Price":    v.in_view_cur(l, l.get("price_eur") or 0),
            "Size":     l.get("size_m2") or 0,
            # Blank without a benchmark: 0% would read as "at market".
            "Below%":   disc * 100 if disc is not None else None,
            "Surplus":  v.in_view_cur(l, surplus),
            "Stage":    (l.get("_stage") or {}).get("stage", ""),
            "URL":      l.get("url") or "",
        })
    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        height=min(420, 40 + 35 * len(rows)),
        column_config={
            "Price":   v.money_col("Price"),
            "Size":    st.column_config.NumberColumn(format="%d m²"),
            "Below%":  st.column_config.NumberColumn(
                format="%.0f%%", help="Asking price per m² below the regional median "
                                      "(negative = above it; blank = no benchmark)"),
            "Surplus": v.money_col("Surplus"),
            "URL":     st.column_config.LinkColumn(display_text="open ↗"),
        })
    st.caption("WHITE listings have no cards. Run one through ANALYSIS → WHAT-IF / TAX for "
               "the full breakdown, or track it from WORKFLOW → DEAL PIPELINE.")


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
            render_white_table(whites, v)
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
