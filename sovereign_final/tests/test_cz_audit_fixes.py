"""Regression tests for the review of the Czech market: one or more per
finding, on synthetic text and synthetic listings only — no real výpis, no
personal data, no request leaves the test."""

import dataclasses
import gzip
import unicodedata
from datetime import datetime

import pytest

import markets
from engine import rent_comps_cz, rent_cz
from modules import lv_cz
from modules.lv_screen_cz import (
    owner_is_cooperative, screen_lv_cz, unit_numbers, unrecognised_entries,
)
from scraper import bezrealitky, rentals_cz
from scraper import cz_common as cz
from tests.conftest import make_listing
from tests.test_lv_cz import BANK_LIEN, HEAD, lv

PRIVATE_LIEN = ("  o Zástavní právo smluvní\n      Oprávnění pro Osoba Testovací, Testov, "
                "RČ/IČO: 000000/0000\n")


def status(text, lv_number=None, area=""):
    return lv_cz.check_text(text, lv_number, area)["status"]


# ── robots.txt ────────────────────────────────────────────────────────────────
def test_an_empty_rule_ends_its_group():
    for empty in ("Disallow:", "Allow:"):
        text = f"User-agent: *\n{empty}\n\nUser-agent: SomeBot\nDisallow: /\n"
        assert cz.Robots(text).allows("https://example.cz/prodam/byt/")


def test_a_bom_does_not_hide_the_first_group():
    for bom in ("﻿", "ï»¿"):
        assert not cz.Robots(bom + "User-agent: *\nDisallow: /\n").allows("https://x.cz/a")


def test_robots_txt_is_read_again_when_stale(monkeypatch):
    monkeypatch.setattr(cz, "_robots_cache", {})
    monkeypatch.setattr(cz, "_robots_expires", {})
    url = "https://r.example.cz/prodam/byt/"
    assert cz.robots_allows(url, lambda u: (429, ""))[0]           # missing: allowed …
    assert cz.robots_allows(url, lambda u: (200, "User-agent: *\nDisallow: /\n"))[0]
    clock = [cz.ROBOTS_MISSING_TTL_SEC + 1]
    import time
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + clock[0])
    # … for an hour; then read again, and the new rules hold.
    assert not cz.robots_allows(url, lambda u: (200, "User-agent: *\nDisallow: /\n"))[0]
    clock[0] += cz.ROBOTS_TTL_SEC - 60
    assert not cz.robots_allows(url, lambda u: (200, "User-agent: *\nAllow: /\n"))[0]
    clock[0] += 120                                                  # a day on: re-read
    assert cz.robots_allows(url, lambda u: (200, "User-agent: *\nAllow: /\n"))[0]


def test_robots_txt_bytes_are_read_as_utf8(monkeypatch):
    monkeypatch.setattr(cz, "_robots_cache", {})

    class R:                       # text/plain with no charset: requests reads Latin-1
        status_code = 200
        content = b"\xef\xbb\xbfUser-agent: *\nDisallow: /\n"
        text = content.decode("latin-1")
    monkeypatch.setattr("scraper._http.get", lambda u, timeout=15: R())
    assert not cz.robots_allows("https://bom.example.cz/x")[0]


# ── Listing text ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,excluded", [
    ("Prodám podíl na bytě 3+1", True), ("Prodej 1/2 podílu bytu 2+kk", True),
    ("Prodám 1/2 bytu 2+1 Praha", True), ("Prodej id. 1/2 bytu 3+1", True),
    ("Podíl 1/3 na bytě 2+1", True), ("Prodej bytu 2+kk, 1/2 podílu", True),
    ("Prodej bytu 2+1 včetně podílu na pozemku", False),
    ("Prodám byt s podílem 1/12 na pozemku", False),
    ("Byt 2+1 s 1/2 podílu na pozemku", False),
    ("Prodej bytu 3+1, 3/5 NP, Brno", False),
    ("Prodej 2+kk s garáží, Praha 5", False), ("Prodám 3+1 s parkovacím stáním", False),
    ("https://reality.bazos.cz/inzerat/1/prodej-2kk-s-garazi.php", False),
    ("Prodej garáže", True), ("Prodej rodinného domu", True),
])
def test_shares_and_layout_only_titles(title, excluded):
    assert cz.is_excluded_cz(title) is excluded


@pytest.mark.parametrize("text,amounts", [
    ("Prodám byt 2+1 52 m2 850 000 Kč, Most", [850_000.0]),
    ("rok 2010 450 000 Kč", [450_000.0]), ("byt 2+1 450 000 Kč", [450_000.0]),
    ("3 450 000 Kč", [3_450_000.0]), ("3.450.000 Kč", [3_450_000.0]),
    ("3 450 000,- Kč", [3_450_000.0]), ("cena 12 345 678 Kč", [12_345_678.0]),
])
def test_a_price_starts_a_number(text, amounts):
    assert cz.czk_amounts(text) == amounts


@pytest.mark.parametrize("text,cls", [
    ("K dispozici PENB a revize elektro.", "UNKNOWN"),
    ("energetická náročnost budovy a vytápění", "UNKNOWN"),
    ("Energetická náročnost budovy: Třída G - Mimořádně nehospodárná", "G"),
    ("energetické náročnosti budovy: B", "B"), ("PENB: C", "C"), ("PENB_C", "C"),
    ("energeticka narocnost budovy G – mimořádně nehospodárná", "G"),
])
def test_the_energy_class_is_a_capital_letter(text, cls):
    assert cz.energy_cz(text) == cls


def test_a_from_price_with_the_czech_dash_is_a_project():
    from database import detect_dev_project
    assert detect_dev_project("", "Byty od 3 990 000,- Kč", "cz") == 1
    assert detect_dev_project("", "Byt 2+kk 3 990 000,- Kč", "cz") == 0


def test_child_sitemaps_keep_to_the_host_and_robots(monkeypatch):
    monkeypatch.setattr(cz, "_robots_cache", {
        "https://www.bezrealitky.cz": cz.Robots("User-agent: *\nDisallow: /sitemap/x\n"),
        "https://api.bezrealitky.cz": cz.Robots("User-agent: *\nDisallow: /\n")})
    kids = ["https://api.bezrealitky.cz/sitemap/a.xml", "https://evil.example/b.xml",
            "https://www.bezrealitky.cz/sitemap/x-1.xml", "https://www.bezrealitky.cz/sitemap/c.xml.gz"]
    index = ("<sitemapindex>" + "".join(f"<sitemap><loc>{k}</loc></sitemap>" for k in kids)
             + "</sitemapindex>").encode()
    asked = []

    def fetch(u):
        asked.append(u)
        return (200, index) if u == bezrealitky.SITEMAP_INDEX else (200, gzip.compress(b"<urlset/>"))
    bezrealitky.walk_sitemap(None, fetch=fetch)
    assert asked == [bezrealitky.SITEMAP_INDEX, kids[3]]


# ── Places and rents ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,place", [
    ("Prodej bytu 2+kk, Praha - Vinohrady", "Praha"),
    ("Byt na Vinohradech, Praha", "Praha"),
    ("Prodej bytu v Táboře, Černovice blízko", "Tábor"),
    ("Prodej bytu Komín", ""),
    ("Prodej bytu v Brně na Žabovřeskách", "Brno - Žabovřesky"),
    ("Prodám byt Praha 2+kk", "Praha"), ("Byt Praha 7+1", "Praha"),
    ("Prodej bytu Praha, 5 minut od metra", "Praha"),
    ("Praha 2 - Vinohrady", "Praha 2"), ("v Praze 2", "Praha 2"), ("Praha-10", "Praha 10"),
    ("Pronájem 2+kk Praha-východ Úvaly", "Praha-východ"),
    ("Prodej bytu Šlapanice, Brno-venkov", "Brno-venkov"),
    ("Byt Plzeň-jih, Přeštice", "Plzeň-jih"), ("Ostrava-Poruba", "Ostrava"),
])
def test_place_names(text, place):
    assert cz.place_from_text(text) == place


@pytest.mark.parametrize("district,key", [
    ("Praha - východ", "praha-východ"), ("Praha – východ", "praha-východ"),
    ("Praha východ", "praha-východ"), ("Brno - venkov", "brno-venkov"),
    ("Plzeň-jih", "plzeň-jih"), ("Plzeň-sever", "plzeň-sever"),
    ("Říčany, Praha-východ", "říčany"), ("Plzeň-město", "plzeň"), ("Praha 7", "praha 7"),
])
def test_suburban_okresy_are_not_their_city(district, key):
    assert rent_cz.match_rent_key(district) == key
    assert rent_cz.baseline_rent(key) == rent_cz.RENT_PER_M2_CZ.get(key)


@pytest.mark.parametrize("text,rent", [
    ("Kauce: 30 000 Kč. Nájemné: 15 000 Kč.", 15_000),
    ("Vratná kauce: 30 000 Kč; nájem: 15 000 Kč", 15_000),
    ("Zálohy na služby: 4 000 Kč, nájem 14 000 Kč", 14_000),
    ("Nájem 15 000 Kč, služby 4 500 Kč/měs.", 15_000),
    ("Cena 15 000 Kč + 4 500 Kč měsíčně energie", 15_000),
    ("Nájem 15 000 Kč/měs. + služby 3 500 Kč", 15_000),
    ("3 000 Kč na energie, nájem 12 000 Kč", 12_000),
])
def test_rent_is_never_a_deposit_or_a_service_charge(text, rent):
    assert rentals_cz.rent_from_text(text) == rent


@pytest.mark.parametrize("text,whole_flat", [
    ("Pronájem bytu 2+kk, obývací pokoj s kuchyňským koutem", True),
    ("Byt má 3 pokoje", True), ("Pronájem bytu 3+1, dětský pokoj a ložnice", True),
    ("Pronájem pokoje 15 m2", False), ("Podnájem pokoje v bytě 3+1", False),
    ("Pokoj k pronájmu, Brno", False), ("Volný pokoj ve sdíleném bytě", False),
])
def test_a_flat_that_names_its_rooms_is_no_room_let(text, whole_flat):
    assert rent_comps_cz.is_long_term_flat(text) is whole_flat


def test_a_room_title_is_a_room_let():
    assert not rent_comps_cz.is_long_term_flat("Pokoj 15 m2, Praha 6", "Hezký pokoj.")


@pytest.mark.parametrize("text,kind", [
    ("Byt je k dispozici bez nábytku, nové sociální zařízení", "unfurnished"),
    ("Pronájem bytu 2+1, nové sociální zařízení", "unknown"),
    ("Kuchyňská linka zařízená spotřebiči, jinak prázdný byt", "unknown"),
    ("Pronájem bytu 2+kk, zařízená kuchyň", "unknown"),
    ("Zařízený byt 2+kk, sociální zařízení nové", "furnished"),
])
def test_fittings_are_not_furniture(text, kind):
    assert rent_comps_cz.furnishing_from_text(text) == kind


# ── The LV screen ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sep", [" ", "\v", " "])
def test_a_vypis_pasted_as_one_line_is_still_read(sep):
    text = lv(PRIVATE_LIEN, "  o Zahájení exekuce\n").replace("\n", sep)
    assert status(text) == "REJECT"


def test_a_lien_after_a_listina_line_is_a_new_lien():
    part_c = ("  o Zástavní právo smluvní\n      Oprávnění pro Testovací banka, a.s.\n"
              "      Listina Smlouva o zřízení zástavního práva V-1234/2020-101\n"
              "  o Předkupní právo\n      Oprávnění pro Město Testov, Náměstí 1\n"
              "      Listina Kupní smlouva V-2/2020-101\n"
              "  o Zástavní právo smluvní\n      ve prospěch Osoba Testovací, Testov\n")
    assert status(lv(part_c)) == "REJECT"
    assert status(lv(part_c).replace("\n", " ")) == "REJECT"
    ban = ("  o Zástavní právo smluvní\n      Oprávnění pro Testovací banka, a.s.\n"
           "      Listina Smlouva zástavní V-555/2021-101\n"
           "  o Zákaz zcizení nebo zatížení\n      ve prospěch Osoba Testovací, Testov\n")
    assert status(lv(ban)) == "REJECT"
    # The bank lien's own Listina line still only refers back to it.
    assert status(lv(BANK_LIEN)) == "PASS"


def test_no_part_c_is_never_clean():
    assert status("Byt 2+1, Praha 2, cena 5 mil.", "1234") == "UNVERIFIED"
    page1 = HEAD.replace("B1 Věcná práva sloužící ve prospěch nemovitostí v části B\n"
                         "  o Věcné břemeno užívání bytu\n     Oprávnění pro Jednotka č. 101/5\n",
                         "")
    r = lv_cz.check_text(page1, "1234")
    assert r["status"] == "UNVERIFIED" and "no part C" in r["detail"]


def test_claude_may_not_clear_a_text_without_part_c():
    from modules.llm_enrichment import lv_text_for_claude
    assert lv_text_for_claude(lv(), market="cz")[1] is True
    assert lv_text_for_claude(HEAD, market="cz")[1] is False


@pytest.mark.parametrize("part_c,part_d", [
    ("  Bez zápisu\n", "  o Předběžné opatření\n      zákaz nakládat s nemovitostí\n"),
    ("  Bez zápisu\n", "  o Rozhodnutí o zajištění nemovité věci v trestním řízení\n"),
    ("  Bez zápisu\n", "  o Soupis nemovité věci do majetkové podstaty\n"),
    ("  Bez zápisu\n", "  o Schválení oddlužení\n"),
    ("  Bez zápisu\n", "  o Dražební vyhláška\n"),
    ("  o Nájemní právo\n      do 31.12.2060\n", "  Bez zápisu\n"),
    ("  o Výhrada vlastnického práva\n", "  Bez zápisu\n"),
    ("  o Výhrada práva lepšího kupce\n", "  Bez zápisu\n"),
    ("  o Pacht\n", "  Bez zápisu\n"),
    ("  o Užívací právo\n", "  Bez zápisu\n"),
])
def test_more_burdens_block(part_c, part_d):
    assert status(lv(part_c, part_d)) == "REJECT"


def test_an_entry_the_screen_does_not_know_is_never_clean():
    text = lv("  o Správa svěřenského fondu\n      Oprávnění pro Osoba Testovací\n")
    assert unrecognised_entries(text) == ["Správa svěřenského fondu"]
    r = lv_cz.check_text(text)
    assert r["status"] == "UNVERIFIED" and "Správa svěřenského fondu" in r["detail"]
    assert unrecognised_entries(lv(BANK_LIEN)) == []


def test_a_lifetime_easement_after_a_utility_one_is_its_own_entry():
    part_c = ("  o Věcné břemeno vedení a údržby kanalizační přípojky\n"
              "      Oprávnění pro Obec Testov\n"
              "      Listina Smlouva o zřízení věcného břemene. POLVZ:12/1996\n"
              "  o Předkupní právo\n      Oprávnění pro Obec Testov\n"
              "      Listina Smlouva kupní POLVZ:13/1996\n"
              "  o Věcné břemeno doživotního užívání bytu\n"
              "      Oprávnění pro Osoba Testovací\n")
    assert status(lv(part_c)) == "REJECT"
    assert status(lv(part_c.split("  o Předkupní")[0])) == "PASS"      # the utility one alone


@pytest.mark.parametrize("text,coop", [
    ("Prodej členského podílu v bytovém družstvu, byt 2+1, Praha 4", True),
    ("Převod podílu v bytovém družstvu. Byt 3+1.", True),
    ("Prodej bytu 2+1 (družstevní)", True),
    ("Byt byl převeden z družstevního do osobního vlastnictví", False),
    ("Dříve družstevní, nyní osobní vlastnictví", False),
    ("Vlastnictví: osobní. Dům spravuje bytové družstvo.", False),
])
def test_cooperative_wording(text, coop):
    assert lv_cz.is_cooperative(text) is coop


def test_a_cooperative_owner_in_part_a_is_never_clean(full_db):
    import database as db
    db.upsert_listing(make_listing("cz9", market="cz", currency="CZK",
                                   description="Vlastnictví: osobní."))
    vypis = lv().replace("Vlastník Testovací, Testovací 1", "Bytové družstvo Testov, Testovací 1")
    assert owner_is_cooperative(vypis) and not owner_is_cooperative(lv())
    db.set_lv_document("cz9", vypis)
    assert lv_cz.check_listing(db.get_lv_row("cz9"))["status"] == "UNVERIFIED"


@pytest.mark.parametrize("creditor,blocking", [
    ("Monetal Invest s.r.o.", True), ("ČSOB Leasing, a.s.", True),
    ("MONETA Auto, s.r.o.", True), ("UniCredit Leasing CZ, a.s.", True),
    ("Raiffeisen - Leasing, s.r.o.", True), ("Wüstenrot pojišťovna a.s.", True),
    ("Spořitelní družstvo Testov", True),
    ("MONETA Money Bank, a.s.", False), ("Komerční banka, a.s.", False),
    ("Raiffeisenbank a.s.", False), ("Wüstenrot - stavební spořitelna a.s.", False),
    ("mBank S.A.", False), ("Státní fond podpory investic", False),
])
def test_only_a_bank_clears_a_lien(creditor, blocking):
    part_c = f"  o Zástavní právo smluvní\n      Oprávnění pro {creditor}, RČ/IČO: 0\n"
    assert [e["blocking"] for e in screen_lv_cz(lv(part_c))] == [blocking]


def test_distress_on_a_shared_lv_still_rejects():
    head = HEAD.replace("Jednotka č. 101/5 byt", "Jednotka č. 101/5 byt\n  Jednotka č. 101/25 garáž")
    assert status(lv(part_d="  o Zahájení exekuce\n", head=head)) == "REJECT"
    assert status(lv(part_d="  o Rozhodnutí o úpadku\n", head=head)) == "REJECT"
    assert status(lv(PRIVATE_LIEN, head=head)) == "UNVERIFIED"        # may be the garage's


def test_units_are_counted_in_part_b_only():
    text = lv(PRIVATE_LIEN + "      Povinnost k Jednotka: č. 101/5\n").replace(
        "V-99/2015-101", "Prohlášení vlastníka, jednotka č. 101/1 V-99/2015-101")
    assert unit_numbers(text) == {"101/5"} and status(text) == "REJECT"


def test_a_holder_name_ends_at_its_line():
    part_c = ("  o Předkupní právo\n      Oprávnění pro Osoba Testovací\n"
              "      Listina Rozsudek Krajského soudu v Testově V-77/2019-101\n")
    assert status(lv(part_c)) == "REJECT"
    company = "  o Předkupní právo\n      Oprávnění pro Krajská nemocnice Testov, a.s.\n"
    assert status(lv(company)) == "REJECT"


def test_the_same_lv_number_in_another_ku_is_another_property():
    text = lv().replace("Katastrální území: Testov",
                        "Kat.území: 727440 Žižkov    List vlastnictví: 1234")
    assert status(text, "1234", "Vinohrady") == "UNVERIFIED"
    assert status(text, "1234", "727441") == "UNVERIFIED"
    for same in ("Žižkov", "k.ú. Žižkov", "727440", ""):
        assert status(text, "1234", same) == "PASS"


def test_a_decomposed_vypis_reads_as_composed(full_db):
    import database as db
    nfd = unicodedata.normalize("NFD", lv(PRIVATE_LIEN))
    r = lv_cz.check_text(nfd, "1234")
    assert r["status"] == "REJECT" and "LV 1234" in r["detail"]
    db.upsert_listing(make_listing("cz8", market="cz", currency="CZK"))
    db.set_lv_document("cz8", nfd)
    assert db.get_lv_document("cz8") == unicodedata.normalize("NFC", nfd).strip()


def test_slovak_screen_is_unchanged_by_the_czech_flag():
    from modules.lv_screen import SK_VOCABULARY
    assert SK_VOCABULARY.reference_needs_same_entry is False


# ── Scheduler ─────────────────────────────────────────────────────────────────
def test_the_scheduler_starts_on_a_fresh_database(tmp_path, monkeypatch):
    import database
    import scheduler
    from modules import pipeline_state
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "status.json"))
    monkeypatch.setattr(scheduler, "LAST_RUN_FILE", str(tmp_path / "last_run.txt"))
    ran = []
    monkeypatch.setattr(scheduler, "run_pipeline", lambda **kw: ran.append(kw) or True)
    assert scheduler.run_all_markets(trigger="catch-up", which=["sk"]) == {"sk": True}
    assert ran


def test_a_retry_waits_for_this_process_s_own_run(monkeypatch):
    import scheduler
    asked = []
    monkeypatch.setattr(scheduler, "due_markets", lambda now, kind: asked.append(kind) or [])
    with scheduler._RUN_GUARD:
        scheduler.retry_failed_run()                 # the 06:00 run holds it: no-op
    assert asked == []
    scheduler.retry_failed_run()
    assert asked == ["retry"]


# ── Dashboard ─────────────────────────────────────────────────────────────────
def _app(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    import database
    from modules import pipeline_state
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setattr(pipeline_state, "STATUS_FILE", str(tmp_path / "status.json"))
    database.init_db()
    now = datetime.now().astimezone().isoformat()
    database.upsert_listing(make_listing("cz1", district="Praha 2", price_eur=4_500_000.0,
                                         size_m2=55.0, title="Byt 2+kk, Praha 2",
                                         source="sreality", url="https://example.cz/cz1",
                                         market="cz", last_seen_at=now, scraped_at=now))
    return database


def _run(open_cards=(), view=None):
    import os
    from streamlit.testing.v1 import AppTest
    app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    at = AppTest.from_file(app, default_timeout=120)
    at.session_state["pending_list"] = True
    for lid in open_cards:
        at.session_state[f"card_{lid}"] = True
    at = at.run()
    if view:
        next(r for r in at.radio if r.key == "market_view").set_value(view).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def _no_jobs(monkeypatch):
    yield
    from modules import jobs
    jobs.wait(60)
    monkeypatch.setattr(jobs, "_job", None)


def _score(price, rent):
    from database import upsert_cashflow
    from engine import financial as fin
    r = fin.analyse(price, 55.0, "Praha 2", listing_id="cz1", rent_override=rent, market="cz")
    row = fin.result_to_db_dict(r)
    row.update(fin.deal_extras(r))
    upsert_cashflow(row)


@pytest.mark.parametrize("threshold,flagged", [(10_000_000.0, True), (-10_000_000.0, False)])
def test_the_dashboard_flags_cash_flow_in_crowns(tmp_path, monkeypatch, _no_jobs,
                                                  threshold, flagged):
    _app(tmp_path, monkeypatch)
    monkeypatch.setitem(markets.MARKETS, "cz",
                        dataclasses.replace(markets.CZ, cashflow_min_surplus=threshold))
    _score(4_500_000.0, 22_000)
    at = _run(open_cards=("cz1",), view="🇨🇿 Czechia")
    md = "\n".join(m.value for m in at.markdown)
    assert ("CASH-FLOW NEGATIVE" in md) is flagged


def test_one_click_close_names_czech_lawyers_for_a_czech_flat(tmp_path, monkeypatch, _no_jobs):
    _app(tmp_path, monkeypatch)
    at = _run(view="🇨🇿 Czechia")
    md = "\n".join(m.value for m in at.markdown)
    assert "Slovak notár" not in md and "Czech advokát or notář" in md


def test_what_if_claims_no_rent_it_did_not_use(tmp_path, monkeypatch, _no_jobs):
    db = _app(tmp_path, monkeypatch)
    db.upsert_listing(make_listing("cz2", district="Plzeň", price_eur=3_000_000.0, size_m2=60.0,
                                   title="Byt 2+1, Plzeň", market="cz",
                                   url="https://example.cz/cz2"))
    at = _run(view="🇨🇿 Czechia")
    pick = next(s for s in at.selectbox if s.key == "wi_pick")
    pick.set_value(next(o for o in pick.options if "Plzeň" in o)).run()
    captions = [c.value for c in at.caption]
    assert not any("National default rent" in c or "for 'default'" in c for c in captions)


def test_a_rejected_czech_flat_takes_a_new_vypis(tmp_path, monkeypatch, _no_jobs):
    db = _app(tmp_path, monkeypatch)
    from modules.debt_bot import reverify
    db.set_lv_document("cz1", lv(PRIVATE_LIEN))
    assert reverify("cz1")["status"] == "REJECT"
    at = _run(view="🇨🇿 Czechia")
    box = next(t for t in at.text_area if t.key == "rej_doc_cz1")
    assert "Osoba Testovací" in box.value
    box.set_value(lv(BANK_LIEN))
    next(b for b in at.button if b.key == "rej_rv").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert db.get_lv_document("cz1") == lv(BANK_LIEN).strip()
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT lv_status FROM listings WHERE id='cz1'").fetchone()[0] == "PASS"
    finally:
        conn.close()


# ── The memo ──────────────────────────────────────────────────────────────────
def test_the_czech_memo_caveat_follows_the_median(monkeypatch):
    from modules import memo
    said = []
    monkeypatch.setattr(memo._Memo, "para", lambda self, text, *a, **k: said.append(text))
    base = {"id": "cz1", "title": "Byt", "district": "Most", "price_eur": 1_200_000.0,
            "size_m2": 55.0, "market": "cz", "currency": "CZK"}
    for median, words in ((None, "no Czech regional price median"),
                          (30_000.0, "judged against the regional median")):
        said.clear()
        try:
            memo.build_memo_pdf({**base, "regional_median_m2": median})
        except Exception:
            pass
        caveat = next((t for t in said if t.startswith("Rent, market value")), "")
        assert words in caveat, caveat
