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


# ── D21: the printouts in the dashboard's font ───────────────────────────────
def _pdf_fonts_and_text(data: bytes):
    import io

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    fonts = set()
    for page in reader.pages:
        for f in (page["/Resources"].get("/Font") or {}).values():
            fonts.add(str(f.get_object()["/BaseFont"]))
    return fonts, "\n".join(p.extract_text() for p in reader.pages)


def test_the_memo_embeds_the_shipped_plex_and_keeps_every_letter():
    from datetime import datetime, timezone

    from modules import memo
    from tests.test_audit3_docs_memo import _sk_row
    assert memo._FONT_CANDIDATES[0][0].endswith("IBMPlexSans-Regular.woff")
    row = {**_sk_row(), "title": "3-izbový byt, Ľudovíta Štúra, Žilina – Řečkovice"}
    data = memo.build_memo_pdf(row, generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc))
    fonts, text = _pdf_fonts_and_text(data)
    assert any("IBMPlexSans" in f for f in fonts), fonts
    assert "Ľudovíta Štúra" in text and "Řečkovice" in text and "€" in text


def test_the_offer_sheet_too():
    from modules.offer_sheet import build_offer_sheet
    from tests.test_audit3_docs_memo import _sk_row
    row = _sk_row()
    comps = [{"title": "Byt 2+1, Ružinov", "district": row.get("district"), "size_m2": 60,
              "price_eur": 150_000, "url": "https://example.sk/1"}]
    fonts, text = _pdf_fonts_and_text(build_offer_sheet(row, comps))
    assert any("IBMPlexSans" in f for f in fonts) and "€" in text


def test_a_long_label_is_fitted_not_run_into_its_value():
    from modules.memo import _Memo
    pdf = _Memo()
    pdf.add_page()
    label = "At rate +2 pp (personal): self-funding"
    fitted = pdf.fit(label, 40, 8)
    assert pdf.get_string_width(fitted) <= 40
    assert pdf.fit("x" * 200, 20, 8).endswith("…")


def test_the_pdf_fonts_are_not_in_the_public_static_folder():
    assert (ROOT / "modules" / "fonts" / "IBMPlexSans-Regular.woff").exists()
    assert (ROOT / "modules" / "fonts" / "OFL-IBM-Plex-Sans.txt").exists()
    assert not list((ROOT / "static").rglob("IBMPlexSans-*.woff"))
