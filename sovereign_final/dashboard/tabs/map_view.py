"""
dashboard/tabs/map_view.py — MAP: the listings with a pin, coloured by class
or by monthly cash flow; nearby pins can be grouped, and the map narrowed to
the listings within a distance of a point (work, a university, a station).

D19: "Districts" lays a circle under the pins for each area with two or more
flats on the map — the benchmark area of each flat, so spellings of one
district fall together — sized by its count and coloured by its median price
per m² (in €, so Slovak and Czech areas share one scale) or its median gross
yield, in five steps from the lowest to the highest area. Circles, not the
districts' outlines: those would need boundary files the app doesn't carry.
"""

import math
import re

import streamlit as st

import markets

from dashboard.fmt import amt, esc, sgn

# The palette's colours (dashboard/style.py tokens).
CLASS_COLOR = {"GREEN": [61, 220, 151], "YELLOW": [245, 184, 74],
               "WHITE": [139, 151, 176], "PENDING": [110, 168, 255]}
_CLASS_RANK = {"GREEN": 3, "YELLOW": 2, "WHITE": 1, "PENDING": 0}
# Monthly surplus, in EUR, to a colour: (at least, colour), best first.
CASHFLOW_COLOR = ((100, [61, 220, 151]), (0, [150, 220, 130]),
                  (-100, [245, 184, 74]), (-math.inf, [255, 138, 138]))
NO_SCORE_COLOR = [139, 151, 176]
LEGEND_CLASS = (("GREEN", "Green: ≥20% under market"), ("YELLOW", "Yellow: 10–20% under"),
                ("WHITE", "White: at market"), ("PENDING", "Not scored"))
LEGEND_CASH = ((CASHFLOW_COLOR[0][1], "≥ +€100 a month"), (CASHFLOW_COLOR[1][1], "break-even or better"),
               (CASHFLOW_COLOR[2][1], "down to −€100"), (CASHFLOW_COLOR[3][1], "worse"),
               (NO_SCORE_COLOR, "not scored"))


# D19: five steps, lightest for the lowest area value.
PRICE_STEPS = ([214, 232, 255], [160, 200, 255], [110, 168, 255], [70, 124, 226], [40, 84, 178])
YIELD_STEPS = ([214, 245, 230], [160, 232, 198], [100, 218, 160], [61, 186, 128], [28, 138, 90])
DISTRICT_MIN_FLATS = 2


def _median(xs):
    import statistics
    return statistics.median(xs) if xs else None


def district_areas(rows: list[dict], by_yield: bool = False) -> list[dict]:
    """One circle a benchmark area with DISTRICT_MIN_FLATS or more of `rows`:
    its median pin, count, median €/m² and gross yield, and a colour step."""
    from engine.regional_prices import median_source
    groups: dict[tuple, list[dict]] = {}
    for l in rows:
        mkt = l.get("_market") or "sk"
        area = (median_source(l.get("district") or "", **({} if mkt == "sk" else {"market": mkt}))[1]
                or (l.get("district") or "").strip())
        if area:
            groups.setdefault((mkt, area), []).append(l)
    areas = []
    for (_mkt, area), ls in groups.items():
        if len(ls) < DISTRICT_MIN_FLATS:
            continue
        per_m2 = _median([l["_price_eur"] / l["size_m2"] for l in ls
                          if l.get("_price_eur") and l.get("size_m2")])
        gross = _median([l["gross_yield"] * 100 for l in ls if l.get("gross_yield")])
        value = gross if by_yield else per_m2
        if value is None:
            continue
        areas.append({"area": area, "n": len(ls), "value": value, "per_m2": per_m2,
                      "gross": gross, "lat": _median([l["lat"] for l in ls]),
                      "lng": _median([l["lng"] for l in ls])})
    ranked = sorted(a["value"] for a in areas)
    steps = YIELD_STEPS if by_yield else PRICE_STEPS
    for a in areas:
        step = (min(int(ranked.index(a["value"]) / max(len(ranked) - 1, 1) * 5), 4)
                if len(ranked) > 1 else 2)
        a["color"] = steps[step] + [95]
        a["line"] = steps[step] + [200]
        a["radius"] = 1500 * math.sqrt(a["n"])
        a["tip"] = (f"<b>{esc(a['area'])}</b><br/>{a['n']} flats on the map"
                    + (f"<br/>median €{a['per_m2']:,.0f}/m²" if a["per_m2"] else "")
                    + (f"<br/>median gross yield {a['gross']:.1f}%" if a["gross"] else ""))
    return areas


def district_legend_html(areas: list[dict], by_yield: bool) -> str:
    """The district circles' scale, lowest to highest."""
    if not areas:
        return ""
    lo, hi = min(a["value"] for a in areas), max(a["value"] for a in areas)
    steps = YIELD_STEPS if by_yield else PRICE_STEPS
    what = (f"gross yield {lo:.1f}% → {hi:.1f}%" if by_yield
            else f"€{lo:,.0f}/m² → €{hi:,.0f}/m² (median, in €)")
    return ('<div class="lg"><span>Districts, ' + esc(what) + ":</span>"
            + "".join(f'<span><i style="background:rgb({c[0]},{c[1]},{c[2]})"></i></span>'
                      for c in steps) + "</div>")


def legend_html(by_cash: bool) -> str:
    """The pins' colours, as swatches (D9)."""
    items = (LEGEND_CASH if by_cash else
             tuple((CLASS_COLOR[c], label) for c, label in LEGEND_CLASS))
    return '<div class="lg">' + "".join(
        f'<span><i style="background:rgb({c[0]},{c[1]},{c[2]})"></i>{esc(label)}</span>'
        for c, label in items) + '<span><i class="faded"></i>faded: area, not street</span></div>'

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
    # Only pins inside the listing's own country: one wrong pin (a swapped
    # pair) used to pull the map's centre abroad.
    from scraper.geo import as_pin
    mapped = [l for l in data if l.get("lat") and l.get("lng")
              and as_pin(l["lat"], l["lng"], l.get("_market") or l.get("market") or "sk")]
    if not data and n_hidden:
        st.info(hidden_note())
        return
    if not mapped:
        st.info("No flat has a place on the map yet. Press LOCATION IQ under DAILY RUN in "
                "the sidebar; it works without a Google key, using OpenStreetMap.")
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

    d1, d2 = st.columns([2, 4])
    with d1:
        show_districts = st.toggle("Districts", key="map_districts",
                                   help="A circle for each area with two or more flats on the "
                                        "map, sized by how many and coloured by their median "
                                        "price per m² or gross yield.")
    with d2:
        by_yield = st.radio("District colour", ["€/m²", "Gross yield"], horizontal=True,
                            key="map_dmetric", disabled=not show_districts,
                            label_visibility="collapsed") == "Gross yield"

    point = None
    if near.strip():
        # Mapy.com's credit, beside the results of its address search.
        from dashboard.legal import mapy_credit_html
        credit = mapy_credit_html()
        if credit:
            st.markdown(credit, unsafe_allow_html=True)
        point, why = _find_point(near, v.market)
        if point is None:
            if why == "not found":
                st.warning(f"“{near.strip()}” isn't on the map. Try a street and town "
                           f"(Hlavná 1, Košice), or paste coordinates such as 48.1486, 17.1077: "
                           f"right-click a spot in a map app to copy them.")
            else:
                st.warning(f"The address search didn't answer ({why}). Check that this "
                           f"computer is online, or paste coordinates such as 48.1486, 17.1077.")

    # Travel time to the point (modules/travel): a straight line misleads
    # across a river or a hill.
    minutes, mode, max_min = {}, None, None
    if point:
        from modules import travel
        t1, t2 = st.columns([3, 2])
        with t1:
            how = st.radio("Distance", ["Straight line"] + [travel.MODES[m] for m in
                                                             travel.available_modes()],
                           horizontal=True, key="map_how",
                           help="On foot and by car: openrouteservice (ORS_API_KEY) or the "
                                "public OSRM servers. Public transport needs "
                                "GOOGLE_ROUTES_API_KEY.")
        mode = next((m for m, label in travel.MODES.items() if label == how), None)
        with t2:
            max_min = st.slider("Within minutes", 5, 120, 30, step=5, key="map_min",
                                disabled=mode is None, format="within %d min")
        if mode:
            near_ones = {l["id"]: (l["lat"], l["lng"]) for l in mapped
                         if km_between(point[0], point[1], l["lat"], l["lng"]) <= radius_km}
            near_ones = dict(list(near_ones.items())[:300])
            with st.spinner(f"Travel times {how.lower()}…"):
                minutes = travel.travel_times(point, near_ones, mode)
            if len(minutes) < len(near_ones):
                st.warning("The router didn't answer for every listing; try again in a minute.")

    pts = []
    for l in mapped:
        cls = (l.get("cf_class") or l.get("classification") or "PENDING").upper()
        surplus = v.surplus(l)
        surplus_eur = markets.to_eur(surplus, l.get("_cur") or "EUR")
        km = km_between(point[0], point[1], l["lat"], l["lng"]) if point else None
        if km is not None and km > radius_km:
            continue
        mins = minutes.get(l["id"]) if mode else None
        if mode and (mins is None or mins > max_min):
            continue
        approx = (l.get("geo_precision") or "") == "area"
        color = cashflow_color(surplus_eur) if by_cash else CLASS_COLOR.get(cls, NO_SCORE_COLOR)
        # The tooltip is drawn as HTML: everything a portal wrote is escaped.
        tip = (f"<b>{esc((l.get('title') or l.get('district') or '—')[:60])}</b><br/>"
               f"{amt(l, l.get('price_eur') or 0)} · {cls}<br/>surplus {sgn(l, surplus)}"
               f"<br/>max YELLOW {amt(l, l['max_price_yellow']) if l.get('max_price_yellow') else '—'}"
               + (f"<br/>{km:.1f} km away" if km is not None else "")
               + (f"<br/>{mins:.0f} min {esc(travel.MODES[mode].lower())}" if mins is not None else "")
               + ("<br/><i>approximate (area centroid)</i>" if approx
                  else f"<br/><i>{esc(l.get('geo_precision') or '')}</i>"))
        pts.append({
            "id": l["id"], "lat": l["lat"], "lng": l["lng"], "tip": tip,
            "color": color + ([110] if approx else [220]),
            "radius": 60 if cls in ("GREEN", "YELLOW") else 35,
            # The pin a group is coloured as: by cash flow or by class.
            "rank": (surplus_eur if surplus_eur is not None else -math.inf) if by_cash
                    else _CLASS_RANK.get(cls, 0),
            "label": "",
        })

    scope = ((f" within {max_min} min ({esc(travel.MODES[mode].lower())}) of {esc(near.strip())}"
              if mode else f" within {radius_km} km (straight line) of {esc(near.strip())}")
             if point else "")
    areas = (district_areas([l for l in mapped if l["id"] in {p["id"] for p in pts}], by_yield)
             if show_districts else [])
    st.markdown(f'<div class="muted">{len(pts)} of {len(data)} filtered listings'
                f'{scope or " have coordinates"}. Click a pin to see the flat below the map.</div>'
                + legend_html(by_cash) + district_legend_html(areas, by_yield),
                unsafe_allow_html=True)
    if not pts:
        st.info("No listing within that distance — widen it, or move the point.")
        return

    import pydeck as pdk
    layers = []
    if areas:            # D19: under everything else
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=areas, get_position="[lng, lat]", id="districts",
            get_fill_color="color", get_line_color="line", get_radius="radius",
            stroked=True, filled=True, line_width_min_pixels=1, radius_min_pixels=12,
            radius_max_pixels=90, pickable=True))
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
            "ScatterplotLayer", data=shown, get_position="[lng, lat]", id="pins",
            get_fill_color="color", get_radius="radius",
            radius_min_pixels=5, radius_max_pixels=46, pickable=True))
        layers.append(pdk.Layer(
            "TextLayer", data=[s for s in shown if s["label"]], get_position="[lng, lat]",
            get_text="label", get_size=13, get_color=[7, 9, 14],
            get_text_anchor="'middle'", get_alignment_baseline="'center'"))
    else:
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=pts, get_position="[lng, lat]", id="pins",
            get_fill_color="color", get_radius="radius",
            radius_min_pixels=4, radius_max_pixels=14, pickable=True))
    if point:
        centre, zoom = point, max(7.0, min(14.0, 14.3 - math.log2(radius_km)))
    else:
        # The median, not the mean: a few far pins don't move it.
        import statistics
        centre = (statistics.median(p["lat"] for p in pts), statistics.median(p["lng"] for p in pts))
        zoom = 7 if len(pts) > 1 else 13
    event = st.pydeck_chart(pdk.Deck(
        initial_view_state=pdk.ViewState(latitude=centre[0], longitude=centre[1], zoom=zoom),
        layers=layers, tooltip={"html": "{tip}"},
    ), on_select="rerun", selection_mode="single-object", key="map_pick")
    # D9: the list of the flats on the map, and the one picked (a pin or a row).
    by_id = {l["id"]: l for l in mapped}
    picked = None
    objs = ((event or {}).get("selection") or {}).get("objects") or {}
    for obj in objs.get("pins") or []:
        picked = by_id.get(obj.get("id"))
    on_map = sorted((by_id[p["id"]] for p in pts if p.get("id") in by_id),
                    key=lambda l: -(v.surplus(l) if v.surplus(l) is not None else -1e12))
    import pandas as pd
    table = pd.DataFrame([{
        "Title": (l.get("title") or l.get("district") or "—")[:60],
        "Price": v.in_view_cur(l, l.get("price_eur") or 0),
        "Surplus": v.in_view_cur(l, v.surplus(l)),
        "Class": (l.get("cf_class") or l.get("classification") or "").title(),
        "_id": l["id"]} for l in on_map[:200]])
    if not table.empty:
        sel = st.dataframe(
            table, hide_index=True, width="stretch", height=min(320, 40 + 35 * len(table)),
            column_order=["Title", "Price", "Surplus", "Class"],
            column_config={"Price": v.money_col("Price"), "Surplus": v.money_col("Surplus")},
            on_select="rerun", selection_mode="single-row", key="map_list")
        rows = (sel.selection.rows if sel else []) or []
        if rows and not picked:
            picked = by_id.get(table.iloc[rows[0]]["_id"])
    if picked:
        from dashboard.tabs.triage import render_summary
        render_summary(picked, v, ctx="map")
