"""
dashboard/cards.py — the listing card (ACTIVE SNAG LIST), its memo button,
one page of cards at a time, and the keyed boxes that hold a deal's stage.
"""

import streamlit as st

import markets
from database import DEAL_STAGES

from dashboard.listing_cache import clear_listing_cache
from modules.redact import redact
from dashboard.fmt import (
    _floor_label, _labels, _lv_link, czech_words, _lv_state_t, _of100, _pct_or_dash,
    _quick_cadastre, _rent_fallback, _risk_label, amt, esc, fp, last_seen_label,
    lv_checked_label, market_badge,
    mkw, safe_href, safe_url, sgn, tier_badge,
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


def _lv_photo(lid: str, cz_mkt: bool, disabled: bool, words: bool | None = None) -> None:
    """📷 An LV photo or scan, read by Claude: its number and cadastral area
    go into the card's boxes (and, for a Czech flat, its text into the výpis
    box), so RE-VERIFY LV checks them. Shown only with ANTHROPIC_API_KEY."""
    cz = cz_mkt if words is None else words
    from modules import doc_reader
    if not doc_reader.enabled():
        return
    with st.expander("Fotka nebo sken LV" if cz else "LV photo or scan", icon=":material/photo_camera:"):
        up = st.file_uploader(
            "Photo (JPEG, PNG, WebP) or PDF", type=["pdf", "jpg", "jpeg", "png", "webp"],
            key=f"lvph_{lid}", disabled=disabled,
            help="Claude copies the deed; nothing is stored until you press RE-VERIFY LV. "
                 "An iPhone photo: share it as JPEG (Settings → Camera → Most Compatible).")
        if up is not None and st.button("READ IT", icon=":material/menu_book:", key=f"lvphb_{lid}", disabled=disabled):
            with st.spinner("Claude is reading the deed…"):
                got = doc_reader.read_title_deed(up.getvalue())
            if not got:
                st.warning("Not read: the file isn't a title deed, or it can't be read.")
                return
            if got["lv_number"]:
                st.session_state[f"lvno_{lid}"] = got["lv_number"]
            if got["cadastral_area"]:
                st.session_state[f"lvku_{lid}"] = got["cadastral_area"]
            if cz_mkt:
                st.session_state[f"lvdoc_{lid}"] = got["text"]
            st.session_state[f"lvphtext_{lid}"] = got["text"]
            st.rerun()
        text = st.session_state.get(f"lvphtext_{lid}")
        if text:
            st.caption("Read from your file. Check the LV number and area below, then press "
                       "RE-VERIFY LV — " + ("the text is in the výpis box." if cz else
                                            "the cadastre's own copy is what gets verified."))
            st.markdown(f'<div class="mono" style="white-space:pre-wrap;max-height:220px;'
                        f'overflow:auto;font-size:.72rem">{esc(text)}</div>',
                        unsafe_allow_html=True)


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


# D4: each card is a fragment: a click inside it (a toggle, a box, the
# card's own open/close) redraws that card only, not the whole page with its
# hundreds of listings. A button that changes what other parts show still
# calls st.rerun(), which redraws everything.
@st.fragment
def render_card(l, v):
    # This run's page state (dashboard/view.py).
    show_sro, using_demo = v.sro(l), v.using_demo
    _LV_DOCS, _cf_negative = v.lv_docs, v.cf_negative
    T        = _labels(l)
    cz_mkt   = l.get("_market") == "cz"     # a Czech flat: Kč, Czech data and rules
    cz       = czech_words(l)               # its card in Czech (D7)
    cls      = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
    emoji    = {"GREEN":"🟢","YELLOW":"🟡","WHITE":"⚪"}.get(cls,"")

    surplus  = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
    ratio    = l.get("ratio_sro")   if show_sro else l.get("ratio_personal")
    total_c  = l.get("total_costs_sro") if show_sro else l.get("total_costs_personal")
    struct   = "s.r.o." if show_sro else T("Personal")
    # The +2 pp stress test of the structure shown (a score from before both
    # were stored has the s.r.o.'s only).
    stress_k = "sro" if show_sro or l.get("stress_surplus_personal") is None else "personal"
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
              f"{sgn(l, surplus)}{cut}{stage_tag}" + ("   ·   🇨🇿 CZ" if cz_mkt else ""))

    # Only an open card builds its body. Every click reruns the whole script,
    # and a collapsed expander still ran its ~40 widgets, so the page slowed
    # to half a minute a click at ~700 listings.
    card = st.expander(header, key=f"card_{l.get('id')}", on_change="rerun")
    if not card.open:
        return
    with card:
        # Composite deal grade (financial + location + energy + risk)
        from engine.financial import compute_deal_score
        deal_score, deal_grade = compute_deal_score(l)

        # D10: a star, lighter than a deal stage — "look at this again".
        lid = l.get("id")
        if not using_demo:
            from database import get_starred, set_starred
            starred = lid in get_starred()
            if st.button("★ Starred" if starred else "☆ Star", key=f"star_{lid}",
                         help="Starred flats are listed first in TODAY."):
                set_starred(lid, not starred)
                st.rerun()

        # UX4: at a viewing, one screen with what matters there, instead of the card.
        if st.toggle("Režim prohlídky" if cz else "Viewing mode", key=f"viewmode_{lid}",
                     help=("Na prohlídku: čísla k vyjednávání, co zkontrolovat, fotky."
                           if cz else "For a viewing: the figures to negotiate with, what "
                           "to look at, photos and notes.")):
            from dashboard import viewing
            viewing.render(l, using_demo, cz)
            return

        # The verdict first: what the flat is, in a sentence (dashboard/verdict.py).
        from dashboard.verdict import days_between, verdict_html
        cut_days = (days_between(ph["history"][0][0], ph["history"][-1][0])
                    if ph and ph.get("history") else None)
        verdict = verdict_html(deal_grade, deal_score, disc, surplus, struct,
                               lambda v: amt(l, v), cz,
                               cut_pct=ph.get("change_pct") if ph else None,
                               cut_days=cut_days)
        # D17: the flat's photo beside it, fetched by the server (dashboard/photos.py).
        from dashboard.photos import listing_photo, photo_url
        photo = listing_photo(photo_url(l))
        if photo:
            ph_col, v_col = st.columns([1, 2.2], vertical_alignment="center")
            with ph_col:
                st.image(photo, width="stretch")
            with v_col:
                st.markdown(verdict, unsafe_allow_html=True)
        else:
            st.markdown(verdict, unsafe_allow_html=True)

        # Key figures: price, surplus and the highest offer, big.
        my, mg = l.get("max_price_yellow"), l.get("max_price_green")
        with st.container(key=f"kf_{lid}"):
            k1, k2, k3 = st.columns(3)
            with k1:
                st.metric(T("Price"), amt(l, price),
                          help=(f"≈ {markets.format_money(l.get('_price_eur'))} "
                                f"({markets.fx_note()})" if cz_mkt else None))
            with k2:
                with st.container(key=f"kfneg_{lid}" if (surplus or 0) < 0 else f"kfpos_{lid}"):
                    st.metric(T("Surplus/mo"), sgn(l, surplus))
            with k3:
                st.metric(T("Max offer 🟡"), amt(l, my) if my else "—",
                          delta=(f"{my / price - 1:+.1%} vs ask" if my and price else None),
                          help=("Nejvyšší cena, při které je byt stále YELLOW (≥10 % pod "
                                "regionálním mediánem Kč/m²)." if cz else
                                "Highest price at which this is still YELLOW "
                                "(≥10% below the regional median €/m²)."))

        # D18: where the price per m² sits among the flats like it listed now.
        if not using_demo and price and size:
            from dashboard.listing_cache import load_active
            from dashboard.verdict import price_band_html
            from engine.regional_prices import median_source
            from modules.offer_sheet import _per_m2, comparables
            band = price_band_html(price / size,
                                   [_per_m2(c) for c in comparables(l, load_active())],
                                   lambda v: amt(l, v, "/m²"),
                                   median_source(district or "", **mkw(l))[1], cz)
            if band:
                st.markdown(band, unsafe_allow_html=True)

        if cz_mkt and cz:
            rent_help = (("Živé srovnání z pronájmů" if l.get("rent_source") == "live"
                          else "Výchozí Kč/m² (engine.rent_cz)")
                         + (f" pro '{l['rent_key']}'" if l.get("rent_key") else ""))
        elif cz_mkt:
            rent_help = (("Live rental comps" if l.get("rent_source") == "live"
                          else "Default Kč/m² (engine.rent_cz)")
                         + (f" for '{l['rent_key']}'" if l.get("rent_key") else ""))
        else:
            rent_help = (("Live prenájom comps" if l.get("rent_source") == "live"
                          else "Published baseline €/m² (config.RENT_PER_M2)")
                         + (f" for '{l['rent_key']}'" if l.get("rent_key") else ""))
        median_m2 = l.get("regional_median_m2")
        from engine.regional_prices import benchmark_note
        unit = "Kč/m²" if cz_mkt else "€/m²"
        # Every other figure, smaller, in two rows.
        with st.container(key=f"sf_{lid}"):
            r1 = st.columns(6)
            with r1[0]:
                st.metric(T("Est. Rent"), amt(l, rent, "/mo"), help=rent_help)
            with r1[1]:
                st.metric(T("Total Costs"), amt(l, total_c, "/mo") if total_c else "—")
            with r1[2]:
                st.metric(T("Self-Fund"), fp(ratio))
            with r1[3]:
                st.metric(T("Cap Rate"), fp(l.get("cap_rate")))
            with r1[4]:
                st.metric(T("CoC Return"), fp(l.get("cash_on_cash")),
                          help=(f"Výnos na vložený kapitál při doporučené struktuře ({opt})."
                                if cz else
                                f"Cash-on-cash under the structure recommended ({opt})."))
            with r1[5]:
                st.metric(T("IRR 10y"),
                          _pct_or_dash(l.get("irr_sro") if show_sro else l.get("irr_personal")),
                          help=("IRR za dobu držení se zhodnocením, náklady prodeje a daní ze "
                                "zisku — viz záložka WHAT-IF." if cz else
                                "Hold-period IRR with appreciation, exit costs and tax on the "
                                "gain — see the WHAT-IF tab."))
            r2 = st.columns(6)
            with r2[0]:
                st.metric(T("Max offer 🟢"), amt(l, mg) if mg else "—",
                          help=("Nejvyšší cena, při které je byt GREEN (≥20 % pod regionálním "
                                "mediánem Kč/m²)." if cz else
                                "Highest price at which this is GREEN "
                                "(≥20% below the regional median €/m²)."))
            with r2[1]:
                # Direction in the label, number in the value: "45% below market"
                # doesn't fit a metric and was cut to "45% b…".
                st.metric(T("vs Market") if disc is None else
                          (T("Below market") if disc >= 0 else T("Above market")),
                          "—" if disc is None else f"{abs(disc) * 100:.0f}%",
                          help=(f"Asking {unit} vs {amt(l, median_m2)}/m² "
                                f"(≈ {amt(l, median_m2 * size)} for {size:.0f} m²) — "
                                f"{benchmark_note(district or '', l.get('rooms'), **mkw(l))}")
                          if median_m2 and size else "No regional median for this district.")
            with r2[2]:
                # S18: how long such flats stay up in this district.
                from dashboard.listing_cache import days_on_market
                from engine.financial import match_rent_key
                _mk = "cz" if cz_mkt else "sk"
                _dk = days_on_market(_mk).get(match_rent_key(l.get("district") or "", market=_mk)) or {}
                _dom_note = (f" In {_dk['District key'].title()}, the {_dk['Left']} flats retired "
                             f"as gone in the last 6 months had been up a median "
                             f"{_dk['Median days to go']:.0f} days."
                             if _dk.get("Left", 0) >= 3 else "")
                st.metric(T("Days tracked"), "—" if l.get("_dom") is None else f"{l['_dom']}",
                          help="Days since this dashboard first saw the flat on any "
                               "portal — not the portal's posting date, so a listing "
                               "that was up long before the first scrape reads young."
                               + _dom_note)
            with r2[3]:
                st.metric(T("Location"), _of100(l.get("location_score")))
            with r2[4]:
                st.metric(T("Size"), f"{size:.0f} m²")

        # Badges
        lv_risk = (l.get("lv_risk_level") or "").upper()
        lv_css  = {"LOW": "bg", "MEDIUM": "by", "HIGH": "br"}.get(lv_risk, "bw")
        lv_label, lv_badge_css = _lv_state_t(l)
        # D2: chips only for what needs action; everything else is one quiet
        # line of facts. A dozen chips in six colours meant none stood out.
        lv_ok = (l.get("lv_status") or "").upper() in ("PASS", "CLEAN")
        action = (
            ([] if lv_ok else [f'<span class="badge {lv_badge_css}">{lv_label}</span>']) +
            ([f'<span class="badge {lv_css}">⚖️ LV {lv_risk}</span>']
             if lv_risk in ("MEDIUM", "HIGH") else []) +
            (['<span class="badge by">⚑ LV SOFT FLAG</span>'] if l.get("lv_soft_flags") else []) +
            (['<span class="badge br">⛔ A COPY FAILED LV</span>'] if l.get("dup_lv_failed") else []) +
            (['<span class="badge br">🏘 COOPERATIVE · NO OWN LV</span>']
             if (l.get("lv_detail") or "").startswith(("Cooperative flat", "LV: Cooperative"))
             else []) +
            (['<span class="badge br">🌊 FLOOD Q100</span>'] if l.get("flood_zone") else []) +
            (['<span class="badge by">⚙️ INDUSTRIAL</span>'] if ind else []) +
            ([tier_badge("POOR")] if loc_tier == "POOR" else []) +
            ([f'<span class="badge br">⛔ CASH-FLOW NEGATIVE · {struct}</span>']
             if _cf_negative(l) else []) +
            ([f'<span class="badge by">⚠ {"DEFAULT" if _rent_fallback(l) == "default" else "KRAJ"} RENT</span>']
             if _rent_fallback(l) else [])
        )
        facts = [cls.title() if cls != "PENDING" else "Not scored",
                 f"grade {deal_grade} · {deal_score}" if deal_grade != "—" else "",
                 "s.r.o." if opt == "SRO" else T("Personal").lower(),
                 f"{loc_tier.title()} location" if loc_tier and loc_tier != "POOR" else "",
                 lv_label.replace("✅ ", "") if lv_ok else "",
                 f"on {l['_portals']} portals" if l.get("_portals", 1) > 1 else "",
                 f"stage {stage['stage']}" if stage else ""]
        badges = (market_badge(l) + " " + " ".join(action)
                  + f'<div class="facts">{" · ".join(esc(f) for f in facts if f)}</div>')
        st.markdown(badges, unsafe_allow_html=True)
        if deal_grade != "—":
            with st.popover(f"Why grade {deal_grade}?" if not cz else f"Proč známka {deal_grade}?"):
                st.markdown(grade_breakdown_html(l), unsafe_allow_html=True)
        # A check Claude decided writes "[Claude LEVEL] <summary>" as the
        # detail, so the summary on its own would say the same thing twice.
        lv_detail, lv_summary = l.get("lv_detail") or "", l.get("lv_summary") or ""
        soft_note = l.get("lv_soft_flags") or ""
        if soft_note and soft_note in lv_detail:
            soft_note = ""
        # When the deed was last read: a PASS is as good as its date.
        for lv_note in (lv_detail, "" if lv_summary in lv_detail else lv_summary,
                        f"⚑ soft flags (not rejected — check with your lawyer): {soft_note}"
                        if soft_note else "", lv_checked_label(l, cz)):
            if lv_note:
                st.markdown(
                    f'<div class="muted" style="margin-top:6px">⚖️ LV: {esc(lv_note)}</div>',
                    unsafe_allow_html=True,
                )
        fallback = _rent_fallback(l)
        if fallback:
            if cz_mkt:
                from engine.financial import baseline_rent as _baseline
                _d = _baseline("default", market="cz")
                why = (f"the national default {amt(l, _d)}/m² — this town is in no rent table"
                       if fallback == "default" and _d else
                       "no Czech rent figure for this town"
                       if fallback == "default" else
                       "the Ministry of Finance rent map's plain 2+kk reference flat — "
                       "no Deloitte figure for this town; it runs 15–25 % under Deloitte's, "
                       "so the surplus is conservative"
                       if fallback == "mf" else
                       f"the {esc(l['rent_key'].title())} median of its towns — no figure for this town")
            else:
                from config import RENT_PER_M2 as _RENT
                why = (f"the national default €{_RENT['default']:.2f}/m² — this town is in no rent table"
                       if fallback == "default" else
                       f"the {esc(l['rent_key'].title())} median of its towns — no figure for this town")
            st.markdown(f'<div class="muted" style="margin-top:6px;color:var(--caution)">⚠ Rent uses '
                        f'{why}. Check local rents before trusting the surplus.</div>',
                        unsafe_allow_html=True)
        # This flat type's own rental comps and how long such ads stay up
        # (engine/rent_comps, M10 of the 12 Nov audit).
        if not cz_mkt and not using_demo:
            from dashboard.listing_cache import rent_types
            from engine.rent_comps import type_note
            _tn = type_note(l.get("district") or "", l.get("rooms"), rent_types())
            if _tn:
                st.markdown(f'<div class="muted" style="margin-top:6px">🏘 {esc(_tn)}</div>',
                            unsafe_allow_html=True)
        # D8: the month's cash flow and the price over time, drawn.
        from dashboard.charts import cost_rows, draw, price_spec, waterfall_spec
        unit = "Kč" if (l.get("_cur") or "EUR") == "CZK" else "€"
        from dashboard.prefs import theme_now
        wf = waterfall_spec(rent, cost_rows(l, show_sro, T), surplus, unit, theme_now())
        pr = price_spec(ph["history"], unit, theme_now()) if ph else None
        if wf or pr:
            g1, g2 = st.columns(2) if wf and pr else (st.container(), None)
            if wf:
                with g1:
                    title = "MĚSÍČNÍ CASH FLOW" if cz else "CASH FLOW, A MONTH"
                    st.markdown(f'<div class="muted">{title} — {esc(struct)}</div>',
                                unsafe_allow_html=True)
                    draw(wf)
            if pr:
                with (g2 or g1):
                    st.markdown(f'<div class="muted">{"CENA V ČASE" if cz else "ASKING PRICE"} · '
                                f'{ph["change_pct"]:+.1%}</div>', unsafe_allow_html=True)
                    draw(pr)
        if ph:
            steps = " → ".join(f"{amt(l, p)} ({str(w)[:10]})" for w, p in ph["history"])
            st.markdown(f'<div class="muted" style="margin-top:6px">📉 Price: {steps} '
                        f'[{ph["change_pct"]:+.1%}]</div>', unsafe_allow_html=True)
        if len(l.get("_copies") or []) > 1:
            links = " · ".join(
                f'<a href="{safe_href(c.get("url"))}" target="_blank">{esc((c.get("source") or "").upper())} '
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
                if cz_mkt:
                    _prof = markets.get("cz")
                    inv_ltv, base_rate, base_term = (_prof.ltv_ratio_investor,
                                                     _prof.mortgage_rate_pa, _prof.loan_term_years)
                else:
                    from config import LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA, LOAN_TERM_YEARS
                    inv_ltv, base_rate, base_term = LTV_RATIO_INVESTOR, MORTGAGE_RATE_PA, LOAN_TERM_YEARS
                inv = _an(price, size, district or "", rent_override=rent or None,
                          ltv=inv_ltv,
                          rate=l.get("mortgage_rate_used") or base_rate,
                          term_years=int(l.get("loan_term_years") or base_term), **mkw(l))
                sts = l.get(f"stress_surplus_{stress_k}")
                s_sro = stress_k == "sro"
                inv_s = inv.surplus_sro if s_sro else inv.surplus_personal
                inv_r = inv.ratio_sro if s_sro else inv.ratio_personal
                inv_c = inv.total_cash_invested_sro if s_sro else inv.total_cash_invested
                html = (f'<div class="muted" style="margin-top:10px">{T("FINANCING STRESS")} — '
                        f'{"s.r.o." if s_sro else T("Personal")}</div>')
                if sts is not None:
                    html += (f'<div class="brow {"pos" if sts >= 0 else "neg"}"><span class="l">{T("Rate +2 pp")}</span>'
                             f'<span class="v">{sgn(l, sts)} · {T("self-funding")} '
                             f'{fp(l.get(f"stress_ratio_{stress_k}"))}</span></div>')
                html += (f'<div class="brow {"pos" if inv_s >= 0 else "neg"}"><span class="l">{T("70% LTV (3rd+ flat)")}</span>'
                         f'<span class="v">{sgn(l, inv_s)} · {T("self-funding")} {fp(inv_r)} · '
                         f'{T("cash in")} {amt(l, inv_c)}</span></div>')
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
        a1,a2,a3,a4,a5,a6 = st.columns(6)
        with a1: st.link_button(T("VIEW LISTING"), safe_url(l.get("url")), width="stretch")
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
        with a6:
            render_offer_sheet_button(l, key=f"offer_{lid}")

        # The flat's own LV — the only thing that can verify it. The building
        # plot found from the map pin is a different LV (see modules/debt_bot).
        # The boxes reload when the stored LV changes (saved in LV TO-DO, say):
        # RE-VERIFY LV takes a box that differs from the stored LV as an edit,
        # and a stale box would clear the saved number or put back an old one.
        # A photo or scan of the LV (the agent's phone picture): Claude copies
        # it into the boxes below (modules/doc_reader).
        _lv_photo(lid, cz_mkt, using_demo, words=cz)
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
        if cz_mkt:
            # As the LV boxes: a výpis pasted since (in the REJECTED tab, say)
            # reloads the box, so RE-VERIFY LV can't write the old text back.
            _load_box(f"lvdoc_{lid}", _LV_DOCS.get(lid, ""))
            lv_doc = st.text_area(
                T("LV extract (text)"), key=f"lvdoc_{lid}",
                height=110, disabled=using_demo,
                placeholder=("Vložte text výpisu z listu vlastnictví…" if cz else
                             "Paste the text of the title deed (výpis z LV)…"),
                help=("Text výpisu z LV této jednotky (CzechPOINT nebo dálkový přístup "
                      "ČÚZK). Bezplatné služby katastru obsah LV programu nedávají; "
                      "OVĚŘIT LV jej projde (části C a D)." if cz else
                      "The text of this flat's title deed (from CzechPOINT or the ČÚZK "
                      "remote access). The cadastre's free services don't give a program "
                      "the deed's content; RE-VERIFY LV reads it (parts C and D)."))
        if verify:
            try:
                from modules.debt_bot import reverify
                if cz_mkt and (lv_doc or "").strip() != _LV_DOCS.get(lid, "").strip():
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
                st.warning(f"Re-verify: {redact(e)}")

        # UX7: a question about this flat, answered by Claude from its figures.
        from dashboard import ask
        ask.render(l, using_demo, cz, deal_score, deal_grade)

        from dashboard.lv_view import render_erase, render_part_c
        render_part_c(l, _LV_DOCS)
        render_erase(l, disabled=using_demo)
        if not using_demo:
            from dashboard.building_view import render_building, render_short_let
            render_building(l, cz_mkt, words=cz)
            render_short_let(l, cz_mkt, words=cz)

        seen = last_seen_label(l, cz)
        seen = f" · {seen}" if seen else ""
        if cz:
            st.markdown(f'<div class="muted">Zdroj: {esc((l.get("source") or "").upper())} · Tento přehled jej poprvé viděl: {esc((l.get("scraped_at") or "")[:10])}{seen}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="muted">Source: {esc((l.get("source") or "").upper())} · First seen by this dashboard: {esc((l.get("scraped_at") or "")[:10])}{seen}</div>', unsafe_allow_html=True)


def grade_breakdown_html(l) -> str:
    """The deal grade's parts as rows (engine.financial.deal_score_parts):
    points out of each part's maximum and why, then the total."""
    from engine.financial import compute_deal_score, deal_score_parts
    parts = deal_score_parts(l)
    score, grade = compute_deal_score(l)
    if not parts:
        return '<div class="muted">No financial figures yet — no grade.</div>'
    rows = "".join(
        f'<div class="brow"><span class="l">{esc(p["part"])} — {esc(p["why"])}</span>'
        f'<span class="v">{p["points"]:.1f} / {p["max"]}</span></div>' for p in parts)
    got = sum(p["points"] for p in parts)
    top = sum(p["max"] for p in parts)
    return (rows + f'<div class="brow tot"><span class="l">{got:.1f} of {top} points = {score}/100 '
                   f'→ grade {grade}</span><span class="v">A ≥ 80 · B ≥ 65 · C ≥ 50</span></div>'
            '<div class="muted" style="margin-top:6px">A part with no data (location not scored, '
            'energy class or condition unknown) is left out of the total, so the grade is over '
            'what is known.</div>')


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
        st.download_button("MEMO PDF", pdf, icon=":material/download:",
                           file_name=f"memo_{(l.get('id') or 'x')[:8]}_{made:%Y%m%d}.pdf",
                           mime="application/pdf", key=f"{key}_dl", width="stretch")
    elif st.button("MEMO", icon=":material/description:", key=key, width="stretch"):
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
            st.warning(f"Memo: {redact(e)}")


def render_offer_sheet_button(l, key):
    """📑 OFFER SHEET: built on the first click (it reads the other active
    listings for its comparables), then offered for download — as the memo."""
    from modules.memo import memo_fingerprint
    ready = st.session_state.setdefault("offer_ready", {})
    sig = memo_fingerprint(l)
    kept = ready.get(key)
    if kept is not None and kept[0] != sig:
        ready.pop(key, None)
        kept = None
    if kept is not None:
        st.download_button("OFFER PDF", kept[1], icon=":material/download:",
                           file_name=f"offer_{(l.get('id') or 'x')[:8]}.pdf",
                           mime="application/pdf", key=f"{key}_dl", width="stretch")
    elif st.button("OFFER SHEET", icon=":material/request_quote:", key=key, width="stretch",
                   help="One page for the viewing: your max offer, flats like it listed now, "
                        "time on the market and price cuts."):
        import markets
        from database import get_all_active
        from modules.offer_sheet import build_offer_sheet, comparables
        try:
            mkt = markets.of_row(l)
            comps = comparables(l, get_all_active(market=mkt))
            ready[key] = (sig, build_offer_sheet(l, comps, days_listed=l.get("_dom")))
            st.rerun()
        except Exception as e:
            st.warning(f"Offer sheet: {redact(e)}")


CARDS_PER_PAGE = 25


def compact_cards_html(listings, v) -> str:
    """The compact cards of one page, as one block of HTML: for each listing
    its title, price, class, monthly surplus and one button — the portal's
    own page. No widgets, so a page of them costs a phone almost nothing."""
    out = []
    for l in listings:
        cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
        emoji = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪"}.get(cls, "⏳")
        surplus = v.surplus(l)
        tone = "" if surplus is None else ("neg" if v.cf_negative(l) else "pos")
        disc = l.get("market_discount")
        below = (f" · {abs(disc):.0%} {'below' if disc >= 0 else 'above'} market"
                 if disc is not None else "")
        stage = (l.get("_stage") or {}).get("stage")
        out.append(
            f'<div class="cc {"g" if cls == "GREEN" else "y" if cls == "YELLOW" else ""}">'
            f'<div class="cct">{emoji} {esc((l.get("title") or l.get("district") or "—")[:70])}'
            f'</div><div class="ccm">{amt(l, l.get("price_eur") or 0)} · {cls}{below} · '
            f'<span class="{tone}">{sgn(l, surplus)}</span>'
            + (f" · [{esc(stage)}]" if stage else "") + "</div>"
            + (f'<a class="ccb" href="{safe_href(l["url"])}" target="_blank">OPEN LISTING ↗</a>'
               if l.get("url") else "") + "</div>")
    return "".join(out)


def render_cards(listings, section, v, compact: bool = False):
    """One page of a section's cards, so a click never redraws hundreds of
    them. The picker's key carries the count: when the filters change how
    many there are, the section starts again at its first page. `compact`
    draws the page as compact cards (compact_cards_html) instead."""
    pages = -(-len(listings) // CARDS_PER_PAGE)
    page = 0
    if pages > 1:
        n = len(listings)
        page = st.selectbox(
            "Cards", range(pages), key=f"page_{section}_{n}", width=260,
            format_func=lambda p: f"{p * CARDS_PER_PAGE + 1}–"
                                  f"{min((p + 1) * CARDS_PER_PAGE, n)} of {n}")
    shown = listings[page * CARDS_PER_PAGE:(page + 1) * CARDS_PER_PAGE]
    if compact:
        st.markdown(compact_cards_html(shown, v), unsafe_allow_html=True)
        return
    for l in shown:
        render_card(l, v)
