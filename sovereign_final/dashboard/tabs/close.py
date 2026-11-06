"""
dashboard/tabs/close.py — ONE-CLICK CLOSE: the notary contract draft and the
internal analysis for a listing, and the drafts saved before.
"""

import streamlit as st

import markets

from dashboard.fmt import _local_stamp, amt


def render(v) -> None:
    """The ONE-CLICK CLOSE tab."""
    data = v.data
    hidden_note = v.hidden_note
    n_hidden = v.n_hidden
    using_demo = v.using_demo
    st.markdown('<div class="muted">ONE-CLICK CLOSE — NOTARY CONTRACT DRAFT GENERATOR</div>', unsafe_allow_html=True)
    # The warning names the country's own way to a valid contract, so it is
    # written once the listing is chosen.
    close_hdr = st.empty()
    _sk_close_hdr = '<div class="muted" style="color:#ff5252;margin-bottom:16px">⚠️ DRAFT ONLY — no legal validity until executed before a licensed Slovak notár</div>'

    if not data:
        close_hdr.markdown(_sk_close_hdr, unsafe_allow_html=True)
        st.info(hidden_note() if n_hidden else "No listings loaded.")
    else:
        opts = {f"{l.get('title') or '?'} — {amt(l, l.get('price_eur') or 0)} [{(l.get('id') or '')[:6]}]": l
                for l in data}
        sel3 = opts[st.selectbox("Select listing", list(opts.keys()), key="close_sel")]
        # A Czech flat gets the Czech draft (modules/contract_draft_cz): a
        # kupní smlouva for a Czech advokát, amounts in Kč.
        close_cz = markets.of_row(sel3) == "cz"
        close_hdr.markdown(
            '<div class="muted" style="color:#ff5252;margin-bottom:16px">⚠️ DRAFT ONLY — no '
            'legal validity until a Czech advokát or notář completes it; ownership passes on '
            'its entry (vklad) into the katastr nemovitostí</div>' if close_cz else _sk_close_hdr,
            unsafe_allow_html=True)
        if close_cz:
            st.warning("🇨🇿 Kupní smlouva — NÁVRH k posouzení českým advokátem (nebo notářem); "
                       "nejde o právní radu ani o hotovou smlouvu.")

        f1, f2 = st.columns(2)
        with f1:
            st.markdown("**BUYER**")
            buyer_name = st.text_input("Full Name / s.r.o. Name")
            buyer_ico  = st.text_input("IČO (if s.r.o., leave blank if personal)")
            ownership  = st.radio("Structure", ["Personal", "s.r.o."], horizontal=True)
        with f2:
            st.markdown("**DEAL**")
            if close_cz:
                # The deposit default is the Slovak one (€2 000) in crowns, rounded.
                agreed  = st.number_input("Agreed Price Kč", value=int(sel3.get("price_eur") or 0),
                                          step=10_000)
                notary  = st.text_input("Advokát / notář")
                escrow  = st.checkbox("Úschova kupní ceny (escrow hold)", value=True)
                deposit = st.number_input("Deposit Kč (záloha)", 0, 2_000_000, 50_000, 10_000)
            else:
                agreed     = st.number_input("Agreed Price €", value=int(sel3.get("price_eur") or 0), step=500)
                notary     = st.text_input("Notár Name")
                escrow     = st.checkbox("Notárska úschova (escrow hold)", value=True)
                deposit    = st.number_input("Deposit € (earnest money)", 0, 50000, 2000, 500)

        if st.button("GENERATE CONTRACT DRAFT", width="stretch"):
            if not buyer_name.strip():
                st.error("Enter buyer name first.")
            else:
                # Bratislava time on the draft, the note, their file names and
                # EARLIER DRAFTS alike, whatever the host's clock is set to.
                from modules.contract_draft import local_now
                now = local_now()
                if close_cz:
                    from modules.contract_draft_cz import (
                        build_contract_draft_cz, build_internal_analysis_cz,
                    )
                    draft = build_contract_draft_cz(
                        sel3, buyer_name=buyer_name.strip(), buyer_ico=buyer_ico,
                        ownership=ownership, agreed_price=agreed, deposit=deposit,
                        lawyer=notary, escrow=escrow, generated_at=now)
                    analysis = build_internal_analysis_cz(sel3, agreed_price=agreed,
                                                          generated_at=now)
                else:
                    from modules.contract_draft import build_contract_draft, build_internal_analysis
                    draft = build_contract_draft(
                        sel3, buyer_name=buyer_name.strip(), buyer_ico=buyer_ico,
                        ownership=ownership, agreed_price=agreed, deposit=deposit,
                        notary=notary, escrow=escrow, generated_at=now)
                    # The deal's numbers used to sit inside the draft you send to
                    # the notár; they are a separate note now.
                    analysis = build_internal_analysis(sel3, agreed_price=agreed, generated_at=now)

                st.text_area("CONTRACT DRAFT", draft, height=500)
                stamp = now.strftime('%Y%m%d_%H%M')
                # on_click="ignore": a rerun would clear the draft and the
                # other download with it.
                st.download_button(
                    "⬇️ DOWNLOAD DRAFT",
                    draft,
                    file_name=f"contract_{sel3['id'][:8]}_{stamp}.txt",
                    mime="text/plain",
                    on_click="ignore",
                    width="stretch",
                )
                if close_cz:
                    st.markdown('<div class="muted">Next: give the draft to a Czech advokát or notář. '
                                'Keep the price in úschova until the vklad. Get a fresh výpis z LV '
                                '48h before signing.</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="muted">Next: Send to your notár. Use Notárska úschova for all funds. Re-verify LV 48h before signing.</div>', unsafe_allow_html=True)
                st.markdown('<div class="muted" style="margin-top:14px">INTERNAL ANALYSIS — '
                            'for you, not part of the draft</div>', unsafe_allow_html=True)
                st.code(analysis, language=None)
                st.download_button(
                    "⬇️ DOWNLOAD ANALYSIS",
                    analysis,
                    file_name=f"analysis_{sel3['id'][:8]}_{stamp}.txt",
                    mime="text/plain",
                    on_click="ignore",
                    width="stretch",
                )
                if using_demo:
                    st.caption("Demo listing — this draft is not saved.")
                else:
                    from database import save_contract_draft
                    save_contract_draft(sel3["id"], ownership, agreed,
                                        buyer_name.strip(), buyer_ico.strip(),
                                        notary.strip(), draft)
                    st.caption("Draft saved — it stays listed under EARLIER DRAFTS below.")

        # Every generated draft is kept, so the exact text sent to the notár can
        # be found again after the page reloads.
        if not using_demo:
            from database import get_contract_drafts
            earlier = get_contract_drafts(sel3["id"])
            if earlier:
                with st.expander(f"EARLIER DRAFTS ({len(earlier)})"):
                    for d in earlier:
                        # Stored in UTC; shown (and named) in the Bratislava
                        # time the draft's own "Vygenerované" line carries.
                        stamp, file_stamp = _local_stamp(d["generated_at"])
                        st.caption(
                            f'{stamp} · {d["buyer_name"]} · '
                            f'{d["ownership_type"]} · '
                            + (amt(sel3, d["agreed_price"] or 0) if close_cz
                               else f'€{d["agreed_price"] or 0:,.0f}'))
                        st.download_button(
                            "⬇️ DOWNLOAD",
                            d["draft_text"] or "",
                            file_name=f"contract_{sel3['id'][:8]}_{file_stamp}.txt",
                            mime="text/plain",
                            key=f"draft_{d['id']}",
                        )
