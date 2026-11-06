"""A Czech listing can be graded GREEN or YELLOW (H1): the okres and kraj
sale-price figures ship from ČSÚ's CEN0402 dataset, and Prague's and Brno's
districts are scaled from their city's figure by their listings' asking
prices (engine/price_comps_cz)."""

import csv
import os

import pytest

from engine import financial as fin
from engine import price_comps_cz as pc
from engine import regional_prices as rp
from engine import regional_prices_cz as cz
from tests.conftest import make_listing


# ── The shipped table ─────────────────────────────────────────────────────────
def _shipped():
    with open(cz.SHIPPED_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_every_okres_and_kraj_has_a_figure():
    rows = _shipped()
    okresy = {r["name"] for r in rows if r["level"] == "okres"}
    kraje = {r["name"] for r in rows if r["level"] == "kraj"}
    assert okresy == set(cz.OKRES_KRAJ)                 # all 76 and Prague
    assert kraje == set(cz.KRAJ_NAMES.values())
    assert set(cz.OKRES_KRAJ) <= set(cz.OKRES_MEDIAN)   # loaded at import


def test_one_source_and_one_period():
    rows = _shipped()
    assert {r["period"] for r in rows} == {"2025"}
    assert all(r["source"].startswith("ČSÚ CEN0402") for r in rows)
    assert all(13_900 <= float(r["median_czk_m2"]) <= 600_000 for r in rows)


@pytest.mark.parametrize("level,name,value", [
    # ČSÚ CEN0402, Byty [Kč/m2], 2025, all municipality sizes.
    ("kraj", "Hlavní město Praha", 131_520), ("okres", "Hlavní město Praha", 131_520),
    ("okres", "Brno-město", 99_713), ("okres", "Plzeň-město", 73_399),
    ("okres", "Hradec Králové", 77_507), ("okres", "Sokolov", 33_203),
    ("okres", "Ostrava-město", 60_498), ("kraj", "Moravskoslezský kraj", 51_694)])
def test_figures_as_published(level, name, value):
    assert {(r["level"], r["name"]): int(r["median_czk_m2"]) for r in _shipped()}[
        (level, name)] == value


@pytest.mark.parametrize("district,where", [
    ("Plzeň 3 - Jižní Předměstí", "okres Plzeň-město"),
    ("Kladno - Kročehlavy", "okres Kladno"),
    ("Říčany, Praha-východ", "okres Praha-východ"),
    ("Praha 7 - Holešovice", "okres Hlavní město Praha"),
    ("Brno-střed", "okres Brno-město")])
def test_districts_resolve_to_a_benchmark(district, where):
    median, found = rp.median_source(district, market="cz")
    assert median and found == where


def test_a_place_with_no_okres_still_has_no_benchmark():
    assert rp.median_source("Horní Dolní", market="cz") == (None, "")


def test_the_note_says_what_the_figure_is():
    note = rp.benchmark_note("Plzeň 3", market="cz")
    assert note.startswith("average purchase price of okres Plzeň-město: 73")
    assert "ČSÚ CEN0402" in note and "2025" in note
    assert "Prague as a whole" in rp.benchmark_note("Praha 14", market="cz")


# ── Classes ───────────────────────────────────────────────────────────────────
PLZEN = 73_399.0


@pytest.mark.parametrize("discount,cls", [(0.25, "GREEN"), (0.20, "GREEN"), (0.15, "YELLOW"),
                                          (0.10, "YELLOW"), (0.05, "WHITE"), (-0.1, "WHITE"),
                                          (0.6, "WHITE")])       # below the sanity floor
def test_a_czech_listing_gets_a_class(discount, cls):
    price = PLZEN * (1 - discount) * 50
    assert fin.class_at_price(price, 50, "Plzeň 3", market="cz") == cls


def test_a_czech_listing_has_a_max_offer():
    offer = fin.max_offer_price(50, "Plzeň 3", "GREEN", market="cz")
    assert offer and offer <= PLZEN * 0.8 * 50 and offer % fin.OFFER_STEP_CZK == 0
    assert fin.class_at_price(offer, 50, "Plzeň 3", market="cz") == "GREEN"


def test_scoring_grades_czech_listings(full_db):
    import database as db
    from modules.cashflow_runner import run_scoring
    for lid, ask in (("g", 0.75), ("y", 0.88), ("w", 1.0)):
        db.upsert_listing(make_listing(lid, market="cz", currency="CZK", district="Plzeň 3",
                                       size_m2=50.0, price_eur=round(PLZEN * ask * 50),
                                       url=f"https://example.cz/{lid}"))
    assert run_scoring(market="cz") == 3
    conn = full_db()
    got = {r["listing_id"]: (r["classification"], r["regional_median_m2"]) for r in conn.execute(
        "SELECT listing_id, classification, regional_median_m2 FROM cashflow_scores")}
    conn.close()
    assert got == {"g": ("GREEN", PLZEN), "y": ("YELLOW", PLZEN), "w": ("WHITE", PLZEN)}


def test_a_score_from_before_the_table_is_redone(full_db, monkeypatch):
    """A Czech listing scored WHITE with no benchmark is re-scored now."""
    import database as db
    from modules.cashflow_runner import run_scoring
    db.upsert_listing(make_listing("g", market="cz", currency="CZK", district="Plzeň 3",
                                   size_m2=50.0, price_eur=round(PLZEN * 0.75 * 50),
                                   url="https://example.cz/g"))
    with monkeypatch.context() as m:
        m.setattr(cz, "OKRES_MEDIAN", {})
        m.setattr(cz, "KRAJ_MEDIAN", {})
        assert run_scoring(market="cz") == 1
    conn = full_db()
    assert conn.execute("SELECT classification FROM cashflow_scores").fetchone()[0] == "WHITE"
    conn.close()
    assert run_scoring(market="cz") == 1
    conn = full_db()
    assert conn.execute("SELECT classification FROM cashflow_scores").fetchone()[0] == "GREEN"
    conn.close()


def test_a_users_own_csv_replaces_the_shipped_rows(tmp_path, monkeypatch):
    for table in ("OKRES_MEDIAN", "MEDIAN_SOURCE"):
        monkeypatch.setattr(cz, table, dict(getattr(cz, table)))
    monkeypatch.setattr(cz, "_TABLES", {**cz._TABLES, "okres": cz.OKRES_MEDIAN})
    monkeypatch.setattr(cz, "SOURCE", dict(cz.SOURCE))
    path = tmp_path / "cz_regional_prices.csv"
    path.write_text("level,name,median_czk_m2,period,source\n"
                    "okres,Sokolov,40000,2026-09,my broker\n", encoding="utf-8")
    assert cz.load_medians(str(path)) == 1
    assert cz.OKRES_MEDIAN["Sokolov"] == 40_000 and cz.OKRES_MEDIAN["Cheb"] > 0
    assert "ČSÚ CEN0402" in cz.SOURCE["source"] and str(path) in cz.SOURCE["source"]


# ── The build script ──────────────────────────────────────────────────────────
HEADER = ('"Ukazatel","IndicatorType","Počet obyvatel obce","VELSKUPOBC","Území-Stát",'
          '"Uz023h22.STAT","Území-Kraj","Uz023h22.KRAJ","Území-Okres","Uz023h22.OKRES",'
          '"Druh nemovitosti","REPRCENNEM","Roční a 3-letá období","CAS1R3R1","Hodnota"')


def _line(kraj, okres, value, kind="Byty [Kč/m2]", period="2025", size="Celkem"):
    return (f'"x","7432","{size}","0","Česko","CZ","{kraj}","","{okres}","","{kind}","1",'
            f'"{period}","{period}","{value}"')


def test_build_takes_flats_of_one_period_for_all_sizes():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_cz", os.path.join(os.path.dirname(cz.SHIPPED_CSV), "..", "dev",
                                 "build_cz_regional_prices.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    text = "\n".join([HEADER,
                      _line("Hlavní město Praha", "", 131520),
                      _line("Karlovarský kraj", "Sokolov", 33203),
                      _line("Karlovarský kraj", "Sokolov", 28592, period="2024"),
                      _line("Karlovarský kraj", "Sokolov", 99999, kind="Rodinné domy [Kč/m2]"),
                      _line("Karlovarský kraj", "Sokolov", 11111, size="do 1 999 obyv.")])
    rows = build.read_rows(text)
    assert build.latest_year(rows) == "2025"
    out = build.build(rows, "2025", "2026-11-06", "0" * 64)
    assert [(r["level"], r["name"], r["median_czk_m2"]) for r in out] == [
        ("kraj", "Hlavní město Praha", "131520"), ("okres", "Hlavní město Praha", "131520"),
        ("okres", "Sokolov", "33203")]
    with pytest.raises(SystemExit, match="Nowhere"):
        build.build(build.read_rows("\n".join([HEADER, _line("Karlovarský kraj", "Nowhere", 1)])),
                    "2025", "2026-11-06", "0" * 64)


# ── District levels in Prague and Brno ────────────────────────────────────────
def _rows(district, per_m2, n, start=0, **kw):
    return [{"id": f"{district}{start + i}", "district": district, "size_m2": 50.0,
             "price_eur": per_m2 * 50, **kw} for i in range(n)]


def test_measure_needs_enough_listings():
    rows = (_rows("Praha 14", 100_000, pc.MIN_DISTRICT_SAMPLE)
            + _rows("Praha 1", 200_000, pc.MIN_DISTRICT_SAMPLE - 1)
            + _rows("Praha", 130_000, 30))
    m = pc.measure(rows)
    assert m["Praha 14"]["factor"] == round(100_000 / 130_000, 3)
    assert m["Praha 1"]["factor"] is None                 # too few
    assert m["Praha 14"]["city_n"] == 2 * pc.MIN_DISTRICT_SAMPLE - 1 + 30


def test_measure_counts_a_flat_once_and_keeps_to_the_bounds():
    rows = (_rows("Praha 14", 100_000, pc.MIN_DISTRICT_SAMPLE, dup_group="same")
            + _rows("Praha 14", 5_000, 20, start=50)          # below the Czech floor
            + _rows("Praha", 130_000, 40))
    m = pc.measure(rows)
    assert m["Praha 14"]["n"] == 1 and m["Praha 14"]["factor"] is None
    m = pc.measure(_rows("Praha 2", 590_000, 10) + _rows("Praha", 100_000, 40))
    assert m["Praha 2"]["factor"] == pc.FACTOR_BOUNDS[1]


def test_brno_districts_are_measured_against_brno():
    m = pc.measure(_rows("Brno - Žabovřesky", 110_000, 10) + _rows("Brno", 100_000, 40))
    assert m["Žabovřesky"]["city"] == "Brno" and m["Žabovřesky"]["factor"] == 1.1
    assert pc.measure(_rows("Plzeň 3", 70_000, 50)) == {}   # outside Prague and Brno


def _cz_listing(lid, district, per_m2, **kw):
    return make_listing(lid, market="cz", currency="CZK", district=district, size_m2=50.0,
                        price_eur=per_m2 * 50, url=f"https://example.cz/{lid}", **kw)


def test_a_prague_district_is_judged_against_its_own_level(full_db):
    import database as db
    from modules.cashflow_runner import run_scoring
    for i in range(10):
        db.upsert_listing(_cz_listing(f"p14-{i}", "Praha 14 - Černý Most", 100_000))
    for i in range(30):
        db.upsert_listing(_cz_listing(f"p-{i}", "Praha", 130_000))
    # 23 % under Prague's figure, but no bargain for Praha 14.
    db.upsert_listing(_cz_listing("cheap", "Praha 14", 101_000))
    before = fin.class_at_price(101_000 * 50, 50, "Praha 14", market="cz")
    out = pc.rebuild()
    assert out["with_factor"] == 1 and out["changed"] == ["Praha 14"]
    median, where = rp.median_source("Praha 14", market="cz")
    factor = round(100_000 / 130_000, 3)
    assert median == round(131_520 * factor, 2)
    assert where.startswith("Praha 14: Prague × 0.77") and "11 listings" in where
    assert before == "GREEN"
    assert fin.class_at_price(101_000 * 50, 50, "Praha 14", market="cz") == "WHITE"
    note = rp.benchmark_note("Praha 14", market="cz")
    assert "Praha 14: Prague × 0.77" in note and "ČSÚ CEN0402" in note
    assert run_scoring(market="cz") >= 1
    conn = full_db()
    cls = conn.execute("SELECT classification FROM cashflow_scores WHERE listing_id='cheap'"
                       ).fetchone()[0]
    conn.close()
    assert cls == "WHITE"
    assert pc.factors_table()[0]["District"] == "Praha 14"


def test_a_moved_district_level_redoes_its_scores(full_db):
    import database as db
    for i in range(10):
        db.upsert_listing(_cz_listing(f"p14-{i}", "Praha 14", 100_000))
    for i in range(30):
        db.upsert_listing(_cz_listing(f"p-{i}", "Praha", 130_000))
    pc.rebuild()
    r = fin.analyse(100_000 * 50, 50, "Praha 14", listing_id="p14-0", rent_override=20_000,
                    market="cz")
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    db.upsert_cashflow(row)
    assert pc.rebuild()["rescored"] == 0                  # nothing moved
    for i in range(10, 20):                               # Praha 14 a lot dearer now
        db.upsert_listing(_cz_listing(f"p14-{i}", "Praha 14", 160_000))
    out = pc.rebuild()
    assert out["changed"] == ["Praha 14"] and out["rescored"] == 1


def test_no_factor_table_means_the_city_figure(full_db):
    assert pc.district_factor("Praha 14") is None
    assert rp.median_source("Praha 14", market="cz") == (131_520.0, "okres Hlavní město Praha")
