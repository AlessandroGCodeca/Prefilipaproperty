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
    from engine.rent_cz import RENT_PER_M2_CZ, RENT_SOURCE, key_label
    from config import RENT_COMP_MIN_SAMPLE, RENT_COMP_ASKING_HAIRCUT
    st.markdown('<div class="muted">🇨🇿 LIVE RENT COMPS — Kč/m² FROM REAL PRONÁJEM LISTINGS '
                '(BAZOŠ, BEZREALITKY), BARE RENT, BLENDED WITH THE DELOITTE RENT INDEX WHERE IT '
                'HAS A FIGURE</div>', unsafe_allow_html=True)
    ct = comps_table_cz()
    if not ct:
        st.info("No Czech rental comps yet — click 🏘️ RENT COMPS in the sidebar (the Czech "
                "pipeline's Rent comps step reads them too). "
                "Until then a Czech rent comes from the baseline table below, and a place "
                "without a figure there isn't scored.")
    else:
        st.dataframe(pd.DataFrame(ct), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="%.0f")
                                    for c in ("Live median Kč/m²", "Baseline Kč/m²", "In use Kč/m²")})
        st.caption(f"A key needs {RENT_COMP_MIN_SAMPLE}+ rentals; its live median is cut "
                   f"{(1 - RENT_COMP_ASKING_HAIRCUT):.0%} (asking → achieved). A place with no "
                   f"Deloitte figure takes the live rate alone.")
    _waiting_cz(ct)
    _district_prices_cz()
    st.caption("Baseline Kč/m²: " + " · ".join(f"{key_label(k)} {v:.0f}"
                                                for k, v in RENT_PER_M2_CZ.items())
               + f" — {RENT_SOURCE['source']}")


def _district_prices_cz() -> None:
    """Prague's and Brno's districts against their city, from the sale
    listings (engine/price_comps_cz): what scales ČSÚ's city figure."""
    from engine import price_comps_cz as pc
    rows = pc.factors_table()
    if not rows:
        return
    st.markdown('<div class="muted">🏙️ PRAGUE / BRNO DISTRICT PRICE LEVELS — EACH DISTRICT\'S '
                'MEDIAN ASKING Kč/m² AGAINST ITS WHOLE CITY\'S, SCALING ČSÚ\'S CITY FIGURE'
                '</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.0f")
                                for c in ("Median ask Kč/m²", "City median ask Kč/m²")}
                 | {"Factor": st.column_config.NumberColumn(format="%.2f")})
    st.caption(f"A factor needs {pc.MIN_DISTRICT_SAMPLE}+ listings in the district and "
               f"{pc.MIN_CITY_SAMPLE}+ in the city, and stays within "
               f"{pc.FACTOR_BOUNDS[0]}–{pc.FACTOR_BOUNDS[1]}; a district without one is judged "
               f"against its whole city's figure. Rebuilt on every scoring run.")


def waiting_rows(waiting: dict[str, int], comps: list[dict]) -> list[dict]:
    """The waiting towns as table rows, with the rental comps each has so far."""
    from engine.rent_cz import key_label
    have = {r["District key"]: r["Comps"] for r in comps}
    return [{"Town": key_label(k), "Listings waiting": n, "Rental comps so far": have.get(k, 0)}
            for k, n in waiting.items()]


def _waiting_cz(comps: list[dict]) -> None:
    """The Czech listings not scored for want of a rent, by town."""
    from config import RENT_COMP_MIN_SAMPLE
    from dashboard.listing_cache import waiting_for_rent
    waiting = waiting_for_rent("cz")
    if not waiting:
        return
    n = sum(waiting.values())
    st.markdown(f'<div class="muted">⏳ WAITING FOR A RENT FIGURE — {n} CZECH LISTING'
                f'{"S" if n != 1 else ""} IN {len(waiting)} TOWN{"S" if len(waiting) != 1 else ""}'
                f'</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(waiting_rows(waiting, comps)), hide_index=True, width="stretch")
    st.caption(f"These towns have no Deloitte Rent Index figure (engine/rent_cz.py), so a "
               f"listing there is scored only once {RENT_COMP_MIN_SAMPLE}+ rentals there give a "
               f"live rate. 🏘️ RENT COMPS reads the rentals and re-scores; the daily run does "
               f"it before scoring.")


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
