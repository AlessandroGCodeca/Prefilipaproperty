"""
dashboard/tabs/compare.py — COMPARE: two to four listings side by side, one
column each — price, price per m², rent and yield, both ownership structures,
the risks and the title deed.
"""

import pandas as pd
import streamlit as st

from dashboard.fmt import (
    _lv_state, _pct_or_dash, _risk_label, amt, esc, last_seen_label, sgn,
)

MAX_COMPARED = 4


def _label(l) -> str:
    return (f"{(l.get('title') or l.get('district') or '?')[:48]} — "
            f"{amt(l, l.get('price_eur') or 0)} [{(l.get('id') or '')[:6]}]")


def comparison_rows(l) -> dict:
    """One listing's column of the comparison: {row label: text}. Money in
    the listing's own currency, as on its card."""
    price, size = l.get("price_eur") or 0, l.get("size_m2") or 0
    disc = l.get("market_discount")
    cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
    best = "s.r.o." if (l.get("optimal_structure") or "").upper() == "SRO" else "personal"
    saving = l.get("annual_sro_saving")
    my = l.get("max_price_yellow")
    ph = l.get("_ph") or {}
    stage = (l.get("_stage") or {}).get("stage")
    return {
        "Market":               "🇨🇿 Czechia" if l.get("_market") == "cz" else "🇸🇰 Slovakia",
        "District":             l.get("district") or "—",
        "Class":                {"GREEN": "🟢 GREEN", "YELLOW": "🟡 YELLOW",
                                 "WHITE": "⚪ WHITE"}.get(cls, "⏳ not scored"),
        "Price":                amt(l, price) if price else "—",
        "Size":                 f"{size:.0f} m²" if size else "—",
        "Price per m²":         amt(l, price / size) if price and size else "—",
        "Regional median / m²": amt(l, l["regional_median_m2"]) if l.get("regional_median_m2")
                                else "—",
        "Against the market":   (f"{abs(disc):.0%} {'below' if disc >= 0 else 'above'}"
                                 if disc is not None else "— no benchmark"),
        "Max offer 🟡":         (amt(l, my) + (f" ({my / price - 1:+.1%} vs ask)" if price else ""))
                                if my else "—",
        "Rent / month":         amt(l, l.get("estimated_rent_eur")) if l.get("estimated_rent_eur")
                                else "—",
        "Gross yield":          _pct_or_dash(l.get("gross_yield"), 2),
        "Cap rate":             _pct_or_dash(l.get("cap_rate"), 2),
        "Surplus — personal":   sgn(l, l.get("surplus_personal")),
        "Surplus — s.r.o.":     sgn(l, l.get("surplus_sro")),
        "Better structure":     (best + (f" (s.r.o. {amt(l, saving)}/yr vs personal)"
                                         if saving is not None else ""))
                                if l.get("optimal_structure") else "—",
        f"Cash-on-cash ({best})": _pct_or_dash(l.get("cash_on_cash"), 2),
        "IRR 10y — personal":   _pct_or_dash(l.get("irr_personal")),
        "IRR 10y — s.r.o.":     _pct_or_dash(l.get("irr_sro")),
        "Cash in — personal":   amt(l, l.get("total_cash_invested")) if l.get("total_cash_invested")
                                else "—",
        "At rate +2 pp (s.r.o.)": sgn(l, l.get("stress_surplus_sro")),
        "Title deed (LV)":      _lv_state(l)[0],
        "LV soft flags":        (l.get("lv_soft_flags") or "—")[:160],
        "Location":             (f"{l.get('location_tier')} · {l.get('location_score'):.0f}/100"
                                 if l.get("location_score") is not None else "— not scored"),
        "Noise":                _risk_label(l.get("noise_flag"), "⚠️ ≥65 dB source"),
        "Flood (Q100)":         _risk_label(l.get("flood_zone"), "⚠️ In flood area"),
        "Construction":         _risk_label(l.get("construction_risk"), "⚠️ Site nearby"),
        "Condition":            l.get("condition") or "—",
        "Energy class":         (l.get("energy_class") or "—").replace("UNKNOWN", "—"),
        "Days tracked":         str(l["_dom"]) if l.get("_dom") is not None else "—",
        "Price change":         f"{ph['change_pct']:+.1%}" if ph.get("change_pct") else "—",
        "Portals":              str(l.get("_portals") or 1),
        "Last seen":            last_seen_label(l).replace("last seen ", "") or "—",
        "Deal stage":           stage or "—",
    }


def comparison_table(listings) -> pd.DataFrame:
    """Rows = what is compared, one column per listing. A label two listings
    share (its "Cash-on-cash (personal)" against another's "(s.r.o.)") gets
    its own row each, blank for the other."""
    cols = {}
    for l in listings:
        name = f"{(l.get('title') or l.get('district') or '?')[:34]} [{(l.get('id') or '')[:6]}]"
        cols[name] = comparison_rows(l)
    order = list(dict.fromkeys(k for rows in cols.values() for k in rows))
    return pd.DataFrame({"": order, **{name: [rows.get(k, "") for k in order]
                                       for name, rows in cols.items()}})


def render(v) -> None:
    """The COMPARE tab."""
    st.markdown('<div class="muted">COMPARE — TWO TO FOUR LISTINGS SIDE BY SIDE. Money in each '
                "listing's own currency; returns are the recommended structure's.</div>",
                unsafe_allow_html=True)
    # Scored listings only: an unscored one has nothing to compare.
    options = {_label(l): l for l in v.greens + v.yellows + v.whites}
    if len(options) < 2:
        st.info("Nothing to compare yet — it takes two scored listings on the page.")
        return
    # A keyed multiselect keeps values that are no longer options (a listing
    # the filters now hide, or one gone from the market).
    st.session_state["cmp_pick"] = [o for o in st.session_state.get("cmp_pick", [])
                                    if o in options]
    picked = st.multiselect(
        "Listings", list(options), key="cmp_pick", max_selections=MAX_COMPARED,
        placeholder="Pick 2 to 4 listings — type to search by title, price or id",
        label_visibility="collapsed")
    if len(picked) < 2:
        st.caption("Pick at least two listings. The six-character id in brackets is the one "
                   "shown on the other tabs' pickers.")
        return
    chosen = [options[p] for p in picked]
    df = comparison_table(chosen)
    st.dataframe(df, hide_index=True, width="stretch", height=38 + 35 * len(df),
                 column_config={"": st.column_config.TextColumn(pinned=True),
                                **{c: st.column_config.TextColumn(width="medium")
                                   for c in df.columns[1:]}})
    st.markdown('<div class="muted">' + " · ".join(
        f'<a href="{esc(l.get("url") or "")}" target="_blank">'
        f'{esc((l.get("title") or l.get("district") or "?")[:34])} ↗</a>'
        for l in chosen if l.get("url")) + "</div>", unsafe_allow_html=True)
