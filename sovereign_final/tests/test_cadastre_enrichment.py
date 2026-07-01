"""Tests for the unofficial Slovak cadastre scraper in backfill_enrichment
(cadastre mode). All HTTP is faked at the _cadastral_get / requests.get level
so the OData parsing, pagination, caching, retry and geoblock-fallback logic
run for real without touching skgeodesy.sk."""

import json
import sqlite3

import pytest

import backfill_enrichment as bf
import database


# ── fake portal responses ─────────────────────────────────────────────────────
KU_ROWS = [{"Id": 3086, "Name": "Nitra", "Code": 838365}]

PARCEL_ROW = {
    "Id": 123, "ValidTo": None, "No": "1234/5", "Area": 456, "HouseNo": "10",
    "Extent": None,
    "OwnershipType": {"Name": "Vlastník", "Code": 1},
    "CadastralUnit": {"Name": "Nitra", "Code": 838365},
    "Localization": {"Name": "Intravilán"},
    "Municipality": {"Name": "Nitra"},
    "LandUse": {"Name": "Zastavaná plocha a nádvorie"},
    "SharedProperty": None, "ProtectedProperty": None,
    "Affiliation": {"Name": "Intravilán"},
    "Folio": {"Id": 999, "No": 4321},
    "Utilisation": {"Name": "Bytový dom"},
    "Status": {"Code": "OK"},
}

# Two pages of participants — exercises @odata.nextLink pagination.
PARTICIPANTS_PAGE1 = {
    "value": [{"Id": 1, "Name": "Novák Ján r. Novák", "Subjects": [
        {"Id": 7, "FirstName": "Ján", "Surname": "Novák", "BirthSurname": "Novák",
         "Address": {"Id": 1, "Street": "Hlavná", "HouseNo": "1",
                     "Municipality": "Nitra", "Zip": "949 01", "State": "SR"}}]}],
    "@odata.nextLink": (bf.PORTAL_ODATA +
                        "ParcelsC(123)/Kn.Participants?$skiptoken=1"),
}
PARTICIPANTS_PAGE2 = {
    "value": [{"Id": 2, "Name": None, "Subjects": [
        {"Id": 8, "FirstName": None, "Surname": "MESTO NITRA",
         "Address": {"Id": 2, "Street": "Štefánikova trieda", "HouseNo": "60",
                     "Municipality": "Nitra", "Zip": "950 06", "State": "SR"}}]}],
}

LV_HTML = """<html><head><script>var hidden = "noise";</script></head><body>
<h1>Výpis z listu vlastníctva č. 4321</h1>
<p>ČASŤ B: VLASTNÍCI — Novák Ján r. Novák, podiel 1/1</p>
<p>ČASŤ C: ŤARCHY — Exekúcia EX 123/2020, exekučné záložné právo</p>
</body></html>"""


def make_dispatcher(calls=None, parcels_c=None):
    """URL-dispatching stand-in for bf._cadastral_get."""
    def dispatch(url, accept="application/json"):
        if calls is not None:
            calls.append(url)
        if "GeneratePrf" in url:
            return LV_HTML
        if "CadastralUnits" in url:
            if "Vieska" in url:
                rows = ([] if "Name eq" in url else
                        [{"Id": 1, "Name": "Vieska nad Žitavou", "Code": 111},
                         {"Id": 2, "Name": "Dolná Vieska", "Code": 222}])
            else:
                rows = KU_ROWS if "Nitra" in url else []
            return json.dumps({"value": rows})
        if "Kn.Participants" in url:
            page = PARTICIPANTS_PAGE2 if "skiptoken" in url else PARTICIPANTS_PAGE1
            return json.dumps(page)
        if "ParcelsC" in url:
            rows = parcels_c if parcels_c is not None else [PARCEL_ROW]
            return json.dumps({"value": rows})
        if "ParcelsE" in url:
            return json.dumps({"value": []})
        raise AssertionError(f"unexpected URL: {url}")
    return dispatch


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Point database.get_conn at a throwaway SQLite file (cache isolation),
    reset the geoblock latch, and neutralise sleeps."""
    path = str(tmp_path / "cadastre_test.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE listings (
        id TEXT PRIMARY KEY, cadastral_area TEXT, cadastral_number TEXT,
        address_raw TEXT, is_active INTEGER DEFAULT 1)""")
    conn.commit()
    conn.close()

    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(database, "get_conn", _conn)
    monkeypatch.setattr(bf, "_geoblock", {"active": False})
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    return path


# ── happy path ────────────────────────────────────────────────────────────────
def test_enrich_parcel_full_flow(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    res = bf.enrich_parcel("Nitra", "1234/5")

    assert res["status"] == "OK"
    assert res["source"] == "live"
    assert res["cadastral_unit"] == {"code": 838365, "name": "Nitra"}
    assert res["parcel"]["no"] == "1234/5"
    assert res["parcel"]["area_m2"] == 456
    assert res["parcel"]["register"] == "C"
    assert res["parcel"]["land_use"] == "Zastavaná plocha a nádvorie"
    assert res["lv"]["no"] == 4321
    assert "GeneratePrf" in res["lv"]["url"]
    assert "prfNumber=4321" in res["lv"]["url"]
    assert "cadastralUnitCode=838365" in res["lv"]["url"]

    # Both participant pages were followed → both owners present.
    assert len(res["owners"]) == 2
    person, company = res["owners"]
    assert person["name"] == "Novák Ján r. Novák"
    assert person["address"] == "Hlavná 1, 949 01 Nitra, SR"
    assert company["name"] == "MESTO NITRA"   # built from Surname (no Participant.Name)

    # LV HTML stripped to text (script dropped) and flag-scanned.
    assert "listu vlastníctva" in res["lv_text"]
    assert "hidden" not in res["lv_text"]
    flags = [f["flag"] for f in res["risk_flags"]]
    assert "exekúcia" in flags
    assert all(f["bank_related"] is False for f in res["risk_flags"])


# ── caching ───────────────────────────────────────────────────────────────────
def test_cache_hit_avoids_network(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    first = bf.enrich_parcel("Nitra", "1234/5")
    assert first["source"] == "live"

    def no_network(url, accept="application/json"):
        raise AssertionError("network hit on cached parcel")
    monkeypatch.setattr(bf, "_cadastral_get", no_network)

    second = bf.enrich_parcel("Nitra", "1234/5")
    assert second["source"] == "cache"
    assert second["lv"]["no"] == 4321
    assert len(second["owners"]) == 2


def test_refresh_bypasses_cache(temp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher(calls=calls))
    bf.enrich_parcel("Nitra", "1234/5")
    before = len(calls)
    res = bf.enrich_parcel("Nitra", "1234/5", refresh=True)
    assert res["source"] == "live"
    assert len(calls) > before


def test_cached_result_without_lv_text_is_a_miss_when_lv_wanted(temp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher(calls=calls))
    lean = bf.enrich_parcel("Nitra", "1234/5", fetch_lv=False)
    assert lean["status"] == "OK" and lean["lv_text"] is None
    before = len(calls)
    full = bf.enrich_parcel("Nitra", "1234/5", fetch_lv=True)
    assert full["source"] == "live"          # cache couldn't serve lv_text
    assert full["lv_text"] is not None
    assert len(calls) > before


def test_errors_are_not_cached(temp_db, monkeypatch):
    def boom(url, accept="application/json"):
        raise bf.CadastreError("portal down")
    monkeypatch.setattr(bf, "_cadastral_get", boom)
    res = bf.enrich_parcel("Nitra", "1234/5")
    assert res["status"] == "ERROR"
    assert "portal down" in res["detail"]

    # Portal recovers → next call must go live and succeed.
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    res = bf.enrich_parcel("Nitra", "1234/5")
    assert res["status"] == "OK" and res["source"] == "live"


# ── not-found and ambiguity ───────────────────────────────────────────────────
def test_parcel_not_found_tries_both_registers(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher(parcels_c=[]))
    res = bf.enrich_parcel("Nitra", "9999/9")
    assert res["status"] == "NOT_FOUND"
    assert "9999/9" in res["detail"]
    assert "C/E" in res["detail"]
    assert res["cadastral_unit"]["code"] == 838365


def test_unknown_cadastral_unit(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    res = bf.enrich_parcel("Neexistujúce Územie", "1/1")
    assert res["status"] == "NOT_FOUND"
    assert "Neexistujúce Územie" in res["detail"]


def test_ambiguous_cadastral_unit_is_a_clear_error(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    res = bf.enrich_parcel("Vieska", "1/1")
    assert res["status"] == "ERROR"
    assert "ambiguous" in res["detail"]
    assert "Vieska nad Žitavou" in res["detail"]


# ── HTTP layer: retries and geoblock fallback ─────────────────────────────────
class _Resp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


def test_geoblock_403_switches_to_zbgis_proxy(temp_db, monkeypatch):
    calls = []
    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _Resp(403, "forbidden") if len(calls) == 1 else _Resp(200, '{"value": []}')
    monkeypatch.setattr(bf.requests, "get", fake_get)

    out = bf._cadastral_get(bf.PORTAL_ODATA + "CadastralUnits")
    assert out == '{"value": []}'
    assert calls[0].startswith("https://kataster.skgeodesy.sk/")
    assert calls[1].startswith(bf.GEOBLOCK_PROXY_PREFIX)


def test_rate_limit_exhaustion_raises_clear_error(temp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, headers=None, timeout=None: (calls.append(url), _Resp(429, "slow down"))[1])
    with pytest.raises(bf.CadastreError) as ei:
        bf._cadastral_get(bf.PORTAL_ODATA + "CadastralUnits")
    assert f"after {bf.MAX_ATTEMPTS} attempts" in str(ei.value)
    assert "HTTP 429" in str(ei.value)
    assert len(calls) == bf.MAX_ATTEMPTS


def test_unexpected_status_fails_fast_with_body(temp_db, monkeypatch):
    monkeypatch.setattr(
        bf.requests, "get",
        lambda url, headers=None, timeout=None: _Resp(400, "Bad $filter"))
    with pytest.raises(bf.CadastreError) as ei:
        bf._cadastral_get(bf.PORTAL_ODATA + "CadastralUnits")
    assert "HTTP 400" in str(ei.value)
    assert "Bad $filter" in str(ei.value)


def test_non_json_response_is_a_clear_error(temp_db, monkeypatch):
    monkeypatch.setattr(bf, "_cadastral_get",
                        lambda url, accept="application/json": "<html>maintenance</html>")
    with pytest.raises(bf.CadastreError) as ei:
        bf._get_json(bf.PORTAL_ODATA + "CadastralUnits")
    assert "non-JSON" in str(ei.value)


# ── risk-flag scan ────────────────────────────────────────────────────────────
def test_scan_risk_flags_bank_vs_nonbank():
    bank = bf.scan_risk_flags(
        "Záložné právo v prospech Slovenská sporiteľňa, a.s.")
    assert bank == [{"flag": "záložné právo", "bank_related": True}]

    nonbank = bf.scan_risk_flags("Exekúcia EX 55/2021 na podiel vlastníka")
    assert nonbank == [{"flag": "exekúcia", "bank_related": False}]

    assert bf.scan_risk_flags("Bez tiarch a obmedzení") == []


# ── DB backfill mode ──────────────────────────────────────────────────────────
def test_run_cadastre_backfill_counts(temp_db, monkeypatch):
    conn = sqlite3.connect(temp_db)
    conn.executemany(
        "INSERT INTO listings (id, cadastral_area, cadastral_number, address_raw)"
        " VALUES (?,?,?,?)",
        [("l1", "Nitra", "1234/5", "Hlavná 1, Nitra"),
         ("l2", "Neexistujúce Územie", "1/1", "Nowhere 9"),
         ("l3", "", "77/1", "no area — must be skipped")])
    conn.commit()
    conn.close()

    monkeypatch.setattr(bf, "init_db", lambda: None)
    monkeypatch.setattr(bf, "_cadastral_get", make_dispatcher())
    counts = bf.run_cadastre_backfill()
    assert counts == {"processed": 2, "ok": 1, "not_found": 1, "errors": 0}
