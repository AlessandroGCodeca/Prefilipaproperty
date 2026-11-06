"""scraper/property_tax_rates — reading a town's flat rate (daň z bytov) from
its own site.

Every phrasing below is quoted from a real ordinance, rate sheet or tax page
read in November 2026 (the town is named), as are the look-alikes that must
not be taken for the flat rate: the floor surcharge before a "Byty" heading,
a dog in a block of flats, a reduction in per cent, a house "s najviac tromi
bytmi", a table of past years.
"""

import io
import zipfile

import pytest

from scraper import property_tax_rates as p


def rates(text, **kw):
    r = p.read_text(text, **kw)
    return r.rates if r else None


# ── The flat rate, as towns write it ──────────────────────────────────────────
@pytest.mark.parametrize("town, text, expected", [
    ("Humenné", "Článok 3 DAŇ Z BYTOV 1. Ročná sadzba dane je za každý aj začatý m2 podlahovej "
                "plochy bytu a nebytového priestoru: a) 0,320 € za byty, b) 2,000 € za nebytové "
                "priestory slúžiace na iný účel", [0.32]),
    ("Nitra (web page)", "Daň z bytov a nebytových priestorov 0,75 € byty, 1,00 € nebytové "
                         "priestory, ktoré neslúžia na podnikateľské účely", [0.75]),
    ("Bardejov", "D a ň z b y t o v Článok 5 Sadzba dane (1) Správca dane určuje ročnú sadzbu "
                 "dane z bytov za byty na území mesta za každý aj začatý m2 podlahovej plochy "
                 "bytu nachádzajúceho sa v bytovom dome vo výške 0,60 €. (2) Správca dane "
                 "určuje ročnú sadzbu dane z bytov za nebytové priestory … vo výške: a) 0,60 € "
                 "za nebytový priestor", [0.60]),
    ("Prievidza (annex)", "i) ostatné stavby neuvedené v písmenách a) až h) 5,400 a) byty 0,675 "
                          "z bytov v eur/m2 b) nebytové priestory v bytovom dome- garáže 2,025",
     [0.675]),
    ("Trebišov", "5.2. Ročná sadzba dane z bytov za byt je 0,710 € za každý aj začatý m2 "
                 "podlahovej plochy bytu. 5.3. Ročná sadzba dane", [0.71]),
    ("Malacky", "Ročná sadzba dane z bytov za každý aj začatý m2 podlahovej plochy sa ustanovuje "
                "nasledovne: a) 0,670 €/m2 za byt, b) 6,700 €/m 2 za nebytový priestor určený "
                "na podnikanie", [0.67]),
    ("Ružomberok", "za každý aj začatý m2 podlahovej plochy bytu a nebytového priestoru takto: "
                   "a) 0,40 €/m2 za byty b) 4,00 € /m2 za nebytové priestory", [0.40]),
    ("Modra", "§ 11 Sadzba dane Správca dane stanovuje ročnú sadzbu dane z bytov alebo nebytových "
              "priestorov za každý aj začatý m² podlahovej plochy za: a) byty vo výške 1,00 €/m² "
              "b) nebytové priestory určené na iné účely ako podnikanie (garážové miesta) vo "
              "výške 1,00 €/m²", [1.00]),
    ("Poprad", "§6 Sadzba dane z bytov l . Správca dane pre všetky katastrálne územia ustanovuje "
               "ročnú sadzbu dane z bytov za byt za každý aj začatý m² podlahovej plochy bytu "
               "1,000 €. 2. Správca dane … za nebytový priestor v bytovom dome", [1.00]),
    ("Banská Bystrica (OCR)", "1. Ročná sadzba dane z bytov za byt za každý aj začatý m? "
                              "podlahovej plochy sa zvyšuje na území mesta podľa miestnych "
                              "podmienok obce nasledovne: za byt na 1,000 €/m.", [1.00]),
    ("Šamorín", "§ 5 Sadzba dane z bytov 1. Ročná sadzba dane z bytov sa určuje v každom "
                "katastrálnom území mesta Šamorín nasledovne: a) 0,850 eur/m² za byty, b) "
                "1,700 eur/m² za nebytové priestory využívané na garážovanie", [0.85]),
    ("Spišská Nová Ves (web page)", "Príplatok za podlažie je 0,07 € za každé ďalšie podlažie "
                                    "okrem prvého nadzemného podlažia. (2) Daň z bytov 0,398 "
                                    "€/m2 podlahovej plochy bytu, 1,346 €/m2 nebytového "
                                    "priestoru.", [0.398]),
    # "Byty" heading over its list: the floor surcharge before it is not a flat rate.
    ("Michalovce (rate sheet)", "i) ostatné stavby neuvedené v písmenách a) až i) 2,50 € "
                                "Zvýšenie sadzby dane za ďalšie podlažie 0,10 € Byty a) byty "
                                "0,60 € b) nebytové priestory, ktoré slúžia na podnikanie 3,20 €",
     [0.60]),
])
def test_a_flat_rate_as_each_town_writes_it(town, text, expected):
    assert rates(text) == expected, town


@pytest.mark.parametrize("town, text, expected", [
    ("Košice (by category)", "Sadzby dane za byty a nebytové priestory na rok 2026 v €/m2 "
                             "podlahovej plochy bytu a nebytového priestoru: I.kat. II.kat. "
                             "III.kat. a) byty 1,270 1,207 1,143 b) nebytové priestory",
     [1.27, 1.207, 1.143]),
    ("Dunajská Streda (by area)", "Sadzba na rok 2026/m2 k.ú. Dunajská Streda, Malé Blahovo "
                                  "Sadzba na rok 2026/m2 k.ú. Mliečany, ulica Čótfa Byt 0,68 €/m2 "
                                  "0,61 €/m2 Nebytové priestory 3,48 €/m2 3,14 €/m2", [0.68, 0.61]),
    ("Bratislava (by pásmo)", "Predmet dane z bytov Ročná sadzba dane v €/m2 podlahovej plochy "
                              "Pásmo A Pásmo B Pásmo C Pásmo D i byty 1,20 1,20 1,25 1,35 ii "
                              "nebytové priestory", [1.20, 1.25, 1.35]),
    # One class for flats and other premises, a column per part of the town,
    # the euro only in the header.
    ("Čadca (by part)", "§ 5 Sadzba dane z bytov Mesto Čadca ustanovuje ročnú sadzbu dane z "
                        "bytov za byt a nebytový priestor takto: Byty a nebytové priestory Ročná "
                        "sadzba dane z bytov za byt a nebytový priestor v eurách/m2 j. č. 1 j. č. "
                        "2 j. č. 3 Byty a nebytové priestory 0,4 0,25 0,25 Nebytové priestory "
                        "slúžiace ako garáž 0,3 0,25 0,25", [0.4, 0.25]),
    # A zone header between the flat and its rates; the "na" ending "zóna" is
    # not "na 0,447 €".
    ("Zvolen (by zone)", "§ 5 Daň z bytov 1. Mesto Zvolen stanovuje ročnú sadzbu dane za byty v "
                         "bytových domoch za každý aj začatý m2 podlahovej plochy bytu: I. zóna "
                         "II. zóna III. zóna 0,636 € 0,588 € 0,447 € 2. Mesto Zvolen stanovuje "
                         "ročnú sadzbu dane za nebytové priestory", [0.636, 0.588, 0.447]),
])
def test_a_zoned_town_gives_each_of_its_rates_once(town, text, expected):
    assert rates(text) == expected, town


def test_rows_by_group_of_areas_are_read_by_their_last_area():
    # Liptovský Mikuláš, VZN 3/2025 § 9.
    text = ("DAŇ Z BYTOV Základ dane Základom dane z bytov je výmera podlahovej plochy bytu "
            "alebo nebytového priestoru v m2. Sadzba dane (1) Správca dane stanovuje ročnú "
            "sadzbu dane z bytov za každý aj začatý m2 podlahovej plochy bytu sa v jednotlivých "
            "katastrálnych územiach nasledovne: a) Benice, Iľanovo, Ploštín, Svätý Štefan 0,30 € "
            "b) Bodice, Demänová, Liptovská Ondrašová, Okoličné, Palúdzka, Ráztoky 0,45 € "
            "c) Liptovský Mikuláš 0,50 € (2) Správca dane stanovuje ročnú sadzbu dane za každý "
            "aj začatý m2 podlahovej plochy nebytového priestoru slúžiaci ako garáž na 1,10 €")
    r = p.read_text(text, areas=p.TOWNS["Liptovský Mikuláš"].areas)
    assert r.areas == {"svaty stefan": 0.3, "raztoky": 0.45, "liptovsky mikulas": 0.5}
    assert sorted(set(r.rates)) == [0.3, 0.45, 0.5]


def test_a_scanned_t_with_an_apostrophe_still_dates_the_ordinance():
    # Liptovský Mikuláš's scan of VZN 3/2025 reads "účinnosť" as "účinnost‘".
    r = p.read_text("a) 0,50 € za byty. Toto VZN o miestnych daniach nadobúda účinnost‘ "
                    "01.01.2026.")
    assert (r.rates, r.tax_year) == ([0.5], 2026)


def test_a_table_by_cadastral_area_is_read_row_by_row():
    # Žilina, VZN 8/2025 § 5: one row per area, flats in the first column. The
    # same areas head the buildings table above it, at other rates.
    text = ("a) stavby na bývanie Bánová 1,100 Žilina 1,200 Závodie 1,100 "
            "3 DAŇ Z BYTOV §5 Sadzba dane Správca dane, v súlade s § 16 zákona, ustanovuje "
            "ročnú sadzbu dane z bytov a nebytových priestorov za každý aj začatý m2 podlahovej "
            "plochy bytu a nebytového priestoru nasledovne: Názov katastrálneho územia byty "
            "nebytové priestory slúžiace ako garáž Ročná sadzba dane v eurách/ m2 Bánová 1,100 "
            "1,800 6,400 Žilina 1,200 2,000 6,500 Závodie 1,200 1,800 6,400 "
            "DRUHÁ ČASŤ DAŇ ZA PSA")
    r = p.read_text(text, areas=("zilina", "zavodie", "banova"))
    assert r.areas == {"banova": 1.1, "zilina": 1.2, "zavodie": 1.2}
    assert sorted(r.rates) == [1.1, 1.2]
    assert "Bánová 1,100 1,800" in r.excerpt


@pytest.mark.parametrize("what, text", [
    ("a dog in a block of flats", "Sadzba dane za jedného psa: rodinný dom 10,00 bytový dom "
                                  "(byt) 40,00 objekt na podnikanie 100,00"),
    ("a reduction in per cent", "Správca dane znižuje daň zo stavieb a daň z bytov pre byty vo "
                                "vlastníctve fyzických osôb starších ako 64 rokov o 50 %"),
    ("a house with up to three flats", "Daň zo stavieb a) 0,398 €/m2 za stavby na bývanie s "
                                       "najviac tromi bytmi a drobné stavby"),
    ("non-residential premises", "a) 0,60 € za nebytové priestory slúžiace ako garáž"),
    ("a table of past years", "Opis Byt a nebytový priestor 2023 2022-2021 2020 2019-2016 2015 "
                              "byt 1,000 0,500 0,500 0,330 0,330 nebytový priestor 1,000 5,000"),
    ("a flat's floor area", "Základom dane z bytov je výmera podlahovej plochy bytu v m2."),
])
def test_what_is_not_a_flat_rate(what, text):
    assert p.read_text(text) is None, what


def test_pdf_text_with_hyphenated_words_and_a_spaced_heading():
    text = ("D a ň z b y t o v\nČlánok 5\nSadzba dane z bytov za byty za každý aj začatý m\n2 "
            "podlahovej plochy bytu vo výške 0,60 €. Za nebyto-\nvý priestor 3,00 €.")
    assert rates(text) == [0.60]


def test_the_excerpt_quotes_the_words_as_written():
    r = p.read_text("Ročná sadzba dane z bytov: a) 0,320 € za byty, b) 2,000 € za nebytové")
    assert "0,320 € za byty" in r.excerpt


# ── The tax year ──────────────────────────────────────────────────────────────
def test_the_tax_year_of_an_ordinance_is_its_latest_effective_date():
    # Prievidza's consolidated text lists every amendment's date; one in force
    # from 1 June is first charged the next year.
    text = ("a) byty 0,675 €. VZN č. 11/2019 … účinnosť nadobúda dňom 1. januára 2020. "
            "VZN č. 4/2022 … účinnosť nadobudlo dňa 1. júna 2022. VZN č. 7/2024 … účinnosť "
            "nadobudlo dňa 1. januára 2025.")
    r = p.read_text(text)
    assert (r.tax_year, r.dated) == (2025, True)
    assert p.read_text("a) byty 0,675 €. Účinnosť od 1.6.2022").tax_year == 2023
    assert p.read_text("a) 0,40 €/m2 za byty. Toto VZN nadobúda účinnosť 1.1.2027.").tax_year == 2027


def test_a_web_page_is_dated_only_by_a_year_beside_its_rates():
    page = ("Od 25. 5. 2018 nadobudlo účinnosť nariadenie Európskeho parlamentu (EÚ) 2016/679. "
            + "x " * 1000 + "Sadzby dane za byty na rok 2026 v €/m2: a) byty 1,270")
    r = p.read_text(page, document=False)
    assert (r.tax_year, r.kind) == (2026, "page")
    undated = p.read_text("Daň z bytov 0,75 € byty", document=False)
    assert (undated.tax_year, undated.dated) == (None, False)


@pytest.mark.parametrize("head, draft", [
    # An adopted ordinance opens with its publication record (Trebišov).
    ("Strana 1 z 12 Návrh VZN vyvesený na úradnej tabuli mesta Trebišov dňa 22.11.2024 "
     "Lehota na pripomienkovanie návrhu VZN do 02.12.2024 VZN schválené dňa 09.12.2024 "
     "uznesením č. 265/2024 VZN nadobúda účinnosť dňa 01.01.2025", False),
    # Šamorín's record: the date after the resolution's number.
    ("Všeobecne záväzné nariadenie č. 7/2024 o miestnych daniach (ďalej len „návrh VZN“) "
     "Návrh VZN vyvesený na úradnej tabuli mesta dňa: 21.11.2024 VZN schválené mestským "
     "zastupiteľstvom mesta Šamorín pod č. 18/2024/V, 12.12.2024", False),
    # Ružomberok's draft: a spaced-out NÁVRH and no approval.
    ("N Á V R H Všeobecne záväzné nariadenie mesta Ružomberok č. 10/2025 o miestnych daniach", True),
    ("Návrh Všeobecne záväzného nariadenia o miestnych daniach VZN schválené dňa: ", True),
    ("Všeobecne záväzné nariadenie mesta Ružomberok č. 10/2025 o miestnych daniach", False),
])
def test_drafts_are_told_from_adopted_ordinances(head, draft):
    assert p.is_draft(head) is draft


def test_a_link_labelled_as_a_draft_is_a_draft():
    assert p.is_draft("Všeobecne záväzné nariadenie", label="NÁVRH - VZN 10_2025 o miestnych daniach")


# ── Choosing among a town's documents ─────────────────────────────────────────
def R(rates, year=None, kind="ordinance", url="u"):
    return p.Reading(url=url, title=url, rates=rates, excerpt="", tax_year=year,
                     dated=year is not None, kind=kind)


def test_the_latest_ordinance_in_force_is_current():
    old, new = R([0.53], 2023), R([0.67], 2025)
    cur, up, conflict = p.pick([old, new], 2026, today=2026)
    assert cur is new and up is None and conflict == []


def test_an_undated_old_ordinance_does_not_beat_a_dated_one():
    # Poprad keeps its repealed VZN 17/2019 (0.35, no readable date) beside
    # VZN 17/2023 (1.00, from 2024).
    repealed, in_force = R([0.35]), R([1.0], 2024)
    assert p.pick([repealed, in_force], 2026, today=2026)[0] is in_force
    # … but counts when it is all there is.
    assert p.pick([repealed], 2026, today=2026)[0] is repealed


def test_an_undated_rate_page_states_this_years_rates():
    # Bratislava's rate sheet has no year; its stale consolidated VZN says 2020.
    sheet, stale = R([1.2, 1.25, 1.35], kind="sheet"), R([0.9, 0.95, 1.0], 2020)
    assert p.pick([sheet, stale], 2026, today=2026)[0] is sheet


def test_a_later_years_ordinance_is_upcoming_not_current():
    now, later = R([0.6], 2026), R([0.7], 2027)
    cur, up, _ = p.pick([now, later], 2026, today=2026)
    assert (cur, up) == (now, later)
    assert p.pick([now, later], 2027, today=2027)[0] is later


def test_two_documents_for_one_year_that_disagree_conflict():
    a, b = R([0.6], 2026, url="a"), R([0.65], 2026, url="b")
    cur, _, conflict = p.pick([a, b], 2026, today=2026)
    assert cur in (a, b) and len(conflict) == 1


# ── Documents ─────────────────────────────────────────────────────────────────
def _pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    if text:
        pdf.multi_cell(0, 5, text)
    else:
        pdf.rect(10, 10, 100, 100)          # an image-only page: a scan
    return bytes(pdf.output())


def test_a_pdf_ordinance_is_read():
    body = ("Vseobecne zavazne nariadenie mesta o miestnych daniach. " * 4
            + "Sadzba dane z bytov: a) 0,60 eur za byty, b) 3,00 eur za nebytove priestory. "
            + "Toto VZN nadobuda ucinnost 1. januara 2026.")
    doc = p.doc_from_bytes("vzn.pdf", _pdf(body))
    assert (doc.kind, doc.problem) == ("pdf", "")
    r = p.read_text(doc.text)
    assert (r.rates, r.tax_year) == ([0.6], 2026)


def test_a_scanned_pdf_is_reported_not_guessed():
    doc = p.doc_from_bytes("scan.pdf", _pdf(""))
    assert "scanned" in doc.problem


def test_a_word_file_is_read():
    xml = ('<?xml version="1.0"?><w:document xmlns:w="w"><w:body><w:p><w:r><w:t>'
           'Ročná sadzba dane z bytov: a) 0,850 eur/m² za byty</w:t></w:r></w:p></w:body>'
           '</w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    doc = p.doc_from_bytes("vzn.docx", buf.getvalue())
    assert doc.kind == "docx" and rates(doc.text) == [0.85]


def test_an_old_word_file_asks_for_a_pdf():
    assert ".doc" in p.doc_from_bytes("x.doc", b"\xd0\xcf\x11\xe0" + b"\0" * 100).problem


class _Resp:
    def __init__(self, status=200, content=b"", ctype="text/html; charset=utf-8", url="https://t.sk/"):
        self.status_code, self.content, self.url, self.reason = status, content, url, "x"
        self.headers = {"content-type": ctype}


def test_a_captcha_page_is_blocked_not_read(monkeypatch):
    page = b'<html><body><form action="/verify"><div class="g-recaptcha"></div></form></body></html>'
    monkeypatch.setattr(p, "_get", lambda url, session=None, timeout=45: _Resp(content=page))
    with pytest.raises(p.Blocked, match="CAPTCHA"):
        p.fetch("https://www.presov.sk/")


def test_access_forbidden_is_blocked(monkeypatch):
    monkeypatch.setattr(p, "_get", lambda url, session=None, timeout=45: _Resp(status=403))
    with pytest.raises(p.Blocked, match="403"):
        p.fetch("https://www.levice.sk/")


def test_a_dropped_connection_is_tried_again_once(monkeypatch):
    import requests
    calls = []

    def flaky(url, session=None, timeout=45):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("reset")
        return _Resp(content=b"<html><body>Dan z bytov 0,75 \xe2\x82\xac byty</body></html>")
    monkeypatch.setattr(p, "_get", flaky)
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    assert p.fetch("https://www.stupava.sk/").kind == "html" and len(calls) == 2
    calls.clear()
    with pytest.raises(p.Blocked, match="reset"):          # a village's site: no second try
        p.fetch("https://www.obec.sk/", retry=False)
    assert len(calls) == 1


def test_brotli_is_not_asked_for(monkeypatch):
    # bratislava.sk answers "br" when offered it, and requests can't unpack it here.
    import config
    monkeypatch.setattr(config, "SCRAPER_API_KEY", "")
    sent = {}

    class S:
        headers = {}

        def get(self, url, timeout):
            sent.update(self.headers)
            return _Resp()
    p._get("https://bratislava.sk/", S())
    assert "br" not in sent["Accept-Encoding"]


# ── A town's site ─────────────────────────────────────────────────────────────
SITE = {
    "https://mesto.sk/dane": """<html><head><base href="//mesto.sk/"></head><body>
        <nav><a href="/dane-a-poplatky">Dane a poplatky</a><a href="/matrika">Matrika</a></nav>
        <table>
          <tr><td>VZN č. 9/2025 o miestnych daniach</td><td>Platné</td>
              <td><a href="download.dat?id=new">stiahnuť (300 kB)</a></td></tr>
          <tr><td>VZN č. 3/2019 o dani z nehnuteľností</td><td>Zrušené, neplatné</td>
              <td><a href="download.dat?id=old">stiahnuť (200 kB)</a></td></tr>
        </table>
        <ul><li><a href="/files/navrh-vzn-miestne-dane-2026.pdf">Návrh VZN o miestnych daniach</a></li>
            <li><a href="/files/priznanie.pdf">Priznanie k dani z nehnuteľností</a></li>
            <li><a href="https://other.sk/vzn.pdf">VZN o miestnych daniach (iný web)</a></li></ul>
        </body></html>""",
    "https://mesto.sk/download.dat?id=new": "%PDF new",
    "https://mesto.sk/download.dat?id=old": "%PDF old",
    "https://mesto.sk/dane-a-poplatky": "<html><body>Dane a poplatky</body></html>",
}
TEXTS = {
    "%PDF new": ("VZN schválené dňa 10.12.2025 uznesením č. 1/2025. Sadzba dane z bytov: "
                 "a) 0,90 € za byty. Toto VZN nadobúda účinnosť 1. januára 2026."),
    "%PDF old": "Sadzba dane z bytov: a) 0,40 € za byty. Účinnosť od 1.1.2020.",
}


def fake_fetch(url, session=None):
    if url not in SITE:
        raise AssertionError(f"followed a link it shouldn't: {url}")
    body = SITE[url]
    if body.startswith("%PDF"):
        return p.Doc(url, "pdf", TEXTS[body])
    return p.doc_from_bytes(url, body.encode())


def test_a_town_is_read_from_its_ordinance_list():
    res = p.check_town(p.Town("Mesto", ("https://mesto.sk/dane",)), 2026,
                       delay=0, fetcher=fake_fetch)
    # The ordinance in force, through <base href>; not the repealed one, the
    # draft, the tax-return form or the other site's file.
    assert res.current.rates == [0.9] and res.current.tax_year == 2026
    followed = [u for u, _ in res.visited]
    assert "https://mesto.sk/download.dat?id=old" not in followed
    assert not any("navrh" in u or "priznanie" in u or "other.sk" in u for u in followed)


def test_a_refused_start_page_is_blocked():
    def refuse(url, session=None):
        raise p.Blocked("the site answered with a CAPTCHA or bot check instead of the page")
    res = p.check_town(p.Town("Prešov", ("https://www.presov.sk/",)), 2026, delay=0, fetcher=refuse)
    assert "CAPTCHA" in res.blocked and not res.found


def test_an_ordinance_page_s_own_file_is_followed_whatever_its_label():
    site = {
        "https://m.sk/vzn": '<html><body><li><a href="/vzn/14-2022-o-miestnych-daniach/">'
                            'VZN č. 14/2022 o miestnych daniach</a></li></body></html>',
        "https://m.sk/vzn/14-2022-o-miestnych-daniach/":
            '<html><body><a href="https://cdn.m.sk/2022/12/VZN-14.pdf">Stiahnuť PDF</a></body></html>',
    }

    def fetch(url, session=None):
        if url.endswith(".pdf"):
            return p.Doc(url, "pdf", "za byt na 1,000 €/m. Účinnosť: 01.01.2023")
        return p.doc_from_bytes(url, site[url].encode())
    res = p.check_town(p.Town("M", ("https://m.sk/vzn",)), 2026, delay=0, fetcher=fetch)
    assert res.current.rates == [1.0] and res.current.url == "https://cdn.m.sk/2022/12/VZN-14.pdf"


def test_an_ordinance_on_several_taxes_is_followed_but_one_on_dogs_is_not():
    # Čadca files its property tax with four others in one ordinance.
    page = p.doc_from_bytes("https://mesto.sk/vzn", """<html><body><ul>
        <li><a href="/files/vzn-9-2023.pdf">VZN o dani z nehnuteľností, dani za psa, dani za
            ubytovanie, dani za predajné automaty a dani za nevýherné hracie prístroje 9/2023</a></li>
        <li><a href="/files/vzn-4-2023.pdf">VZN o dani za psa 4/2023</a></li>
        </ul></body></html>""".encode())
    followed = [href for _, href, _ in p._links(page, "mesto.sk")]
    assert followed == ["https://mesto.sk/files/vzn-9-2023.pdf"]


# ── CUET, for a town whose own site refuses ──────────────────────────────────
def _cuet_item(href, name, note, published):
    return f"""<div class="resultItem">
        <div class="item3"><div class="metadataDocumentName">Zverejnené od:</div>{published}</div>
        <div class="item1"><div class="metadataDocumentName">Názov dokumentu:</div>{name}</div>
        <div class="item1"><div class="metadataDocumentName">Anotácia dokumentu:</div>{note}</div>
        <div class="item1 button"><a href="{href}">Zobraziť</a></div></div>"""


CUET_SEARCH = p.cuet_search_url("Mesto Zvolen", p.date(2026 - p.CUET_YEARS, 1, 1))
CUET_SITE = {
    CUET_SEARCH: "<html><body><div class='searchWrapper'>" + "".join([
        _cuet_item("/sk/dokument/old", "VZN Mesta Zvolen č.230 o miestnych daniach a miesy",
                   "Mesto Zvolen zverejňuje VZN č.230 o miestnych daniach", "14.12.2023"),
        _cuet_item("/sk/dokument/draft", "Návrh Novelizácie č.1 VZN č.230 o miestnych",
                   "Mesto Zvolen zverejňuje Návrh Novelizácie č.1 o miestnych daniach",
                   "22.11.2024"),
        _cuet_item("/sk/dokument/new", "Novelizácia č. 1 VZN č.230 o miestnych daniach a",
                   "Mesto Zvolen zverejňuje Novelizáciu č. 1 VZN č.230 o miestnych daniach",
                   "13.12.2024"),
        _cuet_item("/sk/dokument/dogs", "Oznámenie o dražbe", "Mesto Zvolen — dražba bytu",
                   "05.11.2026"),
    ]) + "</div></body></html>",
    "https://cuet.slovensko.sk/sk/dokument/new":
        '<html><body><a href="/sk/priloha/zobraz/n1">Zobraziť</a>'
        '<a href="/sk/priloha/uloz/n1">Stiahnuť</a></body></html>',
    "https://cuet.slovensko.sk/sk/dokument/old":
        '<html><body><a href="/sk/priloha/zobraz/o1">Zobraziť</a></body></html>',
}
CUET_FILES = {
    "https://cuet.slovensko.sk/sk/priloha/zobraz/n1":
        "Schválené: 12.12.2024 Účinnosť: 01.01.2025 § 5 Daň z bytov ročnú sadzbu dane za byty "
        "… plochy bytu: I. zóna II. zóna III. zóna 0,636 € 0,588 € 0,447 €",
    "https://cuet.slovensko.sk/sk/priloha/zobraz/o1":
        "Schválené: 12.12.2023 Účinnosť: 01.01.2024 § 5 Daň z bytov ročnú sadzbu dane za byty "
        "… plochy bytu: I. zóna II. zóna III. zóna 0,612 € 0,560 € 0,426 €",
}


def test_a_refused_town_is_read_from_cuet():
    asked = []

    def fetch(url, session=None):
        asked.append(url)
        if url == "https://www.zvolen.sk/":
            raise p.Blocked("the site answered with a CAPTCHA or bot check instead of the page")
        if url in CUET_FILES:
            return p.Doc(url, "pdf", CUET_FILES[url])
        if url not in CUET_SITE:
            raise AssertionError(f"opened what it shouldn't: {url}")
        return p.doc_from_bytes(url, CUET_SITE[url].encode())
    res = p.check_town(p.TOWNS["Zvolen"], 2026, delay=0, fetcher=fetch)
    assert "CAPTCHA" in res.blocked
    assert res.current.rates == [0.636, 0.588, 0.447] and res.current.tax_year == 2025
    assert [r.tax_year for r in res.readings] == [2025, 2024]     # the newest first
    # Neither the draft, nor what isn't about the tax, nor a file twice.
    assert not any(u.endswith(("/draft", "/dogs", "/uloz/n1")) for u in asked)


def test_a_town_without_cuet_is_just_blocked():
    def refuse(url, session=None):
        raise p.Blocked("the site refused or reset the connection")
    res = p.check_town(p.TOWNS["Martin"], 2026, delay=0, fetcher=refuse)
    assert res.blocked and res.fetched == 1 and not res.readings


def test_cuet_is_searched_by_annotation():
    # CUET cuts a title at 50 characters ("… č.230 o miestnyy"): the
    # annotation still says "o miestnych daniach".
    assert "DocumentAbstract=miestnych+daniach" in CUET_SEARCH
    assert "PublisherName=Mesto+Zvolen" in CUET_SEARCH


def test_every_town_has_a_start_page_on_the_web():
    assert len(p.TOWNS) >= 30
    for t in p.TOWNS.values():
        assert t.start and all(u.startswith("https://") for u in t.start), t.name


def test_an_upload_is_read_and_a_draft_refused():
    good = _pdf("Sadzba dane z bytov: a) 0,95 eur za byty. Ucinnost od 1.1.2026. " * 3)
    r, why = p.read_upload("vzn.pdf", good)
    assert (r.rates, r.tax_year, why) == ([0.95], 2026, "")
    draft = _pdf("N A V R H Vseobecne zavazne nariadenie. a) 0,95 eur za byty. " * 3)
    r, why = p.read_upload("navrh.pdf", draft)
    assert r is None and "draft" in why
