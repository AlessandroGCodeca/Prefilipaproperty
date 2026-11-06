"""
engine/property_tax_sk.py — daň z bytov on a Slovak flat.

A flat is taxed on its floor area, not its value (zákon 582/2004 Z. z.
o miestnych daniach, § 14–16):

    tax = every started m² of the flat's floor area × the municipality's
          yearly rate per m²

The act's own rate, 0.033 €/m² (§ 16 ods. 1), is only the default: each
municipality sets its rate by VZN (§ 16 ods. 2), and the act limits it only
relative to the municipality's other flat rates (its highest at most 10× its
lowest). The towns below charge 0.25–1.35 €/m², 8–40 times the default.

Bratislava's rate depends on the cadastral area's pásmo (A–D). A city part is
taxed at the highest pásmo among its areas: Ružinov at Nivy's 1.35 (its
Ružinov and Trnávka areas pay 1.25), and a bare "Bratislava II" at its
dearest city part's. Košice, Žilina, Liptovský Mikuláš, Zvolen and Čadca also
rate by area: a listing that names one of their areas pays its rate, any
other part of the town the town's highest. A place not in the table is taxed
at the highest rate in it, 1.35 €/m². That is not a legal ceiling (a
municipality may set more), so such a listing's tax is UNVERIFIED. A 60 m²
flat pays about €15–81 a year in the towns below, so the approximation hardly
moves a cash flow.

The table can be brought up to date from the towns' own sites with one click
on the dashboard (modules/tax_rates, scraper/property_tax_rates). What that
stores in the property_tax_rates table is used here on top of the table: a
town not in it gets its scraped rate; a town in it gets a stored rate only
from a later tax year than TABLE_YEAR (a new ordinance) or one the user
accepted or uploaded. Towns rated by cadastral area keep the table's rates.
"""

from __future__ import annotations

import math
import re
import unicodedata

from engine import regional_prices as rp

# § 16 ods. 1 — what a municipality without its own rate would charge. Shown
# for reference; the table and the fallback below are what the engine uses.
STATUTORY_RATE_PER_M2 = 0.033

# Bratislava (VZN 13/2019 as amended by VZN 16/2023 from 2024; VZN 6/2025
# changes no rate): pásmo A 1.20, B 1.20, C 1.25, D 1.35 €/m². Pásma by
# cadastral area —
# A: Vajnory, Podunajské Biskupice, Vrakuňa, Devínska Nová Ves; B: Čunovo,
# Devín, Dúbravka, Jarovce, Karlova Ves, Lamač, Rača, Rusovce, Záhorská
# Bystrica; C: Nové Mesto, Vinohrady, Ružinov, Trnávka, Petržalka;
# D: Staré Mesto, Nivy. City parts are named as in engine.regional_prices.
BA_PART_RATE_PER_M2 = {
    "staré mesto": 1.35, "stare mesto": 1.35,
    "ružinov":     1.35, "ruzinov":     1.35,   # Nivy (D); its other areas are C
    "nové mesto":  1.25, "nove mesto":  1.25,   # Nové Mesto and Vinohrady (C)
    "petržalka":   1.25, "petrzalka":   1.25,
    "rača":        1.20, "raca":        1.20,
    "karlova ves": 1.20,
    "dúbravka":    1.20, "dubravka":    1.20,
    "lamač":       1.20, "lamac":       1.20,
    "devínska":    1.20, "devinska":    1.20,
    "devín":       1.20, "devin":       1.20,
    "záhorská":    1.20, "zahorska":    1.20,
    "jarovce":     1.20,
    "rusovce":     1.20,
    "čunovo":      1.20, "cunovo":      1.20,
    "vajnory":     1.20,
    "podunajské":  1.20, "podunajske":  1.20,
    "vrakuňa":     1.20, "vrakuna":     1.20,
}
_BA_PARTS_BY_LENGTH = sorted(BA_PART_RATE_PER_M2, key=len, reverse=True)
# "Bratislava I"–"V" with no city part named: the okres's dearest city part.
BA_OKRES_RATE_PER_M2 = {"I": 1.35, "II": 1.35, "III": 1.25, "IV": 1.20, "V": 1.25}

# Other cities: €/m² a year for a flat, and where the figure comes from. A city
# rated by cadastral area (CITY_AREA_RATE_PER_M2) carries its highest rate here.
CITY_RATE_PER_M2 = {
    "bratislava":      (1.35, "Bratislava city-wide — pásmo D, the highest (no city part named)"),
    "košice":          (1.27, "Košice — category I, the highest (no cadastral area named)"),
    "žilina":          (1.20, "Žilina — the Žilina and Závodie areas' rate, the highest"),
    "žilinská lehota": (1.10, "Žilinská Lehota, Žilina"),
    "trnava":          (1.00, "Trnava"),
    "banská bystrica": (1.00, "Banská Bystrica"),
    "prešov":          (0.953, "Prešov"),
    "trenčín":         (0.88, "Trenčín"),
    "nitra":           (0.75, "Nitra"),
    # Towns beyond the kraj seats, each from its own 2026 ordinance (SOURCE).
    "pezinok":         (1.00, "Pezinok"),
    "modra":           (1.00, "Modra"),
    "poprad":          (1.00, "Poprad"),
    "piešťany":        (0.75, "Piešťany"),
    "trebišov":        (0.71, "Trebišov"),
    "dunajská streda": (0.68, "Dunajská Streda — its main areas (Mliečany 0.61)"),
    "prievidza":       (0.675, "Prievidza"),
    "malacky":         (0.67, "Malacky"),
    "senec":           (0.60, "Senec"),
    "stupava":         (0.60, "Stupava"),
    "michalovce":      (0.60, "Michalovce"),
    "bardejov":        (0.60, "Bardejov"),
    "ružomberok":      (0.40, "Ružomberok"),
    "spišská nová ves": (0.398, "Spišská Nová Ves"),
    "humenné":         (0.32, "Humenné"),
    # Rated by area or zone (CITY_AREA_RATE_PER_M2); the highest here.
    "zvolen":          (0.636, "Zvolen — zone I, the highest (no zone III part named)"),
    "liptovský mikuláš": (0.50, "Liptovský Mikuláš — its main cadastral area, the highest"),
    "čadca":           (0.40, "Čadca — the town's streets (part 1), the highest"),
}
CITY_RATE_PER_M2.update({
    "kosice": CITY_RATE_PER_M2["košice"], "zilina": CITY_RATE_PER_M2["žilina"],
    "banska bystrica": CITY_RATE_PER_M2["banská bystrica"],
    "presov": CITY_RATE_PER_M2["prešov"], "trencin": CITY_RATE_PER_M2["trenčín"],
    "zilinska lehota": CITY_RATE_PER_M2["žilinská lehota"],
    "piestany": CITY_RATE_PER_M2["piešťany"], "trebisov": CITY_RATE_PER_M2["trebišov"],
    "dunajska streda": CITY_RATE_PER_M2["dunajská streda"],
    "ruzomberok": CITY_RATE_PER_M2["ružomberok"],
    "spisska nova ves": CITY_RATE_PER_M2["spišská nová ves"],
    "humenne": CITY_RATE_PER_M2["humenné"],
    "liptovsky mikulas": CITY_RATE_PER_M2["liptovský mikuláš"],
    "cadca": CITY_RATE_PER_M2["čadca"],
})
_CITIES_BY_LENGTH = sorted(CITY_RATE_PER_M2, key=len, reverse=True)

# Cadastral areas with a rate of their own, by city (names without diacritics),
# matched only when the city itself is named: "Barca" alone is also a village
# near Rimavská Sobota.
CITY_AREA_RATE_PER_M2 = {
    # VZN 132 § 2 ods. 2 and the 2026 rates: category I 1.270, II 1.207, III 1.143.
    "kosice": {
        "stredne mesto": 1.27,
        **dict.fromkeys(("hustaky", "letna", "skladna", "cermel", "severne mesto", "brody",
                         "nove tahanovce", "terasa", "grunt", "zeleziarne", "furca",
                         "juzne mesto", "jazero"), 1.207),
        **dict.fromkeys(("tahanovce", "kavecany", "lunik", "myslava", "lorincik", "peres",
                         "polov", "saca", "kosicka nova ves", "vysne opatske",
                         "nizna uvrat", "krasna", "barca", "sebastovce", "kamenne"), 1.143),
    },
    # VZN 8/2025 § 5: Žilina and Závodie 1.200, every other area 1.100.
    "zilina": {
        "zavodie": 1.20,
        **dict.fromkeys(("banova", "brodno", "budatin", "bytcica", "mojsova lucka",
                         "povazsky chlmec", "strazov", "trnove", "vranie", "zadubnie",
                         "zastranie"), 1.10),
    },
    # The city's 2026 table: Dunajská Streda and Malé Blahovo 0.68, Mliečany 0.61.
    "dunajska streda": {"mliecany": 0.61},
    # VZN 3/2025 § 9: the Liptovský Mikuláš area 0.50, these six 0.45, these four 0.30.
    "liptovsky mikulas": {
        **dict.fromkeys(("bodice", "demanova", "liptovska ondrasova", "okolicne", "paludzka",
                         "raztoky"), 0.45),
        **dict.fromkeys(("benice", "ilanovo", "plostin", "svaty stefan"), 0.30),
    },
    # VZN 230 § 1 ods. 3 and § 5 as amended by Novelizácia č. 1 (from 2025):
    # zone I (the centre's streets) 0.636, zone II (most other streets, listed
    # one by one — ZONE_RATES_BY_STREET) 0.588, zone III (these city parts and
    # the outskirts) 0.447.
    "zvolen": dict.fromkeys(("zolna", "lukove", "kralova", "sekierska dolina", "bakova jama"),
                            0.447),
    # VZN 9/2023 § 1 and § 5: part 1, the town's streets, 0.40; parts 2 and 3,
    # the outlying settlements, 0.25. Horelica and U Hluška have streets in
    # part 1 and settlements in part 2, so their names alone tell nothing.
    "cadca": dict.fromkeys(("drahosanka", "cadecka", "podzavoz", "milosova", "vojty", "rieka",
                            "u sihelnika"), 0.25),
}
# Rates an ordinance sets for zones drawn street by street, which a listing
# rarely names: charged to no listing (one in such a zone pays the town's
# highest rate), kept so the update can confirm the ordinance's whole table.
ZONE_RATES_BY_STREET = {"zvolen": (0.588,)}
# City parts whose name contains an area's without being it: Košice's
# Sídlisko Ťahanovce is not the Ťahanovce cadastral area.
_NOT_AN_AREA = ("sidlisko tahanovce",)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn").lower()


# What a town's rated areas are, where they are not cadastral areas.
_AREA_KIND = {"zvolen": "zone III", "cadca": "an outlying settlement"}


def _area_rate(city: str, key: str) -> tuple[float, str] | None:
    """The rate of the cadastral area (or zone part) of `city` that `key`
    names, if any."""
    areas = CITY_AREA_RATE_PER_M2.get(_fold(city))
    if not areas:
        return None
    folded = _fold(key)
    for name in _NOT_AN_AREA:
        folded = folded.replace(name, " ")
    for area in sorted(areas, key=len, reverse=True):
        if rp._has_place(area, folded):
            kind = _AREA_KIND.get(_fold(city))
            where = f"{rp._title(area)}, {rp._title(_fold(city))}"
            return areas[area], (f"{where} — {kind}" if kind
                                 else f"{rp._title(area)} cadastral area, {rp._title(_fold(city))}")
    return None

# The tax year every rate above was checked for (SOURCE).
TABLE_YEAR = 2026

# Rated by cadastral area or pásmo: a stored rate never replaces these, since
# it would have to be mapped to the areas by hand.
ZONED = {"bratislava", "kosice", "zilina", "zilinska lehota", "dunajska streda",
         "liptovsky mikulas", "zvolen", "cadca"}


def table_rates(town: str) -> list[float]:
    """The flat rates the table above charges in `town` (several for a town
    rated by area), [] for a town it doesn't have."""
    key = _fold(town)
    if key == "bratislava":
        return sorted(set(BA_PART_RATE_PER_M2.values()))
    rates = set(CITY_AREA_RATE_PER_M2.get(key, {}).values()) | set(ZONE_RATES_BY_STREET.get(key, ()))
    if key in CITY_RATE_PER_M2:
        rates.add(CITY_RATE_PER_M2[key][0])
    if key == "zilina":
        rates.add(CITY_RATE_PER_M2["zilinska lehota"][0])
    return sorted(rates)


# ── Rates read from the towns' sites (modules/tax_rates) ──────────────────────
_stored: dict[str, list[dict]] | None = None
_names: list[tuple[str, str, str, str]] | None = None
_names_of: object = None            # the stored rates _names was built with


def town_key(name: str) -> str:
    """A town's key in the stored rates: its folded name, and for one of
    several municipalities sharing a name ("Porúbka (okres Žilina)") the
    name and district: "porubka|zilina"."""
    m = re.match(r"^(.*?)\s*\((?:okres\s+)?([^)]*)\)\s*$", name or "")
    return f"{_fold(m.group(1))}|{_fold(m.group(2))}" if m else _fold(name)


def _known_names() -> list[tuple[str, str, str, str]]:
    """(name, district required or "", key, district) of every Slovak
    municipality the rates know of, the longest name first — so "Spišská
    Nová Ves" is found before the village "Nová Ves" inside it. A name
    several share counts only with its district named beside it."""
    global _names, _names_of
    if _names is None or _names_of is not stored_rates():
        _names_of = stored_rates()
        names: dict[str, tuple[str, str, str, str]] = {}
        try:
            import database
            conn = database.get_conn()
            try:
                if database._has_table(conn, "sk_municipalities"):
                    for r in conn.execute("SELECT name, okres, key FROM sk_municipalities"):
                        k = town_key(r["key"])
                        okres = _fold(r["okres"] or "")
                        names[k] = (_fold(r["name"]), okres if "|" in k else "", k, okres)
            finally:
                conn.close()
        except Exception:
            pass
        for k in stored_rates():
            if k not in names:
                n, _, okres = k.partition("|")
                names[k] = (n, okres, k, okres)
        _names = sorted(names.values(), key=lambda t: -len(t[0]))
    return _names


def reload() -> None:
    """Forget the stored rates read so far: the next lookup reads them again
    (after an update, and at the start of each scoring run — the dashboard
    and the scheduler are two processes)."""
    global _stored, _names
    _stored = None
    _names = None


def stored_rates() -> dict[str, list[dict]]:
    """{town (folded): its stored rates, the latest tax year first}."""
    global _stored
    if _stored is None:
        _stored = _load_stored()
    return _stored


def _load_stored() -> dict[str, list[dict]]:
    try:
        import database
        conn = database.get_conn()
    except Exception:
        return {}
    try:
        if not database._has_table(conn, "property_tax_rates"):
            return {}
        rows = conn.execute(
            "SELECT town, name, tax_year, rate, origin, source_url, document, saved_at "
            "FROM property_tax_rates ORDER BY tax_year DESC, saved_at DESC").fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["town"], []).append(dict(r))
    return out


def _stored_rate(town: str, year: int, in_table: bool) -> tuple[float, str] | None:
    """The stored rate in force in `town` in tax year `year`, if one should be
    used: for a town in the table only a later year's than TABLE_YEAR or one
    a user accepted or uploaded — the table was checked by hand for its year."""
    for r in stored_rates().get(town, []):
        if r["tax_year"] > year:
            continue
        if in_table and r["origin"] == "scraped" and r["tax_year"] <= TABLE_YEAR:
            return None
        doc = r["document"] or r["source_url"] or "its site"
        how = {"scraped": "read from", "accepted": "accepted from",
               "upload": "uploaded:"}.get(r["origin"], "from")
        return r["rate"], f"{r['name']} — {how} {doc} ({(r['saved_at'] or '')[:10]})"
    return None


def _year() -> int:
    try:
        from config import TAX_YEAR
        return int(TAX_YEAR)
    except Exception:
        from datetime import date
        return date.today().year


# A place the table doesn't know: the highest rate in it (see the docstring).
UNKNOWN_PLACE_RATE_PER_M2 = max(
    [r for r, _ in CITY_RATE_PER_M2.values()] + list(BA_PART_RATE_PER_M2.values()))

SOURCE = {
    "source": (
        "Read from each primary document. Act: zákon 582/2004 Z. z. §§ 15–16 "
        "(static.slov-lex.sk, versions in force from 1.1.2026, 1.9.2026 and "
        "1.1.2027 — 131/2026 Z. z. and the 2027 changes leave the tax on flats "
        "alone). Bratislava: VZN 13/2019 as amended by VZN 16/2023 (from "
        "1.1.2024) — flats 1.20/1.20/1.25/1.35 €/m² in pásma A–D; the city's rate "
        "sheet lists each cadastral area's pásmo; VZN 6/2025 (from 1.1.2026) only "
        "adds an exemption (bratislava.sk). Košice: VZN 132, consolidated from "
        "1.1.2024, § 2 ods. 2 (categories by cadastral area) and the city's 2026 "
        "rates — flats 1.270/1.207/1.143 (kosice.sk). Žilina: VZN 8/2025, adopted "
        "9.12.2025 (uzn. 260/2025), from 1.1.2026, § 5 — Žilina and Závodie 1.200, "
        "other areas 1.100 (zilina.sk). Trnava: VZN 529, § on daň z bytov — 1.00 "
        "in the Trnava and Modranka areas; its amendments 535, 592, 618 and 645, "
        "listed by the city as in force for 2026, leave it alone (trnava.sk). "
        "Nitra: the city's tax page — flats 0.75 (nitra.sk). Banská Bystrica: VZN "
        "14/2022, from 1.1.2023 — flats 1.000; VZN 8/2023, the only amendment in "
        "force, leaves it alone (banskabystrica.sk). Trenčín: VZN 14/2013 as "
        "amended by VZN 21/2025 (uzn. 1145, 12.11.2025, from 1.1.2026) — flats "
        "0.88; VZN 26/2026 leaves it alone (trencin.sk). Prešov: 0.953 per VZN "
        "11/2024, unchanged for 2026 per the city's tax page — read via web "
        "search, as presov.sk answers automated requests with a CAPTCHA. "
        "Other towns, each from its own site: Pezinok VZN 10/2023 (from 2024; "
        "VZN 3/2026 changes only the public-space tax) 1.00; Modra VZN 6/2012, "
        "consolidated from 1.1.2026, 1.00; Poprad VZN 17/2023 (from 2024, listed "
        "in force) 1.000; Piešťany VZN 16/2022 (from 2023; VZN 6/2026 amends "
        "another ordinance) 0.75; Trebišov VZN 191/2024 (from 2025; its 2026 "
        "Dodatok 1 changes only the public-space tax) 0.710; Dunajská Streda the "
        "city's 2026 rate table, 0.68 (Mliečany and ulica Čótfa 0.61); Prievidza "
        "VZN 11/2019, consolidated from 1.1.2025, 0.675, and its mid-2026 report: "
        "no rate changes in 2026; Malacky the city's 2026 rate page 0.67; Senec "
        "VZN 12/2025 (from 1.1.2026) 0.60; Stupava VZN 5/2023 (from 2024) 0.60 — "
        "no later ordinance found; Michalovce VZN 10/2024 (from 2025, listed in "
        "force, no amendment) 0.60; Bardejov the city's tax page citing VZN "
        "195/2024, 0.60; Ružomberok VZN 10/2025 (from 1.1.2026) 0.40; Spišská "
        "Nová Ves the city's tax page (VZN 2/2024, no change for 2026) 0.398; "
        "Humenné VZN 203/2024 (from 2025; VZN 206/2025 changes only the land "
        "tax) 0.320. Liptovský Mikuláš VZN 3/2025 (adopted 20.11.2025, from "
        "1.1.2026) § 9 — the Liptovský Mikuláš area 0.50; Bodice, Demänová, "
        "Liptovská Ondrašová, Okoličné, Palúdzka, Ráztoky 0.45; Benice, Iľanovo, "
        "Ploštín, Svätý Štefan 0.30 (mikulas.sk). Čadca VZN 9/2023 (from 2024) "
        "§ 5 — part 1 (the town's streets) 0.40, parts 2 and 3 (the outlying "
        "settlements) 0.25; its Dodatok 1 (from 2025) and Dodatok 2 (from 2026) "
        "leave flats alone (mestocadca.sk). Zvolen VZN 230 (from 2024) § 5 as "
        "amended by Novelizácia č. 1 (13.12.2024, from 2025) — zones I/II/III "
        "0.636/0.588/0.447; Novelizácia č. 2 (6.11.2025, from 2026) and č. 3 "
        "(28.5.2026, from 2027) leave § 5 alone — read from CUET "
        "(cuet.slovensko.sk), as zvolen.sk answers automated requests with a "
        "CAPTCHA. Left to 🏛️ UPDATE TAX RATES, which reads it cleanly: Šamorín "
        "(VZN 7/2024 § 5, 0.85 from 2025; VZN 5/2025, from 2026, leaves flats "
        "alone). Not added — their sites block automated requests and they "
        "publish no ordinance on CUET, or only old ones are found: Martin, "
        "Považská Bystrica, Nové Zámky, Levice, Lučenec, Topoľčany, Rimavská "
        "Sobota, Komárno. "
        "UNVERIFIED: Prešov's ordinance text; which cadastral areas make up a "
        "Košice city part named without one (taxed at category I); Zvolen's "
        "zone II, drawn street by street (a listing is taxed at zone I's rate "
        "unless it names a zone III part); any place not in the table (taxed at "
        "1.35)."),
    "checked": "2026-11-06 (official sites; Zvolen on CUET)",
}


def rate_source(district: str, year: int | None = None) -> tuple[float, str]:
    """(€/m² a year for a flat in `district` in tax year `year` — default
    config.TAX_YEAR —, what the rate is). A Bratislava city part is matched
    as engine.regional_prices matches it: with "Bratislava" named, or alone
    when it is unambiguous ("Petržalka", not "Staré Mesto", which Košice also
    has). A stored rate read from a town's site comes before the table where
    _stored_rate says so."""
    year = year or _year()
    key = (district or "").lower()
    if key:
        ba = "bratislava" in key
        if ba or not rp._names_non_ba_town(key):
            for part in _BA_PARTS_BY_LENGTH:
                if (part in key if ba else
                        part not in rp._GENERIC_BA_PARTS and rp._has_place(part, key)):
                    return BA_PART_RATE_PER_M2[part], f"{rp._title(part)}, Bratislava"
        if ba:
            m = rp._BA_OKRES_RE.search(key)
            if m:
                okres = m.group(1).upper()
                return (BA_OKRES_RATE_PER_M2[okres],
                        f"Bratislava {okres} — its dearest city part (none named)")
        city = next((c for c in _CITIES_BY_LENGTH if rp._has_place(c, key, rp._CITY_TAIL)), None)
        stored = stored_rates()
        if stored:
            folded = _fold(key)
            # The municipality the string names most fully ("Spišská Nová
            # Ves", not the village "Nová Ves" in it). One only the stored
            # rates know ("Šamorín") takes its rate; when the string also
            # names a table city, the longer name wins, as among the table's
            # own cities.
            name, town, district = next(((n, k, d) for n, okres, k, d in _known_names()
                                         if rp._has_place(n, folded, rp._CITY_TAIL)
                                         and (not okres or okres in folded)), ("", None, ""))
            # A table city in the string that is the municipality's own
            # district ("Ruská, Michalovce") is where it lies, not the place.
            if (town and town in stored and name not in CITY_RATE_PER_M2
                    and (city is None or len(name) > len(_fold(city))
                         or _fold(city) == district)):
                hit = _stored_rate(town, year, in_table=False)
                if hit:
                    return hit
            if city and _fold(city) not in ZONED:
                hit = _stored_rate(_fold(city), year, in_table=True)
                if hit:
                    return hit
        if city:
            return _area_rate(city, key) or CITY_RATE_PER_M2[city]
    return (UNKNOWN_PLACE_RATE_PER_M2,
            "UNVERIFIED — place not in the table; its highest rate is used")


def annual_tax(size_m2: float, district: str = "", year: int | None = None) -> float:
    """€ a year for a flat of `size_m2` m² in `district`: every started m²
    at the rate per m² (rate_source)."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    return round(math.ceil(size_m2 - 1e-9) * rate_source(district, year)[0], 2)
