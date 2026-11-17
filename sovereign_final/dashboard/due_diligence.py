"""
dashboard/due_diligence.py — under DEAL PIPELINE, for the deal picked there:
its due-diligence checklist, the documents that go with it, and the letter
to the building's správca (database/deal_docs, modules/spravca_letter).
"""

import streamlit as st

from dashboard.fmt import _local_stamp, esc


def render(listing: dict, disabled: bool = False) -> None:
    """The checklist, documents and správca letter of one deal."""
    from database.deal_docs import (
        CHECKLIST, FILE_KINDS, MAX_FILE_MB, add_deal_file, delete_deal_file, get_checklist,
        get_deal_file, list_deal_files, set_checklist,
    )
    lid = listing.get("id")
    if not lid:
        return
    cz = (listing.get("market") or listing.get("_market") or "sk") == "cz"
    st.markdown('<hr class="div">', unsafe_allow_html=True)
    have = get_checklist(lid)
    done = sum(1 for k, *_ in CHECKLIST if (have.get(k) or {}).get("done"))
    st.markdown(f'<div class="muted">DUE DILIGENCE — {done} of {len(CHECKLIST)} checked</div>',
                unsafe_allow_html=True)
    st.progress(done / len(CHECKLIST))

    with st.form(f"dd_form_{lid}", border=False):
        typed = {}
        for key, label_sk, label_cz in CHECKLIST:
            item = have.get(key) or {}
            c1, c2 = st.columns([3, 2])
            with c1:
                tick = st.checkbox(label_cz if cz else label_sk, value=item.get("done", False),
                                   key=f"dd_{lid}_{key}", disabled=disabled)
            with c2:
                note = st.text_input("Note", value=item.get("note", ""), key=f"ddn_{lid}_{key}",
                                     label_visibility="collapsed", placeholder="note, date, who",
                                     disabled=disabled)
            typed[key] = (tick, note)
        if st.form_submit_button("💾 SAVE CHECKLIST", disabled=disabled):
            changed = {k: v for k, v in typed.items()
                       if v != ((have.get(k) or {}).get("done", False),
                                (have.get(k) or {}).get("note", ""))}
            set_checklist(lid, changed)
            st.rerun()

    # Documents
    st.markdown('<div class="muted" style="margin-top:10px">DOCUMENTS — kept in the database '
                f'(and so in the daily backup); at most {MAX_FILE_MB} MB each</div>',
                unsafe_allow_html=True)
    u1, u2 = st.columns([1, 3])
    with u1:
        kind = st.selectbox("Kind", FILE_KINDS, key=f"ddk_{lid}", disabled=disabled)
    with u2:
        up = st.file_uploader("Add a document", key=f"ddu_{lid}", disabled=disabled,
                              type=["pdf", "png", "jpg", "jpeg", "heic", "doc", "docx", "txt",
                                    "xlsx", "csv"])
    if up is not None and st.button("⬆️ KEEP THIS DOCUMENT", key=f"ddup_{lid}", disabled=disabled):
        try:
            add_deal_file(lid, kind, up.name, up.getvalue(), up.type)
            st.success(f"Kept {up.name}.")
        except ValueError as e:
            st.warning(f"Not kept: {e}.")
    files = list_deal_files(lid)
    for f in files:
        d1, d2, d3 = st.columns([5, 1, 1])
        with d1:
            st.markdown(f'<div class="brow"><span class="l">{esc(f["kind"])} · {esc(f["name"])}'
                        f'</span><span class="v">{f["size"] / 1024:,.0f} kB · '
                        f'{_local_stamp(f["uploaded_at"])[0]}</span></div>', unsafe_allow_html=True)
        with d2:
            st.download_button("⬇️", data=lambda fid=f["id"]: get_deal_file(fid)["data"],
                               file_name=f["name"], mime=f.get("mime") or "application/octet-stream",
                               key=f"ddd_{f['id']}", width="stretch")
        with d3:
            if st.button("🗑", key=f"ddx_{f['id']}", width="stretch", disabled=disabled,
                         help="Delete this document"):
                delete_deal_file(f["id"])
                st.rerun()

    _seller_checks(listing, lid, cz, disabled)
    from dashboard.building_view import render_facts_form
    render_facts_form(listing, disabled)

    # The letter to the správca / SVJ
    if st.toggle("✉️ Letter to the správca / SVJ" if not cz else "✉️ Dopis SVJ / správci",
                 key=f"ddl_{lid}",
                 help="A request for the confirmation that the flat owes the building nothing, "
                      "the repair fund's balance, the building's loans and the works planned — "
                      "none of it is on the title deed."):
        from modules.spravca_letter import build_letter
        l1, l2 = st.columns(2)
        with l1:
            buyer = st.text_input("Your name", key=f"ddlb_{lid}")
        with l2:
            contact = st.text_input("Your address, e-mail or phone", key=f"ddlc_{lid}")
        text = build_letter(listing, buyer, contact)
        # No key: the box shows the letter as it now reads, name and all.
        st.text_area("Letter", text, height=320)
        st.download_button("⬇️ LETTER (.txt)", text.encode("utf-8"),
                           file_name=f"spravca_{lid[:8]}.txt", mime="text/plain",
                           key=f"ddld_{lid}")


def _seller_checks(listing: dict, lid: str, cz: bool, disabled: bool) -> None:
    """🔍 Who sells: the owners the deed names, companies checked in the
    free registers, and the registers to search for a person by hand."""
    from modules import seller_check
    market = "cz" if cz else "sk"
    st.markdown('<div class="muted" style="margin-top:10px">🔍 SELLER CHECKS — the deed shows '
                'what is entered; the registers show an insolvency or execution that isn\'t '
                'yet</div>', unsafe_allow_html=True)
    text = ""
    try:
        from dashboard.lv_view import deed_text
        docs = {}
        if cz:
            from database import get_lv_document
            docs = {lid: get_lv_document(lid) or ""}
        got = deed_text({**listing, "_market": market}, docs)
        text = got[0] if got else ""
    except Exception:
        text = ""
    found = seller_check.owners(text, market) if text else []
    if not text:
        st.caption("No deed read for this flat yet: verify its LV first (card → RE-VERIFY LV).")
    elif not found:
        st.caption("The deed's owner part couldn't be read — see 📜 Read part C on the card.")
    for o in found:
        st.markdown(f'<div class="brow"><span class="l">{esc(o["name"])}</span><span class="v">'
                    f'{"company · IČO " + esc(o["ico"]) if o["ico"] else "company" if o["company"] else "person"}'
                    f'</span></div>', unsafe_allow_html=True)
    companies = [o for o in found if o["ico"]]
    if companies and st.button("🏢 CHECK THE COMPANIES", key=f"ddsc_{lid}", disabled=disabled,
                               help="ARES (Czechia) or the register of financial statements "
                                    "(Slovakia): name, dissolution and, in Czechia, insolvency."):
        st.session_state[f"ddsc_res_{lid}"] = [seller_check.check_company(o["ico"], market)
                                              for o in companies]
    for res in st.session_state.get(f"ddsc_res_{lid}", []):
        line = (f"{res['ico']} {res['name'] or ''} — {res['source']}: {res['status']}")
        if res["warnings"]:
            st.error("⛔ " + line + " · " + " ".join(res["warnings"]))
        else:
            st.success("✅ " + line)
    st.caption("A person: search these by hand (insolvency is free; executions cost a small "
               "fee per lookup) — " + " · ".join(
                   f"[{name}]({url})" for name, url in seller_check.links(market)))
