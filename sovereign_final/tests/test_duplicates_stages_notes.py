"""Tests for cross-portal duplicate merging, the deal-stage tracker, vibe
notes being read back, the Rejected view, and the description facts
(floor, elevator, cellar, terrace, building floors) that used to be dropped.
"""

import pytest

import database as db
from engine.duplicates import group_duplicates, is_same_flat
from modules.description_enrichment import _to_features
from tests.conftest import make_listing


def _row(lid, **kw):
    base = {"id": lid, "url": f"https://x/{lid}", "district": "Ružinov, Bratislava",
            "size_m2": 62.0, "price_eur": 240_000.0, "rooms": 3, "floor": 4,
            "scraped_at": "2026-09-01"}
    base.update(kw)
    return base


# ── Duplicates ────────────────────────────────────────────────────────────────
class TestSameFlat:
    def test_same_flat_on_two_portals(self):
        assert is_same_flat(_row("a"), _row("b", size_m2=62.4, price_eur=245_000))

    def test_district_spelled_differently_but_same_place(self):
        assert is_same_flat(_row("a", district="Bratislava II - Ružinov"),
                            _row("b", district="Ružinov, Bratislava"))

    @pytest.mark.parametrize("change", [
        {"size_m2": 70.0},                   # different flat size
        {"price_eur": 260_000.0},            # >3% apart
        {"rooms": 2},                        # disagreeing room count
        {"floor": 7},                        # disagreeing floor
        {"district": "Petržalka, Bratislava"},
    ])
    def test_different_flats(self, change):
        assert not is_same_flat(_row("a"), _row("b", **change))

    def test_unknown_rooms_or_floor_do_not_block(self):
        assert is_same_flat(_row("a", rooms=None, floor=None), _row("b"))

    def test_same_url_is_not_a_copy(self):
        assert not is_same_flat(_row("a"), _row("a"))


class TestGrouping:
    def test_group_points_at_the_cheapest_copy(self):
        groups = group_duplicates([_row("a", price_eur=245_000), _row("b"),
                                   _row("c", price_eur=242_000), _row("lonely", size_m2=90)])
        assert groups == {"a": "b", "b": "b", "c": "b"}

    def test_grouping_is_transitive(self):
        # a~b and b~c, though a and c are 6% apart.
        groups = group_duplicates([_row("a", price_eur=230_000), _row("b", price_eur=236_900),
                                   _row("c", price_eur=244_000)])
        assert set(groups) == {"a", "b", "c"} and set(groups.values()) == {"a"}

    def test_no_district_no_grouping(self):
        assert group_duplicates([_row("a", district=""), _row("b", district="")]) == {}

    def test_unmatched_districts_compare_on_the_raw_name(self):
        groups = group_duplicates([_row("a", district="Hornonitrianska Lehota"),
                                   _row("b", district="Hornonitrianska Lehota")])
        assert set(groups) == {"a", "b"}

    def test_the_verified_copy_is_shown_before_a_cheaper_one(self):
        groups = group_duplicates([_row("a", price_eur=245_000, lv_status="PASS"),
                                   _row("b", lv_status="UNVERIFIED")])
        assert groups == {"a": "a", "b": "a"}

    def test_a_rejected_copy_is_never_the_primary(self):
        groups = group_duplicates([_row("a", price_eur=236_000, lv_status="REJECTED"),
                                   _row("b", lv_status="PENDING")])
        assert groups == {"a": "b", "b": "b"}


class TestMarkDuplicates:
    def test_marks_and_clears(self, full_db):
        db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60))
        db.upsert_listing(make_listing("t1", source="topreality", price_eur=152_000, size_m2=60))
        db.upsert_listing(make_listing("other", price_eur=99_000, size_m2=40))
        assert db.mark_duplicates() == 2
        c = full_db()
        groups = dict(c.execute("SELECT id, dup_group FROM listings").fetchall())
        c.close()
        assert groups == {"n1": "n1", "t1": "n1", "other": None}

        # The copy leaves the market: the group dissolves on the next run.
        c = full_db()
        c.execute("UPDATE listings SET is_active=0 WHERE id='t1'")
        c.commit()
        c.close()
        assert db.mark_duplicates() == 0
        c = full_db()
        assert c.execute("SELECT COUNT(*) FROM listings WHERE dup_group IS NOT NULL").fetchone()[0] == 0
        c.close()

    @staticmethod
    def _state(conn_fn):
        c = conn_fn()
        rows = {r["id"]: (r["dup_group"], r["dup_lv_failed"]) for r in
                c.execute("SELECT id, dup_group, dup_lv_failed FROM listings")}
        c.close()
        return rows

    @staticmethod
    def _set_lv(conn_fn, lid, status):
        c = conn_fn()
        c.execute("UPDATE listings SET lv_status=? WHERE id=?", (status, lid))
        c.commit()
        c.close()

    def test_a_rejected_copy_flags_the_shown_one(self, full_db):
        # The same flat on two portals; one copy's title deed failed. The
        # dashboard hides the rejected copy, so the other must say so.
        db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60))
        db.upsert_listing(make_listing("t1", source="topreality", price_eur=149_000, size_m2=60))
        self._set_lv(full_db, "t1", "REJECTED")
        assert db.mark_duplicates() == 0          # no group of shown copies
        assert self._state(full_db) == {"n1": (None, 1), "t1": (None, None)}

    def test_the_shown_group_keeps_its_copies_and_the_flag(self, full_db):
        db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60))
        db.upsert_listing(make_listing("t1", source="topreality", price_eur=151_000, size_m2=60))
        db.upsert_listing(make_listing("b1", source="bazos", price_eur=148_000, size_m2=60))
        self._set_lv(full_db, "b1", "REJECTED")
        assert db.mark_duplicates() == 2
        assert self._state(full_db) == {"n1": ("n1", 1), "t1": ("n1", 1), "b1": (None, None)}

    def test_the_flag_goes_when_the_rejected_copy_does(self, full_db):
        db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60))
        db.upsert_listing(make_listing("t1", source="topreality", price_eur=149_000, size_m2=60))
        self._set_lv(full_db, "t1", "REJECTED")
        db.mark_duplicates()
        c = full_db()
        c.execute("UPDATE listings SET is_active=0 WHERE id='t1'")
        c.commit()
        c.close()
        db.mark_duplicates()
        assert self._state(full_db)["n1"] == (None, None)

    def test_the_verified_copy_is_the_primary(self, full_db):
        db.upsert_listing(make_listing("n1", source="nehnutelnosti", price_eur=150_000, size_m2=60))
        db.upsert_listing(make_listing("t1", source="topreality", price_eur=153_000, size_m2=60))
        self._set_lv(full_db, "t1", "PASS")
        db.mark_duplicates()
        assert self._state(full_db) == {"n1": ("t1", None), "t1": ("t1", None)}


# ── Deal stages ───────────────────────────────────────────────────────────────
class TestDealStages:
    def test_move_and_history(self, full_db):
        db.upsert_listing(make_listing("a"))
        db.set_deal_stage("a", "watching")
        db.set_deal_stage("a", "OFFER", "offered 95k")
        assert db.get_deal_stages()["a"]["stage"] == "OFFER"
        assert [h["stage"] for h in db.get_deal_stage_history("a")] == ["OFFER", "WATCHING"]
        tracked = db.get_tracked_listings()
        assert [(t["id"], t["stage"], t["note"]) for t in tracked] == [("a", "OFFER", "offered 95k")]

    def test_unknown_stage_is_refused(self, full_db):
        with pytest.raises(ValueError):
            db.set_deal_stage("a", "MAYBE")

    def test_a_pulled_listing_stays_on_the_board(self, full_db):
        db.upsert_listing(make_listing("a"))
        db.set_deal_stage("a", "NEGOTIATING")
        c = full_db()
        c.execute("UPDATE listings SET is_active=0 WHERE id='a'")
        c.commit()
        c.close()
        assert db.get_tracked_listings()[0]["is_active"] == 0


# ── Vibe notes ────────────────────────────────────────────────────────────────
class TestVibeNotes:
    def test_saved_notes_are_read_back(self, full_db):
        db.add_annotation("a", "quiet street", 8)
        db.add_annotation("a", "stairwell needs work", 6)
        db.add_annotation("b", "too close to the tram", 4)
        notes = db.get_annotations("a")
        assert len(notes) == 2 and notes[0]["note"] == "stairwell needs work"
        assert db.latest_vibes() == {"a": (6, "stairwell needs work", 2),
                                     "b": (4, "too close to the tram", 1)}


# ── Rejected view ─────────────────────────────────────────────────────────────
class TestRejected:
    def test_reasons_come_back_with_the_listing(self, full_db):
        db.upsert_listing(make_listing("a", title="3-izbový byt, Nitra"))
        db.set_lv_status("a", "REJECTED", "exekúcia", "Exekúcia v prospech XY")
        rej = db.get_rejected()
        assert len(rej) == 1
        r = rej[0]
        assert (r["title"], r["reason"], r["detail"], r["module"]) == \
            ("3-izbový byt, Nitra", "exekúcia", "Exekúcia v prospech XY", "debt_bot")


# ── Description facts ─────────────────────────────────────────────────────────
PARSED = {
    "balcony": False, "terrace": False, "loggia": True, "parking": False,
    "cellar": True, "elevator": True, "furnished": "semi", "condition": "good",
    "floor": 3, "building_floors": 8, "rooms": 2,
}


class TestDescriptionFacts:
    def test_everything_claude_returns_is_kept(self):
        f = _to_features(PARSED)
        assert (f["has_elevator"], f["has_cellar"], f["has_loggia"], f["has_terrace"]) == (1, 1, 1, 0)
        assert (f["floor"], f["building_floors"]) == (3, 8)

    def test_a_loggia_or_terrace_earns_the_balcony_premium(self):
        assert _to_features(PARSED)["has_balcony"] == 1
        assert _to_features({**PARSED, "loggia": False, "terrace": True})["has_balcony"] == 1
        assert _to_features({**PARSED, "loggia": False})["has_balcony"] == 0

    def test_not_stated_becomes_none(self):
        f = _to_features({**PARSED, "floor": -1, "building_floors": -1})
        assert f["floor"] is None and f["building_floors"] is None

    def test_ground_floor_is_a_floor(self):
        assert _to_features({**PARSED, "floor": 0})["floor"] == 0

    def test_impossible_pair_drops_building_floors(self):
        f = _to_features({**PARSED, "floor": 9, "building_floors": 4})
        assert f["floor"] == 9 and f["building_floors"] is None

    def test_persisted_without_overwriting_scraped_floor(self, full_db):
        db.upsert_listing(make_listing("scraped", floor=5))
        db.upsert_listing(make_listing("blank"))
        for lid in ("scraped", "blank"):
            db.update_description_features(lid, _to_features(PARSED))
        c = full_db()
        rows = {r["id"]: dict(r) for r in c.execute(
            "SELECT id, floor, building_floors, has_elevator, has_cellar, has_loggia, "
            "desc_parsed FROM listings")}
        c.close()
        assert rows["scraped"]["floor"] == 5 and rows["blank"]["floor"] == 3
        assert rows["blank"]["building_floors"] == 8
        assert rows["blank"]["has_elevator"] == 1 and rows["blank"]["desc_parsed"] == 1

    def test_requeue_sends_old_parses_back_once(self, full_db):
        db.upsert_listing(make_listing("old", description="Byt s výťahom"))
        db.upsert_listing(make_listing("new", description="Byt s výťahom"))
        c = full_db()
        c.execute("UPDATE listings SET desc_parsed=1")      # parsed before the new fields
        c.commit()
        c.close()
        db.update_description_features("new", _to_features(PARSED))
        assert db.requeue_descriptions_missing_extras() == 1
        assert [r["id"] for r in db.get_unparsed_descriptions()] == ["old"]
