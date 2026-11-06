"""modules/tax_rates and engine/property_tax_sk's stored rates — what one
click on 🏛️ UPDATE TAX RATES does with what it read.

The rule they keep: a rate read from a town's site replaces the hand-checked
table only when it comes from a dated ordinance for a later tax year than the
table's; a town the table lacks takes its rate instead of the fallback; and
anything else that disagrees waits for the user.
"""

import pytest

from engine import property_tax_sk as tax
from modules import tax_rates as tr
from scraper import property_tax_rates as scr
from tests.conftest import make_listing

YEAR = tax.TABLE_YEAR


def reading(rates, year=None, kind="ordinance", url="https://mesto.sk/vzn.pdf",
            title="VZN č. 9/2025 o miestnych daniach"):
    return scr.Reading(url=url, title=title, rates=list(rates), excerpt="a) … € za byty",
                       tax_year=year, dated=year is not None, kind=kind)


def result(town, *readings, blocked="", problems=(), unread_newer=()):
    res = scr.TownResult(town, readings=list(readings), fetched=len(readings) or 1,
                         blocked=blocked, problems=list(problems),
                         unread_newer=list(unread_newer))
    res.current, res.upcoming, res.conflict = scr.pick(list(readings), YEAR, today=YEAR)
    return res


def town(name):
    return scr.TOWNS.get(name) or scr.Town(name, ("https://example.sk/",))


def assess(name, *readings, **kw):
    return tr.assess(town(name), result(name, *readings, **kw), YEAR)


# ── What a reading means ──────────────────────────────────────────────────────
def test_the_tables_rate_is_confirmed():
    o = assess("Pezinok", reading([1.0], 2024))
    assert (o.status, o.store) == ("confirmed", [])
    assert "1.00 €/m²" in o.message


def test_a_different_rate_for_a_year_the_table_covers_waits_for_review():
    # Web search once gave Pezinok 1.50; its ordinance says 1.00. A reading
    # that contradicts the hand-checked table never replaces it on its own.
    o = assess("Pezinok", reading([1.5], 2024))
    assert (o.status, o.store) == ("review", [])
    assert "1.50" in o.message and "1.00" in o.message


def test_an_undated_page_that_disagrees_waits_for_review():
    o = assess("Nitra", reading([0.8], kind="page"))
    assert o.status == "review"


def test_a_later_years_ordinance_is_applied_from_that_year():
    o = assess("Senec", reading([0.6], YEAR), reading([0.7], YEAR + 1))
    assert o.status == "upcoming"
    assert [(y, r) for y, r, _ in o.store] == [(YEAR + 1, 0.7)]
    assert f"From {YEAR + 1}: 0.70" in o.message


def test_a_town_the_table_lacks_is_added():
    o = assess("Šamorín", reading([0.85], 2025, title="1-vzn7-2024-–-web-1.pdf"))
    assert o.status == "new"
    assert [(y, r) for y, r, _ in o.store] == [(2025, 0.85)]
    assert "fallback" in o.message


def test_a_new_towns_undated_ordinance_waits_for_review():
    # Komárno: a 2008 ordinance with no readable date may long be repealed.
    o = assess("Komárno", reading([0.139]))
    assert (o.status, o.store) == ("review", [])


def test_several_flat_rates_in_a_one_rate_town_wait_for_review():
    o = assess("Komárno", reading([0.039, 0.056, 0.139], 2009))
    assert o.status == "review" and "several" in o.message


def test_two_documents_for_one_year_that_disagree_wait_for_review():
    o = assess("Trnava", reading([1.0], 2026, url="https://a.sk/1.pdf"),
               reading([1.1], 2026, url="https://a.sk/2.pdf"))
    assert o.status == "review" and "disagree" in o.message


def test_a_newer_ordinance_it_could_not_read_waits_for_review():
    o = assess("Trenčín", reading([0.88], 2026), unread_newer=["VZN č. 3/2027 (zmena)"])
    assert (o.status, o.store) == ("review", [])
    assert "3/2027" in o.message


def test_a_zoned_town_is_verified_against_its_rates():
    ok = assess("Košice", reading([1.27, 1.207, 1.143], 2026, kind="page"))
    assert (ok.status, ok.store) == ("confirmed", [])
    changed = assess("Košice", reading([1.30, 1.207, 1.143], 2027))
    assert (changed.status, changed.store) == ("review", [])
    assert "by hand" in changed.message


def test_a_blocked_site_says_how_to_get_the_rate_anyway():
    o = assess("Prešov", blocked="the site answered with a CAPTCHA or bot check instead of the page")
    assert o.status == "blocked" and "upload" in o.message


def test_nothing_found_says_what_could_not_be_read():
    o = assess("Stupava", problems=["VZN 5/2023: a scanned PDF with no text layer — it can't be read"])
    assert o.status == "not_found" and "scan" in o.message


# ── Stored rates in the engine ────────────────────────────────────────────────
def stored(town, *rows):
    return {scr.fold(town): [dict(town=scr.fold(town), name=town, tax_year=y, rate=r, origin=o,
                                  source_url="u", document="VZN", saved_at="2026-11-03")
                             for y, r, o in rows]}


def test_a_scraped_rate_for_the_tables_year_does_not_replace_it(monkeypatch):
    monkeypatch.setattr(tax, "_stored", stored("Pezinok", (YEAR, 1.5, "scraped")))
    assert tax.rate_source("Pezinok", YEAR)[0] == 1.0


def test_a_rate_the_user_accepted_replaces_the_table(monkeypatch):
    monkeypatch.setattr(tax, "_stored", stored("Pezinok", (2024, 1.5, "accepted")))
    assert tax.rate_source("Pezinok", YEAR)[0] == 1.5


def test_a_later_years_rate_applies_from_that_year_only(monkeypatch):
    monkeypatch.setattr(tax, "_stored", stored("Senec", (YEAR + 1, 0.7, "scraped")))
    assert tax.rate_source("Senec", YEAR)[0] == 0.6
    assert tax.rate_source("Senec", YEAR + 1)[0] == 0.7
    assert tax.annual_tax(60, "Senec", YEAR + 1) == 42.0


def test_a_new_town_is_charged_its_stored_rate(monkeypatch):
    monkeypatch.setattr(tax, "_stored", stored("Šamorín", (2025, 0.85, "scraped")))
    rate, label = tax.rate_source("Šamorín")
    assert rate == 0.85 and "VZN" in label
    assert tax.annual_tax(59.5, "Šamorín") == round(60 * 0.85, 2)
    assert tax.rate_source("Samorin")[0] == 0.85          # written without diacritics


def test_a_zoned_towns_rates_are_never_replaced(monkeypatch):
    monkeypatch.setattr(tax, "_stored", stored("Košice", (YEAR + 1, 2.0, "accepted")))
    assert tax.rate_source("Košice - Terasa", YEAR + 1)[0] == 1.207


def test_a_town_zoned_by_street_is_confirmed_by_its_whole_table():
    # Zvolen's zone II rate is charged to no listing (its streets aren't
    # matched), yet the ordinance lists it: all three confirm the table.
    o = assess("Zvolen", reading([0.636, 0.588, 0.447], 2026))
    assert (o.status, o.store) == ("confirmed", [])
    assert assess("Čadca", reading([0.4, 0.25], 2026)).status == "confirmed"
    assert assess("Liptovský Mikuláš", reading([0.5, 0.3, 0.45], 2026)).status == "confirmed"


def test_the_table_reports_each_towns_own_rates():
    assert tax.table_rates("Bratislava") == [1.2, 1.25, 1.35]
    assert tax.table_rates("Žilina") == [1.1, 1.2]
    assert tax.table_rates("Zvolen") == [0.447, 0.588, 0.636]
    assert tax.table_rates("Pezinok") == [1.0]
    assert tax.table_rates("Šamorín") == []


# ── The button, end to end ────────────────────────────────────────────────────
SITES = {
    "Pezinok": [reading([1.0], 2024)],
    "Šamorín": [reading([0.85], 2025)],
    "Senec": [reading([0.6], YEAR), reading([0.7], YEAR + 1)],
    "Prešov": "blocked",
}


def fake_check(t, year, session=None, fetcher=None, **kw):
    site = SITES[t.name]
    if site == "blocked":
        return result(t.name, blocked="the site answered with a CAPTCHA or bot check instead "
                                      "of the page")
    return result(t.name, *site)


@pytest.fixture
def db(full_db, monkeypatch):
    import database
    monkeypatch.setattr(scr, "check_town", fake_check)
    monkeypatch.setattr(tax, "_stored", None)        # read what the test DB holds
    return database


def score(db, *listings):
    from modules.cashflow_runner import run_scoring
    for lid, district in listings:
        db.upsert_listing(make_listing(lid, district=district, price_eur=90_000.0, size_m2=60.0))
    run_scoring()


def tax_of(db, lid):
    conn = db.get_conn()
    try:
        r = conn.execute("SELECT property_tax_monthly FROM cashflow_scores WHERE listing_id=?",
                         (lid,)).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def test_one_click_stores_what_is_new_and_rescores_only_what_it_moves(db):
    score(db, ("s1", "Šamorín"), ("p1", "Pezinok"))
    assert tax_of(db, "s1") == round(60 * 1.35 / 12, 2)    # the fallback, before
    before_pezinok = tax_of(db, "p1")

    s = tr.update(only=["Pezinok", "Šamorín", "Senec", "Prešov"], year=YEAR)
    assert s["counts"] == {"confirmed": 1, "new": 1, "upcoming": 1, "blocked": 1}
    assert s["requeued"] == 1                               # Šamorín's flat only
    assert tax_of(db, "s1") is None and tax_of(db, "p1") == before_pezinok

    from modules.cashflow_runner import run_scoring
    run_scoring(market="sk")
    assert tax_of(db, "s1") == round(60 * 0.85 / 12, 2)

    rows = {r["town"]: r for r in tr.check_rows()}
    assert rows["Šamorín"]["status"] == "new" and rows["Šamorín"]["charged"] == 0.85
    assert rows["Prešov"]["status"] == "blocked"
    assert rows["Senec"]["charged"] == 0.6                 # 0.70 waits for its year
    line = tr.summary_text(s)
    assert "4 towns checked" in line and "Šamorín: 0.85 €/m²" in line


def test_a_second_run_finds_nothing_new(db):
    tr.update(only=["Šamorín"], year=YEAR)
    s = tr.update(only=["Šamorín"], year=YEAR)
    assert s["counts"] == {"confirmed": 1} and s["requeued"] == 0


def test_scoring_rereads_rates_stored_by_the_other_process(db):
    # The dashboard stores; the scheduler's scoring run, another process,
    # must still re-score at the new rate.
    score(db, ("s1", "Šamorín"))
    tr.record(tr.Outcome("Šamorín", "new", "", store=[(2025, 0.85, reading([0.85], 2025))]))
    tax._stored = {}                    # this process's stale view
    from modules.cashflow_runner import run_scoring
    run_scoring()
    assert tax_of(db, "s1") == round(60 * 0.85 / 12, 2)


def test_accepting_a_review_charges_it_over_the_table(db):
    SITES["Trnava"] = [reading([1.2], 2024)]
    try:
        assert tr.update(only=["Trnava"], year=YEAR)["counts"] == {"review": 1}
        assert tax.rate_source("Trnava")[0] == 1.0
        assert tr.accept("Trnava") is None
        assert tax.rate_source("Trnava")[0] == 1.2
        assert {r["town"]: r for r in tr.check_rows()}["Trnava"]["status"] == "applied"
        assert tr.revert("Trnava") == 1
        assert tax.rate_source("Trnava")[0] == 1.0
    finally:
        del SITES["Trnava"]


def test_several_rates_need_a_choice_and_a_zoned_town_cant_be_accepted(db):
    SITES["Komárno"] = [reading([0.4, 0.5], 2026)]
    SITES["Košice"] = [reading([1.3, 1.2, 1.1], 2026)]
    try:
        tr.update(only=["Komárno", "Košice"], year=YEAR)
        assert "choose" in tr.accept("Komárno")
        assert "not one of" in tr.accept("Komárno", 0.45)
        assert tr.accept("Komárno", 0.5) is None
        assert tax.rate_source("Komárno")[0] == 0.5
        assert "by hand" in tr.accept("Košice")
    finally:
        del SITES["Komárno"], SITES["Košice"]


def test_keeping_the_table_marks_the_review_done(db):
    SITES["Trnava"] = [reading([1.2], 2024)]
    try:
        tr.update(only=["Trnava"], year=YEAR)
        tr.keep("Trnava")
        row = {r["town"]: r for r in tr.check_rows()}["Trnava"]
        assert row["status"] == "kept" and row["charged"] == 1.0
    finally:
        del SITES["Trnava"]


def test_an_uploaded_ordinance_is_charged(db):
    from tests.test_tax_rate_scraper import _pdf
    pdf = _pdf("VZN schvalene dna 10.12.2025. Sadzba dane z bytov: a) 0,953 eur za byty. "
               "Toto VZN nadobuda ucinnost 1. januara 2026. " * 2)
    status, msg = tr.upload("Prešov", "presov-vzn.pdf", pdf, year=YEAR)
    assert status == "applied" and "0.953" in msg
    assert tax.rate_source("Prešov")[1].startswith("Prešov — uploaded")
    status, msg = tr.upload("Prešov", "scan.pdf", _pdf(""), year=YEAR)
    assert status == "error" and "scanned" in msg


def test_a_user_can_add_and_remove_a_town(db):
    assert "address" in tr.add_town("Senica", "senica.sk")
    assert "already" in tr.add_town("Senec", "https://www.senec.sk/")
    assert tr.add_town("Senica", "https://www.senica.sk/vzn/") is None
    assert tr.towns()["Senica"].start == ("https://www.senica.sk/vzn/",)
    SITES["Senica"] = [reading([0.55], 2026, kind="page")]
    try:
        tr.update(only=["Senica"], year=YEAR)
        assert tax.rate_source("Senica")[0] == 0.55
        tr.remove_town("Senica")
        assert "Senica" not in tr.towns() and tax.rate_source("Senica")[0] == 1.35
    finally:
        del SITES["Senica"]


def test_a_town_whose_check_fails_does_not_stop_the_others(db, monkeypatch):
    def boom(t, year, **kw):
        if t.name == "Pezinok":
            raise RuntimeError("broken page")
        return fake_check(t, year)
    monkeypatch.setattr(scr, "check_town", boom)
    s = tr.update(only=["Pezinok", "Šamorín"], year=YEAR)
    assert s["counts"] == {"not_found": 1, "new": 1}


@pytest.mark.parametrize("title, name", [
    ("VZN_17_2023.pdf 30.10.2025 (PDF, 4,96 MB)", "VZN_17_2023.pdf"),
    ("VZN č. 14 - 2022 Stiahnuť PDF, Veľkosť 6 MB", "VZN č. 14 - 2022"),
    ("VZN č. 10/2023 o miestnych daniach stiahnuť (4,34 MB) Platné znenie",
     "VZN č. 10/2023 o miestnych daniach"),
    ("https://www.kosice.sk/obcan/miestne-dane", "miestne-dane"),
    ("VZN o miestnych daniach a poplatku , otvorí sa v novom okne)", "VZN o miestnych daniach a poplatku"),
    ("súbor VZN 4_2025 o miestnych daniach Veľkosť a typ súboru /", "VZN 4_2025 o miestnych daniach"),
    ("Súbor: vzn-5-2025-dane-a-odpady.pdf Formát", "vzn-5-2025-dane-a-odpady.pdf"),
    ("Miestne dane :: Oficiálne stránky mesta Košice", "Miestne dane"),
    ("Miestne dane a poplatky | Dunajská Streda", "Miestne dane a poplatky"),
    ("VZN č. 8_2025 o miestnych daniach (DzN, pes, PA, NHP) 2. 2. 2026 · PDF · 5.23 MB",
     "VZN č. 8_2025 o miestnych daniach (DzN, pes, PA, NHP)"),
])
def test_document_names_drop_the_download_clutter(title, name):
    assert tr.doc_name(title) == name


def test_rates_read_as_written():
    assert [tr.rate_text(r) for r in (1.0, 0.85, 0.675, 1.2)] == ["1.00", "0.85", "0.675", "1.20"]


# ── The dashboard tab ─────────────────────────────────────────────────────────
def test_the_tab_shows_a_review_and_accepting_it_charges_it(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import database
    import os
    from modules import jobs
    monkeypatch.setattr(jobs, "_job", None)     # no other test's job on the page, nor this one's after
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    database.init_db()
    monkeypatch.setattr(tax, "_stored", None)
    tr.record(tr.assess(town("Pezinok"), result("Pezinok", reading([1.5], 2024)), YEAR))
    tr.record(tr.assess(town("Šamorín"), result("Šamorín", reading([0.85], 2025)), YEAR))
    app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    at = AppTest.from_file(app, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "TAX RATES" in [t.label for t in at.tabs]
    accept = [b for b in at.button if b.label == "Accept 1.50 €/m²"]
    assert accept and [b for b in at.button if b.label == "Keep the table's figure"]
    accept[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    tax.reload()
    assert tax.rate_source("Pezinok")[0] == 1.5
    assert jobs.wait(60).label == "CASHFLOW SCORE"      # it re-scores what moved


# ── Every Slovak municipality ─────────────────────────────────────────────────
MUNICIPALITIES = [
    scr.Municipality("Ivanka pri Dunaji", "Senec", "https://www.ivanka.sk", 7_000),
    scr.Municipality("Nová Ves", "Veľký Krtíš", "https://www.novaves.sk", 300),
    scr.Municipality("Porúbka", "Žilina", "https://www.porubkaza.sk", 1_200),
    scr.Municipality("Porúbka", "Humenné", "https://www.porubkahe.sk", 300),
    scr.Municipality("Senec", "Senec", "https://www.senec.sk", 21_000),     # in TOWNS
    scr.Municipality("Bez webu", "Senec", "", 100),
]


@pytest.fixture
def villages(db, monkeypatch):
    monkeypatch.setattr(scr, "municipalities", lambda session=None: list(MUNICIPALITIES))
    for name, rates in (("Ivanka pri Dunaji", [0.5]), ("Nová Ves", [0.1]),
                        ("Porúbka (okres Žilina)", [0.2]), ("Porúbka (okres Humenné)", [0.15])):
        SITES[name] = [reading(rates, 2026, kind="page")]
    yield
    for name in ("Ivanka pri Dunaji", "Nová Ves", "Porúbka (okres Žilina)",
                 "Porúbka (okres Humenné)"):
        SITES.pop(name, None)


def test_every_municipality_with_a_website_is_a_town_to_read(villages):
    assert tr.refresh_municipalities() == 6
    t = tr.towns()
    assert {"Ivanka pri Dunaji", "Nová Ves", "Porúbka (okres Žilina)",
            "Porúbka (okres Humenné)"} <= set(t)
    assert "Bez webu" not in t                      # nothing to read
    assert t["Senec"] is scr.TOWNS["Senec"]         # the table's town keeps its own start page
    assert t["Ivanka pri Dunaji"].start == ("https://www.ivanka.sk",)


def test_the_list_is_refreshed_once_a_month(villages, monkeypatch):
    tr.refresh_municipalities()
    calls = []
    monkeypatch.setattr(scr, "municipalities", lambda session=None: calls.append(1) or [])
    assert tr.refresh_municipalities() == 6 and calls == []
    tr.refresh_municipalities(force=True)
    assert calls == [1]


def test_a_village_is_charged_its_rate_and_shared_names_need_their_district(villages):
    tr.refresh_municipalities()
    tr.update(only=["Ivanka pri Dunaji", "Nová Ves", "Porúbka (okres Žilina)",
                    "Porúbka (okres Humenné)"], year=YEAR)
    assert tax.rate_source("Ivanka pri Dunaji")[0] == 0.5
    assert tax.rate_source("Nová Ves")[0] == 0.1
    # The village Nová Ves is not Spišská Nová Ves, which the table has.
    assert tax.rate_source("Spišská Nová Ves")[0] == 0.398
    assert tax.rate_source("Porúbka")[0] == tax.UNKNOWN_PLACE_RATE_PER_M2
    assert tax.rate_source("Porúbka, okres Žilina")[0] == 0.2
    assert tax.rate_source("Porúbka, Humenné")[0] == 0.15


def test_a_click_reads_the_listing_towns_and_the_villages_due(villages, db, monkeypatch):
    tr.refresh_municipalities()
    db.upsert_listing(make_listing("v1", district="Ivanka pri Dunaji"))
    monkeypatch.setattr(scr, "TOWNS", {"Pezinok": scr.TOWNS["Pezinok"]})
    # One site at a time, so `read` is the order the towns are taken in: with
    # 16 at once, a later town's thread could record itself first.
    monkeypatch.setattr(tr, "WORKERS", 1)
    read = []

    def check(t, year, **kw):
        read.append((t.name, kw.get("budget"), kw.get("stop_when_found")))
        return fake_check(t, year)
    monkeypatch.setattr(scr, "check_town", check)
    s = tr.update(year=YEAR)
    names = [n for n, _, _ in read]
    assert names[:2] == ["Pezinok", "Ivanka pri Dunaji"]       # the table's, then a listing's
    # Senec is an ordinary municipality here: TOWNS is cut to Pezinok.
    assert set(names) == {"Pezinok", "Ivanka pri Dunaji", "Nová Ves", "Porúbka (okres Žilina)",
                          "Porúbka (okres Humenné)", "Senec"}
    assert dict((n, (b, q)) for n, b, q in read)["Nová Ves"] == (12, True)   # a village: brief
    assert dict((n, (b, q)) for n, b, q in read)["Pezinok"][1] is False
    assert s["left"] == 0

    read.clear()
    tr.update(year=YEAR)                       # within the month: only the towns that always run
    assert sorted(n for n, _, _ in read) == ["Ivanka pri Dunaji", "Pezinok"]


def test_villages_that_dont_fit_in_the_time_wait_for_the_next_click(villages, monkeypatch):
    tr.refresh_municipalities()
    monkeypatch.setattr(scr, "TOWNS", {})
    SITES["Senec"] = [reading([0.6], 2026, kind="page")]
    try:
        s = tr.update(year=YEAR, time_budget_s=0)
        assert s["left"] == 5 and s["outcomes"] == []
        assert "5 more municipalities are due" in tr.summary_text(s)
        s = tr.update(year=YEAR)
        assert s["left"] == 0 and len(s["outcomes"]) == 5
    finally:
        SITES["Senec"] = [reading([0.6], YEAR), reading([0.7], YEAR + 1)]


def test_a_village_named_with_its_district_town_is_new_not_that_towns(villages):
    # "Brestov (okres Prešov)" once read as "was 0.953" — Prešov's rate.
    o = tr.assess(scr.Town("Brestov (okres Prešov)", ("https://brestov.sk",)),
                  result("Brestov (okres Prešov)", reading([0.06], 2024)), YEAR)
    assert o.status == "new" and "fallback" in o.message


# ── Housekeeping (review L7) ──────────────────────────────────────────────────
def test_each_towns_session_is_closed_once_it_is_read(db, monkeypatch):
    import requests
    sessions = []

    class Tracked(requests.Session):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def check(t, year, session=None, fetcher=None, **kw):
        sessions.append(session)
        assert not session.closed                   # open while the town is read
        return fake_check(t, year, session, fetcher, **kw)

    monkeypatch.setattr(requests, "Session", Tracked)
    monkeypatch.setattr(scr, "check_town", check)
    tr.update(only=["Pezinok", "Šamorín"], year=YEAR)
    assert len(sessions) == 2 and len({id(s) for s in sessions}) == 2
    assert all(s.closed for s in sessions)


def test_a_fetch_without_a_session_closes_the_one_it_opens(monkeypatch):
    import requests
    import config
    made = []

    class Tracked(requests.Session):
        closed = False

        def get(self, url, **kw):
            made.append(self)
            return "page"

        def close(self):
            self.closed = True

    monkeypatch.setattr(config, "SCRAPER_API_KEY", "", raising=False)
    monkeypatch.setattr(requests, "Session", Tracked)
    assert scr._get("https://obec.sk/dane") == "page"
    assert made and made[0].closed
    given = Tracked()
    scr._get("https://obec.sk/dane", session=given)
    assert not given.closed                         # the caller's stays open
