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
