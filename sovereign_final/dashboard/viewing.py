"""
dashboard/viewing.py — the viewing mode (UX4): one screen for a flat you
are standing in, made for a phone. The card's "Viewing mode" switch shows
this instead of the rest of the card:

  - the figures to negotiate with: asking price, the most to offer, where the
    price sits among flats like it (D18), days tracked and price cuts;
  - the condition you find it in, which replaces the ad's in the renovation
    estimate, and a checklist of what to look at, each with a note;
  - photos taken there (kept with the deal's documents) and your impression
    as a vibe note.
"""

from __future__ import annotations

import streamlit as st

from dashboard.fmt import amt, esc

# (key, English, Czech): what to look at in the flat and the building.
CHECKS = (
    ("damp", "Damp, mould or water stains", "Vlhkost, plíseň nebo mapy od vody"),
    ("windows", "Windows: draughts, rot, single glazing", "Okna: táhne, hnijí, jednoduché sklo"),
    ("heating", "Heating: radiators, boiler, meters", "Topení: radiátory, kotel, měřiče"),
    ("electrics", "Electrics: old aluminium wiring, few sockets",
     "Elektřina: staré hliníkové rozvody, málo zásuvek"),
    ("bath_kitchen", "Bathroom and kitchen: age, leaks", "Koupelna a kuchyň: stáří, netěsnosti"),
    ("noise", "Noise: street, neighbours, lift", "Hluk: ulice, sousedé, výtah"),
    ("light", "Light: orientation, shade", "Světlo: orientace, stín"),
    ("common", "Common parts: stairwell, roof, lift, cellar",
     "Společné prostory: schodiště, střecha, výtah, sklep"),
    ("smell", "Smell: drains, smoke", "Zápach: odpady, kouř"),
)
CONDITION_WORDS = {"new": ("new", "nový"), "renovated": ("renovated", "po rekonstrukci"),
                   "good": ("good", "dobrý"), "original": ("original", "původní"),
                   "poor": ("poor", "špatný")}


def render(l: dict, demo: bool, cz: bool) -> None:
    """The viewing screen for listing `l` (inside its open card); `demo`: the
    page shows the demo data, which isn't in the database."""
    from database import add_annotation
    from database.deal_docs import add_deal_file, list_deal_files
    from database.viewing import CONDITIONS, get_viewing, set_viewing
    from engine.building import renovation_cost
    lid = l["id"]
    size = l.get("size_m2") or 0
    price = l.get("price_eur") or 0
    market = l.get("_market") or "sk"
    saw = get_viewing(lid) if not demo else {"condition": None, "problems": {}}

    # The figures to negotiate with.
    my, mg = l.get("max_price_yellow"), l.get("max_price_green")
    ph = l.get("_ph") or {}
    cut = ph.get("change_pct")
    rows = [("Cena" if cz else "Asking", amt(l, price)),
            ("Max nabídka 🟡" if cz else "Most to offer 🟡", amt(l, my) if my else "—"),
            ("Max nabídka 🟢" if cz else "To be GREEN 🟢", amt(l, mg) if mg else "—"),
            ("Sledováno dní" if cz else "Days tracked",
             "—" if l.get("_dom") is None else str(l["_dom"])),
            ("Sleva" if cz else "Price cuts", f"{cut:+.1%}" if cut else "—")]
    st.markdown('<div class="pick-k">' + "".join(
        f"<div><span>{esc(k)}</span><b>{esc(val)}</b></div>" for k, val in rows) + "</div>",
        unsafe_allow_html=True)
    if not demo and price and size:
        from dashboard.listing_cache import load_active
        from dashboard.verdict import price_band_html
        from modules.offer_sheet import _per_m2, comparables
        band = price_band_html(price / size, [_per_m2(c) for c in comparables(l, load_active())],
                               lambda x: amt(l, x, "/m²"), "", cz)
        if band:
            st.markdown(band, unsafe_allow_html=True)

    # What you find: the condition, the checklist, your impression.
    ad_cond = (l.get("condition") or "unknown").lower()
    with st.form(f"viewing_{lid}", border=False):
        cond = st.radio("Stav, jak ho vidíte" if cz else "Condition as you see it",
                        CONDITIONS, horizontal=True, key=f"vw_cond_{lid}",
                        index=CONDITIONS.index(saw["condition"]) if saw["condition"] else None,
                        format_func=lambda c: CONDITION_WORDS[c][1 if cz else 0],
                        help=("Nahradí stav z inzerátu v odhadu rekonstrukce."
                              if cz else "Replaces the ad's in the renovation estimate."))
        st.markdown(f'<div class="muted">{"CO ZKONTROLOVAT — ZAŠKRTNĚTE PROBLÉM" if cz else "WHAT TO LOOK AT — TICK A PROBLEM"}</div>',
                    unsafe_allow_html=True)
        problems = {}
        for key, en, cs in CHECKS:
            had = key in saw["problems"]
            ticked = st.checkbox(cs if cz else en, value=had, key=f"vw_{key}_{lid}")
            note = st.text_input("Poznámka" if cz else "Note", value=saw["problems"].get(key, ""),
                                 key=f"vw_{key}_note_{lid}", label_visibility="collapsed",
                                 placeholder="Poznámka" if cz else "Note")
            if ticked:
                problems[key] = note
        vibe = st.slider("Dojem" if cz else "How it felt", 1, 10, 6, key=f"vw_vibe_{lid}")
        impression = st.text_area("Poznámky z prohlídky" if cz else "Notes from the viewing",
                                  key=f"vw_notes_{lid}", height=90)
        if st.form_submit_button("ULOŽIT PROHLÍDKU" if cz else "SAVE THE VIEWING",
                                 disabled=demo, width="stretch", type="primary"):
            set_viewing(lid, cond, problems)
            if impression.strip():
                add_annotation(lid, impression.strip(), int(vibe))
            st.toast("Uloženo." if cz else "Viewing saved.")
            saw = {"condition": cond, "problems": problems}

    seen = saw["condition"] or ad_cond
    reno = renovation_cost(size, seen, market) if size else 0
    st.markdown(f'<div class="muted">{"Odhad rekonstrukce" if cz else "Renovation estimate"}: '
                f'<b>{esc(amt(l, reno))}</b> — '
                + esc(f"stav {CONDITION_WORDS.get(seen, (seen, seen))[1]}" +
                      (" (váš)" if saw["condition"] else " (z inzerátu)") if cz else
                      f"{seen} condition" + (" as you saw it" if saw["condition"] else
                                             ", from the ad"))
                + (f" · {len(saw['problems'])} {'problémů' if cz else 'problems ticked'}"
                   if saw["problems"] else "") + "</div>", unsafe_allow_html=True)

    # Photos taken there, kept with the deal's documents.
    shots = st.file_uploader("Fotky z prohlídky" if cz else "Photos from the viewing",
                             type=["jpg", "jpeg", "png", "heic", "webp"],
                             accept_multiple_files=True, key=f"vw_photos_{lid}", disabled=demo)
    if shots and st.button("ULOŽIT FOTKY" if cz else "SAVE THE PHOTOS", key=f"vw_save_ph_{lid}"):
        kept = 0
        for f in shots:
            try:
                add_deal_file(lid, "Photo", f"viewing-{f.name}", f.getvalue(), f.type)
                kept += 1
            except ValueError as e:
                st.warning(f"{f.name}: {e}")
        st.toast(f"{kept} fotek uloženo." if cz else
                 f"{kept} photo(s) saved with the deal's documents (DEAL PIPELINE).")
    if not demo:
        mine = [f for f in list_deal_files(lid) if f.get("kind") == "Photo"]
        if mine:
            st.caption(("Uložené fotky: " if cz else "Photos kept: ")
                       + ", ".join(f["name"] for f in mine[:8])
                       + (" …" if len(mine) > 8 else ""))
