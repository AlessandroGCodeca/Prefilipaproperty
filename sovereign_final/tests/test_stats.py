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
                         ("e", "PENDING", "PENDING")]:
        db.upsert_listing(make_listing(lid, classification=cls, lv_status=lv))
    # An inactive listing is not counted.
    db.upsert_listing(make_listing("f", classification="GREEN"))
    conn = full_db()
    conn.execute("UPDATE listings SET is_active=0 WHERE id='f'")
    conn.commit()
    conn.close()

    assert db.get_stats() == {"total": 5, "green": 1, "yellow": 0,
                              "white": 2, "rejected": 1, "pending": 2}
