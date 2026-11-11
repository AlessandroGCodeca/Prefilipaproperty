"""
dashboard/cards.py — the listing card (ACTIVE SNAG LIST), its memo button,
one page of cards at a time, and the keyed boxes that hold a deal's stage.
"""

import streamlit as st

import markets
from database import DEAL_STAGES

from dashboard.listing_cache import clear_listing_cache
from dashboard.fmt import (
    _floor_label, _labels, _lv_link, _lv_state_t, _of100, _pct_or_dash,
    _quick_cadastre, _rent_fallback, _risk_label, amt, badge, esc, fp, market_badge,
    mkw, sgn, tier_badge,
)


def _load_stage(key, cur, *source):
    """Put a deal's stored stage into its keyed stage box. A keyed selectbox
    keeps its last value whatever index= says, so picking another deal, or a
    move made elsewhere, left the box on a stale stage — and MOVE DEAL or
    SAVE STAGE then wrote it back. The box is reloaded whenever what it shows
    (the deal, and its stored stage) changes, or its state has gone (a closed
    card drops it); a stage the user picks since then is kept."""
    cur = cur if cur in DEAL_STAGES else DEAL_STAGES[0]
    _load_box(key, cur, *source)


def _load_box(key, value, *source):
    """Put a stored value into its keyed box, as _load_stage does for a stage
    box: a keyed text_input also keeps its last value whatever value= says, so
    a card left open showed (and RE-VERIFY LV or SAVE STAGE wrote back) what
    was stored when it was opened. The box is reloaded whenever the stored
    value (or its source) changes, or its state has gone; what the user types
    since then is kept. The widget is then drawn without value=."""
    src_key, src = f"_src_{key}", (*source, value)
    if key not in st.session_state or st.session_state.get(src_key) != src:
        st.session_state[key] = value
        st.session_state[src_key] = src


def _save_stage(lid):
    """SAVE STAGE, run as a callback — before the page redraws, so the card
    shows the new stage at once. The stage is in the card's header, and an
    expander whose label changes comes back closed, so it is kept open."""
    from database import set_deal_stage
    set_deal_stage(lid, st.session_state[f"stg_{lid}"], st.session_state[f"stgn_{lid}"])
    clear_listing_cache()               # the stages are cached with the listings
    st.session_state[f"card_{lid}"] = True


def render_card(l, v):
    # This run's page state (dashboard/view.py).
    show_sro, using_demo = v.show_sro, v.using_demo
    _LV_DOCS, _cf_negative = v.lv_docs, v.cf_negative
    T        = _labels(l)
    cz       = l.get("_market") == "cz"
    cls      = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
    css_cls  = {"GREEN":"g","YELLOW":"y","WHITE":"w","PENDING":"w"}.get(cls,"w")
    emoji    = {"GREEN":"🟢","YELLOW":"🟡","WHITE":"⚪"}.get(cls,"")

    surplus  = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
    ratio    = l.get("ratio_sro")   if show_sro else l.get("ratio_personal")
    total_c  = l.get("total_costs_sro") if show_sro else l.get("total_costs_personal")
    struct   = "s.r.o." if show_sro else T("Personal")
    rent     = l.get("estimated_rent_eur", 0) or 0
    price    = l.get("price_eur", 0) or 0
    size     = l.get("size_m2", 0) or 0
    district = l.get("district","—")
    title    = l.get("title") or district
    # get_all_active LEFT JOINs location_scores: a listing without a Location
    # IQ row has these keys, set to None, so a .get() default never applies.
    loc_tier = l.get("location_tier")
    transit  = l.get("nearest_transit_m")
    ind      = l.get("industrial_zone", 0)
    opt      = l.get("optimal_structure","—")
    saving   = l.get("annual_sro_saving", 0) or 0
    bev      = l.get("sro_break_even_months")
    ph       = l.get("_ph")
    stage    = l.get("_stage")

    disc     = l.get("market_discount")
    if cz:
        below = (f"{abs(disc)*100:.0f} % {'pod' if disc >= 0 else 'nad'} trhem"
                 if disc is not None else "bez srovnání")
    else:
        below = (f"{abs(disc)*100:.0f}% {'below' if disc >= 0 else 'above'} market"
                 if disc is not None else "no benchmark")
    cut = f"   ·   🔻{ph['change_pct']:+.0%}" if ph and (ph.get("change_pct") or 0) < 0 else ""
    stage_tag = f"   ·   [{stage['stage']}]" if stage else ""
    header = (f"{emoji}  {title[:60]}   ·   {amt(l, price)}   ·   {below}   ·   "
              f"{sgn(l, surplus)}{cut}{stage_tag}" + ("   ·   🇨🇿 CZ" if cz else ""))

    # Only an open card builds its body. Every click reruns the whole script,
    # and a collapsed expander still ran its ~40 widgets, so the page slowed
    # to half a minute a click at ~700 listings.
    card = st.expander(header, key=f"card_{l.get('id')}", on_change="rerun")
    if not card.open:
        return
    with card:
        # Row 1: key metrics
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1:
            st.metric(T("Price"),    amt(l, price),
                      help=(f"≈ {markets.format_money(l.get('_price_eur'))} "
                            f"({markets.fx_note()})" if cz else None))
            st.metric(T("Size"),     f"{size:.0f} m²")
        with c2:
            if cz:
                rent_help = (("Živé srovnání z pronájmů" if l.get("rent_source") == "live"
                              else "Výchozí Kč/m² (engine.rent_cz)")
                             + (f" pro '{l['rent_key']}'" if l.get("rent_key") else ""))
            else:
                rent_help = (("Live prenájom comps" if l.get("rent_source") == "live"
                              else "Published baseline €/m² (config.RENT_PER_M2)")
                             + (f" for '{l['rent_key']}'" if l.get("rent_key") else ""))
            st.metric(T("Est. Rent"),  amt(l, rent, "/mo"), help=rent_help)
            st.metric(T("Total Costs"), amt(l, total_c, "/mo") if total_c else "—")
        with c3:
            surplus_str = sgn(l, surplus)
            st.metric(T("Surplus/mo"),   surplus_str)
            st.metric(T("Self-Fund"),    fp(ratio))
        with c4:
            st.metric(T("Cap Rate"),   fp(l.get("cap_rate")))
            st.metric(T("CoC Return"), fp(l.get("cash_on_cash")))
            st.metric(T("IRR 10y"),    _pct_or_dash(l.get("irr_sro") if show_sro else l.get("irr_personal")),
                      help=("IRR za dobu držení se zhodnocením, náklady prodeje a daní ze "
                            "zisku — viz záložka WHAT-IF." if cz else
                            "Hold-period IRR with appreciation, exit costs and tax on the "
                            "gain — see the WHAT-IF tab."))
        with c5:
            my, mg = l.get("max_price_yellow"), l.get("max_price_green")
            st.metric(T("Max offer 🟡"), amt(l, my) if my else "—",
                      delta=(f"{my / price - 1:+.1%} vs ask" if my and price else None),
                      help=("Nejvyšší cena, při které je byt stále YELLOW (≥10 % pod "
                            "regionálním mediánem Kč/m²)." if cz else
                            "Highest price at which this is still YELLOW "
                            "(≥10% below the regional median €/m²)."))
            st.metric(T("Max offer 🟢"), amt(l, mg) if mg else "—",
                      help=("Nejvyšší cena, při které je byt GREEN (≥20 % pod regionálním "
                            "mediánem Kč/m²)." if cz else
                            "Highest price at which this is GREEN "
                            "(≥20% below the regional median €/m²)."))
        with c6:
            median_m2 = l.get("regional_median_m2")
            from engine.regional_prices import benchmark_note
            # Direction in the label, number in the value: "45% below market"
            # doesn't fit a 6-column metric and was cut to "45% b…".
            unit = "Kč/m²" if cz else "€/m²"
            st.metric(T("vs Market") if disc is None else
                      (T("Below market") if disc >= 0 else T("Above market")),
                      "—" if disc is None else f"{abs(disc) * 100:.0f}%",
                      help=(f"Asking {unit} vs {amt(l, median_m2)}/m² "
                            f"(≈ {amt(l, median_m2 * size)} for {size:.0f} m²) — "
                            f"{benchmark_note(district or '', l.get('rooms'), **mkw(l))}")
                      if median_m2 and size else "No regional median for this district.")
            st.metric(T("Days tracked"), "—" if l.get("_dom") is None else f"{l['_dom']}",
                      help="Days since this dashboard first saw the flat on any "
                           "portal — not the portal's posting date, so a listing "
                           "that was up long before the first scrape reads young.")
            st.metric(T("Location"),   _of100(l.get("location_score")))

        # Composite deal grade (financial + location + energy + risk)
        from engine.financial import compute_deal_score
        deal_score, deal_grade = compute_deal_score(l)
        grade_css = {"A": "bg", "B": "bs", "C": "by", "D": "bw"}.get(deal_grade, "bw")

        # Badges
        lv_risk = (l.get("lv_risk_level") or "").upper()
        lv_css  = {"LOW": "bg", "MEDIUM": "by", "HIGH": "br"}.get(lv_risk, "bw")
        lv_label, lv_badge_css = _lv_state_t(l)
        badges = (
            market_badge(l) + " " +
            badge(css_cls, cls) + " " +
            (f'<span class="badge {grade_css}">GRADE {deal_grade} · {deal_score}</span> '
             if deal_grade != "—" else "") +
            f'<span class="badge bo">{"s.r.o." if opt=="SRO" else T("PERSONAL")}</span>' + " " +
            (tier_badge(loc_tier) if loc_tier else "") +
            (' <span class="badge bg">⚙️ INDUSTRIAL</span>' if ind else "") +
            f' <span class="badge {lv_badge_css}">{lv_label}</span>' +
            (f' <span class="badge {lv_css}">⚖️ LV {lv_risk}</span>' if lv_risk else "") +
            (' <span class="badge by">⚑ LV SOFT FLAG</span>' if l.get("lv_soft_flags") else "") +
            (f' <span class="badge bp">📡 {l["_portals"]} PORTALS</span>' if l.get("_portals", 1) > 1 else "") +
            (' <span class="badge br">⛔ A COPY FAILED LV</span>' if l.get("dup_lv_failed") else "") +
            (' <span class="badge br">🌊 FLOOD Q100</span>' if l.get("flood_zone") else "") +
            (f' <span class="badge br">⛔ CASH-FLOW NEGATIVE · {struct}</span>'
             if _cf_negative(l) else "") +
            (f' <span class="badge by">⚠ {"DEFAULT" if _rent_fallback(l) == "default" else "KRAJ"} RENT</span>'
             if _rent_fallback(l) else "") +
            (f' <span class="badge bs">{stage["stage"]}</span>' if stage else "")
        )
        st.markdown(badges, unsafe_allow_html=True)
        # A check Claude decided writes "[Claude LEVEL] <summary>" as the
        # detail, so the summary on its own would say the same thing twice.
        lv_detail, lv_summary = l.get("lv_detail") or "", l.get("lv_summary") or ""
        soft_note = l.get("lv_soft_flags") or ""
        if soft_note and soft_note in lv_detail:
            soft_note = ""
        for lv_note in (lv_detail, "" if lv_summary in lv_detail else lv_summary,
                        f"⚑ soft flags (not rejected — check with your lawyer): {soft_note}"
                        if soft_note else ""):
            if lv_note:
                st.markdown(
                    f'<div class="muted" style="margin-top:6px">⚖️ LV: {esc(lv_note)}</div>',
                    unsafe_allow_html=True,
                )
        fallback = _rent_fallback(l)
        if fallback:
            if cz:
                from engine.financial import baseline_rent as _baseline
                _d = _baseline("default", market="cz")
                why = (f"the national default {amt(l, _d)}/m² — this town is in no rent table"
                       if fallback == "default" and _d else
                       "no Czech rent figure for this town"
                       if fallback == "default" else
                       f"the {esc(l['rent_key'].title())} median of its towns — no figure for this town")
            else:
                from config import RENT_PER_M2 as _RENT
                why = (f"the national default €{_RENT['default']:.2f}/m² — this town is in no rent table"
                       if fallback == "default" else
                       f"the {esc(l['rent_key'].title())} median of its towns — no figure for this town")
            st.markdown(f'<div class="muted" style="margin-top:6px;color:#ffd740">⚠ Rent uses '
                        f'{why}. Check local rents before trusting the surplus.</div>',
                        unsafe_allow_html=True)
        if ph:
            steps = " → ".join(f"{amt(l, p)} ({str(w)[:10]})" for w, p in ph["history"])
            st.markdown(f'<div class="muted" style="margin-top:6px">📉 Price: {steps} '
                        f'[{ph["change_pct"]:+.1%}]</div>', unsafe_allow_html=True)
        if len(l.get("_copies") or []) > 1:
            links = " · ".join(
                f'<a href="{esc(c.get("url"))}" target="_blank">{esc((c.get("source") or "").upper())} '
                f'{amt(l, c.get("price_eur") or 0)}</a>'
                for c in sorted(l["_copies"], key=lambda c: c.get("price_eur") or 0))
            st.markdown(f'<div class="muted" style="margin-top:6px">📡 Same flat on: {links}</div>',
                        unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Cost breakdown + Location IQ side by side
        bc1, bc2 = st.columns(2)

        with bc1:
            st.markdown(f'<div class="muted">{T("COST BREAKDOWN")} — {struct}</div>',
                        unsafe_allow_html=True)
            mortgage = (l.get("mortgage_monthly_sro") if show_sro
                        and l.get("mortgage_monthly_sro") is not None
                        else l.get("mortgage_monthly"))
            rows = [
                (T("Mortgage"),        mortgage),
                (T("HOA (incl. fond opráv)"), l.get("hoa_monthly")),
                (T("Property Tax"),    l.get("property_tax_monthly")),
                (T("Vacancy 5%"),      l.get("vacancy_cost")),
                (T("Owner reserve"),   l.get("maintenance_monthly")),
                (T("Management"),      l.get("management_monthly")),
                (T("Income Tax"),      l.get("income_tax_sro") if show_sro else l.get("income_tax_personal")),
                (T("Health Levy"),     l.get("health_levy_sro") if show_sro else l.get("health_levy_personal")),
            ]
            if show_sro:
                rows.insert(6, (T("s.r.o. running cost"), l.get("sro_running_cost_monthly")))
            html = ""
            for lbl, val in rows:
                html += f'<div class="brow"><span class="l">{lbl}</span><span class="v">{amt(l, val, "/mo")}</span></div>' if val is not None else ""
            html += f'<div class="brow tot"><span class="l">{T("TOTAL COSTS")}</span><span class="v">{amt(l, total_c, "/mo")}</span></div>' if total_c else ""
            surplus_cls = "pos" if (surplus or 0) >= 0 else "neg"
            html += f'<div class="brow tot {surplus_cls}"><span class="l">{T("NET SURPLUS")}</span><span class="v">{sgn(l, surplus)}</span></div>' if surplus is not None else ""
            st.markdown(html, unsafe_allow_html=True)

            if saving and saving > 0:
                verdict = "" if opt == "SRO" else " — too little to repay its setup cost; personal is better"
                st.markdown(f'<div class="muted" style="margin-top:8px">s.r.o. nets {amt(l, saving, "/yr")} more '
                            f'than personal after its running cost{f" · break-even {bev}mo" if bev else ""}'
                            f'{verdict}</div>', unsafe_allow_html=True)
            elif saving is not None and l.get("sro_running_cost_monthly") is not None:
                st.markdown(f'<div class="muted" style="margin-top:8px">s.r.o. comes out {amt(l, -saving, "/yr")} '
                            f'worse than personal after its running cost and company-loan terms</div>',
                            unsafe_allow_html=True)
            if show_sro and l.get("sro_rate_used") is not None:
                st.markdown(f'<div class="muted">s.r.o. loan: {l["sro_ltv_used"] * 100:.0f}% LTV at '
                            f'{l["sro_rate_used"] * 100:.2f}% · cash in '
                            f'{amt(l, l.get("total_cash_invested_sro") or 0)}</div>',
                            unsafe_allow_html=True)

            # Financing stress: +2 pp rate, and the 70% investor LTV cap.
            if price and size and rent:
                from engine.financial import analyse as _an
                if cz:
                    _prof = markets.get("cz")
                    inv_ltv, base_rate, base_term = (_prof.ltv_ratio_investor,
                                                     _prof.mortgage_rate_pa, _prof.loan_term_years)
                else:
                    from config import LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA, LOAN_TERM_YEARS
                    inv_ltv, base_rate, base_term = LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA, LOAN_TERM_YEARS
                inv = _an(price, size, district or "", rent_override=rent,
                          ltv=inv_ltv,
                          rate=l.get("mortgage_rate_used") or base_rate,
                          term_years=int(l.get("loan_term_years") or base_term), **mkw(l))
                sts = l.get("stress_surplus_sro")
                html = f'<div class="muted" style="margin-top:10px">{T("FINANCING STRESS (s.r.o.)")}</div>'
                if sts is not None:
                    html += (f'<div class="brow {"pos" if sts >= 0 else "neg"}"><span class="l">{T("Rate +2 pp")}</span>'
                             f'<span class="v">{sgn(l, sts)} · {T("self-funding")} '
                             f'{fp(l.get("stress_ratio_sro"))}</span></div>')
                html += (f'<div class="brow {"pos" if inv.surplus_sro >= 0 else "neg"}"><span class="l">{T("70% LTV (3rd+ flat)")}</span>'
                         f'<span class="v">{sgn(l, inv.surplus_sro)} · {T("self-funding")} {fp(inv.ratio_sro)} · '
                         f'{T("cash in")} {amt(l, inv.total_cash_invested)}</span></div>')
                st.markdown(html, unsafe_allow_html=True)

        with bc2:
            st.markdown(f'<div class="muted">{T("LOCATION IQ")}</div>', unsafe_allow_html=True)
            precision = l.get("geo_precision")
            loc_rows = [
                (T("Transit"),        f"{transit:.0f}m {'✅' if (transit or 9999) <= 560 else '⚠️'}" if transit else "—"),
                (T("Amenities"),      "—" if l.get("amenity_count") is None else
                                      f"{l['amenity_count']} {'✅' if l['amenity_count'] >= 3 else '⚠️'}"),
                (T("Walkability"),    _of100(l.get("walkability_score"))),
                (T("Industrial"),     T("✅ YES") if ind else "—"),
                (T("Construction"),   _risk_label(l.get("construction_risk"), T("⚠️ Site nearby"), T("✅ Clear"), T)),
                (T("Noise"),          _risk_label(l.get("noise_flag"), T("⚠️ ≥65 dB source"), T("✅ Clear"), T)),
                (T("Flood (Q100)"),   _risk_label(l.get("flood_zone"), T("⚠️ In flood area"), T("✅ Clear"), T)),
                (T("Geocode"),        precision or "—"),
                (T("Energy Class"),   l.get("energy_class","?")),
                (T("Floor"),          _floor_label(l) or "—"),
                (T("Building"),       " ".join(T(x) for x, c in (("🛗 elevator", "has_elevator"),
                                                              ("📦 cellar", "has_cellar"),
                                                              ("🌿 terrace", "has_terrace"),
                                                              ("🌿 loggia", "has_loggia"))
                                               if l.get(c)) or "—"),
                (T("LV Status"),      _lv_state_t(l)[0]),
            ]
            html = ""
            for lbl, val in loc_rows:
                html += f'<div class="brow"><span class="l">{lbl}</span><span class="v">{val}</span></div>'
            st.markdown(html, unsafe_allow_html=True)
            details = [d for d in (l.get("construction_detail"), l.get("noise_detail"),
                                   l.get("flood_detail")) if d]
            if details:
                st.markdown('<div class="muted" style="margin-top:6px">' +
                            "<br>".join(esc(d) for d in details) + "</div>", unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Deal stage + vibe notes
        s1, s2 = st.columns([1, 1])
        lid = l.get("id", "")
        with s1:
            cur = (stage or {}).get("stage", "NEW")
            # Both boxes reload when the stored row changes (a move in DEAL
            # PIPELINE, even one that only adds a note), so SAVE STAGE never
            # writes back a stage or note that has been replaced since.
            upd = (stage or {}).get("updated_at")
            _load_stage(f"stg_{lid}", cur, upd)
            _load_box(f"stgn_{lid}", (stage or {}).get("note") or "", upd)
            st.selectbox(T("Deal stage"), DEAL_STAGES, key=f"stg_{lid}")
            st.text_input(T("Stage note"), key=f"stgn_{lid}",
                          placeholder="např. prohlídka so 10:00" if cz else "e.g. viewing Sat 10:00")
            # Demo rows aren't in the database: writing their ids would leave
            # deal stages (and LV checks, notes) for listings that don't exist.
            st.button(T("SAVE STAGE"), key=f"stgb_{lid}", width="stretch",
                      disabled=using_demo, on_click=_save_stage, args=(lid,))
        with s2:
            v = l.get("_vibe")
            if v:
                score, note, n = v
                st.markdown(f'<div class="muted">VIBE {score or "—"}/10 · {n} note(s)</div>'
                            f'<div class="mono" style="font-size:.75rem">{esc(note)}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown('<div class="muted">No vibe notes yet — add one in SATELLITE VIEWER.</div>',
                            unsafe_allow_html=True)

        st.markdown('<hr class="div">', unsafe_allow_html=True)

        # Action buttons
        a1,a2,a3,a4,a5 = st.columns(5)
        with a1: st.link_button(T("VIEW LISTING"), l.get("url","#"), width="stretch")
        with a2:
            lat, lng = l.get("lat"), l.get("lng")
            if lat and lng:
                st.link_button(T("MAPS"), f"https://www.google.com/maps?q={lat},{lng}&z=15", width="stretch")
        with a3:
            st.link_button(T("CHECK LV"), _lv_link(l), width="stretch")
        with a4:
            verify = st.button(T("RE-VERIFY LV"), key=f"rv_{lid}", width="stretch",
                               disabled=using_demo)
        with a5:
            render_memo_button(l, key=f"memo_{lid}")

        # The flat's own LV — the only thing that can verify it. The building
        # plot found from the map pin is a different LV (see modules/debt_bot).
        # The boxes reload when the stored LV changes (saved in LV TO-DO, say):
        # RE-VERIFY LV takes a box that differs from the stored LV as an edit,
        # and a stale box would clear the saved number or put back an old one.
        _load_box(f"lvno_{lid}", l.get("lv_number") or "")
        _load_box(f"lvku_{lid}", l.get("cadastral_area") or "")
        v1, v2 = st.columns(2)
        with v1:
            flat_lv = st.text_input(
                T("Flat's own LV no."),
                key=f"lvno_{lid}", placeholder="e.g. 4321",
                help=("Z dokladů prodávajícího nebo od makléře. LV pozemku pod domem "
                      "není LV bytové jednotky." if cz else
                      "From the seller's papers or the agent. The building "
                      "plot's LV is not the flat's."))
        with v2:
            flat_ku = st.text_input(
                T("Katastrálne územie"),
                key=f"lvku_{lid}", placeholder="např. Vinohrady" if cz else "e.g. Petržalka",
                help=("Název nebo kód katastrálního území." if cz else
                      "Name or numeric code of the cadastral unit."))
        lv_doc = None
        if cz:
            # As the LV boxes: a výpis pasted since (in the REJECTED tab, say)
            # reloads the box, so RE-VERIFY LV can't write the old text back.
            _load_box(f"lvdoc_{lid}", _LV_DOCS.get(lid, ""))
            lv_doc = st.text_area(
                T("LV extract (text)"), key=f"lvdoc_{lid}",
                height=110, disabled=using_demo,
                placeholder="Vložte text výpisu z listu vlastnictví…",
                help="Text výpisu z LV této jednotky (CzechPOINT nebo dálkový přístup "
                     "ČÚZK). Bezplatné služby katastru obsah LV programu nedávají; "
                     "OVĚŘIT LV jej projde (části C a D).")
        if verify:
            try:
                from modules.debt_bot import reverify
                if cz and (lv_doc or "").strip() != _LV_DOCS.get(lid, "").strip():
                    from database import set_lv_document
                    set_lv_document(lid, lv_doc or "")
                    clear_listing_cache()   # even if the check below fails
                lv_in = flat_lv.strip()
                ku_in = flat_ku.strip()
                changed = (lv_in != (l.get("lv_number") or "")
                           or ku_in != (l.get("cadastral_area") or ""))
                with st.spinner("Checking the cadastre..."), _quick_cadastre(l):
                    r = reverify(lid, lv_number=lv_in if changed else None,
                                 cadastral_area=ku_in if changed else "")
                from database import mark_duplicates
                mark_duplicates()   # the flat's other copies carry its LV result
                clear_listing_cache()
                if r["status"] == "REJECT":
                    st.error(f"❌ REJECTED: {r['detail']}")
                elif r["status"] == "PASS":
                    st.success(f"✅ Clean: {r['detail']}")
                elif r["status"] == "UNVERIFIED":
                    st.warning(f"⚠ Unverified: {r['detail']}")
                else:
                    st.warning(f"Re-verify: {r.get('detail', r['status'])}")
            except Exception as e:
                st.warning(f"Re-verify: {e}")

        if cz:
            st.markdown(f'<div class="muted">Zdroj: {esc((l.get("source") or "").upper())} · Tento přehled jej poprvé viděl: {esc((l.get("scraped_at") or "")[:10])}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="muted">Source: {esc((l.get("source") or "").upper())} · First seen by this dashboard: {esc((l.get("scraped_at") or "")[:10])}</div>', unsafe_allow_html=True)


def render_memo_button(l, key):
    """Two-step PDF memo: building every card's PDF on each rerun would be
    slow, so the first click builds this one and swaps in the download. The
    built memo is kept with a fingerprint of what it prints: once the row
    changes (price, rescore, LV check, a note, the deal stage), the kept PDF
    is dropped and 📄 MEMO is offered again. The file is named after the time
    the memo was built, the time printed on it (Bratislava time)."""
    from modules.memo import memo_fingerprint
    ready = st.session_state.setdefault("memo_ready", {})
    sig = memo_fingerprint(l)
    kept = ready.get(key)
    if kept is not None and not (isinstance(kept, tuple) and kept[0] == sig):
        ready.pop(key, None)
        kept = None
    if kept is not None:
        _, pdf, made = kept
        st.download_button("⬇️ MEMO PDF", pdf,
                           file_name=f"memo_{(l.get('id') or 'x')[:8]}_{made:%Y%m%d}.pdf",
                           mime="application/pdf", key=f"{key}_dl", width="stretch")
    elif st.button("📄 MEMO", key=key, width="stretch"):
        from modules.memo import build_memo_pdf
        from modules.contract_draft import local_now
        from database import get_annotations
        try:
            made = local_now()
            pdf = build_memo_pdf(l, price_history={l.get("id"): l.get("_ph")} if l.get("_ph") else None,
                                 notes=get_annotations(l.get("id")), stage=l.get("_stage"),
                                 portals=l.get("_copies"), generated_at=made)
            ready[key] = (sig, pdf, made)
            st.rerun()
        except Exception as e:
            st.warning(f"Memo: {e}")


CARDS_PER_PAGE = 25


def render_cards(listings, section, v):
    """One page of a section's cards, so a click never redraws hundreds of
    them. The picker's key carries the count: when the filters change how
    many there are, the section starts again at its first page."""
    pages = -(-len(listings) // CARDS_PER_PAGE)
    page = 0
    if pages > 1:
        n = len(listings)
        page = st.selectbox(
            "Cards", range(pages), key=f"page_{section}_{n}", width=260,
            format_func=lambda p: f"{p * CARDS_PER_PAGE + 1}–"
                                  f"{min((p + 1) * CARDS_PER_PAGE, n)} of {n}")
    for l in listings[page * CARDS_PER_PAGE:(page + 1) * CARDS_PER_PAGE]:
        render_card(l, v)
