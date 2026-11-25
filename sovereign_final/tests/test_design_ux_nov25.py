"""Design D17–D22 and ease of use UX1, UX2, UX4, UX5, UX7 (audit PDF, section 15)."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── D20: one chart style ─────────────────────────────────────────────────────
def test_every_chart_has_the_dashboards_style():
    from dashboard.charts import FONT, flows_spec, price_spec, waterfall_spec
    specs = [waterfall_spec(800, [("Mortgage", 500)], 300, theme="light"),
             price_spec([("2026-01-01", 1), ("2026-02-01", 2)]),
             flows_spec([-30_000, 2_000, 2_100], "€", "dark")]
    for spec in specs:
        assert spec["config"]["font"] == FONT == "IBM Plex Sans"
        assert spec["background"] == "transparent"
        assert spec["config"]["axis"]["gridColor"]
    light = waterfall_spec(800, [("Mortgage", 500)], 300, theme="light")
    assert light["config"]["axis"]["labelColor"] == "#566075"     # the light palette's muted


def test_the_equity_flows_are_red_when_money_goes_out():
    from dashboard.charts import PALETTES, flows_spec
    spec = flows_spec([-30_000, 2_000], "Kč", "dark")
    kinds = [r["kind"] for r in spec["data"]["values"]]
    assert kinds == ["out", "in"]
    assert spec["encoding"]["color"]["scale"]["range"] == [PALETTES["dark"]["good"],
                                                          PALETTES["dark"]["bad"]]
    assert spec["encoding"]["y"]["title"] == "Kč" and flows_spec([]) is None


def test_no_chart_bypasses_the_style():
    """Streamlit's quick charts draw in its own fonts and colours."""
    import re
    for path in (ROOT / "dashboard").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = re.findall(r"st\.(bar|line|area|scatter)_chart\(|st\.altair_chart\(", text)
        assert not hits, f"{path.name}: {hits}"
        if path.name != "charts.py":
            assert "st.vega_lite_chart(" not in text, path.name
