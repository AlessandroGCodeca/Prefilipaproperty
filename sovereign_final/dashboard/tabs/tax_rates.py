"""
dashboard/tabs/tax_rates.py — TAX RATES: each Slovak town's property-tax
rate read from its own site, the ones held for review, and each Czech
municipality's coefficients.
"""

import math
import re

import pandas as pd
import streamlit as st

from modules import jobs

from dashboard.actions import _cf_step, _tax_step
from dashboard.fmt import _SHOW


# ── Property-tax rates ────────────────────────────────────────────────────────
def _plain(text) -> str:
    """Text read from a town's site, shown in markdown as written: no link,
    image or emphasis it happens to spell."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~])", r"\\\1", "" if text is None else str(text))


def _tax_rescore(note: str) -> None:
    """After a decision on a town's rate: its listings are re-scored as a job."""
    _why = jobs.start("CASHFLOW SCORE", _cf_step)
    st.session_state["tax_msg"] = ("success", note + (
        f" Re-scoring when the running job ends — {_why}" if _why else " Re-scoring its listings."))
    if not _why:
        st.session_state["_job_watch"] = jobs.current().id
    st.rerun()


def _tax_rates_tab():
    from modules import tax_rates as tr
    st.markdown('<div class="muted">PROPERTY TAX — DAŇ Z BYTOV, €/m² OF A FLAT A YEAR, READ FROM '
                'EACH TOWN\'S OWN ORDINANCE OR RATE PAGE</div>', unsafe_allow_html=True)
    rows = tr.check_rows()
    checked = [r for r in rows if r["checked_at"]]
    c1, c2 = st.columns([1, 3])
    with c1:
        go = st.button("🏛️ UPDATE TAX RATES", key="tax_update_tab", type="primary",
                       width="stretch", disabled=jobs.running(),
                       help="The same as the sidebar button.")
    with c2:
        if checked:
            counts: dict[str, int] = {}
            for r in checked:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            last = max(r["checked_at"] for r in checked)[:16].replace("T", " ")
            st.caption(f"Last checked {last} UTC · " + " · ".join(
                f"{tr.STATUS_LABEL.get(k, k)} {v}" for k, v in sorted(counts.items())))
        else:
            st.caption("Not checked yet. One click reads every town's ordinance or rate page "
                       "(a few minutes, in the background) and applies only what is clearly "
                       "newer than the table; anything doubtful waits here for you.")
    if go:
        _why = jobs.start("TAX RATES", _tax_step)
        if _why:
            st.warning(_why)
        else:
            st.session_state["_job_watch"] = jobs.current().id
            st.rerun()
    msg = st.session_state.pop("tax_msg", None)
    if msg:
        _SHOW.get(msg[0], st.info)(msg[1])

    reviews = [r for r in rows if r["status"] == "review"]
    # The table's towns and the user's first, then the municipalities.
    reviews.sort(key=lambda r: (r["kind"] == "municipality", r["town"]))
    if reviews:
        st.markdown(f"##### ⚠️ Waiting for your decision ({len(reviews)})")
        if len(reviews) > 12:
            single = [r["town"] for r in reviews if len(r["found"]) == 1 and not r["zoned"]]
            with st.expander(f"Accept several at once — {len(single)} with a single rate"):
                pick = st.multiselect("Municipalities", single, key="tax_bulk_pick",
                                      format_func=lambda t: f"{t} — " + next(
                                          tr.rate_text(r["found"][0]) for r in reviews
                                          if r["town"] == t) + " €/m²")
                if st.button("Accept the selected", key="tax_bulk_go", disabled=not pick):
                    errs = [e for e in (tr.accept(t) for t in pick) if e]
                    _tax_rescore(f"✅ {len(pick) - len(errs)} accepted."
                                 + (f" {len(errs)} not: {errs[0]}" if errs else ""))
        for r in reviews[:12]:
            with st.container(border=True):
                st.markdown(f"**{_plain(r['town'])}** · charged now "
                            f"{tr.rate_text(r['charged'])} €/m²")
                st.caption(_plain(r["message"]))
                if r["excerpt"]:
                    st.code(r["excerpt"], language=None, wrap_lines=True)
                if r["source_url"].startswith("http"):
                    st.markdown(f"[Open the document]({r['source_url'].replace(')', '%29')})")
                if r["zoned"] or not r["found"]:
                    continue
                b1, b2, b3 = st.columns([2, 2, 3])
                rate = r["found"][0]
                if len(r["found"]) > 1:
                    with b3:
                        rate = st.selectbox("The rate in force", r["found"],
                                            key=f"tax_pick_{r['town']}",
                                            format_func=lambda v: f"{tr.rate_text(v)} €/m²")
                with b1:
                    if st.button(f"Accept {tr.rate_text(rate)} €/m²", key=f"tax_acc_{r['town']}",
                                 width="stretch"):
                        _err = tr.accept(r["town"], rate)
                        if _err:
                            st.session_state["tax_msg"] = ("error", _err)
                            st.rerun()
                        _tax_rescore(f"✅ {r['town']}: {tr.rate_text(rate)} €/m² accepted.")
                with b2:
                    if st.button("Keep the table's figure", key=f"tax_keep_{r['town']}",
                                 width="stretch"):
                        tr.keep(r["town"])
                        st.session_state["tax_msg"] = ("info", f"{r['town']}: the table's "
                                                               f"figure stays.")
                        st.rerun()

    from engine import property_tax_sk as _ptx
    villages = [r for r in rows if r["kind"] == "municipality"]
    read = [r for r in villages if r["status"] in ("confirmed", "applied", "upcoming", "new",
                                                   "review", "kept")]
    st.caption(f"{len(rows) - len(villages)} towns in the table or added by you, and "
               f"{len(villages):,} other municipalities from their own websites: "
               f"{len(read):,} read with a rate, "
               f"{sum(1 for r in villages if r['status'] == 'blocked'):,} blocked, "
               f"{sum(1 for r in villages if r['status'] == 'not_found'):,} without a readable "
               f"rate, {sum(1 for r in villages if not r['status']):,} not read yet. A village "
               f"is read again once a month.")
    everything = st.toggle("Show every municipality", key="tax_show_all", value=False)
    shown = rows if everything else [r for r in rows if r["kind"] != "municipality" or r in read]
    table = []
    for r in shown:
        zoned = _ptx.table_rates(r["town"]) if r["zoned"] else []
        table.append({
            "Town": r["town"],
            "Charged €/m²": (f"{tr.rate_text(zoned[0])}–{tr.rate_text(zoned[-1])} by area"
                             if len(zoned) > 1 else tr.rate_text(r["charged"])),
            "Status": tr.STATUS_LABEL.get(r["status"], "not checked"),
            "Site says": (" / ".join(tr.rate_text(v) for v in r["found"]) if r["found"] else ""),
            "From": str(r["found_year"] or ""),
            "Document": r["document"],
            "Source": r["source_url"] if r["source_url"].startswith("http") else None,
            "Checked": r["checked_at"][:10],
            "Note": r["message"],
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch", height=420,
                 column_config={"Source": st.column_config.LinkColumn(display_text="open")})
    st.caption(f"Charged: the rate the engine uses now — the table checked by hand for "
               f"{_ptx.TABLE_YEAR}, a rate from a later year's ordinance, a town the table "
               f"lacks, or one you accepted. A town rated by area (Bratislava, Košice, Žilina, "
               f"Dunajská Streda) is only verified here. A place in no row pays "
               f"{tr.rate_text(_ptx.UNKNOWN_PLACE_RATE_PER_M2)} €/m² (UNVERIFIED).")

    with st.expander("📄 Upload a town's ordinance — for a site that blocks automated requests"):
        st.caption("Open the town's site in your browser, download its VZN o miestnych daniach "
                   "(or its rate page, saved as PDF) and drop it here. The flat rate is read from "
                   "it and charged from the year it states.")
        names = [r["town"] for r in rows]
        stuck = [r["town"] for r in rows if r["status"] in ("blocked", "not_found")]
        town = st.selectbox("Town", names, index=names.index(stuck[0]) if stuck else 0,
                            key="tax_up_town")
        up = st.file_uploader("Ordinance or rate sheet", type=["pdf", "docx", "odt", "html", "htm"],
                              key="tax_up_file")
        if st.button("Read it", key="tax_up_go", disabled=up is None):
            status, note = tr.upload(town, up.name, up.getvalue())
            if status == "applied":
                _tax_rescore("✅ " + note)
            st.session_state["tax_msg"] = ("warning" if status == "review" else "error", note)
            st.rerun()

    with st.expander("➕ Add a town"):
        st.caption("Its name as the listings write it, and the page that links to its "
                   "property-tax ordinance: the town's tax page, its list of ordinances, or a "
                   "search of its site for \"miestnych daniach\". The next update reads it.")
        with st.form("tax_add_town", clear_on_submit=True):
            name = st.text_input("Town")
            url = st.text_input("Start page (https://…)")
            if st.form_submit_button("Add"):
                _err = tr.add_town(name, url)
                st.session_state["tax_msg"] = (("error", _err) if _err else
                                               ("success", f"✅ {name.strip()} added — click "
                                                           f"🏛️ UPDATE TAX RATES to read it."))
                st.rerun()
        custom = [r["town"] for r in rows if r["custom"]]
        if custom:
            gone = st.selectbox("Remove a town you added", custom, key="tax_rm_town")
            if st.button("Remove", key="tax_rm_go"):
                tr.remove_town(gone)
                _tax_rescore(f"{gone} removed.")

    stored = [r["town"] for r in rows if r["stored"]]
    if stored:
        with st.expander("↩️ Undo — charge the table's figure again"):
            back = st.selectbox("Town", stored, key="tax_undo_town")
            r = next(x for x in rows if x["town"] == back)
            st.caption(" · ".join(f"{s['tax_year']}: {tr.rate_text(s['rate'])} €/m² "
                                  f"({s['origin']}, {_plain(s['document'] or s['source_url'])})"
                                  for s in r["stored"]))
            if st.button(f"Forget {back}'s stored rates", key="tax_undo_go"):
                n = tr.revert(back)
                _tax_rescore(f"↩️ {back}: {n} stored rate(s) forgotten.")

    if checked:
        with st.expander("🔍 What was read, town by town"):
            pick = st.selectbox("Town", [r["town"] for r in checked], key="tax_detail_town")
            r = next(x for x in checked if x["town"] == pick)
            st.caption("Started from: " + " · ".join(_plain(u) for u in r["start"]))
            d = r["detail"]
            if d.get("upcoming"):
                u = d["upcoming"]
                st.caption(f"Published for {u['tax_year']}: "
                           f"{' / '.join(tr.rate_text(v) for v in u['rates'])} €/m² "
                           f"({_plain(u['document'])})")
            for url, what in d.get("visited", []):
                st.markdown(f"- {_plain(what)} — {_plain(url)}")
            for p in d.get("problems", []):
                st.caption("⚠ " + _plain(p))


def _tax_rates_tab_cz():
    from modules import tax_rates_cz as trc
    from engine import property_tax_cz as ptc
    st.markdown('<div class="muted">🇨🇿 PROPERTY TAX — DAŇ Z NEMOVITÝCH VĚCÍ ON A FLAT: EVERY '
                'MUNICIPALITY\'S SIZE AND LOCAL COEFFICIENTS, FROM ITS ORDINANCES IN SBIRKAPP.GOV.CZ '
                'AND THE STATISTICAL OFFICE\'S POPULATION</div>', unsafe_allow_html=True)
    rows = trc.table()
    last = trc.last_run()
    if not last:
        st.caption("Not read yet: 🏛️ UPDATE TAX RATES reads every Czech municipality's "
                   "coefficients (a few minutes the first time, about a minute after that). "
                   "Until then Prague, the statutory cities and the 105 other towns over 10,000 "
                   "pay their hand-checked 2026 figures, and every other municipality the size "
                   "coefficient for its population and local coefficient 1.0.")
        if st.button("🏛️ UPDATE TAX RATES", key="tax_update_tab_cz", type="primary",
                     disabled=jobs.running()):
            _why = jobs.start("TAX RATES", _tax_step)
            if _why:
                st.warning(_why)
            else:
                st.session_state["_job_watch"] = jobs.current().id
                st.rerun()
        return
    from engine.property_tax_sk import _year as _tax_year
    ahead = len(trc.table(_tax_year() + 1)) - len(rows)
    st.caption(f"Read {last[:16].replace('T', ' ')} UTC · {len(rows):,} municipalities set "
               f"coefficients by ordinance for {_tax_year()}"
               + (f" ({ahead:,} more from {_tax_year() + 1}, already published)" if ahead > 0 else "")
               + "; the others pay the act's: the size coefficient by "
               f"population (1.0–3.5, Prague 4.5) and local 1.0. Prague, the statutory cities and "
               f"the 105 other towns over 10,000 pay their hand-checked {ptc.TABLE_YEAR} figures, "
               f"and a later year's reading only where it changed. A flat pays floor area × 1.22 × "
               f"{ptc.RATE_PER_M2:.2f} Kč × size × local.")
    place = st.text_input("Look up a place, as a listing names it", key="tax_cz_lookup",
                          placeholder="Praha 3, Brno-střed, Olomouc …")
    if place.strip():
        size, local, why = ptc.coefficients(place)
        st.markdown(f"**{_plain(place)}**: size {size:g} × local {local:g} → a 60 m² flat pays "
                    f"**{ptc.annual_tax(60, place):,.0f} Kč** a year")
        st.caption(_plain(why))
    table = []
    for r in rows:
        main_size, main_local = r["size"][""], r["local"][""]
        parts = sorted((set(r["size"]) | set(r["local"])) - {""})
        table.append({
            "Municipality": r["name"], "District": r["okres"],
            "Population": r["population"],
            "Size": main_size, "Local": main_local,
            "By area": (f"{len(parts)} areas differ" if parts else ""),
            # 60 m² × 1.22 → 74 m², each product rounded up to a crown (§ 11d).
            "60 m² a year, Kč": math.ceil(math.ceil(74 * ptc.RATE_PER_M2 * main_size - 1e-9)
                                          * main_local - 1e-9),
            "Charged": ("this reading" if not ptc.in_tables(r["name"], r["okres"])
                        else "the hand-checked table" if _tax_year() <= ptc.TABLE_YEAR
                        else "the table, unless this reading changed since "
                             f"{ptc.TABLE_YEAR}"),
            "Ordinances": "; ".join(r["sources"]),
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch", height=420,
                 column_config={"Population": st.column_config.NumberColumn(format="%d")})
    bad = trc.unreadable()
    if bad:
        with st.expander(f"📄 {len(bad)} ordinances couldn't be read — an old .doc file or a scan"):
            st.caption("Those municipalities pay the act's defaults here. Each link opens the "
                       "ordinance in the collection.")
            st.dataframe(pd.DataFrame(bad), hide_index=True, width="stretch",
                         column_config={"url": st.column_config.LinkColumn(display_text="open")})


def render(v) -> None:
    """The TAX RATES tab."""
    view_market = v.market
    if view_market != "cz":
        _tax_rates_tab()
    if view_market is None:
        st.markdown('<hr class="div">', unsafe_allow_html=True)
    if view_market != "sk":
        _tax_rates_tab_cz()
