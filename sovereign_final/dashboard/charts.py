"""
dashboard/charts.py — the dashboard's charts, all in one style (D20): the
card's month of cash flow as a waterfall and its asking price over time (D8),
and WHAT-IF's equity cash flows a year. Vega-Lite specs; draw() puts them on
the page with this style only, not Streamlit's own chart theme.

Colours are the palette's (dashboard/style.py tokens), written out: a chart
can't read the page's CSS variables. Dark is palette 1, light palette 3 (D14).
The font is the IBM Plex the dashboard ships and serves itself (D15).
"""

from __future__ import annotations

GOOD, BAD, MUTED, INFO, TEXT = "#3ddc97", "#ff8a8a", "#8b97b0", "#6ea8ff", "#bcc8e0"
PALETTES = {
    "dark": {"good": GOOD, "bad": BAD, "muted": MUTED, "info": INFO,
             "label": MUTED, "title": TEXT, "line": "#1b2132"},
    "light": {"good": "#0a6b43", "bad": "#b3261e", "muted": "#8b95a7", "info": "#1a56c4",
              "label": "#566075", "title": "#2a3342", "line": "#d5dae3"},
}
FONT = "IBM Plex Sans"


def styled(spec: dict | None, theme: str = "dark") -> dict | None:
    """`spec` in the dashboard's chart style: its font, the palette's label,
    title and grid colours, no frame, and the page's own background."""
    if spec is None:
        return None
    c = PALETTES.get(theme, PALETTES["dark"])
    axis = {"labelColor": c["label"], "titleColor": c["title"], "gridColor": c["line"],
            "domainColor": c["line"], "tickColor": c["line"], "labelFontSize": 11,
            "titleFontSize": 11, "titleFontWeight": 500}
    return {**spec, "background": "transparent",
            "config": {"font": FONT, "view": {"stroke": None}, "axis": axis,
                       "legend": {"labelColor": c["label"], "titleColor": c["title"]}}}


def draw(spec: dict) -> None:
    """Put a styled spec on the page as it is (theme=None: Streamlit's chart
    theme would lay its own fonts and colours over the dashboard's)."""
    import streamlit as st
    st.vega_lite_chart(spec, width="stretch", theme=None)


def cost_rows(l: dict, sro: bool, T=lambda s: s) -> list[tuple[str, float]]:
    """The month's costs under the structure shown, as the card's cost
    breakdown lists them; zero and missing ones left out."""
    mortgage = (l.get("mortgage_monthly_sro") if sro and l.get("mortgage_monthly_sro") is not None
                else l.get("mortgage_monthly"))
    rows = [
        (T("Mortgage"), mortgage),
        (T("HOA (incl. fond opráv)"), l.get("hoa_monthly")),
        (T("Property Tax"), l.get("property_tax_monthly")),
        (T("Vacancy 5%"), l.get("vacancy_cost")),
        (T("Owner reserve"), l.get("maintenance_monthly")),
        (T("Management"), l.get("management_monthly")),
        (T("s.r.o. running cost"), l.get("sro_running_cost_monthly") if sro else None),
        (T("Income Tax"), l.get("income_tax_sro") if sro else l.get("income_tax_personal")),
        (T("Health Levy"), l.get("health_levy_sro") if sro else l.get("health_levy_personal")),
    ]
    return [(k, float(v)) for k, v in rows if v]


def waterfall_spec(rent: float, costs: list[tuple[str, float]], surplus: float | None,
                   unit: str = "€", theme: str = "dark") -> dict | None:
    """A waterfall: rent up from 0, each cost down from where the last ended,
    the surplus as the last bar from 0. None without a rent."""
    if not rent:
        return None
    rows, level = [{"step": "Rent", "start": 0.0, "end": float(rent), "kind": "in",
                    "amount": float(rent)}], float(rent)
    for name, value in costs:
        rows.append({"step": name, "start": level, "end": level - value, "kind": "out",
                     "amount": -value})
        level -= value
    end = float(surplus) if surplus is not None else level
    rows.append({"step": "Surplus", "start": 0.0, "end": end,
                 "kind": "net+" if end >= 0 else "net-", "amount": end})
    order = [r["step"] for r in rows]
    c = PALETTES.get(theme, PALETTES["dark"])
    # Sideways, one row per item: every label stays readable at any width.
    return styled({
        "data": {"values": rows},
        "height": 30 * len(rows),
        "mark": {"type": "bar", "cornerRadius": 2, "height": 18},
        "encoding": {
            "y": {"field": "step", "type": "nominal", "sort": order, "title": None,
                  "axis": {"labelLimit": 170, "labelOverlap": False, "labelFontSize": 11}},
            "x": {"field": "start", "type": "quantitative", "title": f"{unit} a month"},
            "x2": {"field": "end"},
            "color": {"field": "kind", "type": "nominal", "legend": None,
                      "scale": {"domain": ["in", "out", "net+", "net-"],
                                "range": [c["good"], c["muted"], c["good"], c["bad"]]}},
            "tooltip": [{"field": "step", "title": "Item"},
                        {"field": "amount", "title": unit, "format": ",.0f"}],
        },
    }, theme)


def price_spec(history, unit: str = "€", theme: str = "dark") -> dict | None:
    """The asking price over time, a step line; None with fewer than two points."""
    pts = [{"date": str(when)[:10], "price": float(p)} for when, p in (history or []) if p]
    if len(pts) < 2:
        return None
    return styled({
        "data": {"values": pts},
        "height": 220,
        "mark": {"type": "line", "interpolate": "step-after", "point": True,
                 "color": PALETTES.get(theme, PALETTES["dark"])["info"]},
        "encoding": {
            "x": {"field": "date", "type": "temporal", "title": None},
            "y": {"field": "price", "type": "quantitative", "title": unit,
                  "scale": {"zero": False}},
            "tooltip": [{"field": "date", "type": "temporal", "title": "Date"},
                        {"field": "price", "title": unit, "format": ",.0f"}],
        },
    }, theme)


def flows_spec(flows, unit: str = "€", theme: str = "dark") -> dict | None:
    """WHAT-IF's equity cash flows, one bar a year: money in (good) up, money
    out (bad) down, from year 0 (the purchase). None without any."""
    rows = [{"year": i, "amount": float(v or 0), "kind": "in" if (v or 0) >= 0 else "out"}
            for i, v in enumerate(flows or [])]
    if not rows:
        return None
    c = PALETTES.get(theme, PALETTES["dark"])
    return styled({
        "data": {"values": rows},
        "height": 180,
        "mark": {"type": "bar", "cornerRadiusEnd": 2},
        "encoding": {
            "x": {"field": "year", "type": "ordinal", "title": "Year",
                  "axis": {"labelAngle": 0}},
            "y": {"field": "amount", "type": "quantitative", "title": unit},
            "color": {"field": "kind", "type": "nominal", "legend": None,
                      "scale": {"domain": ["in", "out"], "range": [c["good"], c["bad"]]}},
            "tooltip": [{"field": "year", "title": "Year"},
                        {"field": "amount", "title": unit, "format": ",.0f"}],
        },
    }, theme)
