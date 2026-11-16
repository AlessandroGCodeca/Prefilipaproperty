"""The rest of the audit of 12 November 2026: duplicates (finding 6), the
Mac launcher (7), villages (10), backups (11), the due-diligence checklist
and documents (S3), the správca letter (S4), the mortgage-offer comparer
(S6), "Why this grade?" (S7) and the offer sheet (S8)."""

import os
import sqlite3

import pytest

from tests.conftest import make_listing

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Finding 6: duplicates ────────────────────────────────────────────────────
def _row(lid, **kw):
    base = {"id": lid, "url": f"https://x/{lid}", "district": "Bratislava - Petržalka",
            "size_m2": 68.0, "price_eur": 189_000.0, "rooms": 3, "floor": None,
            "market": "sk", "scraped_at": "2026-11-01"}
    base.update(kw)
    return base


def test_three_look_alike_flats_on_different_floors_stay_three():
    from engine.duplicates import group_duplicates
    rows = [_row("a"), _row("b", size_m2=68.6, price_eur=192_500, floor=7),
            _row("c", size_m2=67.5, price_eur=187_000, floor=2, rooms=None)]
    assert group_duplicates(rows) == {}


def test_a_group_never_chains_through_a_contradiction():
    from engine.duplicates import group_duplicates
    # b and c state different floors; a (floor unknown) matches each of them.
    rows = [_row("a"), _row("b", floor=7), _row("c", floor=2, price_eur=188_000)]
    groups = group_duplicates(rows)
    assert not ({"b", "c"} <= set(groups) and groups["b"] == groups["c"])


def test_evidence_makes_a_copy_of_a_rounded_size():
    from engine.duplicates import is_same_flat
    a, b = _row("a"), _row("b", size_m2=68.9)
    assert not is_same_flat(a, b)                            # nothing says it is one flat
    pin = dict(coords_source="listing", lat=48.1101, lng=17.1101)
    assert is_same_flat({**a, **pin}, {**b, **pin, "lat": 48.1105})       # ~45 m apart
    assert not is_same_flat({**a, **pin}, {**b, **pin, "lat": 48.12})     # ~1 km apart
    assert is_same_flat({**a, "address_raw": "Hálova 12, Petržalka"},
                        {**b, "address_raw": "ul. Hálova 12/A"})
    assert not is_same_flat({**a, "address_raw": "Hálova 12"},
                            {**b, "size_m2": 68.0, "address_raw": "Jiráskova 5"})
    photo = "https://img.example/abc.jpg"
    assert is_same_flat({**a, "primary_image_url": photo + "?w=640"},
                        {**b, "primary_image_url": photo + "?w=1200"})


def test_mark_duplicates_reads_pins_and_addresses(full_db):
    import database as db
    db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60,
                                   address_raw="Hálova 12", lat=48.11, lng=17.11))
    db.upsert_listing(make_listing("t1", source="topreality", price_eur=151_000, size_m2=60.8,
                                   address_raw="Hálova 12", lat=48.1101, lng=17.1101))
    db.upsert_listing(make_listing("b1", source="bazos", price_eur=150_500, size_m2=60.4,
                                   address_raw="Jiráskova 5", lat=48.13, lng=17.13))
    assert db.mark_duplicates() == 2


# ── Finding 7: the Mac launcher starts the scheduler ─────────────────────────
def test_the_mac_launcher_starts_and_stops_the_scheduler():
    text = open(os.path.join(HERE, "Start Sovereign.command"), encoding="utf-8").read()
    assert 'scheduler.py > logs/scheduler.out 2>&1 &' in text
    assert "trap stop_scheduler EXIT INT TERM HUP" in text
    assert "SOVEREIGN_NO_SCHEDULER" in text
    # The dashboard no longer replaces the shell, or the trap would never run.
    assert 'exec "$VENV/bin/python" -m streamlit' not in text


# ── Finding 10: villages and Košice's city parts ─────────────────────────────
@pytest.mark.parametrize("district,kraj,median", [
    ("Dunajská Lužná", "BA", 2_827),          # okres Senec: Senec's median, not Bratislava's
    ("Trenčianske Teplice", "TN", 1_878),
    ("Veľký Meder", "TT", 2_015),
    ("Košická Nová Ves", "KE", 3_196),        # a Košice city part: the city's
])
def test_a_village_has_a_benchmark(district, kraj, median):
    from engine import regional_prices as rp
    assert rp.kraj_for_district(district) == kraj
    assert rp.median_source(district)[0] == median


def test_a_name_several_villages_share_needs_its_okres():
    from engine import regional_prices as rp
    assert rp.municipality_okres("Podhradie") is None             # three okresy, three kraje
    assert rp.municipality_okres("Podhradie, okres Topoľčany") == ("Topoľčany", "NR")
    assert rp.municipality_okres("Selce")[1] == "BB"              # three okresy, one kraj


@pytest.mark.parametrize("district,key", [
    ("Košická Nová Ves", "košice iii"), ("Košice - Staré Mesto", "košice i"),
    ("Košice - Juh", "košice iv"), ("Sídlisko KVP, Košice", "košice ii"),
    ("Juh", "default"),                       # a word, not Košice, without "Košice"
])
def test_kosices_city_parts_take_their_okres_rent(district, key):
    from engine.financial import match_rent_key
    assert match_rent_key(district) == key


def test_the_municipality_list_covers_every_okres():
    import json
    data = json.load(open(os.path.join(HERE, "engine", "sk_municipalities.json"), encoding="utf-8"))
    okresy = {o for v in data["okres_kraj"].values() for o in v}
    assert len(okresy) == 79
    assert len(data["municipalities"]) > 2_700
    assert {o for v in data["municipalities"].values() for o in v} <= okresy


# ── Finding 11: backups ──────────────────────────────────────────────────────
@pytest.fixture
def backup_dirs(tmp_path, monkeypatch, full_db):
    from modules import backup
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_a_backup_is_checked_and_a_restore_saves_the_live_database_first(backup_dirs):
    import database as db
    from modules import backup
    db.upsert_listing(make_listing("kept"))
    path, written = backup.backup_database()
    assert written and backup.integrity_problem(path) is None
    db.upsert_listing(make_listing("later"))
    saved = backup.restore_database(path)
    assert saved and os.path.basename(saved).startswith("pre-restore-")
    conn = sqlite3.connect(saved)
    assert {r[0] for r in conn.execute("SELECT id FROM listings")} == {"kept", "later"}
    conn.close()
    conn = db.get_conn()
    assert {r[0] for r in conn.execute("SELECT id FROM listings")} == {"kept"}
    conn.close()


def test_a_damaged_file_is_never_restored(backup_dirs):
    from modules import backup
    bad = backup_dirs / "broken.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    assert backup.integrity_problem(str(bad))
    with pytest.raises(backup.BackupError):
        backup.restore_database(str(bad))
    assert not list((backup_dirs / "backups").glob("pre-restore-*")) \
        if (backup_dirs / "backups").exists() else True


# ── S3: due-diligence checklist and documents ────────────────────────────────
def test_the_checklist_and_documents_are_kept_and_exported(full_db, tmp_path, monkeypatch):
    import json
    from database import deal_docs
    from modules import backup
    deal_docs.set_checklist("d1", {"bezdlznost": (True, "from the správca 3 Nov"),
                                   "energy": (False, ""), "nonsense": (True, "x")})
    got = deal_docs.get_checklist("d1")
    assert got["bezdlznost"]["done"] and got["bezdlznost"]["note"] == "from the správca 3 Nov"
    assert "nonsense" not in got
    fid = deal_docs.add_deal_file("d1", "LV", "lv.pdf", b"%PDF-1.4 x", "application/pdf")
    assert deal_docs.list_deal_files("d1")[0]["name"] == "lv.pdf"
    assert deal_docs.get_deal_file(fid)["data"] == b"%PDF-1.4 x"
    with pytest.raises(ValueError):
        deal_docs.add_deal_file("d1", "LV", "big.pdf", b"x" * (deal_docs.MAX_FILE_MB * 2**20 + 1))
    with pytest.raises(ValueError):
        deal_docs.add_deal_file("d1", "LV", "empty.pdf", b"")
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    out = json.load(open(backup.export_user_data(), encoding="utf-8"))
    assert out["deal_checklist"][0]["item"] == "bezdlznost"
    assert out["deal_files"][0]["name"] == "lv.pdf" and "data" not in out["deal_files"][0]
    assert deal_docs.delete_deal_file(fid) and deal_docs.list_deal_files("d1") == []


# ── S4: the správca letter ───────────────────────────────────────────────────
def test_the_letter_is_in_the_listings_language_with_what_is_known():
    from modules.spravca_letter import FILL, build_letter
    sk = build_letter({"address_raw": "Hálova 12, Bratislava", "lv_number": "4521",
                       "cadastral_area": "Petržalka"}, "Ján Novák", "jan@example.sk", "16.11.2026")
    assert "potvrdenie o bezdlžnosti" in sk and "LV" not in sk.split("list vlastníctva č.")[0][-5:]
    assert "4521" in sk and "Petržalka" in sk and "Ján Novák" in sk and FILL in sk
    cz = build_letter({"market": "cz", "address_raw": "Vinohradská 5, Praha"})
    assert "potvrzení" in cz and "fondu oprav" in cz and FILL in cz


# ── S6: mortgage offers and the rate after a fixation ────────────────────────
def test_the_payment_is_recomputed_when_a_fixation_ends():
    from engine.financial import amortization_schedule, calc_mortgage, loan_schedule
    plain = loan_schedule(120_000, 0.038, 25)
    for x, y in zip(plain, amortization_schedule(120_000, 0.038, 25), strict=True):
        assert x[:3] == pytest.approx(y)
    reset = loan_schedule(120_000, 0.038, 25, fixation_years=5, reset_rate=0.06)
    assert reset[4][3] == pytest.approx(calc_mortgage(120_000, 0.038, 25) * 12)
    assert reset[5][3] / 12 == pytest.approx(calc_mortgage(reset[4][2], 0.06, 20), rel=1e-6)
    assert reset[-1][2] == pytest.approx(0, abs=1e-6)       # still repaid on time


def test_a_dearer_rate_after_the_fixation_lowers_the_irr():
    from engine.financial import project_irr
    base = project_irr(150_000, 55, "Petržalka", structure="PERSONAL")
    same = project_irr(150_000, 55, "Petržalka", structure="PERSONAL",
                       fixation_years=5, reset_rate=0.038)
    dear = project_irr(150_000, 55, "Petržalka", structure="PERSONAL",
                       fixation_years=5, reset_rate=0.055)
    assert same.irr == base.irr and dear.irr < base.irr
    fees = project_irr(150_000, 55, "Petržalka", structure="PERSONAL", loan_fees=1_000,
                       monthly_loan_costs=20)
    assert fees.cash_flows[0] == base.cash_flows[0] - 1_000
    assert fees.cash_flows[1] == pytest.approx(base.cash_flows[1] - 240)


def test_offers_are_compared_over_the_hold():
    from dashboard.tabs.what_if import compare_offers, offers_default
    ctx = {"price": 150_000, "size": 55, "district": "Petržalka", "structure": "PERSONAL",
           "irr_kw": {"rent": 660.0, "hold_years": 10, "appreciation": 0.03, "rent_growth": 0.025,
                      "exit_cost_rate": 0.035}}
    offers = offers_default({"rate": 0.038, "term": 25, "ltv": 0.8}).to_dict("records")
    offers.append({"Bank": "broken", "Rate %": "x", "Term (years)": 25, "LTV %": 80})
    out = compare_offers(ctx, offers)
    assert [o["Bank"] for o in out] == ["Offer A", "Offer B"]
    a = out[0]
    assert a["Payment after fixation"] > a["Payment"]
    assert a["Cash flow after reset /mo"] < a["Cash flow year 1 /mo"]


# ── S7: why this grade ───────────────────────────────────────────────────────
@pytest.mark.parametrize("row", [
    {"cap_rate": 0.05, "market_discount": 0.25, "lv_status": "UNVERIFIED"},
    {"cap_rate": 0.07, "market_discount": None, "location_score": 80, "energy_class": "B",
     "condition": "renovated", "noise_flag": 1, "flood_zone": 1, "construction_risk": 1},
    {"market_discount": -0.1, "lv_status": "PASS"},
])
def test_the_breakdown_adds_up_to_the_grade(row):
    from engine.financial import compute_deal_score, deal_score_parts
    parts = deal_score_parts(row)
    score = round(sum(p["points"] for p in parts) / sum(p["max"] for p in parts) * 100)
    assert compute_deal_score(row)[0] == max(0, score)
    assert all(p["why"] for p in parts)


def test_the_card_shows_the_breakdown():
    from dashboard.cards import grade_breakdown_html
    html = grade_breakdown_html({"cap_rate": 0.05, "market_discount": 0.25, "title": "<b>x</b>"})
    assert "Cap rate" in html and "Below market" in html and "→ grade" in html
    assert "No financial figures" in grade_breakdown_html({})


# ── S8: the offer sheet ──────────────────────────────────────────────────────
def test_comparables_are_the_same_area_and_a_similar_size():
    from modules.offer_sheet import comparables
    me = {"id": "me", "district": "Bratislava - Petržalka", "size_m2": 60, "price_eur": 200_000}
    rows = [me,
            {"id": "near", "district": "Petržalka", "size_m2": 62, "price_eur": 210_000},
            {"id": "big", "district": "Petržalka", "size_m2": 90, "price_eur": 290_000},
            {"id": "far", "district": "Nitra", "size_m2": 60, "price_eur": 120_000},
            {"id": "copy", "district": "Petržalka", "size_m2": 60, "price_eur": 199_000,
             "dup_group": "g"},
            {"id": "copy2", "district": "Petržalka", "size_m2": 60, "price_eur": 199_500,
             "dup_group": "g"},
            {"id": "noprice", "district": "Petržalka", "size_m2": 60, "price_eur": 0}]
    assert [r["id"] for r in comparables(me, rows)] == ["copy", "near"]


def test_the_offer_sheet_is_a_pdf():
    from modules.offer_sheet import build_offer_sheet
    me = {"id": "me", "title": "3-izbový byt", "district": "Petržalka", "size_m2": 60,
          "price_eur": 200_000, "max_price_yellow": 190_000, "max_price_green": 168_000,
          "regional_median_m2": 3_685, "market_discount": 0.1, "scraped_at": "2026-09-01",
          "_ph": {"history": [("2026-09-01", 210_000), ("2026-10-01", 200_000)],
                  "change_pct": -0.048}}
    pdf = build_offer_sheet(me, [{"title": "x", "district": "Petržalka", "size_m2": 62,
                                  "price_eur": 210_000, "scraped_at": "2026-10-01"}])
    assert pdf[:4] == b"%PDF" and len(pdf) > 1_000
