"""Tests for repair_districts.py — correcting rows the old location matchers
sent to Bratislava.

The matchers are fixed, but rows already stored keep "Nové Mesto, Bratislava"
for a flat in Nové Mesto nad Váhom until their detail page is read again, and
the cashflow engine keeps pricing them at Bratislava rent. The repair re-runs
the fixed matchers over what each row stores, and must leave genuine
Bratislava rows and real addresses alone.
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import repair_districts  # noqa: E402
from repair_districts import corrected_location, rederive_districts  # noqa: E402

NEHN = "https://www.nehnutelnosti.sk/detail/"

# (id, source, url, title, description, district, address_raw)
ROWS = [
    # Slug path: "nove-mesto" matched inside the town's slug.
    ("slug-nmnv", "nehnutelnosti", NEHN + "A1/2-izbovy-byt-nove-mesto-nad-vahom",
     "2 izbový byt", "", "Nové Mesto", "Nové Mesto"),
    # Slug path: the town AND Bratislava's part, from one name.
    ("slug-knm", "nehnutelnosti", NEHN + "A2/byt-kysucke-nove-mesto",
     "Byt", "", "Nové Mesto, Kysucké Nové Mesto", "Nové Mesto, Kysucké Nové Mesto"),
    # Slug path: town written without diacritics.
    ("slug-komarno", "nehnutelnosti", NEHN + "A3/byt-komarno",
     "Byt", "", "Komarno", "Komarno"),
    # Detail-text path: address "Nové Mesto, Bratislava", district cut to its
    # last part. The generic slug says nothing; the title names the town.
    ("text-nmnv", "nehnutelnosti", NEHN + "A4/moderny-byt",
     "2-izbový byt, Nové Mesto nad Váhom", "", "Bratislava", "Nové Mesto, Bratislava"),
    # bazos: card text stored as the description.
    ("bazos-kosice", "bazos", "https://reality.bazos.sk/inzerat/1/byt.php",
     "Predám 3i byt", "Predám 3i byt Košice - Staré Mesto 040 01",
     "Staré Mesto, Bratislava", "Staré Mesto, Bratislava"),
    # topreality: same shape as the nehnutelnosti detail-text path.
    ("topr-knm", "topreality", "https://www.topreality.sk/x-1.html",
     "Byt Kysucké Nové Mesto", "", "Bratislava", "Nové Mesto, Bratislava"),
    # A real address is kept; only the district changes.
    ("real-address", "nehnutelnosti", NEHN + "A5/byt-nove-mesto-nad-vahom",
     "Byt", "", "Nové Mesto", "Hviezdoslavova 5, Nové Mesto"),

    # ── Rows that must not change ──
    ("ba-genuine", "nehnutelnosti", NEHN + "B1/3-izbovy-byt-nove-mesto",
     "Byt", "", "Bratislava", "Nové Mesto, Bratislava"),
    ("ba-bazos", "bazos", "https://reality.bazos.sk/inzerat/2/byt.php",
     "Predám byt", "Predám byt Nové Mesto, Bratislava 831 01",
     "Nové Mesto, Bratislava", "Nové Mesto, Bratislava"),
    # Nothing stored names a place: left for the next detail-page read.
    ("no-evidence", "topreality", "https://www.topreality.sk/x-2.html",
     "Byt na predaj", "Pekný byt.", "Bratislava", "Nové Mesto, Bratislava"),
    # Already right (the fixed slug parser writes exactly this).
    ("kosice-right", "nehnutelnosti", NEHN + "B2/byt-stare-mesto-kosice",
     "Byt", "", "Staré Mesto, Košice", "Staré Mesto, Košice"),
    # Evidence names a town that isn't the city part the row holds — not this
    # bug, so not touched.
    ("unrelated", "topreality", "https://www.topreality.sk/x-3.html",
     "Predám byt, Senec", "", "Bratislava", "Staré Mesto, Bratislava"),
    ("trnava", "nehnutelnosti", NEHN + "B3/byt-trnava",
     "Byt", "", "Trnava", "Trnava"),
]

EXPECTED = {
    "slug-nmnv":    ("Nové Mesto nad Váhom", "Nové Mesto nad Váhom"),
    "slug-knm":     ("Kysucké Nové Mesto", "Kysucké Nové Mesto"),
    "slug-komarno": ("Komárno", "Komárno"),
    "text-nmnv":    ("Nové Mesto nad Váhom", "Nové Mesto nad Váhom"),
    "bazos-kosice": ("Staré Mesto, Košice", "Staré Mesto, Košice"),
    "topr-knm":     ("Kysucké Nové Mesto", "Kysucké Nové Mesto"),
    "real-address": ("Nové Mesto nad Váhom", "Hviezdoslavova 5, Nové Mesto"),
}


@pytest.fixture
def temp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE listings (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            url         TEXT NOT NULL UNIQUE,
            title       TEXT,
            description TEXT,
            district    TEXT,
            address_raw TEXT
        )
    """)
    conn.executemany("INSERT INTO listings VALUES (?,?,?,?,?,?,?)", ROWS)
    conn.commit()
    conn.close()

    import database as db

    def _temp_conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(db, "get_conn", _temp_conn)

    yield path
    os.unlink(path)


def _stored(path) -> dict:
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT id, district, address_raw FROM listings").fetchall()
    conn.close()
    return {rid: (district, address) for rid, district, address in rows}


class TestRederiveDistricts:
    def test_corrects_exactly_the_misrouted_rows(self, temp_db):
        changes = rederive_districts()
        assert {c["id"]: c["new"] for c in changes} == \
            {rid: new for rid, (new, _) in EXPECTED.items()}

    def test_writes_district_and_matcher_built_address(self, temp_db):
        rederive_districts()
        stored = _stored(temp_db)
        for row in ROWS:
            rid = row[0]
            assert stored[rid] == EXPECTED.get(rid, (row[5], row[6])), rid

    def test_dry_run_writes_nothing(self, temp_db):
        before = _stored(temp_db)
        changes = rederive_districts(dry_run=True)
        assert len(changes) == len(EXPECTED)
        assert _stored(temp_db) == before

    def test_second_run_changes_nothing(self, temp_db):
        rederive_districts()
        assert rederive_districts() == []


class TestCorrectedLocation:
    def test_row_without_suspect_location_is_skipped(self):
        row = {"source": "nehnutelnosti", "district": "Trenčín",
               "address_raw": "Trenčín",
               "url": NEHN + "C1/byt-nove-mesto-nad-vahom"}
        assert corrected_location(row) == ""

    def test_slug_wins_over_title(self):
        # The slug is the exact evidence the slug path read.
        row = {"source": "nehnutelnosti", "district": "Nové Mesto",
               "address_raw": "Nové Mesto",
               "url": NEHN + "C2/byt-kysucke-nove-mesto",
               "title": "Byt Nové Mesto nad Váhom"}
        assert corrected_location(row) == "Kysucké Nové Mesto"

    def test_slug_ignored_for_other_sources(self):
        row = {"source": "topreality", "district": "Bratislava",
               "address_raw": "Nové Mesto, Bratislava",
               "url": NEHN + "C3/byt-nove-mesto-nad-vahom", "title": ""}
        assert corrected_location(row) == ""


class TestMain:
    @pytest.fixture
    def calls(self, temp_db, monkeypatch):
        import database
        import modules.cashflow_runner as runner
        seen = []
        monkeypatch.setattr(database, "init_db", lambda: None)
        monkeypatch.setattr(database, "clear_cashflow_scores",
                            lambda: seen.append("clear") or 0)
        monkeypatch.setattr(runner, "run_scoring",
                            lambda **kw: seen.append("score") or 0)
        return seen

    def test_rescores_everything_after_repair(self, calls, temp_db):
        assert repair_districts.main([]) == 0
        assert calls == ["clear", "score"]
        assert _stored(temp_db)["slug-nmnv"][0] == "Nové Mesto nad Váhom"

    def test_dry_run_neither_writes_nor_rescores(self, calls, temp_db):
        before = _stored(temp_db)
        assert repair_districts.main(["--dry-run"]) == 0
        assert calls == []
        assert _stored(temp_db) == before
