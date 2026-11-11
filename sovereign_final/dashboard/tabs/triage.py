"""
dashboard/tabs/triage.py — TRIAGE TABLE: every scored listing in one flat,
sortable table, to spot the best surplus or yield in one scan instead of
opening each card.
"""

import streamlit as st

import markets

from dashboard.fmt import _features_label, _lv_state, money


def render(v) -> None:
    """The TRIAGE TABLE tab."""
    _cf_negative = v.cf_negative
    greens = v.greens
    hidden_note = v.hidden_note
    in_view_cur = v.in_view_cur
    money_col = v.money_col
    n_hidden = v.n_hidden
    n_loaded = v.n_loaded
    n_scored_loaded = v.n_scored_loaded
    show_sro = v.show_sro
    unscored_note = v.unscored_note
    view_market = v.market
    whites = v.whites
    yellows = v.yellows
    import pandas as pd

    scored = greens + yellows + whites
    if not scored:
        if n_loaded and not n_scored_loaded:
            st.info(unscored_note())
        elif n_hidden:
            st.info(hidden_note("scored listings"))
        else:
            st.info("No scored listings yet — click ▶ RUN EVERYTHING in the sidebar "
                    "(or a portal under 📅 DAILY RUN, then 💰 CASHFLOW SCORE) to populate "
                    "this view.")
    else:
        from engine.financial import compute_deal_score
        emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪", "PENDING": "⏳"}
        triage_rows = []
        for l in scored:
            cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
            surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
            score, grade = compute_deal_score(l)
            price = l.get("price_eur") or 0
            my = l.get("max_price_yellow")
            v = lambda x, _l=l: in_view_cur(_l, x)     # noqa: E731 — the view's currency
            irr_v = l.get("irr_sro") if show_sro else l.get("irr_personal")
            ph = l.get("_ph") or {}
            vibe = l.get("_vibe")
            disc = l.get("market_discount")
            triage_rows.append({
                "": emoji_map.get(cls, ""),
                "Grade":    grade,
                "Score":    score,
                "Title":    (l.get("title") or l.get("district") or "—")[:50],
                "District": l.get("district") or "—",
                "Stage":    (l.get("_stage") or {}).get("stage", ""),
                "Mkt":      "🇨🇿 CZ" if l.get("_market") == "cz" else "🇸🇰 SK",
                "Price":    v(price),
                "Native":   money(l, price),
                "Max 🟡":   v(my),
                "Max 🟢":   v(l.get("max_price_green")),
                # The card's "Max offer 🟡 … vs ask" figure: the move from the
                # asking price to the max YELLOW price.
                "To 🟡":    (my / price - 1) * 100 if my and price else None,
                # Blank without a benchmark: 0% would read as "at market".
                "Below%":   disc * 100 if disc is not None else None,
                "Size":     l.get("size_m2")              or 0,
                "Rent":     v(l.get("estimated_rent_eur")   or 0),
                "Surplus":  v(surplus if surplus is not None else 0),
                "CF":       "⛔" if _cf_negative(l) else ("✅" if surplus is not None else ""),
                "+2pp":     v(l.get("stress_surplus_sro")),
                "Gross%":   (l.get("gross_yield")         or 0) * 100,
                "Cap%":     (l.get("cap_rate")            or 0) * 100,
                "IRR%":     irr_v * 100 if irr_v is not None else None,
                "Yield":    (l.get("net_rental_yield")    or 0) * 100,
                "Days":     l.get("_dom"),
                "ΔPrice":   ph["change_pct"] * 100 if ph.get("change_pct") is not None else None,
                "Portals":  l.get("_portals", 1),
                "Features": _features_label(l),
                "Vibe":     vibe[0] if vibe else None,
                "LV":       _lv_state(l)[0].replace(" LV", "")
                            + (f" · {l['lv_risk_level']}" if l.get("lv_risk_level") else ""),
                "Src":      (l.get("source") or "").upper()[:5],
                "URL":      l.get("url") or "",
            })
        df = pd.DataFrame(triage_rows).sort_values(
            ["Score", "Below%"], ascending=[False, False]
        )
        # The native price only says something when the money columns are
        # converted, i.e. with both markets on the page.
        if view_market is not None or (df["Mkt"] == "🇸🇰 SK").all():
            df = df.drop(columns="Native")
        # A column every row leaves empty (no listing has a benchmark yet) is
        # dropped: a number column shows each missing value as "None".
        df = df.drop(columns=[c for c in ("Max 🟡", "Max 🟢", "To 🟡", "Below%")
                              if df[c].isna().all()])
        st.markdown(
            f'<div class="muted">{len(df)} scored listings — sorted by composite deal '
            f'grade (yield + discount to market + location + energy + condition + '
            f'risk), then discount. Click any header to re-sort.</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            height=min(600, 40 + 35 * len(df)),
            column_config={
                "Score":   st.column_config.NumberColumn(format="%d", help="0–100 composite deal score"),
                "Stage":   st.column_config.TextColumn(width="medium"),
                "Mkt":     st.column_config.TextColumn(help="Market: Slovakia or Czechia"),
                "Price":   money_col("Price"),
                "Native":  st.column_config.TextColumn(help=f"In the listing's own currency · {markets.fx_note()}"),
                "Max 🟡":  money_col("Max 🟡", help="Highest price that still scores YELLOW"),
                "Max 🟢":  money_col("Max 🟢", help="Highest price that scores GREEN"),
                "To 🟡":   st.column_config.NumberColumn(format="%+.1f%%", help="Change from the asking price to the max YELLOW price, as on the card — the cut you need to negotiate (positive = already inside)"),
                "Size":    st.column_config.NumberColumn(format="%d m²"),
                "Rent":    money_col("Rent"),
                "Surplus": money_col("Surplus"),
                "+2pp":    money_col("+2pp", help="s.r.o. surplus at the mortgage rate + 2 pp"),
                "Below%":  st.column_config.NumberColumn(
                    format="%.0f%%", help="Asking €/m² below the regional median "
                                          "(negative = above it; blank = no benchmark)"),
                "Gross%":  st.column_config.NumberColumn(format="%.2f%%"),
                "Cap%":    st.column_config.NumberColumn(format="%.2f%%"),
                "IRR%":    st.column_config.NumberColumn(format="%.1f%%", help="10-year IRR incl. appreciation, exit costs and tax on the gain"),
                "Yield":   st.column_config.NumberColumn(format="%.2f%%", help="Net yield: the yearly cash flow over the price, under the structure recommended for the listing"),
                "CF":      st.column_config.TextColumn(help="⛔ = monthly surplus below CASHFLOW_MIN_SURPLUS: the class is price vs market, not income"),
                "Days":    st.column_config.NumberColumn(format="%d", help="Days tracked: since this dashboard first saw the flat on any portal (not the portal's posting date)"),
                "ΔPrice":  st.column_config.NumberColumn(format="%+.1f%%", help="Price change since first seen"),
                "Portals": st.column_config.NumberColumn(format="%d", help="Portals the same flat is listed on"),
                "Vibe":    st.column_config.NumberColumn(format="%d/10"),
                "URL":     st.column_config.LinkColumn(display_text="open ↗"),
            },
        )
