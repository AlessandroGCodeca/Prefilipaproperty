"""
dashboard/tabs/satellite.py — SATELLITE VIEWER: satellite and Street View of
a listing, and its vibe notes.
"""

import os

import streamlit as st

from dashboard.fmt import _local_stamp, amt, esc


def render(v) -> None:
    """The SATELLITE VIEWER tab."""
    data = v.data
    hidden_note = v.hidden_note
    n_hidden = v.n_hidden
    using_demo = v.using_demo
    GMAPS_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
    st.markdown('<div class="muted">SATELLITE + STREET VIEW VERIFICATION — VIBE CHECK</div>', unsafe_allow_html=True)
    st.markdown("")

    if not data:
        st.info(hidden_note() if n_hidden else "No listings loaded.")
    else:
        opts = {f"{l.get('title') or '?'} — {amt(l, l.get('price_eur') or 0)} [{(l.get('id') or '')[:6]}]": l
                for l in data}
        sel  = opts[st.selectbox("Select listing", list(opts.keys()), label_visibility="collapsed")]

        lat, lng = sel.get("lat"), sel.get("lng")
        c1, c2   = st.columns(2)

        with c1:
            st.markdown('<div class="muted">LISTING PHOTO</div>', unsafe_allow_html=True)
            img = sel.get("primary_image_url","")
            if img and img.startswith("http"):
                st.image(img, width="stretch")
            else:
                st.markdown('<div style="background:#0b0d14;border:1px solid #151924;height:260px;display:flex;align-items:center;justify-content:center;color:#7a89a8;font-family:var(--mono);font-size:0.7rem;letter-spacing:2px">NO IMAGE</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="muted">SATELLITE VIEW</div>', unsafe_allow_html=True)
            if lat and lng and GMAPS_KEY:
                sat = (f"https://maps.googleapis.com/maps/api/staticmap"
                       f"?center={lat},{lng}&zoom=17&size=640x400&maptype=satellite"
                       f"&markers=color:red%7C{lat},{lng}&key={GMAPS_KEY}")
                st.image(sat, width="stretch")
            elif lat and lng:
                st.link_button("📡 OPEN SATELLITE (Google Maps)",
                               f"https://www.google.com/maps?q={lat},{lng}&z=17&t=k",
                               width="stretch")
                st.markdown('<div class="muted">Add GOOGLE_PLACES_API_KEY to .env for inline satellite.</div>', unsafe_allow_html=True)
            else:
                st.info("No coordinates for this listing.")

        if lat and lng:
            sv1, sv2 = st.columns(2)
            with sv1:
                st.link_button("🚶 STREET VIEW",
                               f"https://www.google.com/maps?q=&layer=c&cbll={lat},{lng}",
                               width="stretch")
            with sv2:
                st.link_button("🗺️ FULL MAP",
                               f"https://www.google.com/maps?q={lat},{lng}&z=15",
                               width="stretch")

        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('<div class="muted">VIBE CHECK</div>', unsafe_allow_html=True)
        # Keyed per listing: an unkeyed widget is identified by its label and
        # arguments alone, the same for every listing, so a note typed for A
        # stayed in the box after picking B and could be saved against B.
        vibe = st.slider("Score (1–10)", 1, 10, 5, key=f"vibe_{sel['id']}")
        note = st.text_input("Note", placeholder="e.g. Great location, needs new windows...",
                             key=f"note_{sel['id']}")
        if st.button("SAVE ANNOTATION", width="stretch", disabled=using_demo):
            from database import add_annotation
            add_annotation(sel["id"], note, vibe)
            from dashboard.listing_cache import clear_listing_cache
            clear_listing_cache()       # the cards' vibe is cached with the listings
            st.success(f"✅ Vibe {vibe}/10 saved.")
        if using_demo:
            st.caption("Demo listing — notes can't be saved.")

        # Saved notes for this listing, newest first (in Bratislava time).
        from database import get_annotations
        notes = get_annotations(sel["id"])
        if notes:
            st.markdown(f'<div class="muted" style="margin-top:12px">SAVED NOTES ({len(notes)})</div>',
                        unsafe_allow_html=True)
            html = ""
            for n in notes:
                html += (f'<div class="brow"><span class="l">{_local_stamp(n.get("created_at"))[0]}'
                         f' · {n.get("vibe_score") or "—"}/10</span>'
                         f'<span class="v">{esc(n.get("note"))}</span></div>')
            st.markdown(html, unsafe_allow_html=True)
