"""The MF rent map fallback (engine.rent_map_cz): Deloitte first, a town or
its katastrální území, the listing's own size category, no low-coverage
figure and no neighbour's — and dev/build_cz_rent_map.py's extraction. Real
place names, synthetic figures only."""

import csv
import importlib.util
import os

import pytest

import markets
from engine import financial as fin
from engine import rent_comps_cz, rent_cz, rent_map_cz

# kraj, obec, code, ku, coverage, rents for VK 1–4.
PLACES = [
    ("Středočeský kraj", "Kladno", "665061", "Kladno", 5, (300, 280, 260, 240)),
    ("Středočeský kraj", "Kladno", "665126", "Kročehlavy", 5, (310, 290, 270, 250)),
    ("Středočeský kraj", "Kladno", "664961", "Rozdělov", 2, (330, 320, 310, 300)),
    ("Pardubický kraj", "Kladno", "571580", "", 4, (160, 150, 140, 130)),   # a village
    ("Moravskoslezský kraj", "Opava", "711560", "Opava-Město", 5, (220, 200, 180, 160)),
    ("Moravskoslezský kraj", "Opava", "711578", "Opava-Předměstí", 5, (225, 205, 185, 165)),
    ("Moravskoslezský kraj", "Opava", "711756", "Kateřinky u Opavy", 4, (230, 210, 190, 170)),
    ("Ústecký kraj", "Most", "699357", "Most I", 1, (230, 180, 170, 150)),
    ("Ústecký kraj", "Most", "699594", "Most II", 5, (225, 190, 180, 160)),
    ("Jihočeský kraj", "Písek", "720755", "Písek", 5, (260, 230, 210, 200)),
    ("Královéhradecký kraj", "Písek", "570575", "", 3, (240, 220, 200, 180)),
    ("Moravskoslezský kraj", "Písek", "512028", "", 3, (230, 210, 190, 170)),
    ("Jihomoravský kraj", "Bukovany", "586331", "", 4, (200, 190, 180, 170)),
    ("Jihomoravský kraj", "Bukovany", "586332", "", 4, (210, 200, 190, 180)),
    ("Kraj Vysočina", "Horní Vilémovice", "590657", "", 1, (287, 217, 199, 173)),
    ("Jihočeský kraj", "Tábor", "766275", "Tábor", 5, (250, 3, 210, 200)),   # VK 2 misread
    ("Hlavní město Praha", "Praha", "727181", "Vinohrady", 5, (100, 100, 100, 100)),
    ("Jihomoravský kraj", "Brno", "610003", "Město Brno", 5, (100, 100, 100, 100)),
]
SURCHARGES = {1: (16, 36, 30, 45, 39), 2: (7, 38, 32, 48, 44),
              3: (5, 35, 28, 37, 47), 4: (9, 26, 25, 34, 60)}


def _write_places(path, places=PLACES, extra=()):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(rent_map_cz.PLACES_COLUMNS)
        for kraj, obec, code, ku, cov, rents in places:
            for vk, ref in enumerate(rents, 1):
                w.writerow([kraj, obec, code, ku, vk, ref, ref - 10, ref + 10, ref + 40,
                            ref - 100, ref + 300, ref - 5, cov])
        for row in extra:
            w.writerow(row)


def _write_surcharges(path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(rent_map_cz.SURCHARGE_COLUMNS)
        for vk, vals in SURCHARGES.items():
            w.writerow([vk, *vals, "TEST release"])


@pytest.fixture
def mf(tmp_path):
    """The synthetic map loaded (the conftest empties it again afterwards)."""
    places, sur = tmp_path / "cz_rent_map.csv", tmp_path / "cz_rent_map_surcharges.csv"
    _write_places(places)
    _write_surcharges(sur)
    rent_map_cz.load_map(str(places), str(sur))
    return rent_map_cz


# ── Shipped without the CSV: nothing changes ─────────────────────────────────
def test_without_the_csv_nothing_changes():
    assert rent_map_cz.UNITS == {} and "not loaded" in rent_map_cz.SOURCE["source"]
    assert rent_cz.baseline_rent("kladno") is None
    with pytest.raises(LookupError, match="engine/rent_cz.py"):
        fin.get_rent_estimate("Kladno", 55, market="cz")


# ── Deloitte first ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("district,rate", [
    ("Praha 2 - Vinohrady", 482), ("Praha 11 - Chodov", 462), ("Brno", 390),
    ("Brno-střed", 390), ("Ostrava-Poruba", 254),
])
def test_deloitte_comes_first(mf, district, rate):
    assert rent_cz.baseline_rate(district, rooms=1) == (rate, "baseline")
    assert rent_cz.mf_rent(district) is None
    assert fin.base_rent_rate(district, market="cz", rooms=1) == (
        rate, rent_cz.match_rent_key(district), "baseline")


# ── Where a district resolves to ─────────────────────────────────────────────
@pytest.mark.parametrize("district,rate,where", [
    ("Kladno", 280, "Kladno (KÚ Kladno)"),                       # the town's own KÚ
    ("Kladno - Kročehlavy", 290, "Kladno (KÚ Kročehlavy)"),      # the KÚ it names
    ("Kladno - Rozdělov", 280, "Kladno (KÚ Kladno)"),            # coverage 2: the town's
    ("Kladno, Chrudim", 150, "Kladno"),                          # the okres picks the village
    ("Opava", 200, "Opava (KÚ Opava-Město)"),                    # its "-Město" KÚ
    ("Opava - Kateřinky", 210, "Opava (KÚ Kateřinky u Opavy)"),  # named without "u Opavy"
    ("Opava - Předměstí", 205, "Opava (KÚ Opava-Předměstí)"),    # without the town in front
    ("Most - Most II", 190, "Most (KÚ Most II)"),
    ("Písek", 230, "Písek (KÚ Písek)"),                          # okres Písek: the town
    ("Písek, Frýdek-Místek", 210, "Písek"),                      # the village there
    ("Most", None, None),                    # Most I / Most II: no town-wide KÚ
    ("Most - Most I", None, None),           # coverage 1, and no town figure to fall to
    ("Bukovany", None, None),                # two of them, no kraj named: ambiguous
    ("Horní Vilémovice", None, None),        # coverage 1: MF pooling its neighbours
    ("Tábor", None, None),                   # a misread VK 2 cell was skipped
    ("Atlantis", None, None), ("", None, None), ("Brno-venkov", None, None),
])
def test_where_a_district_resolves(mf, district, rate, where):
    found = rent_cz.mf_rent(district, rooms=2)
    assert (found.rate if found else None) == rate
    assert (found.where if found else None) == where
    assert rent_cz.baseline_rate(district, rooms=2) == ((rate, "mf") if rate else
                                                        (None, "baseline"))


def test_the_listings_own_size_category(mf):
    assert rent_map_cz.vk_for_rooms(None) == rent_map_cz.vk_for_rooms(0) == 2
    assert [rent_map_cz.vk_for_rooms(r) for r in (1, 2, 3, 4, 6, "x")] == [1, 2, 3, 4, 4, 2]
    assert [rent_cz.mf_rent("Kladno", r).rate for r in (1, 2, 3, 5, None)] == \
        [300, 280, 260, 240, 280]
    # The figure already is the size's: no rooms multiplier on top.
    assert fin.get_rent_estimate("Kladno", 40, rooms=1, market="cz") == 300 * 40


def test_low_coverage_is_judged_per_size_category(tmp_path):
    rows = [("Středočeský kraj", "Beroun", "601001", "Beroun", 5, (260, 250, 240, 230))]
    path = tmp_path / "m.csv"
    _write_places(path, rows, extra=[
        # VK 4 of the same KÚ at coverage 2 replaces the row above.
        ("Středočeský kraj", "Beroun", "601001", "Beroun", 4, 230, 1, 1, 1, 1, 1, 1, 2)])
    rent_map_cz.load_map(str(path))
    assert rent_cz.mf_rent("Beroun", 3).rate == 240
    assert rent_cz.mf_rent("Beroun", 4) is None              # never VK 3's figure instead


def test_the_key_level_baseline_is_the_towns_two_room_figure(mf):
    """What live comps (of every size) blend with: the town as a whole, VK 2."""
    assert rent_cz.baseline_rent("kladno") == 280
    assert rent_cz.baseline_rent("opava") == 200
    assert rent_cz.baseline_rent("praha 2") == 482
    assert rent_cz.baseline_rent("most") is None and rent_cz.baseline_rent("default") is None
    from config import RENT_COMP_ASKING_HAIRCUT as H, RENT_COMP_PRIOR_WEIGHT as K
    assert rent_comps_cz.rate_for("kladno", 300.0, 6) == round((6 * 300 * H + K * 280) / (6 + K), 2)
    # A live rate still wins over the map.
    assert fin.base_rent_rate("Kladno", {"kladno": 275.0}, market="cz", rooms=1) == (
        275.0, "kladno", "live")


# ── Premiums: MF's own surcharges for what MF prices ─────────────────────────
def test_mf_surcharges_replace_the_balcony_and_furnished_premiums(mf):
    cz = markets.get("cz")
    base = fin.get_rent_estimate("Opava", 50, rooms=2, market="cz")
    assert base == 200 * 50
    both = fin.get_rent_estimate("Opava", 50, rooms=2, furnished="furnished", balcony=True,
                                 market="cz")
    assert both == (200 + 7 + 32) * 50                       # VK 2: balcony 7, furnished 32
    assert fin.get_rent_estimate("Opava", 50, rooms=1, balcony=True, market="cz") == \
        (220 + 16) * 50
    # MF has no semi-furnished class, and the parking flag mixes a garage with
    # an outdoor space: those keep the market's % premiums.
    assert fin.get_rent_estimate("Opava", 50, rooms=2, furnished="semi", market="cz") == \
        pytest.approx(200 * cz.semi_furnished_premium * 50)
    assert fin.get_rent_estimate("Opava", 50, rooms=2, parking=True, balcony=True,
                                 market="cz") == pytest.approx((200 + 7) * cz.parking_rent_premium * 50)
    # A Deloitte rate keeps the % premiums.
    assert fin.get_rent_estimate("Praha 2", 50, balcony=True, market="cz") == \
        pytest.approx(482 * cz.balcony_rent_premium * 50)


def test_without_the_surcharges_file_the_premiums_are_the_markets(tmp_path):
    path = tmp_path / "m.csv"
    _write_places(path)
    rent_map_cz.load_map(str(path), str(tmp_path / "missing.csv"))
    cz = markets.get("cz")
    assert "% premiums apply" in rent_map_cz.SOURCE["source"]
    assert fin.get_rent_estimate("Opava", 50, rooms=2, balcony=True, market="cz") == \
        pytest.approx(200 * cz.balcony_rent_premium * 50)


def test_the_score_says_where_the_rent_came_from(mf):
    r = fin.analyse(4_000_000, 55, "Kladno - Kročehlavy", rooms=2, market="cz")
    assert r.estimated_rent == 290 * 55
    assert "MF rent map: Kladno (KÚ Kročehlavy), VK 2" in r.recommendation
    assert "coverage 5/5" in r.recommendation
    # With a live rate, no MF note.
    r = fin.analyse(4_000_000, 55, "Kladno", rooms=2, rent_rates={"kladno": 300.0}, market="cz")
    assert "MF rent map" not in r.recommendation
    with pytest.raises(LookupError, match="rent figure for 'Most'"):
        fin.analyse(4_000_000, 55, "Most", rooms=2, market="cz")


# ── Loading ───────────────────────────────────────────────────────────────────
def test_the_loader_skips_what_is_not_a_rent(tmp_path):
    path = tmp_path / "m.csv"
    _write_places(path, PLACES[:1], extra=[
        ("Středočeský kraj", "Kladno", "665061", "Kladno", 7, 300, 1, 1, 1, 1, 1, 1, 5),  # VK 7
        ("Středočeský kraj", "Kladno", "665062", "X", 1, 300, 1, 1, 1, 1, 1, 1, 6),       # cov 6
        ("Středočeský kraj", "Kladno", "665063", "Y", 1, 5000, 1, 1, 1, 1, 1, 1, 5),      # rent
        ("", "Kladno", "665064", "Z", 1, 300, 1, 1, 1, 1, 1, 1, 5),                       # no kraj
    ])
    assert rent_map_cz.load_map(str(path)) == 4
    assert set(rent_map_cz.UNITS) == {"665061"}
    # Loading again replaces, never adds to, what was there.
    _write_places(path, PLACES[4:5])
    rent_map_cz.load_map(str(path))
    assert set(rent_map_cz.UNITS) == {"711560"} and "kladno" not in rent_map_cz.OBCE


def test_the_source_names_the_release(mf):
    s = rent_map_cz.SOURCE["source"]
    assert "Cenová mapa nájemného TEST release" in s and "456/2024" in s
    assert "unfurnished" in s


# ── dev/build_cz_rent_map.py ─────────────────────────────────────────────────
def _build_script():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "dev", "build_cz_rent_map.py")
    spec = importlib.util.spec_from_file_location("build_cz_rent_map", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_BLOCK_HEAD = ["VK", "Nájemné referenčního bytu za m² v Kč za 1 měsíc",
               "Dolní interval nájemného u referenčního bytu za m² v Kč za 1 měsíc",
               "Horní interval nájemného u referenčního bytu za m² v Kč za 1 měsíc",
               "Nájemné referenčního bytu novostavby za m² v Kč za 1 měsíc",
               "Minimální hodnota nájemného za m² v Kč", "Maximální hodnota nájemného za m² v Kč",
               "Mediánová hodnota nájemného za m² v Kč", "Datová pokrytost"]


def _mf_workbook(path, head=None):
    """A workbook laid out as MF's (2026-08-15 release), with two places."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    info = wb.active
    info.title = "Základní informace"
    info["G4"] = "ID: 26.15.08.001"
    info["C6"] = "Výpočet cenových map vychází z dat z období od 1.7.2021 do 30.6.2026."
    info.append([])
    info.append(["Přehled cen cenotvorných parametrů (dodatečných vlastností bytu) pro "
                 "referenční byt  v Kč/m²"])
    info.append(["Velikostní kategorie"] + [f'Cena v Kč za atribut "{w}"' for w in
                                            ("balkón", "terasa", "vybavennost", "garáž", "výtah")])
    for vk, vals in SURCHARGES.items():
        info.append([f"VK{vk}", *vals])
    info.append([])
    info.append(["Přehled cen cenotvorných parametrů (dodatečných vlastností bytu) pro "
                 "referenční byt novostavba  v Kč/m²"])
    ws = wb.create_sheet("Cenové mapy nájemného")
    header = ["Kraj", "Katastrální území", "Obec", "Kód obce"]
    for _ in range(4):
        header += (head or _BLOCK_HEAD) + [None]
    ws.append(header[:-1])
    for kraj, obec, code, ku, cov, rents in (PLACES[0], PLACES[3]):
        row = [kraj, ku or None, obec, int(code)]
        for vk, ref in enumerate(rents, 1):
            row += [vk, ref, ref - 10, ref + 10, ref + 40, ref - 100, ref + 300, ref - 5, cov, None]
        ws.append(row[:-1])
    wb.save(path)


def test_the_build_script_extracts_mfs_file(tmp_path):
    src = tmp_path / "2026-08-15_Cenova-mapa.xlsx"
    _mf_workbook(src)
    _build_script().main([str(src), "--out-dir", str(tmp_path)])
    with open(tmp_path / "cz_rent_map.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 8
    assert rows[1] == {"kraj": "Středočeský kraj", "obec": "Kladno", "code": "665061",
                       "ku": "Kladno", "vk": "2", "ref": "280", "low": "270", "high": "290",
                       "new_build": "320", "min": "180", "max": "580", "median": "275",
                       "coverage": "5"}
    assert rows[4]["ku"] == "" and rows[4]["code"] == "571580"
    with open(tmp_path / "cz_rent_map_surcharges.csv", encoding="utf-8") as f:
        sur = list(csv.DictReader(f))
    assert [(r["vk"], r["balcony"], r["furnished"], r["lift"]) for r in sur] == \
        [("1", "16", "30", "39"), ("2", "7", "32", "44"), ("3", "5", "28", "47"),
         ("4", "9", "25", "60")]
    assert sur[0]["release"] == "2026-08-15 (ID 26.15.08.001; data 1.7.2021–30.6.2026)"
    # And the engine reads what it wrote.
    assert rent_map_cz.load_map(str(tmp_path / "cz_rent_map.csv"),
                                str(tmp_path / "cz_rent_map_surcharges.csv")) == 8
    assert rent_cz.mf_rent("Kladno", 2).rate == 280
    assert rent_map_cz.SURCHARGES[2]["furnished"] == 32


def test_the_build_script_stops_on_a_changed_layout(tmp_path):
    src = tmp_path / "changed.xlsx"
    _mf_workbook(src, head=_BLOCK_HEAD[:2] + ["Medián"] + _BLOCK_HEAD[3:])
    with pytest.raises(SystemExit, match="block at column"):
        _build_script().main([str(src), "--out-dir", str(tmp_path)])
    assert not (tmp_path / "cz_rent_map.csv").exists()
