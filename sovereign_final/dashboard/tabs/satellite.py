"""
dashboard/tabs/satellite.py — SATELLITE VIEWER: satellite and Street View of
a listing, and its vibe notes.
"""

import logging
import os

import streamlit as st

from dashboard.fmt import _local_stamp, amt, esc

log = logging.getLogger("sovereign")

STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"


class NoPicture(Exception):
    """Google sent no picture. str() says why: Google's own words (it answers
    a refusal in plain text) and, when known, what to change in Google Cloud."""


# Google's reason → what to do. The first match wins; checked in lower case.
_FIXES = (
    ("referer", "the key is limited to websites, but this request comes from the dashboard's "
                "server: in Google Cloud → Credentials → the key, set Application restrictions "
                "to None (keep the API restrictions)"),
    ("key is not authorized", "the key's API restrictions leave this API out: in Google Cloud → "
                              "Credentials → the key → API restrictions, tick Maps Static API"),
    ("project is not authorized", "Maps Static API isn't enabled: in Google Cloud → APIs & "
                                  "Services → Library, open Maps Static API and click Enable"),
    ("not activated", "Maps Static API isn't enabled: in Google Cloud → APIs & Services → "
                      "Library, open Maps Static API and click Enable"),
    ("billing", "the key's Google Cloud project has no billing account: add one under Billing"),
    ("invalid", "the key isn't valid: copy it again from Google Cloud → Credentials into .env, "
                "then restart"),
    ("quota", "the day's or minute's quota is used up: it resets by itself"),
)


def why_no_picture(status: int, text: str) -> str:
    """One line for a refusal: Google's reason, redacted and shortened, and
    the fix when the reason is a known one."""
    from modules.redact import redact
    said = " ".join(redact(text or "").split())[:240]
    fix = next((f for k, f in _FIXES if k in said.lower()), None)
    if not fix and status == 403:
        fix = ("check that Maps Static API is enabled for the key and allowed by its API "
               "restrictions in Google Cloud")
    return f"HTTP {status}" + (f": “{said}”" if said else "") + (f" — {fix}." if fix else ".")


@st.cache_data(ttl=7 * 24 * 3600, max_entries=200, show_spinner=False)
def satellite_image(lat: float, lng: float) -> bytes:
    """The satellite picture of a point, fetched here on the server. The key
    goes in this request only: put in an <img> link, it would sit in every
    viewer's browser, free to copy, and it also works for Geocoding and Places
    on your bill.

    Raises NoPicture when Google refuses or can't be reached. A raise isn't
    cached, so once the key is fixed in Google Cloud the next look shows the
    picture (a cached "no picture" used to stay for a week)."""
    import requests
    key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not key:
        raise NoPicture("no GOOGLE_PLACES_API_KEY in .env")
    try:
        r = requests.get(STATIC_MAP_URL, params={
            "center": f"{lat},{lng}", "zoom": 17, "size": "640x400", "maptype": "satellite",
            "markers": f"color:red|{lat},{lng}", "key": key}, timeout=10)
    except requests.RequestException as e:
        from modules.redact import redact
        why = f"Google couldn't be reached ({type(e).__name__})"
        log.warning(f"Satellite image: {redact(e)}")
        raise NoPicture(why) from None
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or not ctype.startswith("image/"):
        text = r.text if ctype.startswith("text/") else ""
        why = why_no_picture(r.status_code, text)
        log.warning(f"Satellite image: {why}")
        raise NoPicture(why)
    return r.content


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
                st.markdown('<div style="background:var(--panel);border:1px solid var(--line);height:260px;display:flex;align-items:center;justify-content:center;color:var(--muted);font-family:var(--mono);font-size:0.7rem;letter-spacing:2px">NO IMAGE</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="muted">SATELLITE VIEW</div>', unsafe_allow_html=True)
            sat, why = None, ""
            if lat and lng and GMAPS_KEY:
                try:
                    sat = satellite_image(float(lat), float(lng))
                except NoPicture as e:
                    why = str(e)
            shown = False
            if sat:
                try:
                    st.image(sat, width="stretch")
                    shown = True
                except Exception:                 # not a picture after all
                    log.warning("Satellite image: Google's answer isn't a picture")
            if shown:
                pass
            elif lat and lng and GMAPS_KEY:
                st.link_button("📡 OPEN SATELLITE (Google Maps)",
                               f"https://www.google.com/maps?q={lat},{lng}&z=17&t=k",
                               width="stretch")
                st.markdown('<div class="muted">Google didn\'t send the picture: '
                            f'{esc(why or "it was not a picture.")}</div>', unsafe_allow_html=True)
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
