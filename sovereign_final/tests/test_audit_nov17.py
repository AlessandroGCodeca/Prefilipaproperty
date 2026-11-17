"""The follow-up to the 12 November audit, built on 17 November: the market
mortgage rate from the ECB (section 8, row 1), the daily-run check (M4), the
December reminder (M14), Slovak cooperative flats and auctions (M13), seller
checks (M7), the building's facts with renovation and heating (M9, S12), rent
by rooms and furnishing (M10, S9), the portfolio (M11, S10), the backtest and
sold prices (S11, M6), the short-let scenario (S13), travel times (S16) and
scanned documents read by Claude (S17)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import make_listing

ECB_CSV = (
    "KEY,FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
    "MIR.M.SK.B.A2C.A.R.A.2250.EUR.N,M,SK,2026-07,3.7,A\n"
    "MIR.M.SK.B.A2C.A.R.A.2250.EUR.N,M,SK,2026-09,3.74,A\n"
    "MIR.M.SK.B.A2C.A.R.A.2250.EUR.N,M,SK,2026-08,3.73,A\n")


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.encoding = text, status, "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


def _get(text, calls=None):
    def get(url, **kw):
        if calls is not None:
            calls.append(url)
        return _Resp(text)
    return get


# ── Section 8, row 1: the market mortgage rate ───────────────────────────────
def test_the_newest_ecb_observation_is_read():
    from modules.market_rates import parse_ecb_csv
    assert parse_ecb_csv(ECB_CSV) == ("2026-09", pytest.approx(0.0374))


def test_an_arad_answer_is_read():
    from modules.market_rates import parse_arad_csv
    text = "indicator_id;snapshot_id;period;value\nX;;20260731;4,61\nX;;20260831;4,58\n"
    assert parse_arad_csv(text) == ("2026-08", pytest.approx(0.0458))


@pytest.mark.parametrize("bad", ["KEY,TIME_PERIOD,OBS_VALUE\n", "KEY,TIME_PERIOD,OBS_VALUE\nX,2026-09,74\n"])
def test_an_empty_or_implausible_answer_is_refused(bad):
    from modules.market_rates import parse_ecb_csv
    with pytest.raises(ValueError):
        parse_ecb_csv(bad)


def test_the_ecb_rate_becomes_the_models_rate_and_is_stored():
    import config
    from engine import financial
    from modules import market_rates
    changed = market_rates.refresh(get=_get(ECB_CSV))
    assert changed == ["sk"]
    assert financial.MORTGAGE_RATE_PA == pytest.approx(0.0374)
    assert config.market_rate("sk") == pytest.approx(0.0374)
    stored = json.load(open(config.MARKET_RATES_PATH))
    assert stored["sk"]["period"] == "2026-09" and "ECB" in stored["sk"]["source"]
    assert "3.74 %" in market_rates.describe("sk") and "in use" in market_rates.describe("sk")


def test_your_own_rate_wins(monkeypatch):
    from engine import financial
    from modules import market_rates
    monkeypatch.setenv("MORTGAGE_RATE_PA", "0.041")
    before = financial.MORTGAGE_RATE_PA
    assert market_rates.refresh(get=_get(ECB_CSV)) == []
    assert financial.MORTGAGE_RATE_PA == before
    assert "yours is used instead" in market_rates.describe("sk")


def test_the_bank_is_read_at_most_weekly_and_a_failure_keeps_the_last_value():
    from modules import market_rates
    calls = []
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    market_rates.refresh(get=_get(ECB_CSV, calls), now=now)
    market_rates.refresh(get=_get(ECB_CSV, calls), now=now + timedelta(days=2))
    assert len(calls) == 1

    def broken(url, **kw):
        raise OSError("down")
    market_rates.refresh(get=broken, now=now + timedelta(days=8))
    assert market_rates.latest("sk")["rate"] == pytest.approx(0.0374)


def test_czechia_needs_its_arad_key():
    from modules import market_rates
    assert market_rates.fetch_cz(get=_get("x")) is None
    assert "CZ_ARAD_API_KEY" in market_rates.describe("cz")


def test_scores_on_an_older_rate_are_redone(full_db):
    import database
    from modules import market_rates
    from modules.cashflow_runner import run_scoring
    database.upsert_listing(make_listing("r1"))
    run_scoring()
    assert database.requeue_scores_from_older_model() == 0
    market_rates.refresh(get=_get(ECB_CSV))
    assert database.requeue_scores_from_older_model() == 1
    run_scoring()
    row = next(r for r in database.get_all_active() if r["id"] == "r1")
    assert row["mortgage_rate_used"] == pytest.approx(0.0374)


# ── M4: did the daily run happen? ────────────────────────────────────────────
def _poster(calls, status=200):
    def post(url, data=None, timeout=None):
        calls.append((url, data))

        class R:
            status_code = status
        return R
    return post


def test_no_healthcheck_url_no_ping():
    from modules import heartbeat
    calls = []
    assert not heartbeat.ping("start", post=_poster(calls)) and calls == []


def test_the_watcher_hears_start_success_and_failure(monkeypatch):
    from modules import heartbeat
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc/")
    calls = []
    assert heartbeat.ping("start", post=_poster(calls))
    assert heartbeat.ping("", body="SK ok", post=_poster(calls))
    assert heartbeat.ping("fail", post=_poster(calls))
    assert [u for u, _ in calls] == ["https://hc-ping.com/abc/start", "https://hc-ping.com/abc",
                                     "https://hc-ping.com/abc/fail"]
    assert calls[1][1] == b"SK ok"


def test_a_ping_that_fails_never_fails_the_run(monkeypatch):
    from modules import heartbeat
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc")

    def down(*a, **k):
        raise OSError("no route")
    assert heartbeat.ping("", post=down) is False


def test_each_run_pings_and_a_failed_market_reports_fail(monkeypatch):
    import scheduler
    from modules import alerts, heartbeat
    pings = []
    monkeypatch.setattr(heartbeat, "ping", lambda signal="", body="", post=None: pings.append(
        (signal, body)))
    monkeypatch.setattr(alerts, "run_quietly", lambda: None)
    monkeypatch.setattr(scheduler, "_refresh_fx", lambda: None)
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **kw: False)
    scheduler.run_all_markets(holder="test", which=["sk"])
    assert pings[0][0] == "start" and pings[-1][0] == "fail" and "SK FAILED" in pings[-1][1]
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **kw: True)
    scheduler.run_all_markets(holder="test", which=["sk"])
    assert pings[-1] == ("", "06:00: SK ok")


def test_a_run_more_than_a_day_old_is_overdue():
    from modules.pipeline_state import overdue
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    assert overdue({"finished_at": (now - timedelta(hours=31)).isoformat()}, now)
    assert not overdue({"finished_at": (now - timedelta(hours=7)).isoformat()}, now)
    assert not overdue(None, now)


# ── M14: the yearly reminder ─────────────────────────────────────────────────
def test_december_reminds_you_to_collect_next_years_figures():
    from datetime import date
    from modules import yearly
    got = yearly.due(date(2026, 12, 3))
    assert {r["market"] for r in got} == {"sk", "cz"}
    assert all(r["level"] == "info" and "2027" in r["text"] for r in got)
    assert yearly.due(date(2026, 11, 17)) == []


def test_january_warns_while_the_new_years_table_is_missing():
    from datetime import date
    from modules import yearly
    got = yearly.due(date(2027, 1, 5))
    assert got and all(r["level"] == "warning" and "2026's" in r["text"] for r in got)


def test_the_reminder_is_messaged_once(monkeypatch, tmp_path):
    from datetime import date
    import config
    import database
    import requests
    from modules import alerts, yearly
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "s.db"))
    database.init_db()
    sent = []

    def post(url, data=None, timeout=None):
        sent.append(data["text"])

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True, "result": {}}
        return R
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    alerts.run()                                       # the first run: "alerts are on"
    monkeypatch.setattr(yearly, "reminders", lambda today=None: yearly.due(date(2026, 12, 2)))
    assert alerts.run().endswith("2 issue(s)")
    assert "collect the 2027 tax figures" in sent[-1]
    assert alerts.run() == "nothing new"


# ── M13 / finding 24: Slovak cooperative flats ───────────────────────────────
@pytest.mark.parametrize("text, coop", [
    ("Predaj 3-izbový družstevný byt, Petržalka", True),
    ("Vlastníctvo: družstevné", True),
    ("prevod členských práv a povinností k bytu", True),
    ("byt v družstevnom vlastníctve", True),
    ("Vlastníctvo: osobné. Družstevná ulica 5", False),
    ("byt v osobnom vlastníctve, pôvodne družstevný", False),
    ("Správca: Bytové družstvo Petržalka", False),
    ("byt na Družstevnej 12", False),
    ("byt bol prevedený z družstevného do osobného vlastníctva", False),
])
def test_a_slovak_cooperative_flat_is_recognised(text, coop):
    from modules.debt_bot import is_cooperative_sk
    assert is_cooperative_sk(text) is coop


def test_a_cooperative_flat_is_never_called_clean(full_db, monkeypatch):
    import database
    from modules import debt_bot
    database.upsert_listing(make_listing("c1", title="2-izbový družstevný byt", lv_number="4521"))
    monkeypatch.setattr(debt_bot, "check_flat_lv", lambda *a, **k: pytest.fail("cadastre read"))
    row = {"id": "c1", "title": "2-izbový družstevný byt", "market": "sk", "lv_number": "4521",
           "cadastral_area": "Petržalka"}
    got = debt_bot.check_listing(row)
    assert got["status"] == "UNVERIFIED" and got["detail"].startswith("Cooperative flat")


# ── M13: auctions from the notaries' register ────────────────────────────────
RESULTS_HTML = """<table class="search_results"><thead><tr><th>x</th></tr></thead><tbody>
<tr><td><a href="drazba?actId=6afaf5b6" title="x">1387/2026</a></td>
<td>SAN &amp; DRUM INVEST s.r.o. <br> IČO: 47660457 </td>
<td><span class="proposers">Slovenská sporiteľňa, a.s. <br> IČO: 00151653</span></td>
<td>Oznámenie o dražbe</td><td></td><td>18.12.2026</td></tr>
<tr><td>broken row</td></tr></tbody></table>"""
DETAIL_HTML = """<p><span class="key">Miesto konania dražby:</span><span class="value">Dunajská 4</span></p>
<p><span class="key">Bližšie označenie miesta konania dražby:</span><span class="value">2. poschodie</span></p>
<p><span class="key">Dátum a čas otvorenia dražby:</span><span class="value">18.12.2026 11:00:00</span></p>
<p><span class="key">Druh predmetu dražby:</span><span class="value">Nehnuteľná vec</span></p>
<p><span class="key">Uverejnené listiny:</span><span class="value"><a href="/listina/?actId=6afaf5b6&amp;documentId=d1">Oznámenie o dražbe</a></span></p>"""


def test_the_registers_rows_and_records_are_read():
    from modules.auctions_sk import parse_detail, parse_results
    rows = parse_results(RESULTS_HTML)
    assert rows == [{"act_id": "6afaf5b6", "ncr_no": "1387/2026",
                     "auctioneer": "SAN & DRUM INVEST s.r.o.", "auctioneer_ico": "47660457",
                     "proposer": "Slovenská sporiteľňa, a.s.", "act_type": "Oznámenie o dražbe",
                     "auction_date": "2026-12-18"}]
    d = parse_detail(DETAIL_HTML)
    assert d["subject_kind"] == "Nehnuteľná vec" and d["venue"] == "Dunajská 4, 2. poschodie"
    assert d["doc_url"] == "https://www.notar.sk/listina/?actId=6afaf5b6&documentId=d1"
    assert d["auction_date"] == "2026-12-18"


def test_a_full_window_is_split_until_nothing_is_cut():
    from modules import auctions_sk
    asked = []
    full = "<table class='search_results'><tbody>" + "".join(
        f"<tr><td><a href='drazba?actId={i:04x}'>{i}/2026</a></td><td>A</td><td>B</td>"
        f"<td>Oznámenie o dražbe</td><td></td><td>01.12.2026</td></tr>" for i in range(20)
    ) + "</tbody></table>"

    def get(url, params=None, **kw):
        asked.append((params["auctionDateFrom"], params["auctionDateTo"]))
        return _Resp(full if params["auctionDateFrom"] == params["auctionDateTo"] == "2026-12-01"
                     or params["auctionDateTo"] > "2026-12-01" and params["auctionDateFrom"] <= "2026-12-01"
                     else "<table class='search_results'><tbody></tbody></table>")
    from datetime import date
    rows = auctions_sk.search(date(2026, 12, 1), date(2026, 12, 4), get=get)
    assert len(asked) > 1 and len(rows) == 20


def test_the_register_is_stored_and_an_announcement_read(full_db, monkeypatch):
    from datetime import date
    from database.auctions import get_auctions
    from modules import auctions_sk, doc_reader

    def get(url, params=None, **kw):
        if url == auctions_sk.SEARCH:
            return _Resp(RESULTS_HTML if params["auctionDateFrom"] == "2026-12-15" else
                         "<table class='search_results'><tbody></tbody></table>")
        if url == auctions_sk.DETAIL:
            return _Resp(DETAIL_HTML)
        r = _Resp("")
        r.content = b"%PDF-1.3 scan"
        return r
    got = auctions_sk.refresh(days_ahead=14, get=get, today=date(2026, 12, 1))
    assert got == {"seen": 1, "new": 1, "details": 1}
    monkeypatch.setattr(doc_reader, "enabled", lambda: True)
    monkeypatch.setattr(doc_reader, "ask", lambda *a, **k: {
        "is_real_estate": True, "is_flat": True, "municipality": "Trnava", "address": "Hlavná 1",
        "cadastral_area": "Trnava", "lv_number": "1234", "size_m2": 62.0, "rooms": 3,
        "minimum_bid_eur": 90_000, "valuation_eur": 140_000, "deposit_eur": 20_000,
        "inspection": "2.12.2026 10:00", "notes": "A tenant's lease stays."})
    row = auctions_sk.read_announcement("6afaf5b6", get=get)
    assert row["is_flat"] == 1 and row["min_bid_eur"] == 90_000
    assert get_auctions(today=date(2026, 12, 1))[0]["municipality"] == "Trnava"
    d = auctions_sk.discount_to_median(row)
    assert d is not None and 0 < d < 1


# ── S17: documents read by Claude ────────────────────────────────────────────
@pytest.mark.parametrize("head, kind", [
    (b"%PDF-1.7", "application/pdf"), (b"\xff\xd8\xff\xe0", "image/jpeg"),
    (b"\x89PNG\r\n", "image/png"), (b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
    (b"\x00\x00\x00\x18ftypheic", None)])
def test_what_claude_can_be_sent(head, kind):
    from modules.doc_reader import media_type
    assert media_type(head + b"rest") == kind


def test_nothing_is_sent_without_a_key():
    from modules import doc_reader
    assert doc_reader.transcribe(b"%PDF-1.4 scan") is None
    assert doc_reader.read_title_deed(b"\xff\xd8\xffphoto") is None


def test_a_photo_of_a_deed_is_sent_as_an_image(monkeypatch):
    from modules import doc_reader, llm_enrichment
    sent = {}

    def ask_json(system, user, schema, **kw):
        sent.update(user=user, model=kw.get("model"))
        return {"is_title_deed": True, "lv_number": "4521 ", "cadastral_area": "Petržalka",
                "text": "ČASŤ C: ŤARCHY Bez zápisu"}
    monkeypatch.setattr(doc_reader, "enabled", lambda: True)
    monkeypatch.setattr(llm_enrichment, "_ask_json", ask_json)
    got = doc_reader.read_title_deed(b"\xff\xd8\xffphoto")
    assert got == {"text": "ČASŤ C: ŤARCHY Bez zápisu", "lv_number": "4521",
                   "cadastral_area": "Petržalka"}
    assert sent["user"][0]["type"] == "image" and sent["user"][0]["source"]["media_type"] == "image/jpeg"


def test_an_uploaded_scanned_ordinance_is_read_by_claude(monkeypatch):
    from modules import doc_reader
    from scraper import property_tax_rates as scr
    monkeypatch.setattr(scr, "_pdf_text", lambda content: ("1", 3))
    monkeypatch.setattr(doc_reader, "transcribe", lambda content, what="": "Sadzba dane za byty 0,25 eura za m2")
    doc = scr.doc_from_bytes("u.pdf", b"%PDF-1.4", ocr=True)
    assert not doc.problem and "0,25" in doc.text
    doc = scr.doc_from_bytes("u.pdf", b"%PDF-1.4")          # an automated run: off by default
    assert doc.problem.startswith(scr.SCAN_PROBLEM)
    monkeypatch.setenv("TAX_SCANS_WITH_CLAUDE", "1")
    assert not scr.doc_from_bytes("u.pdf", b"%PDF-1.4").problem


# ── M7: seller checks ────────────────────────────────────────────────────────
SK_DEED = ("LIST VLASTNÍCTVA č. 1 ČASŤ B: VLASTNÍCI A INÉ OPRÁVNENÉ OSOBY 1 Novák Ján, nar. "
           "01.01.1970, Hlavná 1, Nitra, SR Spoluvlastnícky podiel: 1/2 2 ABC Reality s.r.o., "
           "Mlynská 2, Trnava, IČO: 12345678 Spoluvlastnícky podiel: 1/2 ČASŤ C: ŤARCHY 1 "
           "Záložné právo v prospech XY banka, IČO 00151653")
CZ_DEED = ("Katastrální území: Testov\nA Vlastník, jiný oprávněný\n  Vlastnické právo\n"
           "  Novák Jan, Hlavní 1, 11000 Praha 1\n  XYZ s.r.o., Dlouhá 5, Praha, IČO: 27074358\n"
           "B Nemovitosti\n  Jednotka č. 5")


def test_the_owners_are_read_from_the_deed():
    from modules.seller_check import owners
    assert owners(SK_DEED) == [
        {"name": "Novák Ján", "ico": "", "company": False},
        {"name": "ABC Reality s.r.o.", "ico": "12345678", "company": True}]
    # The bank's IČO in part C is not an owner's.
    assert owners(CZ_DEED, "cz") == [
        {"name": "Novák Jan", "ico": "", "company": False},
        {"name": "XYZ s.r.o.", "ico": "27074358", "company": True}]
    assert owners("") == []


class _JsonResp(_Resp):
    def __init__(self, data, status=200):
        super().__init__("", status)
        self._data = data

    def json(self):
        return self._data


def test_a_czech_company_in_insolvency_is_flagged():
    from modules.seller_check import check_company

    def get(url, **kw):
        return _JsonResp({"obchodniJmeno": "XYZ s.r.o.",
                          "seznamRegistraci": {"stavZdrojeIr": "AKTIVNI", "stavZdrojeVr": "AKTIVNI"}})
    got = check_company("27074358", "cz", get=get)
    assert got["name"] == "XYZ s.r.o." and "insolvency register" in got["warnings"][0]


def test_a_dissolved_slovak_company_is_flagged_and_an_outage_said():
    from modules.seller_check import check_company

    def get(url, params=None, **kw):
        if "uctovne-jednotky" in url:
            return _JsonResp({"id": [1, 7]})
        assert params == {"id": 7}
        return _JsonResp({"nazovUJ": "ABC Reality s.r.o.", "datumZrusenia": "2025-03-01"})
    got = check_company("12345678", "sk", get=get)
    assert got["warnings"] == ["Dissolved on 2025-03-01."]

    def down(url, **kw):
        raise OSError("timeout")
    assert check_company("12345678", "sk", get=down)["status"].startswith("register not reachable")


# ── M9 + S12: the building, renovation, heating and the flip ──────────────────
def test_the_ad_says_what_the_building_is():
    from engine.building import parse_ad
    got = parse_ad("Tehlový byt v zateplenom dome, ústredné kúrenie, rok výstavby 1978. "
                   "Mesačné náklady 185 € vrátane záloh, fond opráv 45 €.")
    assert got == {"construction": "brick", "insulated": True, "heating": "district",
                   "year_built": 1978, "costs_monthly": 185.0, "fund_monthly": 45.0}
    got = parse_ad("Panelák, nie je zateplený, vlastný plynový kotol")
    assert (got["construction"], got["insulated"], got["heating"]) == ("panel", False,
                                                                       "gas boiler (flat)")
    assert parse_ad("")["construction"] is None


def test_renovation_and_heating_scale_with_size_and_state():
    from engine.building import heating_monthly, renovation_cost
    assert renovation_cost(55, "renovated") == 0
    assert renovation_cost(55, "poor") > renovation_cost(55, "original") > renovation_cost(55, "good")
    assert heating_monthly(55, "G") > heating_monthly(55, "B") > heating_monthly(55, "A0")


def test_the_flip_adds_up():
    from engine.building import flip
    f = flip(90_000, 55, "Žilina", "original", rooms=2)
    assert f is not None and f.renovation > 0 and f.months == 6
    assert f.profit == pytest.approx(f.sale_price - f.selling_costs - f.buy - f.buying_costs
                                     - f.renovation - f.holding - f.tax, abs=0.05)
    assert flip(90_000, 55, "", "original", sale_price=150_000).sale_note == "your sale price"


def test_an_old_uninsulated_building_is_a_risk():
    from engine.building import building_risks
    assert building_risks({"year_built": 1975, "insulated": None}, 2026)
    assert not building_risks({"year_built": 1975, "insulated": True}, 2026)


def test_the_real_fee_you_enter_replaces_the_estimate(full_db):
    import database
    from database.building import get_building_facts, set_building_facts
    from modules.cashflow_runner import run_scoring
    database.upsert_listing(make_listing("b1"))
    run_scoring()
    before = next(r for r in database.get_all_active() if r["id"] == "b1")
    set_building_facts("b1", {"hoa_monthly": "140", "insulated": "no", "year_built": 1971})
    assert get_building_facts("b1")["insulated"] == 0
    run_scoring()
    after = next(r for r in database.get_all_active() if r["id"] == "b1")
    assert after["hoa_monthly"] == 140 and before["hoa_monthly"] != 140
    assert after["surplus_personal"] < before["surplus_personal"]


# ── M10 + S9: rent by flat type, and time to let ─────────────────────────────
def _rental(key, rooms, rent, size=50.0, furnished="unfurnished", first="2026-09-01",
            last="2026-11-10"):
    return {"rent_key": key, "rooms": rooms, "rent_eur": rent, "size_m2": size,
            "furnished": furnished, "energies_included": 0,
            "scraped_at": f"{first}T08:00:00+00:00", "last_seen_at": f"{last}T08:00:00+00:00"}


def test_comps_are_split_by_rooms_and_furnishing():
    from engine.rent_comps import aggregate_by_rooms, rates_by_rooms
    rows = ([_rental("žilina", 1, 600, size=35) for _ in range(6)]
            + [_rental("žilina", 3, 800, size=75, furnished="furnished") for _ in range(3)])
    comps = aggregate_by_rooms(rows)
    assert comps[("žilina", 1)]["n"] == 6 and comps[("žilina", 3)]["n"] == 3
    assert comps[("žilina", 3)]["by_furnishing"]["furnished"]["median_eur_per_m2"] == pytest.approx(800 / 75, 0.01)
    rates = rates_by_rooms(comps)
    assert "žilina#r1" in rates and "žilina#r3" not in rates      # 3 comps: too few


def test_a_flat_types_own_rate_replaces_the_rooms_factor():
    from engine.financial import get_rent_estimate
    plain = get_rent_estimate("Žilina", 35, rooms=1, rates={})
    typed = get_rent_estimate("Žilina", 35, rooms=1, rates={"žilina#r1": 20.0})
    assert typed == pytest.approx(20.0 * 35) and typed != plain
    # Another type in the same district keeps the factor.
    assert get_rent_estimate("Žilina", 55, rooms=2, rates={"žilina#r1": 20.0}) == \
        get_rent_estimate("Žilina", 55, rooms=2, rates={})


def test_time_to_let_counts_ads_that_went():
    from engine.rent_comps import time_to_let
    rows = ([_rental("nitra", 2, 600, first="2026-09-01", last="2026-11-15")]   # tracking start
            + [_rental("nitra", 2, 600, first="2026-10-01", last=f"2026-10-{d:02d}")
               for d in (11, 21, 31)]                                       # 10, 20, 30 days
            + [_rental("nitra", 2, 600, first="2026-10-01", last="2026-11-14")])  # still up
    assert time_to_let(rows) == {("nitra", 2): {"n": 3, "median_days": 20}}


def test_the_rebuild_stores_types_and_scoring_reads_them(full_db):
    import database
    from engine.rent_comps import load_live_rates, rebuild_rent_comps, rooms_table
    now = datetime.now(timezone.utc).isoformat()
    for i in range(7):
        database.upsert_rental({"id": f"r{i}", "source": "bazos", "url": f"https://x/{i}",
                                "title": "1-izbový byt", "rent_eur": 640.0, "size_m2": 34.0,
                                "rooms": 1, "district": "Žilina", "rent_key": "žilina",
                                "energies_included": 0, "furnished": "unfurnished",
                                "scraped_at": now, "last_seen_at": now})
    rebuild_rent_comps()
    assert "žilina#r1" in load_live_rates()
    row = next(r for r in rooms_table() if r["Flat"] == "1 room")
    assert row["Comps"] == 7 and row["Source"] == "this type's comps"


# ── M11 + S10: the portfolio ─────────────────────────────────────────────────
def test_the_loan_balance_follows_the_bank_schedule():
    from engine import financial
    from engine.portfolio import balance_after
    sched = financial.loan_schedule(100_000, 0.04, 25, 3, 0.055)
    assert balance_after(100_000, 0.04, 25, 12) == pytest.approx(sched[0][2], abs=0.01)
    assert balance_after(100_000, 0.04, 25, 48, 3, 0.055) == pytest.approx(sched[3][2], abs=0.01)
    assert balance_after(100_000, 0.04, 25, 400) == 0


def test_a_flat_you_own_has_its_figures_and_the_model_is_compared(full_db):
    from database.portfolio import get_ledger, get_owned_flats, save_owned_flat, set_ledger_month
    from engine.portfolio import calibration, flat_numbers
    fid = save_owned_flat({"name": "Žilina 2i", "market": "sk", "district": "Žilina",
                           "size_m2": 55, "rooms": 2, "bought_on": "2024-05-01", "price": 120_000,
                           "loan_principal": 96_000, "loan_rate": 0.041, "loan_years": 30,
                           "rent_monthly": 650, "hoa_monthly": 90})
    set_ledger_month(fid, "2026-10", 650, 120, 0)
    set_ledger_month(fid, "2026-09", 0, 110, 30)
    with pytest.raises(ValueError):
        set_ledger_month(fid, "Oct 2026", 1, 1)
    with pytest.raises(ValueError):
        save_owned_flat({"name": " "})
    f = get_owned_flats()[0]
    from datetime import date
    n = flat_numbers(f, get_ledger(fid), date(2026, 11, 17))
    assert n.months_on_record == 2 and n.rent_12m == 650 * 11
    assert 0 < n.balance < 96_000 and n.equity == pytest.approx(n.value - n.balance)
    assert n.cash_flow_12m == pytest.approx(n.rent_12m - n.costs_12m - n.payment * 12 - n.tax_year_est,
                                            abs=0.05)
    rows = calibration([f], [n])
    assert {r["Assumption"] for r in rows} >= {"Rent a month", "Building fee a month"}


# ── S11 + M6: the backtest and sold prices ───────────────────────────────────
def _seen(lid, first, last, active=1, **kw):
    return make_listing(lid, now=f"{first}T08:00:00+00:00", **kw), last, active


def test_greens_that_went_fast_show_in_the_backtest(full_db):
    from datetime import date
    import database
    from engine import backtest
    rows = [("g1", "2026-09-20", "2026-09-30", 0, "GREEN"), ("g2", "2026-09-22", "2026-10-25", 0, "GREEN"),
            ("w1", "2026-09-20", "2026-11-16", 1, "WHITE"), ("w2", "2026-09-21", "2026-11-16", 1, "WHITE")]
    for lid, first, *_ in rows:
        database.upsert_listing(make_listing(lid, now=f"{first}T08:00:00+00:00"))
    conn = database.get_conn()
    for lid, _first, last, active, cls in rows:
        conn.execute("UPDATE listings SET last_seen_at=?, is_active=? WHERE id=?",
                     (f"{last}T08:00:00+00:00", active, lid))
        conn.execute("INSERT INTO cashflow_scores (listing_id, classification) VALUES (?, ?)",
                     (lid, cls))
    conn.execute("INSERT INTO price_history (listing_id, price_eur, observed_at) VALUES "
                 "('g2', 100000, '2026-09-22'), ('g2', 95000, '2026-10-10')")
    conn.commit()
    conn.close()
    rows, exact = backtest.run(60, 30, today=date(2026, 11, 17))
    assert not exact                              # no snapshots yet: first seen in the window
    green = next(r for r in rows if r["Class"] == "GREEN")
    white = next(r for r in rows if r["Class"] == "WHITE")
    assert green["Gone %"] == 100 and white["Gone %"] == 0
    assert green["Gone within 30 days %"] == 50 and green["Median cut %"] == -5.0
    # Once snapshots exist, they decide the cohort's class.
    assert backtest.take_snapshot(date(2026, 9, 25)) == 2      # the two still active
    classes, exact = backtest.cohort(date(2026, 9, 18), date(2026, 10, 18))
    assert exact and classes == {"w1": "WHITE", "w2": "WHITE"}


def test_sold_prices_and_last_asking_are_compared_with_asking(full_db):
    import database
    from engine import backtest
    for i, price in enumerate((100_000, 110_000, 120_000)):
        database.upsert_listing(make_listing(f"a{i}", price_eur=float(price), size_m2=50.0,
                                             district="Žilina"))
    backtest.add_sold_price("sk", "Žilina", 50, 95_000, "2026-10")
    with pytest.raises(ValueError):
        backtest.add_sold_price("sk", "", 50, 1)
    row = next(r for r in backtest.asking_vs("sk") if r["District key"] == "žilina")
    assert row["Asking €/m²"] == 2200 and row["Sold (yours) €/m²"] == 1900
    assert row["Sold (yours) vs asking %"] == pytest.approx(-13.6, abs=0.1)


# ── S13: the short-let scenario ──────────────────────────────────────────────
@pytest.mark.parametrize("district, market, key", [
    ("Bratislava I", "sk", "ba1"), ("Bratislava-Staré Mesto", "sk", "ba1"),
    ("Bratislava II", "sk", None), ("Košice I - Staré Mesto", "sk", None),
    ("Vysoké Tatry", "sk", "tatry"), ("Praha 1", "cz", "praha1"), ("Praha 10", "cz", None),
    ("Praha 2 - Vinohrady", "cz", "praha2"), ("Žilina", "sk", None)])
def test_a_flat_is_placed_in_its_short_let_area(district, market, key):
    from engine.short_let import area_for
    a = area_for(district, market)
    assert (a.key if a else None) == key


def test_the_short_let_month_and_its_break_even(monkeypatch):
    from engine.short_let import scenario
    row = {"district": "Bratislava I", "market": "sk", "size_m2": 45, "price_eur": 230_000,
           "mortgage_monthly": 880, "surplus_personal": -450}
    s = scenario(row)
    costs = (s.platform_monthly + s.cleaning_monthly + s.local_tax_monthly + s.manager_monthly
             + s.utilities_monthly + s.furnishing_monthly + s.building_monthly)
    assert s.surplus_monthly == pytest.approx(s.gross_monthly - costs - s.tax_monthly
                                              - s.mortgage_monthly, abs=0.05)
    at_break_even = scenario(row, occupancy=s.break_even_occupancy)
    assert at_break_even.surplus_monthly == pytest.approx(-450, abs=5)
    assert scenario(row, manager=True).surplus_monthly < s.surplus_monthly
    monkeypatch.setenv("SHORT_LET_BA1_ADR", "120")
    assert scenario(row).adr == 120
    assert scenario({**row, "district": "Žilina"}) is None


# ── S16: travel time to a point ──────────────────────────────────────────────
def test_travel_times_are_asked_once_and_kept(full_db):
    from modules import travel
    calls = []

    def get(url, params=None, **kw):
        calls.append(url)
        return _JsonResp({"durations": [[600.0], [None]]})
    target = (48.1486, 17.1077)
    origins = {"a": (48.1593, 17.1252), "b": (48.1120, 17.1090)}
    got = travel.travel_times(target, origins, "walk", get=get)
    assert got == {"a": 10.0, "b": None} and "routed-foot" in calls[0]
    assert travel.travel_times(target, origins, "walk", get=get) == got and len(calls) == 1


def test_openrouteservice_and_google_are_used_with_their_keys(full_db, monkeypatch):
    from modules import travel
    assert travel.available_modes() == ["walk", "drive"]
    monkeypatch.setenv("ORS_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "g")
    assert travel.provider("drive") == "ors" and "transit" in travel.available_modes()
    sent = []

    def post(url, json=None, headers=None, **kw):
        sent.append((url, json, headers))
        if "googleapis" in url:
            return _JsonResp([{"originIndex": 0, "destinationIndex": 0, "duration": "1500s",
                               "condition": "ROUTE_EXISTS"}])
        return _JsonResp({"durations": [[300.0]]})
    assert travel.travel_times((48.1, 17.1), {"a": (48.2, 17.2)}, "drive", post=post) == {"a": 5.0}
    assert travel.travel_times((48.1, 17.1), {"a": (48.2, 17.2)}, "transit", post=post) == {"a": 25.0}
    assert sent[0][2]["Authorization"] == "k" and sent[1][1]["travelMode"] == "TRANSIT"
