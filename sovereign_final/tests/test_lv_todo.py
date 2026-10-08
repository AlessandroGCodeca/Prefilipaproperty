"""The LV to-do queue (audit A8): which listings it lists, and bulk entry of
the flats' own LV numbers."""

import database as db
import modules.debt_bot as bot
from tests.conftest import make_listing


def _scored(lid, cls, lv_status="UNVERIFIED", discount=0.3, **kw):
    from engine.financial import analyse, result_to_db_dict
    db.upsert_listing(make_listing(lid, **kw))
    score = result_to_db_dict(analyse(100_000, 55, "Žilina", listing_id=lid))
    db.upsert_cashflow({**score, "classification": cls, "market_discount": discount})
    if lv_status != "PENDING":
        db.set_lv_status(lid, lv_status, "", "")


class TestQueue:
    def test_lists_green_and_yellow_without_a_verified_lv(self, full_db):
        _scored("g", "GREEN", discount=0.25)
        _scored("g2", "GREEN", discount=0.35)
        _scored("y", "YELLOW", lv_status="PENDING", discount=0.15)
        _scored("ok", "GREEN", lv_status="PASS")
        _scored("rej", "GREEN", lv_status="REJECTED")
        _scored("w", "WHITE")
        _scored("gone", "GREEN")
        db.deactivate_listings(["https://example.sk/gone"])
        assert [t["id"] for t in db.get_lv_todo()] == ["g2", "g", "y"]

    def test_a_listing_with_a_number_that_failed_to_verify_stays(self, full_db):
        _scored("g", "GREEN")
        db.set_flat_lv("g", "4321", "")
        assert [t["lv_number"] for t in db.get_lv_todo()] == ["4321"]


class TestBulkEntry:
    def test_save_stores_and_queues_for_the_next_run(self, full_db):
        _scored("a", "GREEN")
        _scored("b", "YELLOW")
        # Checked just now, so the 7-day recheck would otherwise skip them.
        assert {r["id"] for r in db.get_pending_lv()} == set()
        res = bot.save_flat_lvs([("a", " 4321 ", "Petržalka"), ("b", "77", "")])
        assert res["saved"] == 2
        rows = {r["id"]: r for r in db.get_pending_lv()}
        assert set(rows) == {"a", "b"}
        assert rows["a"]["lv_number"] == "4321"
        assert rows["a"]["cadastral_area"] == "Petržalka"

    def test_verify_now_checks_each_and_counts_the_verdicts(self, full_db, monkeypatch):
        verdicts = {"a": "PASS", "b": "REJECT", "c": "UNVERIFIED"}
        seen = []

        def reverify(lid, lv_number=None, cadastral_area=""):
            seen.append((lid, lv_number, cadastral_area))
            if lid == "d":
                raise RuntimeError("cadastre down")
            return {"status": verdicts[lid], "detail": ""}

        monkeypatch.setattr(bot, "reverify", reverify)
        calls = []
        res = bot.save_flat_lvs([(x, "1", "Nitra") for x in "abcd"], verify=True,
                                progress_callback=lambda i, n, a="": calls.append((i, n)))
        assert res == {"saved": 4, "PASS": 1, "REJECT": 1, "UNVERIFIED": 1, "ERROR": 1}
        assert seen[0] == ("a", "1", "Nitra")
        assert calls[-1] == (4, 4)
