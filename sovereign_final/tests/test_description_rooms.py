"""Tests for the description-parsed rooms fill: parse_description returns a
rooms count (0 = not stated) that update_description_features now writes via
COALESCE(rooms, ?) — filling only listings whose rooms are NULL, because
structured scraper data outranks the description's phrasing."""

import os
import sqlite3
import sys
import tempfile

import pytest

from modules.description_enrichment import _to_features


class TestToFeaturesRooms:
    def test_valid_rooms_pass_through(self):
        assert _to_features({"rooms": 3})["rooms"] == 3

    def test_not_stated_and_garbage_become_none(self):
        for bad in (0, -1, None, "abc", 99):
            assert _to_features({"rooms": bad})["rooms"] is None


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id TEXT PRIMARY KEY, source TEXT, url TEXT UNIQUE, rooms REAL
        )
    """)
    conn.execute("INSERT INTO listings (id, source, url, rooms) VALUES ('norooms','t','http://x/1', NULL)")
    conn.execute("INSERT INTO listings (id, source, url, rooms) VALUES ('scraped','t','http://x/2', 2)")
    conn.commit()
    conn.close()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import database as db
    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _conn)
    yield path
    os.unlink(path)


def _features(rooms):
    return {"has_parking": 0, "has_balcony": 0, "furnished": "unknown",
            "condition": "unknown", "rooms": rooms}


class TestRoomsFill:
    def test_fills_null_rooms(self, temp_db):
        from database import update_description_features
        update_description_features("norooms", _features(3))
        conn = sqlite3.connect(temp_db)
        assert conn.execute("SELECT rooms FROM listings WHERE id='norooms'").fetchone()[0] == 3
        conn.close()

    def test_never_overwrites_scraped_rooms(self, temp_db):
        from database import update_description_features
        update_description_features("scraped", _features(4))
        conn = sqlite3.connect(temp_db)
        assert conn.execute("SELECT rooms FROM listings WHERE id='scraped'").fetchone()[0] == 2
        conn.close()

    def test_none_rooms_leaves_null(self, temp_db):
        from database import update_description_features
        update_description_features("norooms", _features(None))
        conn = sqlite3.connect(temp_db)
        assert conn.execute("SELECT rooms FROM listings WHERE id='norooms'").fetchone()[0] is None
        conn.close()
