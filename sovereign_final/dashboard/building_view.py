"""
dashboard/building_view.py — the building and the flat's state on a card
(🏗 Building · renovation · flip), and the form for the building's facts in
DEAL PIPELINE (database/building, engine/building).
"""

from datetime import date

import streamlit as st

from dashboard.fmt import amt, esc


def known_facts(l: dict) -> tuple[dict, dict]:
    """(facts, where each came from): yours first, then the ad's text, then
    the listing's own fields."""
    from database import get_listing_description
    from database.building import get_building_facts
    from engine.building import parse_ad
    lid = l.get("id") or ""
    mine = get_building_facts(lid) if lid else {}
    ad = parse_ad(f"{l.get('title') or ''}\n{get_listing_description(lid) if lid else ''}")
    facts, src = {}, {}
    for key in ("construction", "year_built", "insulated", "heating"):
        for origin, value in (("you", mine.get(key)), ("ad", ad.get(key)),
                              ("listing", l.get(key) if key == "year_built" else None)):
            if value not in (None, ""):
                facts[key], src[key] = value, origin
                break
    if mine.get("hoa_monthly"):
        facts["hoa_monthly"], src["hoa_monthly"] = mine["hoa_monthly"], "you"
    for key in ("costs_monthly", "fund_monthly"):
        if ad.get(key):
            facts[key], src[key] = ad[key], "ad"
    return facts, src


def _row(label: str, value: str) -> str:
    return f'<div class="brow"><span class="l">{esc(label)}</span><span class="v">{value}</span></div>'


def render_building(l: dict, cz: bool) -> None:
    """The card's 🏗 toggle: the building's facts and risks, the renovation
    and heating estimates, and the flip scenario."""
    from engine.building import building_risks, flip, heating_monthly, renovation_cost
    lid = l.get("id") or ""
    if not st.toggle("🏗 Dům · rekonstrukce · flip" if cz else "🏗 Building · renovation · flip",
                     key=f"bld_{lid}"):
        return
    market = "cz" if cz else "sk"
    facts, src = known_facts(l)
    size = l.get("size_m2") or 0
    html = ""
    labels = {"construction": "Construction", "year_built": "Built", "insulated": "Insulated",
              "heating": "Heating", "hoa_monthly": "Owner's monthly fee (správa + fond)",
              "costs_monthly": "Monthly costs the ad quotes", "fund_monthly": "Fond opráv (ad)"}
    for key, label in labels.items():
        if key not in facts:
            continue
        v = facts[key]
        shown = ("yes" if v else "no") if key == "insulated" else \
            amt(l, v) + "/mo" if key in ("hoa_monthly", "costs_monthly", "fund_monthly") else esc(str(v))
        html += _row(label, f"{shown} <span class='muted'>({src[key]})</span>")
    if not html:
        html = _row("Building", "nothing known yet — the správca letter asks for it")
    if "hoa_monthly" not in facts:
        html += _row("Owner's monthly fee", f"{amt(l, l.get('hoa_monthly') or 0)}/mo "
                                            f"<span class='muted'>(estimated by size)</span>")
    cond = (l.get("condition") or "unknown").lower()
    reno = renovation_cost(size, cond, market)
    html += _row("Condition (ad)", esc(cond))
    html += _row("Renovation estimate", f"{amt(l, reno)}" + (" — none needed" if not reno else ""))
    heat = heating_monthly(size, l.get("energy_class"), market)
    html += _row(f"Heating, class {esc(l.get('energy_class') or '?')}", f"~{amt(l, heat)}/mo "
                 "<span class='muted'>(the tenant's while let)</span>")
    st.markdown(html, unsafe_allow_html=True)
    for risk in building_risks(facts, date.today().year):
        st.warning(risk)
    f = flip(l.get("price_eur") or 0, size, l.get("district") or "", cond, rooms=l.get("rooms"),
             market=market)
    if f:
        st.markdown(
            '<div class="muted" style="margin-top:6px">FLIP — buy, renovate, sell '
            f'({f.months} months; sale at the {esc(f.sale_note)})</div>'
            + _row("Buy + buying costs", amt(l, f.buy + f.buying_costs))
            + _row("Renovation + holding", amt(l, f.renovation + f.holding))
            + _row("Sale − selling costs", amt(l, f.sale_price - f.selling_costs))
            + _row("Tax on the gain", amt(l, f.tax))
            + _row("Profit · on your cash", f"<b>{amt(l, f.profit)}</b> · {f.roi * 100:+.0f} % "
                   f"of {amt(l, f.cash_in)}"),
            unsafe_allow_html=True)
    st.caption("Estimates for a first look: a contractor's quote, the energy certificate and the "
               "správca's figures replace them (DEAL PIPELINE → 🏢 Building facts).")


def render_facts_form(listing: dict, disabled: bool = False) -> None:
    """DEAL PIPELINE: the building's facts as you learned them. The real fee
    replaces the estimate in the score."""
    from database.building import CONSTRUCTIONS, HEATING, get_building_facts, set_building_facts
    lid = listing.get("id")
    if not lid:
        return
    have = get_building_facts(lid)
    st.markdown('<div class="muted" style="margin-top:10px">🏢 BUILDING FACTS — from the správca, '
                'the viewing and the energy certificate. The fee replaces the estimate in the '
                'score.</div>', unsafe_allow_html=True)
    with st.form(f"bf_form_{lid}", border=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cons = st.selectbox("Construction", CONSTRUCTIONS,
                                index=CONSTRUCTIONS.index(have.get("construction") or "")
                                if (have.get("construction") or "") in CONSTRUCTIONS else 0,
                                key=f"bf_cons_{lid}", disabled=disabled)
            year = st.number_input("Year built", min_value=0, max_value=2100,
                                   value=int(have.get("year_built") or listing.get("year_built") or 0),
                                   step=1, key=f"bf_year_{lid}", disabled=disabled,
                                   help="0: unknown")
        with c2:
            ins = st.selectbox("Insulated (zateplený)", ("unknown", "yes", "no"),
                               index={None: 0, 1: 1, 0: 2}.get(have.get("insulated"), 0),
                               key=f"bf_ins_{lid}", disabled=disabled)
            heat = st.selectbox("Heating", HEATING,
                                index=HEATING.index(have.get("heating") or "")
                                if (have.get("heating") or "") in HEATING else 0,
                                key=f"bf_heat_{lid}", disabled=disabled)
        with c3:
            hoa = st.number_input("Owner's monthly fee (správa + fond opráv)", min_value=0.0,
                                  value=float(have.get("hoa_monthly") or 0.0), step=5.0,
                                  key=f"bf_hoa_{lid}", disabled=disabled,
                                  help="Without the energy advances the tenant pays. 0: unknown.")
            notes = st.text_input("Notes", value=have.get("notes") or "", key=f"bf_notes_{lid}",
                                  disabled=disabled, placeholder="lift 2019, roof 2010, loans…")
        if st.form_submit_button("💾 SAVE BUILDING FACTS", disabled=disabled):
            set_building_facts(lid, {"construction": cons, "year_built": year or None,
                                     "insulated": {"yes": 1, "no": 0}.get(ins),
                                     "heating": heat, "hoa_monthly": hoa or None, "notes": notes})
            from modules.cashflow_runner import run_scoring
            run_scoring(market=listing.get("market") or listing.get("_market") or "sk")
            from dashboard.listing_cache import clear_listing_cache
            clear_listing_cache()
            st.success("Saved; the flat was re-scored with them.")


def render_short_let(l: dict, cz: bool) -> None:
    """The card's 🛏 toggle, where short lets are a market (engine/short_let)."""
    from engine.short_let import area_for, scenario
    market = "cz" if cz else "sk"
    lid = l.get("id") or ""
    if not area_for(l.get("district") or "", market):
        return
    if not st.toggle("🛏 Krátkodobý pronájem" if cz else "🛏 Short let (Airbnb)", key=f"str_{lid}"):
        return
    manager = st.checkbox("Through a manager (20 %)", key=f"strm_{lid}")
    s = scenario({**l, "market": market}, manager=manager)
    if not s:
        return
    st.markdown(
        f'<div class="muted">{esc(s.area)} · {amt(l, s.adr)} a night · {s.occupancy:.0%} of '
        f'nights booked ({s.nights} a year) — assumptions, not market data</div>'
        + _row("Bookings a month", amt(l, s.gross_monthly))
        + _row("Platform · cleaning · local tax", f"{amt(l, s.platform_monthly)} · "
               f"{amt(l, s.cleaning_monthly)} · {amt(l, s.local_tax_monthly)}")
        + (_row("Manager", amt(l, s.manager_monthly)) if s.manager_monthly else "")
        + _row("Utilities · furnishing (5 years)", f"{amt(l, s.utilities_monthly)} · "
               f"{amt(l, s.furnishing_monthly)}")
        + _row("Building fee + property tax · loan", f"{amt(l, s.building_monthly)} · "
               f"{amt(l, s.mortgage_monthly)}")
        + _row("Income tax", amt(l, s.tax_monthly))
        + _row("Surplus a month · long let", f"<b>{amt(l, s.surplus_monthly)}</b> · "
               f"{amt(l, s.long_let_surplus)}")
        + _row("Beats the long let from", f"{s.break_even_occupancy:.0%} of nights booked"),
        unsafe_allow_html=True)
    st.caption("Replace the rate and occupancy with real figures (Inside Airbnb, AirDNA, a local "
               "manager) in .env: SHORT_LET_<AREA>_ADR / _OCCUPANCY. Check the town's rules "
               "(registration, night caps, tax per guest-night) before buying for this.")
