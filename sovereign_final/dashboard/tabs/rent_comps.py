"""
dashboard/tabs/rent_comps.py — RENT COMPS: live rents per m² from real rental
listings, against the baseline table, per market.
"""

import pandas as pd
import streamlit as st


def _comps_cz():
    """The Czech comps: live Kč/m² from pronájem listings against the Deloitte
    Rent Index baseline (engine/rent_comps_cz, engine/rent_cz)."""
    from engine.rent_comps_cz import comps_table as comps_table_cz
    from engine.rent_cz import RENT_PER_M2_CZ, RENT_SOURCE
    from config import RENT_COMP_MIN_SAMPLE, RENT_COMP_ASKING_HAIRCUT
    st.markdown('<div class="muted">🇨🇿 LIVE RENT COMPS — Kč/m² FROM REAL PRONÁJEM LISTINGS '
                '(BAZOŠ, BEZREALITKY), BARE RENT, BLENDED WITH THE DELOITTE RENT INDEX WHERE IT '
                'HAS A FIGURE</div>', unsafe_allow_html=True)
    ct = comps_table_cz()
    if not ct:
        st.info("No Czech rental comps yet — the Czech pipeline's Rent comps step reads them. "
                "Until then a Czech rent comes from the baseline table below, and a place "
                "without a figure there isn't scored.")
    else:
        st.dataframe(pd.DataFrame(ct), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.0f")
                                    for c in ("Live median Kč/m²", "Baseline Kč/m²", "In use Kč/m²")})
        st.caption(f"A key needs {RENT_COMP_MIN_SAMPLE}+ rentals; its live median is cut "
                   f"{(1 - RENT_COMP_ASKING_HAIRCUT):.0%} (asking → achieved). A place with no "
                   f"Deloitte figure takes the live rate alone.")
    st.caption("Baseline Kč/m²: " + " · ".join(f"{k.title()} {v:.0f}"
                                                for k, v in RENT_PER_M2_CZ.items())
               + f" — {RENT_SOURCE['source']}")


def render(v) -> None:
    """The RENT COMPS tab."""
    data = v.data
    view_market = v.market
    if view_market != "cz":
        from engine.rent_comps import comps_table
        st.markdown('<div class="muted">LIVE RENT COMPS — €/m² FROM REAL PRENÁJOM LISTINGS, '
                    'NORMALISED TO A BARE-RENT UNFURNISHED 2-IZB FLAT AND BLENDED WITH THE '
                    'BASELINE TABLE BY SAMPLE SIZE</div>', unsafe_allow_html=True)
        ct = comps_table()
        if not ct:
            st.info("No rental comps yet — click 🏘️ RENT COMPS in the sidebar. Until then every "
                    "rent comes from config.RENT_PER_M2.")
        else:
            comps_df = pd.DataFrame(ct)
            comps_df["Δ vs baseline %"] = (comps_df["In use €/m²"] / comps_df["Baseline €/m²"] - 1) * 100
            st.dataframe(comps_df, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(format="%.2f")
                                        for c in ("Live median €/m²", "Baseline €/m²", "In use €/m²")}
                         | {"Δ vs baseline %": st.column_config.NumberColumn(format="%+.1f%%")})
            from config import RENT_COMP_MIN_SAMPLE, RENT_COMP_PRIOR_WEIGHT, RENT_COMP_ASKING_HAIRCUT
            st.caption(f"A district needs {RENT_COMP_MIN_SAMPLE}+ rentals; its live median is cut "
                       f"{(1 - RENT_COMP_ASKING_HAIRCUT):.0%} (asking → achieved) and weighted against "
                       f"the baseline as if the baseline were {RENT_COMP_PRIOR_WEIGHT} comps.")
    # Czechia's own comps: in its view, and in the combined one once there
    # are Czech listings.
    if view_market == "cz" or (view_market is None
                               and any(l.get("_market") == "cz" for l in data)):
        if view_market is None:
            st.markdown('<hr class="div">', unsafe_allow_html=True)
        _comps_cz()
