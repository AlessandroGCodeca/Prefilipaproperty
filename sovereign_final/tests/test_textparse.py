"""Tests for scraper/textparse.py::rooms_from_title — the title-based rooms
fallback that lets the ±15% per-m² rooms rent multiplier fire for sources that
carry no structured rooms count (bazos, topreality, most nehnutelnosti rows)."""

import pytest

from scraper.textparse import rooms_from_title


class TestIzbPatterns:
    @pytest.mark.parametrize("title,expected", [
        ("3-izbový byt, Dúbravka",              3),
        ("2-izbový byt na predaj, Petržalka",   2),
        ("1-izbovy byt v centre",                1),   # no diacritics
        ("4-IZBOVÝ BYT, Karlova Ves",           4),   # uppercase
        ("Predám 2-izb. byt, Nitra",            2),   # abbreviated
        ("3 izbový byt s balkónom",             3),   # space instead of hyphen
        ("2izb byt Žilina",                     2),   # no separator
        ("1-izb. byt (dražba), Klokočina",      1),
        ("5-izbový mezonet",                    5),
    ])
    def test_extracts_room_count(self, title, expected):
        assert rooms_from_title(title) == expected

    def test_garsonka_is_one_room(self):
        assert rooms_from_title("Garsónka na predaj, Ružinov") == 1
        assert rooms_from_title("garzónka v centre") == 1
        assert rooms_from_title("Predám garsonku") == 1


class TestNoFalsePositives:
    @pytest.mark.parametrize("title", [
        "",                                     # empty
        None,                                   # missing
        "Byt na predaj, Bratislava",            # no room count stated
        "Novostavba pri jazere",                # nothing numeric
        "Pozemok 800 m2, Senec",                # size, not rooms
        "Byt 65 m2 s balkónom",                 # only size
        "7-izbový kaštieľ",                     # out of 1–6 range → not matched
    ])
    def test_returns_none(self, title):
        assert rooms_from_title(title) is None

    def test_price_digits_not_mistaken_for_rooms(self):
        # "…129 000 € … 3-izbový…" must return 3, not something from the price
        assert rooms_from_title("Predaj za 129 000 €, 3-izbový byt") == 3


# ── area_from_text ────────────────────────────────────────────────────────────
from scraper.textparse import area_from_text  # noqa: E402


class TestAreaFromText:
    @pytest.mark.parametrize("text,expected", [
        ("3-izbový byt 74 m2", 74.0),
        ("58m² byt v centre", 58.0),
        ("Predaj 2-izb, 46,41 m²", 46.41),
        ("úžitková plocha 120 m²", 120.0),
    ])
    def test_reads_the_area(self, text, expected):
        assert area_from_text(text) == expected

    def test_loggia_is_not_the_flat(self):
        """This put a 6 m² flat priced at €182 000 into the database — the
        bare-m form matched the loggia before the flat's own area."""
        assert area_from_text("1,5-izb.byt s 6m logiou, komplet.rek, Jaltská") == 0.0

    def test_explicit_m2_wins_over_an_earlier_bare_m(self):
        assert area_from_text("balkón 6m, byt 62 m²") == 62.0

    def test_scans_past_an_implausible_first_match(self):
        assert area_from_text("pivnica 4 m², byt 70 m²") == 70.0

    @pytest.mark.parametrize("text", [
        "", "byt bez rozlohy", "garáž 12 m²", "pozemok 5000 m²",
    ])
    def test_nothing_plausible(self, text):
        assert area_from_text(text) == 0.0

    def test_bounds_are_tunable(self):
        assert area_from_text("garáž 12 m²", min_m2=5.0) == 12.0


# ── is_excluded_listing ───────────────────────────────────────────────────────
import sqlite3  # noqa: E402

from scraper.textparse import is_excluded_listing  # noqa: E402


class TestIsExcludedListing:
    """Most EXCLUDE_KEYWORDS are ASCII ("garaz", "kancelar", "nebytov") while
    titles keep their diacritics, and a nehnutelnosti URL (/detail/{id}) has
    no slug — so the title alone has to trip the filter."""

    @pytest.mark.parametrize("title", [
        "Predaj garáže, Žilina",
        "Kancelárske priestory na predaj",
        "Nebytový priestor",
        "Prenájom 2-izbového bytu",
        "POZEMOK NA PREDAJ",
    ])
    def test_diacritic_titles_are_excluded(self, title):
        assert is_excluded_listing(title, "https://www.nehnutelnosti.sk/detail/JuXyZ123")

    @pytest.mark.parametrize("title", [
        "Reštaurácia v centre",   # "reštaur" keyword is stored with diacritics
        "DRAŽBA bytu, Košice",    # so is "dražb"
        "Viacúčelová budova",
    ])
    def test_diacritic_keywords_still_match_raw(self, title):
        assert is_excluded_listing(title)

    def test_ascii_url_slug_still_excludes(self):
        assert is_excluded_listing("", "https://www.topreality.sk/predaj-garaz-r123.html")

    def test_apartment_is_kept(self):
        assert not is_excluded_listing(
            "3-izbový byt, Ružinov", "https://www.nehnutelnosti.sk/detail/JuXyZ123")

    @pytest.mark.parametrize("texts", [(), ("",), (None,), (None, None)])
    def test_missing_text_is_kept(self, texts):
        assert not is_excluded_listing(*texts)

    @pytest.mark.parametrize("title", [
        "3-izbový byt, Michalovce",                  # "chal" inside a town name
        "Byt v Michalovciach",
        "2-izbový byt, Michalská ulica, Staré Mesto",
        "Novovybudovaný 2-izbový byt, Nitra",        # "budov" inside "vybudovaný"
        "Rozbudovaný 3-izbový byt",
    ])
    def test_stem_inside_a_longer_word_is_kept(self, title):
        # The keywords are stems that catch every declension, so they have to
        # start a word — not turn up anywhere in one.
        assert not is_excluded_listing(title, "https://www.nehnutelnosti.sk/detail/JuXyZ123")

    @pytest.mark.parametrize("text", [
        "Chata pri jazere",
        "Predaj chaty, Orava",
        "Budova na predaj",
        "Garážové státie",
        "predaj-garaz-bratislava",       # URL slug: a hyphen is a word boundary
        "2garaz",                        # a digit is not a letter
    ])
    def test_stem_at_the_start_of_a_word_still_excludes(self, text):
        assert is_excluded_listing(text)


class TestDeactivateNonApartments:
    """The retroactive cleanup on both scrapers used to be SQL LIKE clauses,
    which share the blind spot (and SQLite's LOWER() folds ASCII only)."""

    @pytest.fixture
    def temp_db(self, tmp_path, monkeypatch):
        path = str(tmp_path / "listings.db")
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE listings (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT, price_eur REAL NOT NULL, is_active INTEGER,
                classification TEXT
            )
        """)
        rows = [
            ("garage",  "Predaj garáže, Žilina"),
            ("office",  "Kancelárske priestory na predaj"),
            ("nonres",  "Nebytový priestor"),
            ("flat",    "3-izbový byt, Ružinov"),
            ("untitled", None),
        ]
        for source in ("nehnutelnosti", "topreality"):
            for rid, title in rows:
                conn.execute(
                    "INSERT INTO listings VALUES (?,?,?,?,150000,1,'GREEN')",
                    (f"{source}-{rid}", source, f"https://x/{source}/detail/{rid}9",
                     title),
                )
        conn.commit()
        conn.close()

        import database as db

        def _temp_conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c
        monkeypatch.setattr(db, "get_conn", _temp_conn)
        return path

    @pytest.mark.parametrize("source", ["nehnutelnosti", "topreality"])
    def test_deactivates_diacritic_titles_only(self, temp_db, source):
        import importlib
        mod = importlib.import_module(f"scraper.{source}")
        assert mod._deactivate_non_apartments() == 3

        conn = sqlite3.connect(temp_db)
        state = {
            rid: (active, price, cls) for rid, active, price, cls in conn.execute(
                "SELECT id, is_active, price_eur, classification FROM listings")
        }
        conn.close()
        for rid in ("garage", "office", "nonres"):
            assert state[f"{source}-{rid}"] == (0, 0, "WHITE")
        assert state[f"{source}-flat"] == (1, 150000, "GREEN")
        assert state[f"{source}-untitled"] == (1, 150000, "GREEN")
        other = "topreality" if source == "nehnutelnosti" else "nehnutelnosti"
        assert all(state[f"{other}-{rid}"][0] == 1
                   for rid in ("garage", "office", "nonres", "flat"))
