"""database.get_stats feeds the dashboard's headline counts and the scheduler's
end-of-run summary."""

import database as db
from tests.conftest import make_listing


def test_empty_database_counts_are_zero_not_none(full_db):
    # SUM() over no rows is NULL, which the dashboard printed as "None".
    assert db.get_stats() == {"total": 0, "green": 0, "yellow": 0,
                              "white": 0, "rejected": 0, "pending": 0}


def test_counts_active_listings_by_class_and_lv_status(full_db):
    for lid, cls, lv in [("a", "GREEN", "PASS"), ("b", "WHITE", "PASS"),
                         ("c", "WHITE", "PASS"), ("d", "PENDING", "REJECTED"),
                         ("e", "PENDING", "PENDING"), ("g", "GREEN", "REJECTED")]:
        db.upsert_listing(make_listing(lid, classification=cls, lv_status=lv))
    # An inactive listing is not counted.
    db.upsert_listing(make_listing("f", classification="GREEN"))
    conn = full_db()
    conn.execute("UPDATE listings SET is_active=0 WHERE id='f'")
    conn.commit()
    conn.close()

    # A rejected listing keeps the class it had; it is counted as rejected
    # only, so the counts add up to the total instead of past it.
    stats = db.get_stats()
    assert stats == {"total": 6, "green": 1, "yellow": 0,
                     "white": 2, "rejected": 2, "pending": 1}
    assert stats["total"] == sum(v for k, v in stats.items() if k != "total")


def test_active_sources_lists_every_source_once(full_db):
    for lid, source in [("a", "bazos"), ("b", "sample"), ("c", "bazos"), ("d", "")]:
        db.upsert_listing(make_listing(lid, source=source))
    db.upsert_listing(make_listing("e", source="topreality"))
    conn = full_db()
    conn.execute("UPDATE listings SET is_active=0 WHERE id='e'")
    conn.commit()
    conn.close()
    assert db.get_active_sources() == ["bazos", "sample"]


def test_rejected_listings_come_back_only_when_asked_for(full_db):
    db.upsert_listing(make_listing("ok", lv_status="PASS"))
    db.upsert_listing(make_listing("no", lv_status="REJECTED"))
    assert [r["id"] for r in db.get_all_active()] == ["ok"]
    assert [r["id"] for r in db.get_all_active(rejected=True)] == ["no"]
