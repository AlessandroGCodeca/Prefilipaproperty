"""The Czech LV check (modules/lv_screen_cz, lv_cz, cuzk_cz) on synthetic
výpisy and synthetic cadastre answers: no real LV contents, no personal data,
no request leaves the test."""

import pytest

from modules import cuzk_cz, debt_bot, lv_cz
from modules.lv_screen_cz import (
    lv_number_in, part_c_start, screen_lv_cz, unit_numbers,
)
from tests.conftest import make_listing

HEAD = """Výpis z katastru nemovitostí
LIST VLASTNICTVÍ: 1234
Katastrální území: Testov
A Vlastník, jiný oprávněný
  Vlastník Testovací, Testovací 1, Testov
B Nemovitosti
  Jednotka č. 101/5 byt
B1 Věcná práva sloužící ve prospěch nemovitostí v části B
  o Věcné břemeno užívání bytu
     Oprávnění pro Jednotka č. 101/5
"""
C = "C Věcná práva zatěžující nemovitosti v části B včetně souvisejících údajů\n Typ vztahu\n"
D = "D Poznámky a další obdobné údaje\n"
E = ("E Nabývací tituly a jiné podklady zápisu\n"
     " Listina Usnesení soudního exekutora o udělení příklepu V-99/2015-101\n")


def lv(part_c="  Bez zápisu\n", part_d="  Bez zápisu\n", head=HEAD):
    return head + C + part_c + D + part_d + E


BANK_LIEN = """  o Zástavní právo smluvní
      k zajištění pohledávky ve výši 2 400 000 Kč
      Oprávnění pro Testovací banka, a.s., Testovací 33, Testov, RČ/IČO: 00000000
      Povinnost k Jednotka: č. 101/5
      Listina Smlouva o zřízení zástavního práva podle obč.z. V-1234/2020-101
  o Zákaz zcizení nebo zatížení
      Oprávnění pro Testovací banka, a.s., RČ/IČO: 00000000
"""


def flags(text):
    return [(e["flag"], e["blocking"]) for e in screen_lv_cz(text)]


# ── The screen ────────────────────────────────────────────────────────────────
def test_a_clean_lv_has_nothing():
    assert flags(lv()) == []


def test_a_bank_lien_and_its_ban_on_sale_do_not_block():
    assert flags(lv(BANK_LIEN)) == [("zástavní právo", False), ("zákaz zcizení", False)]


@pytest.mark.parametrize("creditor", ["UniCredit Bank Czech Republic, a.s.",
                                      "Stavební spořitelna Testov, a.s.",
                                      "Moneta Money Bank, a.s."])
def test_banks_by_word_or_by_name(creditor):
    part_c = f"  o Zástavní právo smluvní\n      Oprávnění pro {creditor}, RČ/IČO: 0\n"
    assert flags(lv(part_c)) == [("zástavní právo", False)]


def test_a_private_lien_blocks():
    part_c = ("  o Zástavní právo smluvní\n      Oprávnění pro Osoba Testovací, Testov, "
              "RČ/IČO: 000000/0000\n      Povinnost k Jednotka: č. 101/5\n")
    assert flags(lv(part_c)) == [("zástavní právo", True)]


def test_a_bank_named_in_another_entry_clears_nothing():
    part_c = (BANK_LIEN + "  o Zástavní právo smluvní\n      Oprávnění pro Osoba "
              "Testovací, RČ/IČO: 0\n")
    assert ("zástavní právo", True) in flags(lv(part_c))


@pytest.mark.parametrize("part_c,part_d,flag", [
    ("  o Zástavní právo exekutorské\n   Oprávnění pro Testovací banka, a.s.\n",
     "  o Zahájení exekuce\n", "exekuce"),
    ("  Bez zápisu\n", "  o Rozhodnutí o úpadku\n   Krajský soud v Testově\n", "insolvence"),
    ("  Bez zápisu\n", "  o Poznámka spornosti zápisu\n", "soudní spor"),
    ("  o Nařízení výkonu rozhodnutí prodejem nemovitosti\n", "  Bez zápisu\n",
     "výkon rozhodnutí"),
    ("  o Zástavní právo soudcovské\n   Oprávnění pro Testovací banka, a.s.\n",
     "  Bez zápisu\n", "zástavní právo z rozhodnutí"),
])
def test_distress_always_blocks_even_beside_a_bank(part_c, part_d, flag):
    found = screen_lv_cz(lv(part_c, part_d))
    hit = [e for e in found if e["flag"] == flag]
    assert hit and all(e["blocking"] and e["kind"] == "distress" for e in hit)


@pytest.mark.parametrize("entry,blocking", [
    ("  o Věcné břemeno doživotního užívání bytu\n   Oprávnění pro Osoba Testovací\n", True),
    ("  o Služebnost užívání bytu\n   Oprávnění pro Osoba Testovací\n", True),
    ("  o Věcné břemeno zřizování a provozování vedení\n   Oprávnění pro Distributor, a.s.\n", False),
    ("  o Věcné břemeno chůze a jízdy\n   Oprávnění pro Parcela 12/3\n", False),
    ("  o Věcné břemeno\n   Oprávnění pro Osoba Testovací\n", True),     # kind unknown
    ("  o Předkupní právo\n   Oprávnění pro Město Testov, Náměstí 1\n", False),
    ("  o Předkupní právo\n   Oprávnění pro Osoba Testovací\n", True),
    ("  o Výhrada zpětné koupě\n   Oprávnění pro Osoba Testovací\n", True),
    ("  o Výměnek\n   Oprávnění pro Osoba Testovací\n", True),
])
def test_easements_and_rights_are_tiered(entry, blocking):
    found = screen_lv_cz(lv(entry))
    assert found and found[0]["blocking"] is blocking
    if not blocking:
        assert found[0]["tier"] == "soft"


def test_a_lifetime_use_easement_is_one_entry():
    found = screen_lv_cz(lv("  o Věcné břemeno doživotního užívání bytu\n"))
    assert [e["flag"] for e in found] == ["věcné břemeno"]


def test_notes_and_plombs_are_soft_flags():
    part_d = "  o Poznámka o uzavření smlouvy\n"
    head = HEAD.replace("B Nemovitosti", "Nemovitost je dotčena změnou práv - Plomba "
                                         "V-555/2026\nB Nemovitosti")
    found = screen_lv_cz(lv(part_d=part_d, head=head))
    assert {(e["flag"], e["tier"], e["blocking"]) for e in found} == {
        ("poznámka", "soft", False), ("plomba", "soft", False)}


def test_parts_b1_and_e_are_not_burdens():
    # B1 has an easement in the flat's favour, E an exekutor's auction deed.
    assert flags(lv()) == []
    assert "exekutor" in lv() and "Věcné břemeno" in lv()


def test_without_headings_the_whole_text_is_read():
    text = "Zástavní právo smluvní Oprávnění pro Osoba Testovací, RČ: 0"
    assert flags(text) == [("zástavní právo", True)]
    assert part_c_start(text) is None


def test_lv_number_and_units():
    assert lv_number_in(HEAD) == "1234"
    assert unit_numbers(HEAD) == {"101/5"}
    assert part_c_start(lv()) is not None


def test_soft_flags_reject_when_configured(monkeypatch):
    from modules import lv_screen
    monkeypatch.setattr(lv_screen, "LV_SOFT_FLAGS_REJECT", True)
    found = screen_lv_cz(lv("  o Předkupní právo\n   Oprávnění pro Město Testov\n"))
    assert found[0]["blocking"] is True


# ── The verdict on a pasted výpis ─────────────────────────────────────────────
def test_check_text_verdicts():
    assert lv_cz.check_text(lv(BANK_LIEN))["status"] == "PASS"
    clean = lv_cz.check_text(lv(), "1234")
    assert clean["status"] == "PASS" and clean["detail"].startswith("LV 1234: Clean title")
    assert clean["market"] == "cz"
    bad = lv_cz.check_text(lv("  o Zástavní právo smluvní\n   Oprávnění pro Osoba X, RČ: 0\n"))
    assert bad["status"] == "REJECT" and bad["claude_may_clear"] is True
    distress = lv_cz.check_text(lv(part_d="  o Zahájení exekuce\n"))
    assert distress["status"] == "REJECT" and distress["claude_may_clear"] is False


def test_a_vypis_of_another_lv_is_not_the_flats():
    r = lv_cz.check_text(lv(), "999")
    assert r["status"] == "UNVERIFIED" and "LV 1234" in r["detail"] and "LV 999" in r["detail"]


def test_a_shared_lv_does_not_reject():
    head = HEAD.replace("Jednotka č. 101/5 byt", "Jednotka č. 101/5 byt\n  Jednotka č. 101/6 byt")
    r = lv_cz.check_text(lv("  o Zástavní právo smluvní\n   Oprávnění pro Osoba X, RČ: 0\n",
                            head=head))
    assert r["status"] == "UNVERIFIED" and "2 units" in r["detail"]


@pytest.mark.parametrize("text,coop", [
    ("Vlastnictví: družstevní. Byt 2+1.", True),
    ("Prodej družstevního bytu 3+1", True),
    ("Převod členských práv a povinností v družstvu", True),
    ("Vlastnictví: osobní. Dům spravuje bytové družstvo.", False),
])
def test_cooperative_flats(text, coop):
    assert lv_cz.is_cooperative(text) is coop


# ── check_listing, through the database ──────────────────────────────────────
@pytest.fixture
def cz_row(full_db):
    import database as db
    db.upsert_listing(make_listing("cz1", market="cz", currency="CZK", district="Praha 2",
                                   description="Vlastnictví: osobní."))
    return db.get_lv_row("cz1")


def test_a_pasted_vypis_decides(cz_row, monkeypatch):
    import database as db
    monkeypatch.delenv("CZ_CUZK_API_KEY", raising=False)
    r = lv_cz.check_listing(cz_row)
    assert r["status"] == "UNVERIFIED" and "Paste the flat's výpis" in r["detail"]
    db.set_lv_document("cz1", lv(BANK_LIEN))
    assert lv_cz.check_listing(cz_row)["status"] == "PASS"
    db.set_lv_document("cz1", lv("  o Zástavní právo smluvní\n   Oprávnění pro Osoba X, RČ: 0\n"))
    assert lv_cz.check_listing(cz_row)["status"] == "REJECT"
    db.set_lv_document("cz1", "  ")                   # blank removes it
    assert db.get_lv_document("cz1") is None


def test_a_cooperative_flat_is_never_clean(full_db):
    import database as db
    db.upsert_listing(make_listing("cz2", market="cz", currency="CZK",
                                   description="Vlastnictví: družstevní."))
    db.set_lv_document("cz2", lv(BANK_LIEN))
    r = lv_cz.check_listing(db.get_lv_row("cz2"))
    assert r["status"] == "UNVERIFIED" and "družstevní" in r["detail"]


def test_the_store_records_a_czech_verdict(cz_row, full_db):
    import database as db
    db.set_lv_document("cz1", lv(BANK_LIEN))
    r = debt_bot._check_and_store(cz_row)
    assert r["status"] == "PASS"
    conn = full_db()
    assert conn.execute("SELECT lv_status FROM listings WHERE id='cz1'").fetchone()[0] == "PASS"
    conn.close()


def test_the_building_under_the_pin(full_db, monkeypatch):
    import database as db
    db.upsert_listing(make_listing("cz3", market="cz", currency="CZK",
                                   district="Praha 2 - Vinohrady", lat=50.075, lng=14.44))
    conn = full_db()
    conn.execute("UPDATE listings SET coords_source='listing' WHERE id='cz3'")
    conn.commit()
    conn.close()
    monkeypatch.setenv("CZ_CUZK_API_KEY", "test-key")
    building = {"lv_no": 777, "ku_name": "Vinohrady", "ku_code": 727181, "house_numbers": ["1234"],
                "part_of_town": "Vinohrady", "municipality": "Praha", "units": [1, 2, 3],
                "unit_ids": {}, "parcel_no": "2345/1", "pending": ["V-555/2026"]}
    monkeypatch.setattr(cuzk_cz, "building_at_pin",
                        lambda lat, lng: {"status": "OK", "building": building, "detail": ""})
    r = debt_bot._check_and_store(db.get_lv_row("cz3"))
    assert r["status"] == "UNVERIFIED"
    assert "building LV 777" in r["detail"] and "V-555/2026" in r["detail"]
    row = db.get_lv_row("cz3")
    assert (row["cadastral_area"], row["cadastral_number"], row["plot_lv_number"]) == (
        "Vinohrady", "2345/1", "777")
    # A pin in another town finds nothing for this listing.
    monkeypatch.setattr(cuzk_cz, "building_at_pin", lambda lat, lng: {
        "status": "OK", "detail": "",
        "building": {**building, "municipality": "Brno", "part_of_town": "Žabovřesky",
                     "ku_name": "Žabovřesky"}})
    r = lv_cz.check_building(db.get_lv_row("cz3") | {"lv_number": None})
    assert r["status"] == "UNVERIFIED" and "not Praha 2 - Vinohrady" in r["detail"]


def test_claude_reads_a_czech_lv_with_the_czech_prompt(monkeypatch):
    seen = {}

    def fake(text, market="sk"):
        seen["market"] = market
        return {"risk_level": "LOW", "is_safe_to_proceed": True, "flags": [], "summary": "ok"}
    monkeypatch.setattr(debt_bot, "claude_enabled", lambda: True)
    monkeypatch.setattr(debt_bot, "claude_analyze_lv", fake)
    r = debt_bot._decide_lv(lv_cz.check_text(lv(part_d="  o Zahájení exekuce\n")))
    assert seen["market"] == "cz"
    assert r["status"] == "REJECT" and "exekuce / insolvence" in r["detail"]


def test_the_czech_prompt_and_excerpt(monkeypatch):
    from modules import llm_enrichment as llm
    from kataster_scraper import LV_TEXT_MAX_CHARS
    long_text = HEAD + "x" * (LV_TEXT_MAX_CHARS + 10) + "\n" + C + BANK_LIEN + D + E
    text, whole = llm.lv_text_for_claude(long_text, market="cz")
    assert whole                                  # a pasted výpis is never cut
    assert text.count("x") < LV_TEXT_MAX_CHARS and "Zástavní právo smluvní" in text
    asked = {}
    monkeypatch.setattr(llm, "_ask_json", lambda system, user, schema, **kw: asked.update(
        system=system, user=user))
    llm.analyze_lv(lv(BANK_LIEN), market="cz")
    assert asked["system"] is llm._LV_SYSTEM_CZ and "Zástavní právo" in asked["user"]
    llm.analyze_lv("LV text", )
    assert asked["system"] is llm._LV_SYSTEM


# ── The cadastre client ──────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


def test_api_kn_needs_a_key(monkeypatch):
    monkeypatch.delenv("CZ_CUZK_API_KEY", raising=False)
    assert cuzk_cz.building_at_address(1)["status"] == "NO_KEY"
    assert cuzk_cz.building_at_pin(50.0, 14.0)["status"] == "NO_KEY"


@pytest.mark.parametrize("status,body,want", [
    (200, {"data": {"id": 1}}, "OK"),
    (200, {"data": None, "zpravy": [{"text": "Nenalezeno"}]}, "NOT_FOUND"),
    (404, None, "NOT_FOUND"),
    (429, None, "ERROR"),
    (401, None, "ERROR"),
])
def test_api_kn_answers(monkeypatch, status, body, want):
    monkeypatch.setenv("CZ_CUZK_API_KEY", "test-key")
    asked = {}

    def fake(url, params=None, headers=None):
        asked.update(url=url, headers=headers)
        return _Resp(status, body)
    monkeypatch.setattr(cuzk_cz, "_http_get", fake)
    assert cuzk_cz.building_at_address(25133616)["status"] == want
    assert asked["url"].endswith("/api/v1/Stavby/AdresniMisto/25133616")
    assert asked["headers"]["ApiKey"] == "test-key"


def test_summarize_building():
    stavba = {"lv": {"cislo": 777, "katastralniUzemi": {"kod": 727181, "nazev": "Vinohrady"}},
              "cislaDomovni": [1234], "castObce": {"nazev": "Vinohrady"}, "obec": {"nazev": "Praha"},
              "jednotky": [{"id": 9, "cisloJednotky": 1}, {"id": 10, "cisloJednotky": 2}],
              "parcely": [{"kmenoveCisloParcely": 2345, "poddeleniCislaParcely": 1}],
              "rizeniPlomby": [{"typRizeni": "V", "poradoveCislo": 555, "rok": 2026}]}
    b = cuzk_cz.summarize_building(stavba)
    assert (b["lv_no"], b["ku_name"], b["ku_code"]) == (777, "Vinohrady", 727181)
    assert b["units"] == [1, 2] and b["unit_ids"] == {1: 9, 2: 10}
    assert b["parcel_no"] == "2345/1" and b["pending"] == ["V-555/2026"]
    assert cuzk_cz.summarize_building(None)["units"] == []


def test_the_nearest_address_point(monkeypatch):
    body = {"features": [
        {"attributes": {"KOD": 2}, "geometry": {"x": 14.4410, "y": 50.0760}},
        {"attributes": {"KOD": 1}, "geometry": {"x": 14.4401, "y": 50.0751}},
    ]}
    asked = {}

    def fake(url, params=None, headers=None):
        asked.update(url=url, params=params)
        return _Resp(200, body)
    monkeypatch.setattr(cuzk_cz, "_http_get", fake)
    r = cuzk_cz.address_point_near(50.075, 14.44)
    assert r == {"status": "OK", "kod": 1, "attributes": {"kod": 1}}
    assert asked["params"]["inSR"] == 4326 and asked["url"].endswith("/MapServer/1/query")
    monkeypatch.setattr(cuzk_cz, "_http_get", lambda *a, **k: _Resp(200, {"features": []}))
    assert cuzk_cz.address_point_near(50.0, 14.0)["status"] == "NOT_FOUND"
    monkeypatch.setattr(cuzk_cz, "_http_get",
                        lambda *a, **k: _Resp(200, {"error": {"message": "Invalid layer"}}))
    assert cuzk_cz.address_point_near(50.0, 14.0) == {"status": "ERROR", "detail": "Invalid layer"}


def test_a_slovak_listing_still_goes_to_the_slovak_check(monkeypatch):
    called = []

    def fake_plot(row):
        called.append(row["id"])
        return {"status": "UNVERIFIED", "detail": "", "raw": {}}
    monkeypatch.setattr(debt_bot, "check_plot", fake_plot)
    monkeypatch.setattr(lv_cz, "check_listing", lambda row: pytest.fail("Czech check on SK"))
    debt_bot.check_listing({"id": "x", "market": "sk"})
    debt_bot.check_listing({"id": "y"})               # a row from before markets
    assert called == ["x", "y"]
