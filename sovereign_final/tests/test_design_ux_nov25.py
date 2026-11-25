"""Design D17–D22 and ease of use UX1, UX2, UX4, UX5, UX7 (audit PDF, section 15)."""

import pathlib

import pytest

import tests.test_app_smoke as smoke
from tests.test_app_smoke import run_app

db = smoke.db
populated_db = smoke.populated_db
_isolated_runs = smoke._isolated_runs

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


# ── D17: the flat's photo, fetched by the server ─────────────────────────────
def _png(w=1200, h=800) -> bytes:
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 140, 160)).save(buf, "PNG")
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, body=b"", location=None):
        self.status_code, self._body = status, body
        self.headers = {"location": location} if location else {}

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        pass


def _resolve(monkeypatch, table):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(2, 1, 6, "", (table[host], 0))])


def test_the_photo_address_is_the_first_web_address():
    from dashboard.photos import photo_url
    assert photo_url({"primary_image_url": "", "image_urls": "x https://img.sk/1.jpg, b"}) \
        == "https://img.sk/1.jpg"
    assert photo_url({"primary_image_url": "javascript:alert(1)"}) == ""


def test_only_public_web_addresses_are_fetched(monkeypatch):
    import pytest

    from dashboard import photos
    _resolve(monkeypatch, {"img.portal.sk": "93.184.216.34", "router": "192.168.1.1",
                           "me": "127.0.0.1", "meta": "169.254.169.254", "v6": "::1"})
    assert photos._checked("https://img.portal.sk/a.jpg")
    for bad in ("http://router/a.jpg", "http://me/a.jpg", "http://meta/latest",
                "http://v6/a", "ftp://img.portal.sk/a", "https://img.portal.sk:8443/a",
                "file:///etc/passwd"):
        with pytest.raises(photos.NoPhoto):
            photos._checked(bad)


@pytest.mark.real_photos
def test_a_redirect_into_your_network_is_refused_and_the_size_capped(monkeypatch):
    import pytest
    import requests

    from dashboard import photos
    _resolve(monkeypatch, {"img.portal.sk": "93.184.216.34", "me": "127.0.0.1"})
    answers = {"https://img.portal.sk/a.jpg": _Resp(302, location="http://me/secret"),
               "https://img.portal.sk/big.jpg": _Resp(200, b"x" * (photos.MAX_BYTES + 10)),
               "https://img.portal.sk/ok.jpg": _Resp(301, location="/real.jpg"),
               "https://img.portal.sk/real.jpg": _Resp(200, b"bytes")}
    monkeypatch.setattr(requests, "get", lambda url, **kw: answers[url])
    with pytest.raises(photos.NoPhoto, match="not a public address"):
        photos._download("https://img.portal.sk/a.jpg")
    with pytest.raises(photos.NoPhoto, match="too large"):
        photos._download("https://img.portal.sk/big.jpg")
    assert photos._download("https://img.portal.sk/ok.jpg") == b"bytes"   # a same-site hop


def test_a_photo_is_shrunk_and_re_encoded_and_a_non_picture_refused():
    import io

    import pytest
    from PIL import Image

    from dashboard import photos
    out = photos.thumbnail(_png(1600, 900))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG" and max(img.size) == photos.THUMB_PX
    with pytest.raises(photos.NoPhoto):
        photos.thumbnail(b"<html>not a picture</html>")


def test_a_failure_is_not_kept_and_not_retried_on_every_click(monkeypatch):
    from dashboard import photos
    calls = []

    def fake(url):
        calls.append(url)
        raise photos.NoPhoto("HTTP 403")
    monkeypatch.setattr(photos, "_download", fake)
    photos._photo.clear()
    assert photos.listing_photo("https://img.sk/x.jpg") is None
    assert photos.listing_photo("https://img.sk/x.jpg") is None
    assert len(calls) == 1                                # not again for FAIL_TTL_S
    monkeypatch.setattr(photos, "_download", lambda url: _png())
    photos._failed.clear()
    assert photos.listing_photo("https://img.sk/x.jpg")   # now it works, and is kept
    photos._photo.clear()


def test_the_card_shows_the_servers_copy_never_the_portals_address(populated_db, monkeypatch):
    from dashboard import photos
    portal = "https://img.portal.sk/byt-g1.jpg"
    asked = []
    monkeypatch.setattr(photos, "_download", lambda url: asked.append(url) or _png())
    photos._photo.clear()
    conn = populated_db.get_conn()
    conn.execute("UPDATE listings SET primary_image_url=? WHERE id='g1'", (portal,))
    conn.commit()
    conn.close()
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    assert asked == [portal] and at.get("image")
    page = " ".join(str(e.proto) for e in at.get("image")) + " ".join(m.value for m in at.markdown)
    assert portal not in page
    photos._photo.clear()


def test_the_privacy_notice_says_the_server_fetches_the_photos():
    from dashboard import legal
    text = " ".join(legal.privacy_md().split())
    assert "Listing photos are fetched by the dashboard's server" in text
    assert "listing photos from the portals'" not in text


# ── D18: where the price sits ────────────────────────────────────────────────
def _eur_m2(v):
    return f"€{v:,.0f}/m²"


def test_the_band_marks_the_flat_and_the_median_and_says_it_in_words():
    from dashboard.verdict import price_band_html
    html = price_band_html(1800, [2000, 2400, 2600, 3000], _eur_m2, "Trnava")
    assert "cheaper than 4 of 4 similar flats (Trnava)" in html
    assert "€2,000/m² to €3,000/m²" in html and "median €2,500/m²" in html
    assert 'class="pband-me good"' in html and 'left:0.0%' in html      # the cheapest
    dear = price_band_html(3200, [2000, 2400, 2600], _eur_m2)
    assert 'class="pband-me bad"' in dear and "cheaper than 0 of 3" in dear


def test_too_few_flats_like_it_and_no_band():
    from dashboard.verdict import price_band_html
    assert price_band_html(1800, [2000, 2400], _eur_m2) == ""
    assert price_band_html(None, [2000, 2400, 2600], _eur_m2) == ""


def test_the_band_escapes_the_area_and_speaks_czech():
    from dashboard.verdict import price_band_html
    html = price_band_html(80_000, [90_000, 100_000, 110_000],
                           lambda v: f"{v:,.0f} Kč/m²".replace(",", " "),
                           "<b>Praha 2</b>", cz=True)
    assert "&lt;b&gt;Praha 2" in html and "<b>Praha 2" not in html
    assert "levnější než 3 z 3 podobných bytů" in html


def test_an_open_card_shows_where_its_price_sits(populated_db):
    from tests.conftest import make_listing
    for i, price in enumerate((120_000, 130_000, 140_000)):
        populated_db.upsert_listing(make_listing(f"t{i}", district="Trnava", price_eur=float(price),
                                                 size_m2=55.0))
    at = run_app(open_cards=("g1",))
    assert not at.exception, [e.value for e in at.exception]
    bands = [m.value for m in at.markdown if 'class="pband"' in m.value]
    assert bands and "cheaper than 3 of 3 similar flats" in bands[0]


# ── D22 + UX5: TRIAGE TABLE as a list on a phone; acting on several rows ──────
def _tick(monkeypatch, rows):
    """Make the triage table report `rows` as ticked (AppTest can't tick a
    dataframe row itself)."""
    from types import SimpleNamespace

    from streamlit.delta_generator import DeltaGenerator
    real = DeltaGenerator.dataframe

    def ticked(self, data=None, *a, **kw):
        if str(kw.get("key", "")).startswith("triage_pick"):
            real(self, data, *a, **{k: v for k, v in kw.items()
                                    if k not in ("on_select", "selection_mode", "key")})
            return SimpleNamespace(selection=SimpleNamespace(rows=list(rows)))
        return real(self, data, *a, **kw)
    monkeypatch.setattr(DeltaGenerator, "dataframe", ticked)


def test_one_ticked_row_shows_its_summary(populated_db, monkeypatch):
    """D3's summary: it used to raise, because the row loop had reused the
    name `v` for a money helper by the time the summary read v.data."""
    _tick(monkeypatch, [0])
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    assert any("pick-t" in m.value for m in at.markdown)


def test_several_ticked_rows_can_be_starred_compared_or_passed(populated_db, monkeypatch):
    _tick(monkeypatch, [0, 1, 2])
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    star = at.button(key="bulk_star")
    assert star.label == "★ Star all 3"
    star.click().run()
    assert len(populated_db.get_starred()) == 3
    at.button(key="bulk_cmp").click().run()
    assert len(at.session_state["cmp_pick"]) == 3
    assert at.query_params["tab"] in ("COMPARE", ["COMPARE"])


def test_passing_several_needs_a_tick_and_spares_a_closed_deal(populated_db, monkeypatch):
    _tick(monkeypatch, [0, 1, 2])
    at = run_app()
    assert at.button(key="bulk_pass").disabled
    populated_db.set_deal_stage("w1", "CLOSED", "bought")
    at.checkbox(key="bulk_pass_ok").check().run()
    at.button(key="bulk_pass").click().run()
    stages = populated_db.get_deal_stages()
    assert sum(1 for s in stages.values() if s["stage"] == "PASSED") == 2
    assert stages["w1"]["stage"] == "CLOSED"


def test_a_phone_gets_a_list_a_page_at_a_time(populated_db):
    from tests.conftest import make_listing
    for i in range(30):
        populated_db.upsert_listing(make_listing(f"m{i:02d}", district="Žilina",
                                                 price_eur=80_000.0 + i, size_m2=55.0))
    from modules.cashflow_runner import run_scoring
    run_scoring()
    at = run_app()
    assert not at.exception, [e.value for e in at.exception]
    opens = [b for b in at.button if str(b.key).startswith("trio_")]
    assert len(opens) == 25                                   # a page
    opens[0].click().run()
    assert any("pick-t" in m.value for m in at.markdown)      # its summary, under it
    at.button(key="trip_next").click().run()
    assert at.session_state["triage_phone_page"] == 1


def test_the_stylesheet_shows_one_of_the_two():
    from dashboard import style
    css = style.CSS if hasattr(style, "CSS") else open(style.__file__, encoding="utf-8").read()
    assert "@media (min-width: 601px) { .st-key-triage_narrow { display: none !important; } }" in css
    assert "@media (max-width: 600px) { .st-key-triage_wide { display: none !important; } }" in css


# ── UX1: the filters remembered, and saved searches ──────────────────────────
def test_a_changed_filter_is_still_set_in_a_new_session(populated_db):
    at = run_app()
    at.sidebar.slider(key="fl_max_price").set_value(150_000).run()
    at.sidebar.toggle(key="fl_cf").set_value(True).run()
    again = run_app()                                    # a reload, or the phone
    assert not again.exception, [e.value for e in again.exception]
    assert again.sidebar.slider(key="fl_max_price").value == 150_000
    assert again.sidebar.toggle(key="fl_cf").value is True


def test_a_stale_or_broken_stored_value_falls_back_to_its_default():
    from dashboard import filters
    opts, structs = ["bazos", "topreality"], ["Recommended", "Personal"]
    assert filters._valid("fl_sources", ["bazos", "gone_portal"], opts, structs) == ["bazos"]
    assert filters._valid("fl_sources", "not a list", opts, structs) == opts
    assert filters._valid("fl_max_price", 9_999_999, opts, structs) == 300_000
    assert filters._valid("fl_max_price", 152_400, opts, structs) == 150_000   # on the step
    assert filters._valid("fl_parking", "yes", opts, structs) is False
    assert filters._valid("structure", "Gone", opts, structs) == "Recommended"
    assert filters._valid("fl_classes", ["GREEN", "<script>"], opts, structs) == ["GREEN"]


def test_a_saved_search_comes_back_and_can_be_deleted(populated_db):
    at = run_app()
    at.sidebar.slider(key="fl_min_size").set_value(60).run()
    at.sidebar.text_input(key="fl_district").input("Žilina").run()
    at.sidebar.text_input(key="fl_save_name").input("Žilina big").run()
    at.sidebar.button(key="fl_save").click().run()
    at.sidebar.slider(key="fl_min_size").set_value(25).run()
    at.sidebar.text_input(key="fl_district").input("").run()
    at.sidebar.selectbox(key="fl_saved_pick").select("Žilina big").run()
    at.sidebar.button(key="fl_apply").click().run()
    assert at.sidebar.slider(key="fl_min_size").value == 60
    assert at.sidebar.text_input(key="fl_district").value == "Žilina"
    at.sidebar.button(key="fl_delete").click().run()
    from dashboard import filters
    assert filters.saved_names() == []


def test_a_saved_search_becomes_an_alert_rule(populated_db):
    from dashboard import filters
    rule = filters.rule_from({"fl_classes": ["GREEN", "WHITE"], "fl_district": "Žilina",
                              "fl_min_size": 50, "fl_max_price": 150_000, "fl_cf": True},
                             "Žilina big")
    assert rule["classes"] == "GREEN" and rule["district"] == "Žilina"
    assert (rule["min_size"], rule["max_price_eur"], rule["min_surplus"]) == (50, 150_000, 0)
    at = run_app()
    at.sidebar.text_input(key="fl_save_name").input("Cheap Žilina").run()
    at.sidebar.button(key="fl_save").click().run()
    at.sidebar.selectbox(key="fl_saved_pick").select("Cheap Žilina").run()
    at.sidebar.button(key="fl_rule").click().run()
    rules = populated_db.get_alert_rules()
    assert [r["name"] for r in rules] == ["Cheap Žilina"]
    at.sidebar.button(key="fl_rule").click().run()               # not twice
    assert len(populated_db.get_alert_rules()) == 1
