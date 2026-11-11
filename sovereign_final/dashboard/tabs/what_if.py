"""
dashboard/tabs/what_if.py — WHAT-IF / TAX: re-run any listing, or a property
typed in, with your own price, financing and rent.
"""

import pandas as pd
import streamlit as st

import markets

from dashboard.fmt import _rent_fallback, amt, fe, money, sgn


def render(v) -> None:
    """The what-if calculator, in the picked listing's market (or, for a
    custom property, the market selected at the top; Slovakia for all)."""
    data = v.data
    view_market = v.market
    from engine.financial import (
        analyse, default_ltv, max_offer_price, project_irr, get_rent_estimate,
        base_rent_rate,
    )
    from engine.rent_comps import load_live_rates
    from config import HOLD_YEARS
    st.markdown('<div class="muted">WHAT-IF — RE-RUN ANY DEAL WITH YOUR OWN FINANCING, '
                'RENT AND HOLD ASSUMPTIONS · PERSONAL vs s.r.o.</div>', unsafe_allow_html=True)

    opts = {"✏️ Custom property": None}
    opts.update({f"{l.get('title') or l.get('district') or '?'} — {amt(l, l.get('price_eur') or 0)}"
                 f" [{(l.get('id') or '')[:6]}]": l for l in data})
    pick = opts[st.selectbox("Property", list(opts.keys()), key="wi_pick")]
    wm = markets.of_row(pick) if pick else (view_market or "sk")
    sk = wm == "sk"
    prof = markets.get(wm)
    mk = {} if sk else {"market": wm}
    sfx = "" if sk else f"_{wm}"           # a market's own widget state
    cur = {"_cur": prof.currency}
    sym = prof.currency_symbol
    if sk:
        from config import (
            MORTGAGE_RATE_PA as base_rate, LOAN_TERM_YEARS as base_term,
            LTV_RATIO as base_ltv, LTV_RATIO_INVESTOR as inv_ltv,
            APPRECIATION_RATE as base_app, RENT_GROWTH_RATE as base_rg,
            EXIT_COST_RATE as base_exit, SRO_RATE_PREMIUM_PP as base_prem,
            SRO_LTV_RATIO as base_sro_ltv, SRO_ANNUAL_RUNNING_COST as base_sro_cost,
        )
    else:
        base_rate, base_term = prof.mortgage_rate_pa, prof.loan_term_years
        base_ltv, inv_ltv = prof.ltv_ratio, prof.ltv_ratio_investor
        base_app, base_rg, base_exit = (prof.appreciation_rate, prof.rent_growth_rate,
                                        prof.exit_cost_rate)
        base_prem, base_sro_ltv, base_sro_cost = (prof.sro_rate_premium_pp, prof.sro_ltv_ratio,
                                                  prof.sro_annual_running_cost)
        if None in (base_rate, base_term, base_ltv, inv_ltv, base_app, base_rg, base_exit,
                    base_prem, base_sro_ltv, base_sro_cost):
            st.info(f"{prof.name}: the lending, tax and cost figures are not in markets.py "
                    f"yet, so there is nothing to calculate.")
            return
    live_rates = load_live_rates(**mk)
    # Widget keys carry the pick so choosing another listing reloads its values.
    pk = (pick or {}).get("id") or "custom"
    # A Slovak price is in euros (up to €5M); a Czech one in crowns.
    p_min, p_max, p_step, p_default = ((10_000, 5_000_000, 1_000, 120_000) if sk else
                                       (100_000, 200_000_000, 10_000, 2_900_000))

    w1, w2, w3 = st.columns(3)
    with w1:
        st.markdown("**PROPERTY**")
        # Only a custom property starts from the example price. A listing
        # scraped without one (price 0, awaiting its detail page) starts
        # blank: the example would show a class, cash flow and cap rate the
        # listing never had.
        no_price = bool(pick) and (pick.get("price_eur") or 0) <= 0
        wi_price = st.number_input(f"Price {sym}", p_min, p_max,
                                   None if no_price else
                                   min(max(int((pick or {}).get("price_eur") or p_default), p_min), p_max),
                                   p_step, key=f"wi_price_{pk}{sfx}")
        if no_price:
            st.caption("This listing has no price — enter one to run the numbers.")
        wi_size = st.number_input("Size m²", 10.0, 500.0,
                                  min(max(float((pick or {}).get("size_m2") or 60.0), 10.0), 500.0),
                                  1.0, key=f"wi_size_{pk}")
        # Only a custom property starts from an example district. A listing
        # with none stays blank: borrowing Bratislava II's median and rent
        # would show a class and a max offer the listing never had.
        wi_district = st.text_input(
            "District", (pick.get("district") or "") if pick else
            ("Bratislava II" if sk else "Praha 2"), key=f"wi_dist_{pk}{sfx}")
        if pick and not (pick.get("district") or "").strip():
            st.caption("This listing has no district — enter one to benchmark it.")
        wi_rooms = st.number_input("Rooms (0 = unknown)", 0, 6,
                                   min(int((pick or {}).get("rooms") or 0), 6),
                                   key=f"wi_rooms_{pk}")
    try:
        est_rent = get_rent_estimate(wi_district, wi_size, wi_rooms or None,
                                     (pick or {}).get("has_parking"), (pick or {}).get("furnished"),
                                     (pick or {}).get("has_balcony"), rates=live_rates, **mk)
        rate_used, rent_key, rent_src = base_rent_rate(wi_district, live_rates, **mk)
    except (LookupError, TypeError):
        # No rent figure for this market and place: the user types one —
        # nothing was estimated, so no estimate or fallback is captioned.
        est_rent, rate_used, rent_key, rent_src = 0.0, 0.0, None, None
    regulator = (prof.lending_rules.get("regulator") or "NBS") if not sk else "NBS"
    with w2:
        st.markdown("**FINANCING**")
        investor = st.toggle(f"3rd+ property ({regulator} {inv_ltv:.0%} LTV cap)",
                             value=default_ltv(**mk) < base_ltv, key=f"wi_inv{sfx}",
                             help=("From 1 Oct 2026 banks may lend at most 70% on a 3rd-and-"
                                   "subsequent residential property." if sk else
                                   prof.lending_rules.get("investor_note")))
        cap = inv_ltv if investor else base_ltv
        wi_ltv = st.slider("LTV %", 0, 90, int(cap * 100), 5, key=f"wi_ltv_{investor}{sfx}") / 100
        if wi_ltv > cap + 1e-9:
            st.warning(f"Above the {cap:.0%} {regulator} cap for this purchase — a bank won't lend this.")
        wi_rate = st.slider("Mortgage rate %", 1.0, 9.0, base_rate * 100, 0.1,
                            key=f"wi_rate{sfx}") / 100
        wi_term = st.slider("Term (years)", 5, 30, base_term, 1, key=f"wi_term{sfx}")
        wi_sro_prem = st.slider("s.r.o. loan: rate premium (pp)", 0.0, 4.0,
                                base_prem * 100, 0.1, key=f"wi_sro_prem{sfx}",
                                help="A company borrows on commercial terms, above the "
                                     "hypotéka rate. Use a bank's quote.") / 100
        wi_sro_ltv = st.slider("s.r.o. loan: max LTV %", 0, 90, int(round(base_sro_ltv * 100)),
                               5, key=f"wi_sro_ltv{sfx}") / 100
        wi_sro_cost = st.number_input(f"s.r.o. running cost {sym}/yr", 0,
                                      20_000 if sk else 500_000,
                                      int(base_sro_cost), 100 if sk else 1_000,
                                      key=f"wi_sro_cost{sfx}",
                                      help="Bookkeeping, annual accounts, registered office, "
                                           "bank fees — paid every year the company exists.")
    with w3:
        st.markdown("**RENT & HOLD**")
        if rent_src:
            st.caption(f"Estimate {amt(cur, est_rent, '/mo')} · {rate_used:.2f} {sym}/m² for "
                       f"'{rent_key}' ({'live comps' if rent_src == 'live' else 'baseline table'})")
        _fb = _rent_fallback({"rent_key": rent_key, "market": wm})
        if _fb:
            st.caption("⚠ " + ("National default rent — this town is in no rent table."
                               if _fb == "default" else
                               "Kraj-level rent — no figure for this town itself."))
        wi_rent = st.number_input(f"Rent {sym}/mo (override)", 0, 20_000 if sk else 500_000,
                                  int(round(est_rent)), 10 if sk else 100,
                                  key=f"wi_rent_{pk}_{wi_district}_{wi_size}_{wi_rooms}{sfx}")
        wi_hold = st.slider("Hold (years)", 1, 30, HOLD_YEARS, key="wi_hold")
        wi_app = st.slider("Price growth % p.a.", -3.0, 10.0, base_app * 100, 0.5,
                           key=f"wi_app{sfx}") / 100
        wi_rg = st.slider("Rent growth % p.a.", -3.0, 10.0, base_rg * 100, 0.5,
                          key=f"wi_rg{sfx}") / 100
        wi_exit = st.slider("Exit costs %", 0.0, 8.0, base_exit * 100, 0.5,
                            key=f"wi_exit{sfx}") / 100
    if wi_price is None:
        st.info("Enter a price to run the numbers.")
        return
    if not wi_rent and not est_rent:
        st.info("No rent estimate for this place — type the rent in to run the numbers.")
        return

    sro_kw = dict(sro_ltv=wi_sro_ltv, sro_rate_premium=wi_sro_prem,
                  sro_running_cost=float(wi_sro_cost))
    fin = dict(rent_override=wi_rent or None, ltv=wi_ltv, rate=wi_rate, term_years=wi_term,
               rooms=wi_rooms or None, hold_years=wi_hold, **sro_kw, **mk)
    r = analyse(wi_price, wi_size, wi_district, **fin)
    # The rate shock and the cash flows show the structure recommended.
    best_sro = r.optimal_structure == "SRO"
    best_tag = "s.r.o." if best_sro else "personal"
    irr_kw = dict(rent=r.estimated_rent, ltv=wi_ltv, rate=wi_rate, term_years=wi_term,
                  hold_years=wi_hold, appreciation=wi_app, rent_growth=wi_rg,
                  exit_cost_rate=wi_exit, **sro_kw, **mk)
    irr_p = project_irr(wi_price, wi_size, wi_district, structure="PERSONAL", **irr_kw)
    irr_s = project_irr(wi_price, wi_size, wi_district, structure="SRO", **irr_kw)
    # The class is the discount to the regional median, so the max offer
    # depends on size and district only — financing moves cashflow, not class.
    max_y = max_offer_price(wi_size, wi_district, "YELLOW", rooms=wi_rooms or None, **mk)
    max_g = max_offer_price(wi_size, wi_district, "GREEN", rooms=wi_rooms or None, **mk)

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    # market_discount is positive BELOW the median: "+25% vs the median" read
    # as 25% above it.
    from engine.regional_prices import benchmark_note
    # The class is price vs market; the delta is what it earns a month under
    # the better structure (red and pointing down when it costs money).
    k1.metric("Class", r.classification,
              delta=f"{sgn(cur, max(r.surplus_personal, r.surplus_sro), '')} cash flow",
              help=(f"{abs(r.market_discount):.0%} "
                    f"{'below' if r.market_discount >= 0 else 'above'} the regional median "
                    f"{sym}/m² ({benchmark_note(wi_district, wi_rooms or None, **mk)}) · s.r.o. "
                    f"self-funding {r.ratio_sro:.0%}")
              if r.market_discount is not None else "No regional median for this district.")
    k2.metric("Best structure", "s.r.o." if r.optimal_structure == "SRO" else "Personal",
              delta=(f"{fe(r.annual_sro_saving, suffix='/yr', signed=True)}" if sk else
                     money(cur, r.annual_sro_saving, "/yr", signed=True))
              + " s.r.o. vs personal")
    k3.metric("Cash in", amt(cur, r.total_cash_invested),
              help=f"Personal; the s.r.o. puts in {amt(cur, r.total_cash_invested_sro)} "
                   f"({r.sro_ltv:.0%} LTV).")
    k4.metric("Cap rate", f"{r.cap_rate:.2%}")
    k5.metric("Max offer 🟡", amt(cur, max_y) if max_y else "—",
              delta=f"{max_y / wi_price - 1:+.1%} vs price" if max_y else None)
    k6.metric("Max offer 🟢", amt(cur, max_g) if max_g else "—")

    rows = [
        ("Rent", r.estimated_rent, r.estimated_rent),
        ("Mortgage (interest + principal)", r.mortgage_monthly, r.mortgage_monthly_sro),
        ("HOA + property tax" if sk else "SVJ + property tax",
         r.hoa_monthly + r.property_tax_monthly, r.hoa_monthly + r.property_tax_monthly),
        ("Vacancy + reserve + mgmt", r.vacancy_cost + r.maintenance_monthly + r.management_monthly,
         r.vacancy_cost + r.maintenance_monthly + r.management_monthly),
        ("s.r.o. running cost", 0.0, r.sro_running_cost_monthly),
        ("Income tax", r.income_tax_personal, r.income_tax_sro),
        ("Total costs", r.total_costs_personal, r.total_costs_sro),
        ("Net surplus", r.surplus_personal, r.surplus_sro),
    ]
    head = f"{sym} / month"
    cmp_df = pd.DataFrame(
        [{head: a, "Personal (FO)": p, "s.r.o.": s_} for a, p, s_ in rows]
        + [{head: "Self-funding ratio %", "Personal (FO)": r.ratio_personal * 100,
            "s.r.o.": r.ratio_sro * 100},
           {head: "Loan LTV %", "Personal (FO)": r.ltv * 100,
            "s.r.o.": r.sro_ltv * 100},
           {head: "Loan rate %", "Personal (FO)": r.mortgage_rate * 100,
            "s.r.o.": r.sro_mortgage_rate * 100},
           {head: f"Cash in {sym}", "Personal (FO)": r.total_cash_invested,
            "s.r.o.": r.total_cash_invested_sro},
           # None when it can't be worked out (the cash flows never turn
           # positive): shown as "—", not as a 0% that reads like a result.
           {head: f"IRR over {wi_hold}y %",
            "Personal (FO)": irr_p.irr * 100 if irr_p.irr is not None else None,
            "s.r.o.": irr_s.irr * 100 if irr_s.irr is not None else None},
           {head: "Equity multiple ×", "Personal (FO)": irr_p.equity_multiple,
            "s.r.o.": irr_s.equity_multiple},
           {head: f"Tax caused by the sale {sym}", "Personal (FO)": irr_p.exit_tax,
            "s.r.o.": irr_s.exit_tax},
           {head: f"Total profit {sym}", "Personal (FO)": irr_p.total_profit,
            "s.r.o.": irr_s.total_profit}])
    c_left, c_right = st.columns([3, 2])
    with c_left:
        st.markdown('<div class="muted">TAX TOGGLE — PERSONAL vs s.r.o.</div>', unsafe_allow_html=True)
        # Text, right-aligned: a number column can only show a missing value
        # as "None".
        for col in ("Personal (FO)", "s.r.o."):
            cmp_df[col] = [f"{x:.2f}" if pd.notna(x) else "—" for x in cmp_df[col]]
        st.dataframe(cmp_df, hide_index=True, width="stretch",
                     column_config={c: st.column_config.TextColumn(alignment="right")
                                    for c in ("Personal (FO)", "s.r.o.")})
        if sk:
            st.caption(f"Tax rules {r.tax_year}. Personal: §6(3) passive rental, €500 exempt, no "
                       "health levy, interest not deductible; sale exempt after 5 years. s.r.o.: "
                       "company loan on its own terms, interest and running cost deductible, "
                       "corporate + 10% dividend tax; the sale is taxed whenever it happens. "
                       "s.r.o. is recommended only when it nets more than personal and repays "
                       "its setup cost within the hold. Confirm with an účtovník.")
        else:
            st.caption(f"{prof.name} tax rules {r.tax_year}: "
                       + (markets.tax_rules(r.tax_year, wm).get("summary") or "")
                       + " Confirm with a daňový poradce.")
    with c_right:
        st.markdown(f'<div class="muted">RATE SHOCK ({best_tag})</div>', unsafe_allow_html=True)
        shock_rows = []
        for bump in (0.0, 0.01, 0.02, 0.03):
            x = analyse(wi_price, wi_size, wi_district, **{**fin, "rate": wi_rate + bump})
            shock_rows.append({"Rate": f"{(wi_rate + bump) * 100:.1f}%",
                               f"Surplus {sym}/mo": x.surplus_sro if best_sro else x.surplus_personal,
                               "Self-funding %": (x.ratio_sro if best_sro else x.ratio_personal) * 100})
        st.dataframe(pd.DataFrame(shock_rows), hide_index=True, width="stretch",
                     column_config={f"Surplus {sym}/mo": (
                                        st.column_config.NumberColumn(format="euro", step=1) if sk
                                        else st.column_config.NumberColumn(format="localized", step=1)),
                                    "Self-funding %": st.column_config.NumberColumn(format="%.1f%%")})
        st.markdown(f'<div class="muted">EQUITY CASH FLOWS ({best_tag})</div>',
                    unsafe_allow_html=True)
        flows = (irr_s if best_sro else irr_p).cash_flows
        st.bar_chart(pd.DataFrame({"Year": list(range(len(flows))),
                                   sym: flows}).set_index("Year"), height=180)
