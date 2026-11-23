"""
dashboard/tabs/portfolio.py — PORTFOLIO: the flats you own, as they really
do (database/portfolio, engine/portfolio): loan balance, equity, the last
twelve months, tax, and the model's assumptions against your figures.
"""

from datetime import date

import streamlit as st

from dashboard.fmt import esc

_FIELDS = (
    # key, label, kind, help
    ("name", "Name", "text", "How you call it, e.g. Žilina Vlčince 2i"),
    ("market", "Market", "market", ""),
    ("district", "District / town", "text", "As the listings name it — picks the rent and median"),
    ("size_m2", "Size m²", "num", ""),
    ("rooms", "Rooms", "int", ""),
    ("bought_on", "Bought on (YYYY-MM-DD)", "text", ""),
    ("price", "Price paid", "num", ""),
    ("buying_costs", "Buying costs", "num", "Notary, cadastre, agent, bank"),
    ("structure", "Owner", "structure", ""),
    ("loan_principal", "Loan amount", "num", "0 without a loan"),
    ("loan_rate", "Loan rate % a year", "pct", ""),
    ("loan_years", "Loan term (years)", "int", ""),
    ("loan_start", "First payment (YYYY-MM-DD)", "text", "Blank: the purchase date"),
    ("fixation_years", "Rate fixed for (years)", "int", "0: whole term"),
    ("reset_rate", "Rate after the fixation %", "pct", ""),
    ("rent_monthly", "Rent a month (contract)", "num", ""),
    ("hoa_monthly", "Building fee a month (správa + fond)", "num", ""),
    ("other_costs_monthly", "Other costs a month", "num", "Insurance, repairs reserve, agent"),
    ("value_estimate", "Value today (blank: district median)", "num", ""),
    ("notes", "Notes", "text", ""),
)


def _money(v, cur) -> str:
    return f"{'−' if v < 0 else ''}{'Kč ' if cur == 'CZK' else '€'}{abs(v):,.0f}"


def _form(prefix: str, have: dict, disabled: bool) -> dict:
    out = {}
    cols = st.columns(3)
    for i, (key, label, kind, help_) in enumerate(_FIELDS):
        with cols[i % 3]:
            v = have.get(key)
            k = f"{prefix}_{key}"
            if kind == "market":
                out[key] = st.selectbox(label, ("sk", "cz"), index=1 if v == "cz" else 0,
                                        key=k, disabled=disabled)
            elif kind == "structure":
                out[key] = st.selectbox(label, ("personal", "sro"),
                                        index=1 if v == "sro" else 0, key=k, disabled=disabled)
            elif kind == "num":
                out[key] = st.number_input(label, min_value=0.0, value=float(v or 0), step=100.0,
                                           key=k, disabled=disabled, help=help_ or None)
            elif kind == "int":
                out[key] = st.number_input(label, min_value=0, value=int(v or 0), step=1, key=k,
                                           disabled=disabled, help=help_ or None)
            elif kind == "pct":
                out[key] = st.number_input(label, min_value=0.0, max_value=25.0,
                                           value=float(v or 0) * 100, step=0.05, format="%.2f",
                                           key=k, disabled=disabled) / 100
            else:
                out[key] = st.text_input(label, value=v or "", key=k, disabled=disabled,
                                         help=help_ or None)
    return {k: (None if v in (0, 0.0, "") and k not in ("name",) else v) for k, v in out.items()}


def render(v) -> None:
    """The PORTFOLIO tab."""
    from database.portfolio import (delete_owned_flat, get_ledger, get_owned_flats,
                                    save_owned_flat, set_ledger_month)
    from engine.portfolio import calibration, flat_numbers
    disabled = v.using_demo
    st.markdown('<div class="muted" style="margin-bottom:6px">PORTFOLIO — THE FLATS YOU OWN: loan '
                'balance, equity, the last twelve months as they were, the tax on them — and the '
                'model\'s assumptions against your own figures.</div>', unsafe_allow_html=True)
    flats = [] if disabled else get_owned_flats()
    ledger = [] if disabled else get_ledger()
    numbers = [flat_numbers(f, [m for m in ledger if m["flat_id"] == f["id"]]) for f in flats]
    if numbers:
        for cur in sorted({n.currency for n in numbers}):
            sub = [n for n in numbers if n.currency == cur]
            c = st.columns(4)
            c[0].metric("Value", _money(sum(n.value for n in sub), cur))
            c[1].metric("Loans left", _money(sum(n.balance for n in sub), cur))
            c[2].metric("Equity", _money(sum(n.equity for n in sub), cur))
            c[3].metric("Cash flow, 12 months", _money(sum(n.cash_flow_12m for n in sub), cur))
        import pandas as pd
        st.dataframe(pd.DataFrame([{
            "Flat": n.name, "Value": round(n.value), "Value from": n.value_source,
            "Loan left": round(n.balance), "Equity": round(n.equity),
            "Rent 12 m": round(n.rent_12m), "Costs 12 m": round(n.costs_12m),
            "Loan payments 12 m": round(n.payment * 12), "Tax (est.)": round(n.tax_year_est),
            "Cash flow 12 m": round(n.cash_flow_12m),
            "Gross yield %": round(n.gross_yield * 100, 2), "Net yield %": round(n.net_yield * 100, 2),
            "Months on record": n.months_on_record} for n in numbers]),
            hide_index=True, width="stretch")
        rows = calibration(flats, numbers)
        if rows:
            st.markdown('<div class="muted" style="margin-top:8px">THE MODEL AGAINST YOUR FLATS — '
                        'where they differ a lot, set your own figures (YOUR SITUATION, .env) '
                        'or treat the scores with care</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(rows).astype(object).fillna("—"), hide_index=True, width="stretch")
    else:
        st.info("No flat yet. Add the ones you own below — or one you just bought from DEAL "
                "PIPELINE (stage CLOSED) with “Start from a deal”.")

    with st.expander("➕ Add a flat you own"):
        start = {}
        if not disabled:
            # The page's cached stages and listings: a rerun reads no table.
            from dashboard.listing_cache import page_context
            closed = {k: s for k, s in page_context()[1].items() if s.get("stage") == "CLOSED"}
            if closed:
                rows_by_id = {l["id"]: l for l in v.data if l["id"] in closed}
                pick = st.selectbox("Start from a deal (stage CLOSED)", ["—"] + [
                    f"{(l.get('title') or '')[:50]} [{lid[:8]}]" for lid, l in rows_by_id.items()],
                    key="pf_from_deal")
                if pick != "—":
                    lid = next(i for i in rows_by_id if f"[{i[:8]}]" in pick)
                    l = rows_by_id[lid]
                    start = {"name": (l.get("title") or "")[:60], "market": l.get("market") or "sk",
                             "district": l.get("district"), "size_m2": l.get("size_m2"),
                             "rooms": l.get("rooms"), "price": l.get("price_eur"),
                             "rent_monthly": l.get("estimated_rent_eur"),
                             "hoa_monthly": l.get("hoa_monthly"), "listing_id": lid}
        with st.form("pf_add", border=False):
            vals = _form("pf_new", start, disabled)
            if st.form_submit_button("💾 ADD THIS FLAT", disabled=disabled):
                try:
                    save_owned_flat({**vals, "listing_id": start.get("listing_id")})
                    st.rerun()
                except ValueError as e:
                    st.warning(str(e).capitalize() + ".")

    for f in flats:
        with st.expander(f"✏️ {f['name']} — edit · this month's figures"):
            with st.form(f"pf_edit_{f['id']}", border=False):
                vals = _form(f"pf_{f['id']}", f, disabled)
                if st.form_submit_button("💾 SAVE", disabled=disabled):
                    save_owned_flat({**vals, "listing_id": f.get("listing_id")}, f["id"])
                    st.rerun()
            st.markdown('<div class="muted">A MONTH AS IT WAS — rent that came in, every cost you '
                        'paid (fee, repairs, insurance), days it stood empty</div>',
                        unsafe_allow_html=True)
            with st.form(f"pf_month_{f['id']}", border=False):
                m1, m2, m3, m4 = st.columns(4)
                today = date.today()
                month = m1.text_input("Month", value=f"{today.year}-{today.month:02d}",
                                      key=f"pfm_m_{f['id']}")
                rent = m2.number_input("Rent received", min_value=0.0, step=10.0,
                                       value=float(f.get("rent_monthly") or 0), key=f"pfm_r_{f['id']}")
                costs = m3.number_input("Costs paid", min_value=0.0, step=10.0,
                                        key=f"pfm_c_{f['id']}")
                empty = m4.number_input("Days empty", min_value=0, max_value=31, step=1,
                                        key=f"pfm_e_{f['id']}")
                if st.form_submit_button("💾 RECORD THE MONTH", disabled=disabled):
                    try:
                        set_ledger_month(f["id"], month.strip(), rent, costs, int(empty))
                        st.rerun()
                    except ValueError as e:
                        st.warning(str(e))
            done = [m for m in ledger if m["flat_id"] == f["id"]][-12:]
            if done:
                st.markdown("".join(
                    f'<div class="brow"><span class="l">{esc(m["month"])}</span><span class="v">'
                    f'rent {m.get("rent_received") or 0:,.0f} · costs {m.get("costs") or 0:,.0f}'
                    f'{" · empty " + str(m["vacant_days"]) + " d" if m.get("vacant_days") else ""}'
                    f'</span></div>' for m in done), unsafe_allow_html=True)
            if st.button("🗑 Remove this flat", key=f"pf_del_{f['id']}", disabled=disabled):
                delete_owned_flat(f["id"])
                st.rerun()
