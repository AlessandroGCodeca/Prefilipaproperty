"""Dashboard features from the 6 November 2026 audit's suggestions: the triage
table's column chooser and CSV export, "last seen" on every card, the portal
health strip, the COMPARE tab, the richer map and the compact cards."""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("streamlit")

from tests.conftest import make_listing  # noqa: E402
from tests.test_app_smoke import markdown_of, run_app  # noqa: E402

XSS = '<img src=x onerror="alert(1)"> Byt'


def _iso(days_ago=0, hours_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)).isoformat()


@pytest.fixture
def db(monkeypatch, tmp_path):
    import database
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    return database


def _add(db, lid, ratio=0.7, district="Žilina", **over):
    """A flat at `ratio` × its district's median, scored (0.7: GREEN)."""
    from engine.regional_prices import regional_median_price
    from modules.cashflow_runner import run_scoring
    price = round(regional_median_price(district) * 55 * ratio)
    over.setdefault("last_seen_at", _iso())
    db.upsert_listing(make_listing(lid, district=district, price_eur=float(price), size_m2=55.0,
                                   scraped_at=_iso(9), **over))
    run_scoring()


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def _triage(at):
    return next(d for d in at.dataframe if "Grade" in d.value.columns)


# ── Triage: the column chooser and the CSV export ─────────────────────────────
def test_triage_columns_can_be_hidden_but_the_pinned_ones_stay(db):
    from dashboard.tabs.triage import PINNED
    _add(db, "g1")
    at = _ok(run_app())
    order = list(_triage(at).proto.column_order)
    assert order[:len(PINNED)] == list(PINNED) and "Score" in order and "URL" in order
    chooser = at.multiselect(key="triage_hide")
    assert not set(PINNED) & set(chooser.options)        # the pinned can't be hidden
    chooser.set_value(["Score", "URL"]).run()
    order = list(_triage(_ok(at)).proto.column_order)
    assert "Score" not in order and "URL" not in order
    assert order[:len(PINNED)] == list(PINNED)


def test_a_hidden_column_that_is_gone_is_forgotten(db):
    # "Native" only exists with both markets on the page: a choice kept from
    # then must not break the page.
    _add(db, "g1")
    at = run_app()
    at.session_state["triage_hide"] = ["Native", "No such column"]
    _ok(at.run())
    assert at.session_state["triage_hide"] == []


def test_the_triage_table_exports_as_csv(db):
    import pandas as pd
    from dashboard.tabs.triage import triage_csv
    _add(db, "g1", title="Byt, Žilina — čerešňa")
    at = _ok(run_app())
    assert any(b.label == "⬇️ CSV" for b in at.get("download_button"))
    csv = triage_csv(_triage(at).value)
    assert csv.startswith(b"\xef\xbb\xbf")               # Excel reads the diacritics
    text = csv.decode("utf-8-sig")
    assert text.splitlines()[0].split(",")[1:4] == ["Grade", "Score", "Title"]
    assert "Byt, Žilina — čerešňa" in text
    assert len(pd.read_csv(pd.io.common.BytesIO(csv))) == 1


# ── "Last seen" on every card ─────────────────────────────────────────────────
@pytest.mark.parametrize("days, cz, text", [
    (0, False, "last seen today"), (1, False, "last seen yesterday"),
    (5, False, "last seen 5 days ago"), (9, False, "last seen 9 days ago ⚠"),
    (0, True, "naposledy viděno dnes"), (3, True, "naposledy viděno před 3 dny"),
])
def test_last_seen_label(days, cz, text):
    from dashboard.fmt import last_seen_label
    assert last_seen_label({"last_seen_at": _iso(days, hours_ago=1)}, cz) == text


def test_last_seen_is_blank_without_a_date():
    from dashboard.fmt import last_seen_label
    assert last_seen_label({}) == "" and last_seen_label({"last_seen_at": "nonsense"}) == ""


def test_an_open_card_says_when_it_was_last_seen(db):
    _add(db, "g1", last_seen_at=_iso(4, hours_ago=1))
    md = markdown_of(_ok(run_app(open_cards=("g1",))))
    assert "First seen by this dashboard" in md and "last seen 4 days ago" in md


# ── The portal health strip ───────────────────────────────────────────────────
def test_portal_health_counts_each_day_and_the_last_good_run(db):
    conn = db.get_conn()
    try:
        for days_ago, n, err in ((6, 400, ""), (2, 380, ""), (2, 420, ""), (1, 0, ""),
                                 (0, 0, "HTTP 403")):
            conn.execute("INSERT INTO portal_runs (market, source, run_at, listings, error) "
                         "VALUES ('sk', 'bazos', ?, ?, ?)", (_iso(days_ago, hours_ago=1), n, err))
        conn.commit()
    finally:
        conn.close()
    h = db.portal_health(days=7)[("sk", "bazos")]
    assert h["daily"] == [400, None, None, None, 420, 0, 0]      # the day's best run
    assert h["last"]["error"] == "HTTP 403" and h["last"]["listings"] == 0
    assert h["last_good_at"][:10] == _iso(2, hours_ago=1)[:10]


def test_sparkline():
    from dashboard.overview import sparkline
    # Each day against the week's best, on eight levels.
    assert sparkline([400, None, 200, 0, 0, 100, 400]) == "█·▅▁▁▃█"
    assert sparkline([None] * 3) == "···" and sparkline([0, 0]) == "▁▁"


def test_the_strip_shows_each_portal_and_flags_a_bad_or_late_one():
    from dashboard.overview import portal_strip
    now = datetime.now(timezone.utc)
    run = lambda h, n, err="": {"run_at": (now - timedelta(hours=h)).isoformat(),  # noqa: E731
                                "listings": n, "error": err}
    health = {
        ("sk", "nehnutelnosti"): {"daily": [300] * 7, "last": run(2, 310), "last_good_at": None},
        ("sk", "bazos"): {"daily": [50, 0], "last": run(3, 0, "<b>403</b> blocked"),
                          "last_good_at": (now - timedelta(days=3)).isoformat()},
        ("sk", "topreality"): {"daily": [90], "last": run(60, 90), "last_good_at": None},
    }
    html = portal_strip(health, "sk", now)
    chips = html.split('<span class="phc ')[1:]
    assert [c.split('"')[0] for c in chips] == ["ok", "bad", "old"]
    assert "Nehnutelnosti.sk <b>310</b>" in chips[0]
    assert "failed" in chips[1] and "last good" in chips[1]
    assert "<b>403</b>" not in chips[1] and "&lt;b&gt;403" in chips[1]   # escaped
    assert "last run" in chips[2]
    # Czech portals aren't on a Slovak page; with no run at all, no strip.
    assert "Bezrealitky" not in html and "Bezrealitky" in portal_strip(health, None, now)
    assert portal_strip({}, "sk", now) == ""


def test_the_page_shows_the_strip_once_a_portal_has_run(db):
    _add(db, "g1")
    assert 'class="ph"' not in markdown_of(_ok(run_app()))
    db.record_portal_run("sk", "bazos", _iso(hours_ago=1), 12, "")
    md = markdown_of(_ok(run_app()))
    assert 'class="ph"' in md and "Bazos.sk <b>12</b>" in md
    assert "Nehnutelnosti.sk — no run yet" in md


# ── COMPARE ───────────────────────────────────────────────────────────────────
def test_comparison_table_has_a_column_per_listing(db):
    from dashboard.tabs.compare import comparison_table
    from dashboard.fmt import _tag_market
    _add(db, "g1", title="Flat one")
    _add(db, "w1", ratio=1.0, district="Nitra", title="Flat two")
    rows = [_tag_market(l) for l in db.get_all_active()]
    df = comparison_table(rows)
    assert list(df.columns) == ["", "Flat one [g1]", "Flat two [w1]"]
    col = dict(zip(df[""], df["Flat one [g1]"]))
    assert col["Class"] == "🟢 GREEN" and col["District"] == "Žilina"
    g1 = next(l for l in rows if l["id"] == "g1")
    assert col["Against the market"] == f"{g1['market_discount']:.0%} below"
    assert col["Price per m²"].startswith("€") and col["Surplus — personal"].endswith("/mo")
    assert col["Title deed (LV)"] and col["Flood (Q100)"] == "— unknown"
    assert dict(zip(df[""], df["Flat two [w1]"]))["Class"] == "⚪ WHITE"


def test_compare_tab_compares_the_listings_picked(db):
    for i in range(5):
        _add(db, f"g{i}", title=f"Flat {i} {XSS if i == 0 else ''}")
    at = _ok(run_app())
    pick = at.multiselect(key="cmp_pick")
    assert pick.proto.max_selections == 4 and len(pick.options) == 5
    assert any("Pick at least two listings" in c.value for c in at.caption)
    pick.set_value(pick.options[:2]).run()
    table = next(d.value for d in _ok(at).dataframe
                 if "" in d.value.columns and "Against the market" in set(d.value[""]))
    assert len(table.columns) == 3
    md = markdown_of(at)
    assert "<img src=x" not in md                        # the links under it are escaped


def test_compare_needs_two_scored_listings(db):
    _add(db, "g1")
    at = _ok(run_app())
    assert any("it takes two scored listings" in i.value for i in at.info)
    assert not [m for m in at.multiselect if m.key == "cmp_pick"]


def test_a_compared_listing_the_filters_hide_is_dropped(db):
    _add(db, "g1")
    _add(db, "g2")
    at = run_app()
    at.session_state["cmp_pick"] = ["Gone flat — €1 [zzzzzz]"]
    _ok(at.run())
    assert at.session_state["cmp_pick"] == []


# ── The map ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, point", [
    ("48.1486, 17.1077", (48.1486, 17.1077)), ("48,1486; 17,1077", (48.1486, 17.1077)),
    (" 49.2  18.7 ", (49.2, 18.7)), ("Hlavná 5, Košice", None), ("", None),
    ("95.0, 17.1", None),
])
def test_parse_point(text, point):
    from dashboard.tabs.map_view import parse_point
    assert parse_point(text) == point


def test_distance_colour_and_grouping():
    from dashboard.tabs.map_view import cashflow_color, cluster, cluster_cell, km_between
    # Bratislava to Košice, about 313 km in a straight line.
    assert km_between(48.1486, 17.1077, 48.7164, 21.2611) == pytest.approx(313, abs=5)
    assert cashflow_color(150) == [0, 230, 118] and cashflow_color(0) == [150, 220, 130]
    assert cashflow_color(-50) == [255, 145, 0] and cashflow_color(-400) == [255, 82, 82]
    assert cashflow_color(None) == [96, 125, 139]
    pins = [{"lat": 49.2200, "lng": 18.7400, "rank": 1, "id": "a"},
            {"lat": 49.2210, "lng": 18.7410, "rank": 3, "id": "b"},
            {"lat": 49.2205, "lng": 18.7405, "rank": 2, "id": "c"},
            {"lat": 48.1486, "lng": 17.1077, "rank": 0, "id": "d"}]
    groups = cluster(pins, 0.03)
    assert [g["n"] for g in groups] == [3, 1]
    # One town either side of a grid line (49.2 | 49.3 at a 0.1° cell) is one
    # group, not two circles on top of each other.
    split = [{"lat": 49.299, "lng": 18.74, "rank": 1}, {"lat": 49.301, "lng": 18.74, "rank": 2},
             {"lat": 49.302, "lng": 18.74, "rank": 0}, {"lat": 48.70, "lng": 21.26, "rank": 0}]
    assert [g["n"] for g in cluster(split, 0.1)] == [3, 1]
    # The cell follows the view: a tenth of the pins' span, or of the search
    # circle's width — within its limits.
    assert cluster_cell(pins) == pytest.approx((18.7410 - 17.1077) / 10)
    assert cluster_cell(pins, radius_km=10) == pytest.approx(20 / 111 / 10)
    assert cluster_cell(pins, radius_km=1) == 0.01 and cluster_cell(pins[:1]) == 0.01
    assert groups[0]["best"]["id"] == "b"                 # coloured as its best listing
    assert groups[0]["lat"] == pytest.approx(49.2205)


def _deck(at) -> str:
    return next(iter(at.get("deck_gl_json_chart"))).proto.json


def test_map_colours_groups_and_filters_by_distance(db):
    _add(db, "near", lat=49.2231, lng=18.7394, title=XSS)             # Žilina
    _add(db, "near2", lat=49.2240, lng=18.7400)
    _add(db, "far", district="Košice", lat=48.7164, lng=21.2611)
    at = _ok(run_app())
    spec = _deck(at)
    assert "<img src=x" not in spec and "&lt;img src=x" in spec      # the tooltip is HTML
    assert "3 of 3 filtered listings have coordinates" in markdown_of(at)

    at.radio(key="map_color").set_value("Cash flow").run()
    assert "light green: break-even or better" in markdown_of(_ok(at))
    at.toggle(key="map_group").set_value(True).run()
    spec = _deck(_ok(at))
    assert "TextLayer" in spec and "2 listings here" in spec

    at.text_input(key="map_near").set_value("49.2231, 18.7394").run()
    md = markdown_of(_ok(at))
    assert "2 of 3 filtered listings within 10 km (straight line) of 49.2231, 18.7394" in md
    assert "km away" in _deck(at)
    at.text_input(key="map_near").set_value("50.0755, 14.4378").run()   # Prague
    assert any("No listing within that distance" in i.value for i in _ok(at).info)


def test_an_address_that_cant_be_placed_says_so(db, monkeypatch):
    from modules import location_iq
    looked_up = []
    monkeypatch.setattr(location_iq, "geocode_precise",
                        lambda a, m="sk": looked_up.append(a) or (None, None, ""))
    _add(db, "g1", lat=49.2231, lng=18.7394)
    at = _ok(run_app())
    at.text_input(key="map_near").set_value("Nowhere 5").run()
    assert any("Couldn't place" in w.value for w in _ok(at).warning)
    assert "1 of 1 filtered listings have coordinates" in markdown_of(at)   # not filtered
    at.run()
    assert looked_up == ["Nowhere 5"]                    # looked up once, not per rerun


# ── Compact cards ─────────────────────────────────────────────────────────────
def test_compact_cards_show_the_essentials_and_one_button(db):
    _add(db, "g1", title=XSS)
    _add(db, "y1", ratio=0.92, title="Yellow flat")   # 10–20 % under its 2-room benchmark
    at = _ok(run_app())
    assert [e for e in at.expander if e.label.startswith(("🟢", "🟡"))]
    at.toggle(key="compact_cards").set_value(True).run()
    assert not [e for e in _ok(at).expander if e.label.startswith(("🟢", "🟡"))]
    md = markdown_of(at)
    cards = md.split('<div class="cc ')[1:]
    assert len(cards) == 2 and cards[0].startswith('g">') and cards[1].startswith('y">')
    assert "<img src=x" not in md and "&lt;img src=x" in cards[0]
    assert "GREEN" in cards[0] and "% below market" in cards[0] and "/mo" in cards[0]
    assert cards[0].count("OPEN LISTING ↗") == 1 and 'href="https://example.sk/g1"' in cards[0]
