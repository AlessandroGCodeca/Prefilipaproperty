"""
dashboard/tabs/map_view.py — MAP: the listings with a pin, coloured by class.
"""

import streamlit as st

from dashboard.fmt import amt, sgn


def render(v) -> None:
    """The MAP tab."""
    data = v.data
    hidden_note = v.hidden_note
    n_hidden = v.n_hidden
    show_sro = v.show_sro
    mapped = [l for l in data if l.get("lat") and l.get("lng")]
    if not data and n_hidden:
        st.info(hidden_note())
    elif not mapped:
        st.info("No coordinates yet — run 📍 LOCATION IQ (works without a Google key: "
                "it falls back to OpenStreetMap).")
    else:
        import pydeck as pdk
        palette = {"GREEN": [0, 230, 118], "YELLOW": [255, 215, 64],
                   "WHITE": [96, 125, 139], "PENDING": [68, 138, 255]}
        pts = []
        for l in mapped:
            cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
            surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
            approx = (l.get("geo_precision") or "") == "area"
            pts.append({
                "lat": l["lat"], "lng": l["lng"],
                "color": palette.get(cls, [96, 125, 139]) + ([110] if approx else [220]),
                "radius": 60 if cls in ("GREEN", "YELLOW") else 35,
                "title": (l.get("title") or l.get("district") or "—")[:60],
                "price": amt(l, l.get("price_eur") or 0),
                "cls": cls,
                "surplus": sgn(l, surplus),
                "maxy": amt(l, l["max_price_yellow"]) if l.get("max_price_yellow") else "—",
                "where": "approximate (area centroid)" if approx else (l.get("geo_precision") or ""),
            })
        st.markdown(f'<div class="muted">{len(pts)} of {len(data)} filtered listings have '
                    f'coordinates. Faded dots are geocoded to an area, not a street.</div>',
                    unsafe_allow_html=True)
        st.pydeck_chart(pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=sum(p["lat"] for p in pts) / len(pts),
                longitude=sum(p["lng"] for p in pts) / len(pts),
                zoom=7 if len(pts) > 1 else 13),
            layers=[pdk.Layer(
                "ScatterplotLayer", data=pts, get_position="[lng, lat]",
                get_fill_color="color", get_radius="radius",
                radius_min_pixels=4, radius_max_pixels=14, pickable=True)],
            tooltip={"html": "<b>{title}</b><br/>{price} · {cls}<br/>surplus {surplus}"
                             "<br/>max YELLOW {maxy}<br/><i>{where}</i>"},
        ))
