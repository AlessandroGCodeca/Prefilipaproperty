"""
dashboard/tabs/map_view.py — MAP: the listings with a pin, coloured by class
or by monthly cash flow; nearby pins can be grouped, and the map narrowed to
the listings within a distance of a point (work, a university, a station).
"""

import math
import re

import streamlit as st

import markets

from dashboard.fmt import amt, esc, sgn

CLASS_COLOR = {"GREEN": [0, 230, 118], "YELLOW": [255, 215, 64],
               "WHITE": [96, 125, 139], "PENDING": [68, 138, 255]}
_CLASS_RANK = {"GREEN": 3, "YELLOW": 2, "WHITE": 1, "PENDING": 0}
# Monthly surplus, in EUR, to a colour: (at least, colour), best first.
CASHFLOW_COLOR = ((100, [0, 230, 118]), (0, [150, 220, 130]),
                  (-100, [255, 145, 0]), (-math.inf, [255, 82, 82]))
NO_SCORE_COLOR = [96, 125, 139]
# Grouping draws the pins of one grid cell as one circle. The map draws what
# the page computed — it can't regroup as you zoom — so the cell is sized to
# the view the map opens on: about a tenth of its width, between ~1 km and
# ~55 km (in degrees of latitude).
CLUSTER_CELLS_ACROSS = 10
CLUSTER_CELL_MIN_DEG, CLUSTER_CELL_MAX_DEG = 0.01, 0.5
KM_PER_DEG = 111.0


def cluster_cell(points: list[dict], radius_km: float | None = None) -> float:
    """The grid cell (degrees) for the view: the search circle's width when a
    point is set, else the span of the pins."""
    if radius_km:
        span = 2 * radius_km / KM_PER_DEG
    else:
        span = max(max(p["lat"] for p in points) - min(p["lat"] for p in points),
                   max(p["lng"] for p in points) - min(p["lng"] for p in points))
    return min(max(span / CLUSTER_CELLS_ACROSS, CLUSTER_CELL_MIN_DEG), CLUSTER_CELL_MAX_DEG)

_POINT_RE = re.compile(r"^\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$")


def parse_point(text: str) -> tuple[float, float] | None:
    """"48.1486, 17.1077" → (lat, lng); None for anything else (an address)."""
    m = _POINT_RE.match(text or "")
    if not m:
        return None
    lat, lng = (float(g.replace(",", ".")) for g in m.groups())
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


def km_between(lat1, lng1, lat2, lng2) -> float:
    """Straight-line (great-circle) distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def cashflow_color(surplus_eur) -> list[int]:
    """The pin colour for a monthly surplus in EUR; grey when not scored."""
    if surplus_eur is None:
        return NO_SCORE_COLOR
    return next(color for least, color in CASHFLOW_COLOR if surplus_eur >= least)


def _group(members: list[dict]) -> dict:
    return {"lat": sum(p["lat"] for p in members) / len(members),
            "lng": sum(p["lng"] for p in members) / len(members),
            "n": len(members), "best": max(members, key=lambda p: p["rank"]),
            "members": members}


def cluster(points: list[dict], cell: float = 0.03) -> list[dict]:
    """Group pins that are close together. Each group: its centre, how many,
    its best pin (highest "rank") and the pins themselves; a lone pin is a
    group of one. Largest groups first.

    Pins are grouped by grid cell first; then a group whose centre lies
    within a cell's width of a larger group's joins it — one town's flats
    either side of a grid line are one group, not two circles on top of
    each other."""
    cells: dict[tuple, list[dict]] = {}
    for p in points:
        cells.setdefault((math.floor(p["lat"] / cell), math.floor(p["lng"] / cell)), []).append(p)
    merged: list[dict] = []
    for g in sorted((_group(m) for m in cells.values()), key=lambda g: g["n"], reverse=True):
        near = next((m for m in merged
                     if math.hypot(m["lat"] - g["lat"], m["lng"] - g["lng"]) < cell), None)
        if near is None:
            merged.append(g)
        else:
            near.update(_group(near["members"] + g["members"]))
    return sorted(merged, key=lambda g: g["n"], reverse=True)


def _find_point(text: str, market) -> tuple[tuple[float, float] | None, str]:
    """((lat, lng), "") for coordinates or an address that geocodes; (None,
    why) otherwise. An address is looked up once per text (the session keeps
    it): each lookup is a request to the geocoder."""
    point = parse_point(text)
    if point:
        return point, ""
    found = st.session_state.setdefault("_map_points", {})
    key = (text.strip().lower(), market)
    if key not in found:
        from modules.location_iq import geocode_precise
        try:
            lat, lng, _precision = geocode_precise(text.strip(), market or "sk")
        except Exception as e:                      # no network, a geocoder error
            return None, f"{type(e).__name__}"
        found[key] = (lat, lng) if lat is not None and lng is not None else None
    return found[key], "" if found[key] else "not found"


def render(v) -> None:
    """The MAP tab."""
    data = v.data
    hidden_note = v.hidden_note
    n_hidden = v.n_hidden
    show_sro = v.show_sro
    mapped = [l for l in data if l.get("lat") and l.get("lng")]
    if not data and n_hidden:
        st.info(hidden_note())
        return
    if not mapped:
        st.info("No coordinates yet — run 📍 LOCATION IQ (works without a Google key: "
                "it falls back to OpenStreetMap).")
        return

    c1, c2, c3, c4 = st.columns([2, 2, 4, 2])
    with c1:
        by_cash = st.radio("Colour by", ["Class", "Cash flow"], horizontal=True,
                           key="map_color") == "Cash flow"
    with c2:
        grouped = st.toggle("Group nearby pins", key="map_group",
                            help="Draws neighbouring listings as one circle with their "
                                 "count, coloured as its best listing. The groups are sized "
                                 "to the view the map opens on; set a point to look closer.")
    with c3:
        near = st.text_input(
            "Near", key="map_near", placeholder="Near: an address, or 48.1486, 17.1077",
            label_visibility="collapsed",
            help="Show only the listings within the distance of this point — your work, a "
                 "university, a station. Coordinates are used as typed; an address is looked "
                 "up once.")
    with c4:
        radius_km = st.slider("Within km", 1, 50, 10, key="map_km",
                              label_visibility="collapsed", disabled=not near.strip(),
                              format="within %d km")

    point = None
    if near.strip():
        point, why = _find_point(near, v.market)
        if point is None:
            st.warning(f"Couldn't place “{near.strip()}” ({why}). Type its coordinates "
                       f"instead, as 48.1486, 17.1077 — right-click a spot in a map app to "
                       f"copy them.")

    pts = []
    for l in mapped:
        cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
        surplus = l.get("surplus_sro") if show_sro else l.get("surplus_personal")
        surplus_eur = markets.to_eur(surplus, l.get("_cur") or "EUR")
        km = km_between(point[0], point[1], l["lat"], l["lng"]) if point else None
        if km is not None and km > radius_km:
            continue
        approx = (l.get("geo_precision") or "") == "area"
        color = cashflow_color(surplus_eur) if by_cash else CLASS_COLOR.get(cls, NO_SCORE_COLOR)
        # The tooltip is drawn as HTML: everything a portal wrote is escaped.
        tip = (f"<b>{esc((l.get('title') or l.get('district') or '—')[:60])}</b><br/>"
               f"{amt(l, l.get('price_eur') or 0)} · {cls}<br/>surplus {sgn(l, surplus)}"
               f"<br/>max YELLOW {amt(l, l['max_price_yellow']) if l.get('max_price_yellow') else '—'}"
               + (f"<br/>{km:.1f} km away" if km is not None else "")
               + ("<br/><i>approximate (area centroid)</i>" if approx
                  else f"<br/><i>{esc(l.get('geo_precision') or '')}</i>"))
        pts.append({
            "lat": l["lat"], "lng": l["lng"], "tip": tip,
            "color": color + ([110] if approx else [220]),
            "radius": 60 if cls in ("GREEN", "YELLOW") else 35,
            # The pin a group is coloured as: by cash flow or by class.
            "rank": (surplus_eur if surplus_eur is not None else -math.inf) if by_cash
                    else _CLASS_RANK.get(cls, 0),
            "label": "",
        })

    scope = (f" within {radius_km} km (straight line) of {esc(near.strip())}" if point else "")
    st.markdown(f'<div class="muted">{len(pts)} of {len(data)} filtered listings'
                f'{scope or " have coordinates"}. '
                + ("Green: at least +€100 a month · light green: break-even or better · "
                   "orange: down to −€100 · red: worse · grey: not scored. "
                   if by_cash else "") +
                'Faded dots are geocoded to an area, not a street.</div>',
                unsafe_allow_html=True)
    if not pts:
        st.info("No listing within that distance — widen it, or move the point.")
        return

    import pydeck as pdk
    layers = []
    if point:
        ring = [{"lat": point[0], "lng": point[1],
                 "tip": f"<b>{esc(near.strip())}</b><br/>{radius_km} km around it"}]
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=ring, get_position="[lng, lat]",
            get_radius=radius_km * 1000, stroked=True, filled=False,
            get_line_color=[228, 234, 245, 160], line_width_min_pixels=1.5))
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=ring, get_position="[lng, lat]", get_radius=40,
            get_fill_color=[228, 234, 245], radius_min_pixels=5, pickable=True))
    if grouped:
        cell = cluster_cell(pts, radius_km if point else None)
        groups = cluster(pts, cell)
        biggest = groups[0]["n"]
        # A cell's narrower side, in metres: a degree of longitude is shorter
        # than one of latitude (about two thirds at Slovakia's).
        mid_lat = sum(p["lat"] for p in pts) / len(pts)
        cell_m = cell * KM_PER_DEG * 1000 * math.cos(math.radians(mid_lat))
        shown = []
        for g in groups:
            if g["n"] == 1:
                shown.append(g["best"])
                continue
            shown.append({
                "lat": g["lat"], "lng": g["lng"], "label": str(g["n"]),
                "color": g["best"]["color"][:3] + [200],
                # Never wider than its cell, so neighbours don't overlap.
                "radius": cell_m * (0.2 + 0.25 * math.sqrt(g["n"] / biggest)),
                "tip": f"<b>{g['n']} listings here</b><br/>best: {g['best']['tip']}",
            })
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=shown, get_position="[lng, lat]",
            get_fill_color="color", get_radius="radius",
            radius_min_pixels=5, radius_max_pixels=46, pickable=True))
        layers.append(pdk.Layer(
            "TextLayer", data=[s for s in shown if s["label"]], get_position="[lng, lat]",
            get_text="label", get_size=13, get_color=[7, 9, 14],
            get_text_anchor="'middle'", get_alignment_baseline="'center'"))
    else:
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=pts, get_position="[lng, lat]",
            get_fill_color="color", get_radius="radius",
            radius_min_pixels=4, radius_max_pixels=14, pickable=True))
    if point:
        centre, zoom = point, max(7.0, min(14.0, 14.3 - math.log2(radius_km)))
    else:
        centre = (sum(p["lat"] for p in pts) / len(pts), sum(p["lng"] for p in pts) / len(pts))
        zoom = 7 if len(pts) > 1 else 13
    st.pydeck_chart(pdk.Deck(
        initial_view_state=pdk.ViewState(latitude=centre[0], longitude=centre[1], zoom=zoom),
        layers=layers, tooltip={"html": "{tip}"},
    ))
