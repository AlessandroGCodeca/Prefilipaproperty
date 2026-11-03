"""
engine/property_tax_cz.py — daň z nemovitých věcí on a Czech flat.

A flat (jednotka in the group "ostatní zdanitelné jednotky") is taxed on its
floor area, not its value (zákon 338/1992 Sb. as in force for 2026):

    base   = floor area × 1.22, rounded up to a whole m²       (§ 10 odst. 3)
    tax    = base × 3.50 Kč × the size coefficient            (§ 11 odst. 1 j), 4)
             × the inflation coefficient (1.0 for 2026)        (§ 11d, § 11f)
             × the local coefficient                           (§ 12)
             — each product rounded up to whole crowns         (§ 11d)

The size coefficient is 3.5 in every statutory city and 4.5 in Prague; a city
may raise it one step (to 4.5, or 5.0 in Prague) for chosen cadastral areas or
districts (§ 11 odst. 5). The local coefficient (0.5–5.0) is set by each
municipality's ordinance, for the whole municipality, an area or district, or
a group of properties; a group or area coefficient replaces the municipality's
(§ 12 odst. 5).

Prague and the 26 statutory cities are taxed as their 2026 ordinances say
(CITY_COEFFICIENTS, PRAHA_DISTRICTS). A part of a city named without its area
pays the city's highest combination. Anywhere else is taxed at 3.5 — the
highest size coefficient outside Prague, which a smaller town's may be lower
than — times CZ_PROPERTY_TAX_LOCAL_COEF (1.0 unless set): that town's own
coefficients are UNVERIFIED. A 60 m² flat comes to about 450 Kč a year in
Třinec, 900 Kč in Brno, 1,750 Kč in Praha 2 and 2,600 Kč in Praha 3.
"""

from __future__ import annotations

import math
import os
import re

from engine import regional_prices_cz as rpcz

# Kč per m² for a flat, § 11 odst. 1 písm. j).
RATE_PER_M2 = 3.50
# § 10 odst. 3: 1.22 for a unit in an apartment building that carries a share of
# the land, 1.20 otherwise. A listing rarely says which, so the higher is used.
UNIT_COEFFICIENT = 1.22
# § 11f: CPI for May 2025 over May 2023 (ČSÚ: 155.0 / 147.6 = 1.050), rounded
# down to one decimal place — 1.0 for 2026.
INFLATION_COEFFICIENT = 1.0
PRAGUE_COEFFICIENT = 4.5
# The coefficient for a place whose population isn't known here: the highest
# outside Prague (§ 11 odst. 4 písm. f).
UNKNOWN_PLACE_COEFFICIENT = 3.5
# A place not in the tables below: its local coefficient, if the user knows it.
LOCAL_COEFFICIENT = float(os.getenv("CZ_PROPERTY_TAX_LOCAL_COEF", "1.0") or 1.0)

# Prague, OZV hl. m. Prahy 11/2024 as amended by 12/2025 (from 1.1.2026):
# city part → (size coefficient, local coefficient). Příloha 1 sets the size
# coefficient per city part; § 4 a local coefficient of 1.5 for the city,
# replaced by příloha 2's in Praha 3, 6, 7, 8, Kolovraty, Petrovice and Slivenec.
_P = {4.5: (4.5, 1.5), 5: (5.0, 1.5)}
PRAHA_DISTRICTS = {
    "Praha 1": _P[5], "Praha 2": _P[4.5], "Praha 3": (5.0, 2.0), "Praha 4": _P[4.5],
    "Praha 5": _P[5], "Praha 6": (5.0, 2.0), "Praha 7": (5.0, 2.0), "Praha 8": (5.0, 1.7),
    "Praha 9": _P[4.5], "Praha 10": _P[4.5], "Praha 11": _P[4.5], "Praha 12": _P[4.5],
    "Praha 13": _P[4.5], "Praha 14": _P[5], "Praha 15": _P[4.5], "Praha 16": _P[4.5],
    "Praha 17": _P[4.5], "Praha 18": _P[5], "Praha 19": _P[5], "Praha 20": _P[4.5],
    "Praha 21": _P[4.5], "Praha 22": _P[4.5],
    "Benice": _P[4.5], "Běchovice": _P[4.5], "Březiněves": _P[5], "Čakovice": _P[4.5],
    "Dolní Chabry": _P[4.5], "Dolní Měcholupy": _P[4.5], "Dolní Počernice": _P[4.5],
    "Dubeč": _P[4.5], "Ďáblice": _P[4.5], "Klánovice": _P[4.5], "Koloděje": _P[4.5],
    "Kolovraty": (5.0, 2.0), "Královice": _P[4.5], "Křeslice": _P[4.5],
    "Kunratice": _P[4.5], "Libuš": _P[4.5], "Lipence": _P[4.5], "Lochkov": _P[4.5],
    "Lysolaje": _P[5], "Nebušice": _P[4.5], "Nedvězí": _P[4.5], "Petrovice": (5.0, 2.0),
    "Přední Kopanina": _P[4.5], "Řeporyje": _P[5], "Satalice": _P[4.5],
    "Slivenec": (5.0, 2.0), "Suchdol": _P[5], "Šeberov": _P[4.5], "Štěrboholy": _P[4.5],
    "Troja": _P[5], "Újezd": _P[5], "Velká Chuchle": _P[4.5], "Vinoř": _P[4.5],
    "Zbraslav": _P[4.5], "Zličín": _P[4.5],
}
_PRAHA_NAMED = sorted(((rpcz._pattern(n), n) for n in PRAHA_DISTRICTS if not n[-1].isdigit()),
                      key=lambda pn: len(pn[0].pattern), reverse=True)
# "Praha-východ" / "-západ" are the okresy around Prague, not Prague.
_PRAHA_RE = re.compile(r"(?<!\w)praha(?!\s+(?:vychod|zapad)(?!\w))")

# Statutory cities, each per its ordinance in force for 2026 (SOURCE):
# (size coefficient, local coefficient for a flat, {cadastral area or district:
# (size, local)}). The city's own pair is its highest; a part of the city with
# a lower one is listed with it.
CITY_COEFFICIENTS: dict[str, tuple[float, float, dict[str, tuple[float, float]]]] = {
    "Brno": (3.5, 1.0, {}),
    # 4.5 only in the district Moravská Ostrava a Přívoz; the other 22 districts
    # (as ostrava.cz lists them) keep 3.5.
    "Ostrava": (4.5, 1.0, {
        **dict.fromkeys(("Hošťálkovice", "Hrabová", "Krásné Pole", "Lhotka",
                         "Mariánské Hory", "Hulváky", "Martinov", "Michálkovice",
                         "Nová Bělá", "Nová Ves", "Ostrava-Jih", "Jih", "Petřkovice", "Plesná",
                         "Polanka nad Odrou", "Poruba", "Proskovice", "Pustkovec",
                         "Radvanice", "Bartovice", "Slezská Ostrava", "Stará Bělá", "Svinov",
                         "Třebovice", "Vítkovice"), (3.5, 1.0)),
    }),
    "Plzeň": (4.5, 1.0, {
        **dict.fromkeys(("Koterov", "Valcha", "Radobyčice", "Bukovec", "Křimice", "Litice",
                         "Radčice", "Černice", "Lhota"), (3.5, 1.0)),
        **dict.fromkeys(("Malesice", "Dolní Vlkýš"), (3.5, 0.5)),
    }),
    "Liberec": (3.5, 2.0, {}),
    "Olomouc": (3.5, 2.0, {}),
    "Ústí nad Labem": (3.5, 2.0, {}),
    "Hradec Králové": (4.5, 1.3, {
        **dict.fromkeys(("Svobodné Dvory", "Pouchov", "Plotiště nad Labem", "Plácky",
                         "Březhrad", "Svinary", "Slatina", "Plačice", "Malšova Lhota",
                         "Roudnička", "Rusek", "Piletice"), (3.5, 1.3)),
    }),
    "České Budějovice": (3.5, 1.0, {}),
    "Pardubice": (3.5, 2.0, {}),
    "Havířov": (3.5, 1.8, {}),
    "Zlín": (3.5, 2.0, {
        **dict.fromkeys(("Klečůvka", "Lhotka", "Salaš"), (3.5, 1.4)),
        **dict.fromkeys(("Jaroslavice", "Kostelec", "Kudlov", "Lužkovice",
                         "Louky nad Dřevnicí", "Malenovice", "Mladcová", "Prštné", "Příluky",
                         "Štípa", "Velíková"), (3.5, 1.6)),
    }),
    "Kladno": (3.5, 1.0, {}),
    "Most": (3.5, 2.0, {}),
    "Karviná": (3.5, 2.0, {
        **dict.fromkeys(("Darkov", "Doly", "Staré Město", "Louky nad Olší"), (3.5, 0.9)),
    }),
    "Opava": (3.5, 1.5, {}),
    "Frýdek-Místek": (4.5, 1.0, {
        **dict.fromkeys(("Chlebovice", "Lískovec", "Lysůvky", "Panské Nové Dvory", "Skalice"),
                        (3.5, 0.7)),
    }),
    "Karlovy Vary": (4.5, 2.0, {}),
    "Teplice": (4.5, 1.0, {}),
    "Děčín": (3.5, 2.0, {}),
    "Chomutov": (3.5, 2.0, {}),
    "Jihlava": (3.5, 1.8, {}),
    "Jablonec nad Nisou": (3.5, 2.0, {}),
    "Prostějov": (3.5, 1.0, {}),
    "Přerov": (3.5, 1.0, {
        **dict.fromkeys(("Čekyně", "Dluhonice", "Henčlov", "Penčice", "Penčičky", "Kozlovice",
                         "Lověšice", "Újezdec", "Lýsky", "Popovice", "Vinary", "Žeravice"),
                        (3.5, 0.8)),
    }),
    "Mladá Boleslav": (3.5, 1.7, {}),
    "Třinec": (3.5, 0.5, {}),
}
# A city's name, not the okres around it: "Plzeň-jih" and "Brno-venkov" are
# villages (Ostrava-Jih and Brno-sever are city districts).
_CITY_NOT = {"Plzeň": r"(?!\s+(?:jih|sever)(?!\w))", "Brno": r"(?!\s+venkov(?!\w))"}
_CITIES = sorted(((re.compile(rpcz._town_pattern(c).pattern + _CITY_NOT.get(c, "")), c)
                  for c in CITY_COEFFICIENTS), key=lambda pc: len(pc[1]), reverse=True)
_AREAS = {c: sorted(((rpcz._pattern(a), a) for a in areas), key=lambda pa: len(pa[1]), reverse=True)
          for c, (_, _, areas) in CITY_COEFFICIENTS.items()}

SOURCE = {
    "source": (
        "zákon 338/1992 Sb. as in force from 1.10.2025 (zakonyprolidi.cz): § 10 "
        "odst. 3 (× 1.22 / 1.20), § 11 odst. 1 písm. j) (3.50 Kč/m²), § 11 odst. 4–5 "
        "(size coefficients; 3.5 in a statutory city, 4.5 in Prague; one step up "
        "by ordinance), § 11d (rounding), § 11f (inflation coefficient: CPI May "
        "2025 / May 2023 = 155.0 / 147.6 per ČSÚ, rounded down → 1.0 for 2026), "
        "§ 12 (local coefficient 0.5–5.0). Statutory cities per zákon 128/2000 Sb. "
        "§ 4 (version from 1.1.2026). Each city's ordinances in force for 2026, "
        "read from sbirkapp.gov.cz: Praha 11/2024 as amended by 12/2025; Ostrava "
        "8/2024; Plzeň 2/2024; Liberec 7/2024; Olomouc 7/2024; Ústí nad Labem "
        "3/2024; Hradec Králové 6/2024; Pardubice 9/2024; Havířov 3/2024; Zlín "
        "8/2024; Most 5/2024; Karviná 7/2024; Opava 3/2024; Frýdek-Místek 4/2024; "
        "Karlovy Vary 3/2024; Teplice 1/2024; Děčín 3/2025 (from 1.1.2026); "
        "Chomutov 3/2024; Jihlava 10/2024; Jablonec nad Nisou 8/2024; Přerov "
        "7/2024; Mladá Boleslav 5/2024; Třinec 9/2024. Brno (28/2024 repealed its "
        "coefficient), Kladno (2/2025 repealed its zones), Prostějov (7/2024 "
        "repealed its coefficient) and České Budějovice have none in force. "
        "UNVERIFIED: the coefficients of any other municipality (3.5 × "
        "CZ_PROPERTY_TAX_LOCAL_COEF is used); which cadastral areas make up a city "
        "part named without one (the city's highest is used); a 'Praha N' that is a "
        "postal district rather than city part Praha N."),
    "checked": "2026-11-03 (sbirkapp.gov.cz, zakonyprolidi.cz, csu.gov.cz)",
}


def coefficients(district: str) -> tuple[float, float, str]:
    """(size coefficient, local coefficient, where they come from) for a flat
    in `district`."""
    text = rpcz._words(district or "")
    if _PRAHA_RE.search(text):
        for rx, name in _PRAHA_NAMED:
            if rx.search(text):
                return (*PRAHA_DISTRICTS[name], f"Praha-{name}")
        part = rpcz.praha_district(district)
        if part in PRAHA_DISTRICTS:
            return (*PRAHA_DISTRICTS[part], part)
        size, local = max(PRAHA_DISTRICTS.values(), key=lambda sl: sl[0] * sl[1])
        return size, local, "Praha — its dearest city part (none named)"
    for rx, city in _CITIES:
        if rx.search(text):
            size, local, _ = CITY_COEFFICIENTS[city]
            for arx, area in _AREAS[city]:
                if arx.search(text):
                    return (*CITY_COEFFICIENTS[city][2][area], f"{area}, {city}")
            return size, local, city
    return (UNKNOWN_PLACE_COEFFICIENT, LOCAL_COEFFICIENT,
            "UNVERIFIED — place not in the table; 3.5 and CZ_PROPERTY_TAX_LOCAL_COEF")


def size_coefficient(district: str) -> float:
    return coefficients(district)[0]


def annual_tax(size_m2: float, district: str = "") -> float:
    """Kč a year for a flat of `size_m2` m² in `district`, rounded as § 11d
    rounds: the base up to a whole m², each product up to a whole crown."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    size, local, _ = coefficients(district)
    base = math.ceil(size_m2 * UNIT_COEFFICIENT - 1e-9)
    tax = math.ceil(base * RATE_PER_M2 * size - 1e-9)
    tax = math.ceil(tax * INFLATION_COEFFICIENT - 1e-9)
    return float(math.ceil(tax * local - 1e-9))
