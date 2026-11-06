"""The database reads that fall back to an empty answer (the built-in tax
tables, the baseline rents, no village put first) log a warning naming the
error, rather than hiding it — and still fall back."""

import logging
import sqlite3

import pytest

import database
from engine import property_tax_cz, property_tax_sk, rent_comps, rent_comps_cz
from modules import tax_rates


def _locked(*_a, **_kw):
    raise sqlite3.OperationalError("database is locked")


class _BrokenConn:
    """Opens, then fails every query."""
    def execute(self, *_a, **_kw):
        raise sqlite3.DatabaseError("database disk image is malformed")

    def close(self):
        pass


def _warned(caplog, *words):
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(all(w in m for w in words) for m in msgs), msgs


@pytest.mark.parametrize("broken", [_locked, lambda: _BrokenConn()])
def test_cz_coefficients_read_failure_is_logged(monkeypatch, caplog, broken):
    monkeypatch.setattr(database, "get_conn", broken)
    with caplog.at_level(logging.WARNING):
        assert property_tax_cz._load() == {}
    _warned(caplog, "Czech tax coefficients", "Error")


@pytest.mark.parametrize("broken", [_locked, lambda: _BrokenConn()])
def test_sk_stored_rates_read_failure_is_logged(monkeypatch, caplog, broken):
    monkeypatch.setattr(database, "get_conn", broken)
    with caplog.at_level(logging.WARNING):
        assert property_tax_sk._load_stored() == {}
    _warned(caplog, "Slovak tax rates", "Error")


def test_sk_municipality_list_failure_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(database, "get_conn", _locked)
    monkeypatch.setattr(property_tax_sk, "_names", None)
    with caplog.at_level(logging.WARNING):
        property_tax_sk._known_names()
    _warned(caplog, "municipality list", "OperationalError", "database is locked")


def test_listing_districts_failure_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(database, "get_conn", _locked)
    with caplog.at_level(logging.WARNING):
        assert tax_rates._with_listings(["Porúbka (Žilina)"]) == set()
    _warned(caplog, "lose their priority", "OperationalError", "database is locked")


@pytest.mark.parametrize("mod", [rent_comps, rent_comps_cz])
def test_rent_comps_read_failure_is_logged(monkeypatch, caplog, mod):
    monkeypatch.setattr(database, "_has_table", lambda *_: True)
    monkeypatch.setattr(database, "get_conn", lambda: _BrokenConn())
    with caplog.at_level(logging.WARNING):
        assert mod.load_live_rates() == {}
        assert mod.comps_table() == []
    _warned(caplog, "rent comps", "baseline", "DatabaseError")
    _warned(caplog, "rent comps", "comps table", "DatabaseError")


@pytest.mark.parametrize("mod", [rent_comps, rent_comps_cz])
def test_no_rent_comps_table_yet_is_quiet(caplog, mod):
    """A database the comps were never built in is the expected empty case."""
    with caplog.at_level(logging.WARNING):
        assert mod.load_live_rates() == {}
        assert mod.comps_table() == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_bug_in_the_read_is_not_swallowed(monkeypatch):
    """Only database errors fall back; anything else is a bug and surfaces."""
    def bug(*_a, **_kw):
        raise KeyError("size")
    monkeypatch.setattr(database, "get_conn", bug)
    with pytest.raises(KeyError):
        property_tax_cz._load()
    with pytest.raises(KeyError):
        tax_rates._with_listings(["Žilina"])
