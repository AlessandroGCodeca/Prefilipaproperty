"""
engine/property_tax_cz.py — daň z nemovitých věcí on a Czech flat.

A flat (jednotka in the group "ostatní zdanitelné jednotky") is taxed on its
floor area, not its value (zákon 338/1992 Sb. as in force for 2026):

    base   = floor area × 1.22, rounded up to a whole m²       (§ 10 odst. 3)
    tax    = base × 3.50 Kč × the size coefficient            (§ 11 odst. 1 j), 4)
             × the inflation coefficient (1.0 for 2026)        (§ 11d, § 11f)
             × the local coefficient                           (§ 12)
             — each product rounded up to whole crowns         (§ 11d)

The size coefficient follows the municipality's population (§ 11 odst. 4):
1.0 up to 1,000 people, 1.4 to 6,000, 1.6 to 10,000, 2.0 to 25,000, 2.5 to
50,000 and 3.5 above that, in every statutory city and in four spa towns;
4.5 in Prague. A municipality may raise it one step for chosen cadastral areas
or districts (§ 11 odst. 5). The local coefficient (0.5–5.0) is set by the
municipality's ordinance for the whole municipality, an area or district, or a
group of properties; a group or area coefficient replaces the municipality's
(§ 12 odst. 5), and of a group's and an area's the higher applies (§ 12 odst. 7).

Where the tax comes from:
  * Prague and the 26 statutory cities, each per its 2026 ordinance
    (PRAHA_DISTRICTS, CITY_COEFFICIENTS); the other 105 towns over 10,000
    people per theirs (TOWN_COEFFICIENTS).
  * Any other municipality: its coefficients as 🏛️ UPDATE TAX RATES read them
    from its ordinances (modules/tax_rates_cz → the property_tax_cz table).
    Until that has run, the size coefficient for its population (ČSÚ) times
    CZ_PROPERTY_TAX_LOCAL_COEF (1.0, the law's when a municipality sets none,
    unless set) — its own local coefficient is then UNVERIFIED.
  * A place that names no municipality: 3.5 × CZ_PROPERTY_TAX_LOCAL_COEF.

The tables are a hand-checked reading of the ordinances in force for
TABLE_YEAR, and they win for that year. For a later year a place in them
takes the update's reading when that changed since TABLE_YEAR (a new
ordinance, a population band crossed); otherwise the table still stands.

engine/property_tax_cz_data.json (dev/build_cz_property_tax_data.py, from
ČÚZK's RÚIAN and ČSÚ) supplies the populations and the geography: which city
parts each Prague quarter and postal district ("Praha 9") covers, which
Ostrava district each Ostrava quarter lies in, and which cadastral areas each
quarter of a city that rates by area holds its flats in. A quarter that spans
several gets the highest of them, as does a city part or town named without
its area. A 60 m² flat comes to about 450 Kč a year in Třinec, 520 Kč in
Klatovy, 900 Kč in Brno, 1,750 Kč in Praha 2 and 2,600 Kč in Praha 3.
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
import unicodedata

from engine import regional_prices_cz as rpcz

# The tax year PRAHA_DISTRICTS, CITY_COEFFICIENTS and TOWN_COEFFICIENTS were
# read for.
TABLE_YEAR = 2026

# Kč per m² for a flat, § 11 odst. 1 písm. j).
RATE_PER_M2 = 3.50
# § 10 odst. 3: 1.22 for a unit in an apartment building that carries a share of
# the land, 1.20 otherwise. A listing rarely says which, so the higher is used.
UNIT_COEFFICIENT = 1.22
# § 11f: CPI for May 2025 over May 2023 (ČSÚ: 155.0 / 147.6 = 1.050), rounded
# down to one decimal place — 1.0 for 2026.
INFLATION_COEFFICIENT = 1.0
PRAGUE_COEFFICIENT = 4.5
# The coefficient for a place that names no municipality: the highest outside
# Prague (§ 11 odst. 4 písm. f).
UNKNOWN_PLACE_COEFFICIENT = 3.5
# A municipality whose ordinance isn't in the tables below: its local
# coefficient, if the user knows it.
LOCAL_COEFFICIENT = float(os.getenv("CZ_PROPERTY_TAX_LOCAL_COEF", "1.0") or 1.0)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "property_tax_cz_data.json")


def load_data(path: str = DATA_PATH) -> dict:
    """The populations and geography dev/build_cz_property_tax_data.py writes,
    or {} when the file is missing or unreadable — every place then falls
    back to the tables below and 3.5 × CZ_PROPERTY_TAX_LOCAL_COEF."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_DATA = load_data()


def population_coefficient(population: int) -> float:
    """§ 11 odst. 4 písm. a)–f): the size coefficient for a municipality of
    `population` people (as the RUD decree in force on 1 January counts them)."""
    for limit, coef in ((1000, 1.0), (6000, 1.4), (10000, 1.6), (25000, 2.0), (50000, 2.5)):
        if population <= limit:
            return coef
    return 3.5


# § 11 odst. 4 písm. f): 3.5 whatever their size.
SPA_TOWNS = {("Františkovy Lázně", "Cheb"), ("Luhačovice", "Zlín"),
             ("Mariánské Lázně", "Cheb"), ("Poděbrady", "Nymburk")}

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

# The other towns over 10,000 people (ČSÚ, 1.1.2025), keyed by (name, okres):
# (size coefficient, local coefficient for a flat, {cadastral area: (size,
# local)}, the ordinances read — "none" when the register holds none in force
# on 1.1.2026). A pair is the highest anywhere in the town: the size
# coefficient raised one step (§ 11 odst. 5, or an old § 11 odst. 3 písm. a)
# raise kept by zákon 349/2023 part 2 point 11) where any of its areas is, and
# the group coefficient for "ostatní zdanitelné jednotky" if set, else the
# highest area coefficient, else the town's. Litvínov's 5.0 areas hold 3 of
# its 12,338 flats (RÚIAN), so it is kept to them.
TOWN_COEFFICIENTS: dict[tuple[str, str], tuple[float, float, dict[str, tuple[float, float]], str]] = {
    # Středočeský kraj
    ("Benešov", "Benešov"): (2.0, 2.0, {}, "3/2024"),
    ("Vlašim", "Benešov"): (2.5, 2.0, {}, "2/2024"),
    ("Beroun", "Beroun"): (2.5, 1.0, {}, "6/2011"),
    ("Králův Dvůr", "Beroun"): (2.0, 2.0, {}, "2/2024"),
    ("Slaný", "Kladno"): (2.0, 1.0, {}, "5/2024 (repeals 6/1993)"),
    ("Kolín", "Kolín"): (2.5, 2.0, {}, "7/2024"),
    ("Čáslav", "Kutná Hora"): (2.0, 1.0, {}, "3/2024"),
    ("Kutná Hora", "Kutná Hora"): (2.0, 2.0, {}, "7/2024"),
    ("Kralupy nad Vltavou", "Mělník"): (2.0, 1.6, {}, "5/2024"),
    ("Mělník", "Mělník"): (2.0, 1.0, {}, "none"),
    ("Neratovice", "Mělník"): (2.0, 2.5, {}, "2/2024"),
    ("Lysá nad Labem", "Nymburk"): (2.0, 1.0, {}, "4/2024, 6/2024"),
    ("Milovice", "Nymburk"): (2.0, 1.0, {}, "2/2003"),
    ("Nymburk", "Nymburk"): (2.5, 2.0, {}, "3/2025"),
    ("Poděbrady", "Nymburk"): (3.5, 0.7, {}, "4/2024"),
    ("Brandýs nad Labem-Stará Boleslav", "Praha-východ"): (2.0, 2.0, {}, "4/2024"),
    ("Čelákovice", "Praha-východ"): (2.0, 1.0, {}, "none"),
    ("Říčany", "Praha-východ"): (2.5, 5.0, {}, "3/2024, 1/2025"),
    ("Jesenice", "Praha-západ"): (2.0, 3.0, {}, "2/2024"),
    ("Příbram", "Příbram"): (2.5, 2.0, {}, "3/2024"),
    ("Rakovník", "Rakovník"): (2.5, 1.0, {}, "3/2024"),
    # Jihočeský kraj
    ("Český Krumlov", "Český Krumlov"): (2.5, 2.0, {}, "6/2024"),
    ("Jindřichův Hradec", "Jindřichův Hradec"): (2.0, 1.4, {}, "3/2024"),
    ("Písek", "Písek"): (3.5, 1.4, {}, "1/2023"),
    ("Prachatice", "Prachatice"): (2.5, 1.0, {}, "3/2024"),
    ("Strakonice", "Strakonice"): (2.0, 2.0, {}, "4/2024"),
    ("Tábor", "Tábor"): (2.5, 2.0, {}, "5/2024"),
    # Plzeňský a Karlovarský kraj
    ("Domažlice", "Domažlice"): (2.0, 1.0, {}, "none"),
    ("Klatovy", "Klatovy"): (2.0, 1.0, {}, "7/2024"),
    ("Sušice", "Klatovy"): (2.5, 1.0, {}, "4/2024"),
    ("Rokycany", "Rokycany"): (2.0, 1.0, {}, "4/2024"),
    ("Tachov", "Tachov"): (2.0, 3.0, {}, "5/2021"),
    ("Aš", "Cheb"): (2.0, 1.9, {}, "3/2024"),
    ("Cheb", "Cheb"): (2.5, 2.0, {}, "4/2024"),
    ("Mariánské Lázně", "Cheb"): (4.5, 1.2, {}, "3/2024"),
    ("Ostrov", "Karlovy Vary"): (2.0, 1.0, {}, "4/2024"),
    ("Chodov", "Sokolov"): (2.0, 1.0, {}, "4/2025"),
    ("Sokolov", "Sokolov"): (2.0, 2.0, {}, "6/2024"),
    # Ústecký kraj
    ("Rumburk", "Děčín"): (2.0, 1.0, {}, "none"),
    ("Varnsdorf", "Děčín"): (2.0, 1.0, {}, "3/2024"),
    ("Jirkov", "Chomutov"): (2.0, 2.0, {}, "3/2024"),
    ("Kadaň", "Chomutov"): (2.0, 1.0, {}, "2/2024"),
    ("Klášterec nad Ohří", "Chomutov"): (2.5, 2.0, {}, "4/2024"),
    ("Litoměřice", "Litoměřice"): (2.0, 2.5, {}, "5/2024"),
    ("Roudnice nad Labem", "Litoměřice"): (2.0, 2.0, {}, "2/2024"),
    ("Louny", "Louny"): (2.0, 1.5, {}, "6/2024 (repeals 5/2014)"),
    ("Žatec", "Louny"): (2.0, 2.0, {}, "3/2024"),
    ("Litvínov", "Most"): (2.0, 2.5, dict.fromkeys(("Záluží", "Růžodol"), (2.0, 5.0)), "2/2024"),
    ("Bílina", "Teplice"): (2.0, 0.5, {}, "4/2024"),
    ("Krupka", "Teplice"): (2.5, 2.0, {}, "5/2024"),
    # Liberecký a Královéhradecký kraj
    ("Česká Lípa", "Česká Lípa"): (2.5, 2.0, {}, "4/2024"),
    ("Nový Bor", "Česká Lípa"): (2.0, 1.0, {}, "1/2024"),
    ("Turnov", "Semily"): (2.0, 1.6, {}, "4/2024"),
    ("Jičín", "Jičín"): (2.0, 1.0, {}, "2/2024 (repeals 6/2021)"),
    ("Jaroměř", "Náchod"): (2.0, 1.0, {}, "none"),
    ("Náchod", "Náchod"): (2.5, 1.0, {}, "4/2024"),
    ("Rychnov nad Kněžnou", "Rychnov nad Kněžnou"): (2.0, 0.7, {}, "2/2024"),
    ("Dvůr Králové nad Labem", "Trutnov"): (2.0, 1.0, {}, "4/2024"),
    ("Trutnov", "Trutnov"): (2.5, 1.0, {}, "4/2024"),
    ("Vrchlabí", "Trutnov"): (2.5, 1.0, {}, "3/2024"),
    # Pardubický kraj
    ("Chrudim", "Chrudim"): (2.0, 1.0, {}, "3/2011"),
    ("Přelouč", "Pardubice"): (2.0, 1.0, {}, "7/2024"),
    ("Litomyšl", "Svitavy"): (2.0, 3.0, {}, "4/2024"),
    ("Svitavy", "Svitavy"): (2.0, 1.0, {}, "3/2024"),
    ("Česká Třebová", "Ústí nad Orlicí"): (2.0, 1.0, {}, "5/2024"),
    ("Ústí nad Orlicí", "Ústí nad Orlicí"): (2.5, 1.0, {}, "1/2024"),
    ("Vysoké Mýto", "Ústí nad Orlicí"): (2.0, 1.0, {}, "4/2024"),
    # Kraj Vysočina
    ("Havlíčkův Brod", "Havlíčkův Brod"): (2.0, 2.3, {}, "5/2024"),
    ("Humpolec", "Pelhřimov"): (2.0, 1.0, {}, "none"),
    ("Pelhřimov", "Pelhřimov"): (2.0, 0.8, {}, "9/2025"),
    ("Třebíč", "Třebíč"): (2.5, 1.0, {}, "4/2024"),
    ("Velké Meziříčí", "Žďár nad Sázavou"): (2.0, 1.0, {}, "1/2024"),
    ("Žďár nad Sázavou", "Žďár nad Sázavou"): (2.0, 1.0, {}, "none"),
    # Jihomoravský kraj
    ("Blansko", "Blansko"): (2.0, 1.0, {}, "4/2004"),
    ("Boskovice", "Blansko"): (2.0, 1.0, {}, "none"),
    ("Kuřim", "Brno-venkov"): (2.0, 1.0, {}, "3/2024"),
    ("Břeclav", "Břeclav"): (2.5, 1.0, {}, "9/2024"),
    ("Hodonín", "Hodonín"): (2.0, 1.0, {}, "none"),
    ("Kyjov", "Hodonín"): (2.5, 1.0, {}, "11/2024"),
    ("Veselí nad Moravou", "Hodonín"): (2.0, 2.0, {}, "2/2024"),
    ("Vyškov", "Vyškov"): (2.0, 1.0, {}, "4/2024"),
    ("Znojmo", "Znojmo"): (2.5, 1.8, {}, "7/2024"),
    # Olomoucký a Zlínský kraj
    ("Jeseník", "Jeseník"): (2.0, 1.0, {}, "2/2024"),
    ("Šternberk", "Olomouc"): (2.5, 2.0, {}, "2/2024"),
    ("Uničov", "Olomouc"): (2.0, 1.0, {}, "4/2025"),
    ("Hranice", "Přerov"): (2.0, 1.0, {}, "5/2024"),
    ("Šumperk", "Šumperk"): (2.0, 1.0, {}, "none"),
    ("Zábřeh", "Šumperk"): (2.0, 1.0, {}, "none"),
    ("Holešov", "Kroměříž"): (2.0, 2.0, {}, "3/2024"),
    ("Kroměříž", "Kroměříž"): (2.5, 1.0, {}, "7/2024"),
    ("Uherské Hradiště", "Uherské Hradiště"): (2.0, 2.2, {}, "3/2023 as amended by 3/2024"),
    ("Uherský Brod", "Uherské Hradiště"): (2.0, 1.0, {}, "4/2024"),
    ("Rožnov pod Radhoštěm", "Vsetín"): (2.0, 2.5, {}, "4/2024"),
    ("Valašské Meziříčí", "Vsetín"): (2.5, 2.0, {}, "2/2024"),
    ("Vsetín", "Vsetín"): (2.5, 2.0, {}, "3/2024"),
    ("Otrokovice", "Zlín"): (2.0, 2.0, {}, "3/2024"),
    # Moravskoslezský kraj
    ("Bruntál", "Bruntál"): (2.0, 1.0, {}, "5/2024"),
    ("Krnov", "Bruntál"): (2.0, 1.0, {}, "none (8/2023 repealed its coefficient)"),
    ("Bohumín", "Karviná"): (2.0, 2.0, {}, "3/2024"),
    ("Český Těšín", "Karviná"): (2.5, 2.0, {}, "6/2024"),
    ("Orlová", "Karviná"): (2.5, 2.0, {}, "5/2024"),
    ("Frenštát pod Radhoštěm", "Nový Jičín"): (2.0, 1.0, {}, "1/2025, 9/2024 (repeals 04/2006)"),
    ("Kopřivnice", "Nový Jičín"): (2.5, 1.0, {}, "4/2025"),
    ("Nový Jičín", "Nový Jičín"): (2.5, 1.5, {}, "2/2024"),
    ("Hlučín", "Opava"): (2.0, 1.0, {}, "none"),
}


def _pair_key(pair: tuple[float, float]) -> tuple[float, float]:
    return pair[0] * pair[1], pair[0]


def _hits(text: str, needles) -> list:
    """The values of the needles found in `text`, less any found only inside a
    longer one's match ("Újezd" inside "Újezd nad Lesy")."""
    found = [(m.start(), m.end(), value) for rx, value in needles for m in rx.finditer(text)]
    return [v for s, e, v in found
            if not any(s2 <= s and e <= e2 and e2 - s2 > e - s for s2, e2, _ in found)]


def _needles(names: dict) -> list:
    return sorted(((rpcz._pattern(n), v) for n, v in names.items()),
                  key=lambda nv: len(nv[0].pattern), reverse=True)


# Prague: a quarter (část obce) or a named city part → the city parts it spans;
# "Praha N" → city part Praha N or, for N ≤ 10, the postal district of that
# name (obvod Prahy N in RÚIAN).
_PRAHA_QUARTERS = {q: parts for q, parts in _DATA.get("praha_quarters", {}).items()
                   if parts and all(p in PRAHA_DISTRICTS for p in parts)}
for _n in PRAHA_DISTRICTS:
    if not _n[-1].isdigit():
        _PRAHA_QUARTERS.setdefault(_n, [_n])
_PRAHA_NEEDLES = _needles({q: q for q in _PRAHA_QUARTERS})
_PRAHA_POSTAL = {d: [p for p in parts if p in PRAHA_DISTRICTS]
                 for d, parts in _DATA.get("praha_old_districts", {}).items()}


def _dearest(labels: list[str], pairs: dict[str, tuple[float, float]]) -> str:
    return max(labels, key=lambda lab: _pair_key(pairs[lab]))


def _praha(text: str, district: str, pairs: dict[str, tuple[float, float]] = PRAHA_DISTRICTS,
           how: str = "") -> tuple[float, float, str]:
    """Prague's pair for the city part `text` names, from `pairs` (city part →
    (size, local): PRAHA_DISTRICTS, or the update's reading for a later year)."""
    quarters = _hits(text, _PRAHA_NEEDLES)
    if quarters:
        parts = list(dict.fromkeys(p for q in quarters for p in _PRAHA_QUARTERS[q]))
        best = _dearest(parts, pairs)
        note = "" if len(parts) == 1 else f" (the dearest of {', '.join(parts)})"
        return (*pairs[best], f"{', '.join(quarters)}, Praha — city part {best}{note}{how}")
    part = rpcz.praha_district(district)
    if part in pairs:
        parts = list(dict.fromkeys([part, *_PRAHA_POSTAL.get(part, [])]))
        best = _dearest(parts, pairs)
        if len(parts) == 1:
            return (*pairs[part], part + how)
        return (*pairs[best],
                f"{part} — city part {part} or postal district {part}, the dearest of "
                f"{', '.join(parts)} ({best}){how}")
    best = _dearest(list(pairs), pairs)
    return (*pairs[best], f"Praha — its dearest city part (none named){how}")


class _Place:
    """A city or town rated by area: its own pair, its areas' pairs, and its
    quarters (části obce) → the areas or districts holding their flats."""

    def __init__(self, name: str, size: float, local: float,
                 areas: dict[str, tuple[float, float]], quarters: dict[str, list[str]],
                 rest: tuple[float, float] | None = None):
        # `pair` is charged where no area is named; `rest` (default: the
        # same) where a quarter lies in an area the ordinance doesn't list.
        self.name, self.pair, self.areas = name, (size, local), areas
        self.rest = rest or self.pair
        own = rpcz._words(name)
        self.own = rpcz._pattern(name)
        self.area_needles = _needles({a: a for a in areas})
        names = {}
        for q, targets in quarters.items():
            if rpcz._words(q) != own:
                names[q] = targets
                # "Přerov VIII-Henčlov" is also written "Henčlov".
                short = re.sub(r"^.+?\s[IVXL]+-", "", q)
                if short != q and rpcz._words(short) not in ("mesto", own):
                    names.setdefault(short, targets)
        self.quarters = names
        self.needles = _needles({**{a: ("area", a) for a in areas},
                                 **{q: ("quarter", q) for q in names}})

    def _target(self, target: str) -> tuple[float, float]:
        words = rpcz._words(target)
        for rx, area in self.area_needles:
            if rx.search(words):
                return self.areas[area]
        return self.rest

    def coefficients(self, text: str) -> tuple[float, float, str]:
        # The place's own name isn't one of its quarters: "Frýdek-Místek"
        # names neither Frýdek nor Místek.
        text = self.own.sub(" ", text, count=1)
        found: dict[str, tuple[float, float]] = {}
        for kind, label in _hits(text, self.needles):
            if kind == "area":
                found[label] = self.areas[label]
            else:
                for target in self.quarters[label]:
                    found[f"{label} ({target})"] = self._target(target)
        if not found:
            return (*self.pair, self.name)
        best = _dearest(list(found), found)
        note = "" if len(found) == 1 else " — the dearest of " + ", ".join(found)
        return (*found[best], f"{best}, {self.name}{note}")


_CITY_QUARTERS = {**_DATA.get("city_quarters", {}), "Ostrava": _DATA.get("ostrava_quarters", {})}
_CITY_PLACES = {c: _Place(c, s, lo, areas, _CITY_QUARTERS.get(c, {}))
                for c, (s, lo, areas) in CITY_COEFFICIENTS.items()}
_TOWN_PLACES = {key: _Place(key[0], s, lo, areas, _CITY_QUARTERS.get(key[0], {}))
                for key, (s, lo, areas, _) in TOWN_COEFFICIENTS.items()}

# A city's name, not the okres around it: "Plzeň-jih" and "Brno-venkov" are
# villages (Ostrava-Jih and Brno-sever are city districts).
_CITY_NOT = {"Plzeň": r"(?!\s+(?:jih|sever)(?!\w))", "Brno": r"(?!\s+venkov(?!\w))"}
_CITIES = sorted(((re.compile(rpcz._town_pattern(c).pattern + _CITY_NOT.get(c, "")), c)
                  for c in CITY_COEFFICIENTS), key=lambda pc: len(pc[1]), reverse=True)
_OKRES_WORD = re.compile(r"(?<!\w)okr(?:es)?\s+$")

# Every municipality by its folded name: [(name, okres, population)].
_MUNICIPALITIES: dict[str, list[tuple[str, str, int]]] = {}
for _name, _okres, _pop in _DATA.get("municipalities", []):
    _MUNICIPALITIES.setdefault(rpcz._words(_name), []).append((_name, _okres, int(_pop)))
# The statutory cities and Prague are found above; their namesakes elsewhere
# (a village Kladno in okres Chrudim) stay.
_CITY_OKRES = {}
for _c in [*CITY_COEFFICIENTS, "Praha"]:
    _rows = _MUNICIPALITIES.get(rpcz._words(_c), [])
    if _rows:
        _big = max(_rows, key=lambda r: r[2])
        _CITY_OKRES[_c] = _big[1]
        _MUNICIPALITIES[rpcz._words(_c)] = [r for r in _rows if r is not _big]
for _u, _town in rpcz._TOWN_U_NAMES.items():      # "Benešov u Prahy" → Benešov
    _MUNICIPALITIES.setdefault(rpcz._words(_u), _MUNICIPALITIES.get(rpcz._words(_town), []))
_BY_FIRST: dict[str, list[tuple[str, ...]]] = {}
for _w in _MUNICIPALITIES:
    if _MUNICIPALITIES[_w]:
        _BY_FIRST.setdefault(_w.split()[0], []).append(tuple(_w.split()))
for _v in _BY_FIRST.values():
    _v.sort(key=len, reverse=True)
_TAIL = {"nad", "pod", "u", "v", "ve", "na"}


def _city_hit(text: str, district: str) -> tuple[int, str] | None:
    """(position, city) of the first statutory city `text` names — not one
    named as the okres ("okres Karviná"), nor a namesake village in another
    okres ("Kladno, Chrudim")."""
    hits = []
    for rx, city in _CITIES:
        for m in rx.finditer(text):
            if not _OKRES_WORD.search(text[:m.start()]):
                hits.append((m.start(), city))
                break
    if not hits:
        return None
    pos, city = min(hits)
    okres = rpcz.okres_for_district(district)
    if okres and okres != _CITY_OKRES.get(city) and any(
            r[1] == okres for r in _MUNICIPALITIES.get(rpcz._words(city), [])):
        return None
    return pos, city


def _municipality_hit(text: str) -> tuple[int, str] | None:
    """(position, folded name) of the first municipality `text` names — not
    one named as the okres, nor the start of a longer name ("Benešov nad
    Ploučnicí")."""
    words, pos = text.split(), 0
    for i, w in enumerate(words):
        if not (i and words[i - 1] in ("okres", "okr")):
            for cand in _BY_FIRST.get(w, ()):
                n = len(cand)
                if tuple(words[i:i + n]) == cand and not (
                        len(words) > i + n + 1 and words[i + n] in _TAIL):
                    return pos, " ".join(cand)
        pos += len(w) + 1
    return None


# ── What 🏛️ UPDATE TAX RATES read (modules/tax_rates_cz) ──────────────────────
_stored: dict | None = None


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "")
                   if unicodedata.category(c) != "Mn").lower()


def reload() -> None:
    """Forget the stored coefficients: the next lookup reads them again."""
    global _stored
    _stored = None


def _load() -> dict:
    """{"places": {code: {"name", "okres", "population", "years": {year:
    (size, local, sources)}}}} from the property_tax_cz table, or {}. `size`
    and `local` map "" (the municipality) and any area that differs to its
    coefficient; `okres` is set only where municipalities share a name."""
    try:
        import database
        conn = database.get_conn()
    except Exception:
        return {}
    try:
        if not database._has_table(conn, "property_tax_cz"):
            return {}
        rows = conn.execute("SELECT code, tax_year, name, okres, population, size, local, "
                            "sources FROM property_tax_cz").fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    places: dict[str, dict] = {}
    for r in rows:
        p = places.setdefault(r["code"], {"name": r["name"], "okres": r["okres"] or "",
                                          "population": r["population"] or 0, "years": {}})
        p["years"][r["tax_year"]] = (json.loads(r["size"]), json.loads(r["local"]),
                                     json.loads(r["sources"] or "[]"))
    return {"places": places} if places else {}


def stored() -> dict:
    global _stored
    if _stored is None:
        _stored = _load()
    return _stored


def _year() -> int:
    try:
        from config import TAX_YEAR
        return int(TAX_YEAR)
    except Exception:
        from datetime import date
        return date.today().year


def _stored_place(data: dict, name: str, okres: str | None = None) -> dict | None:
    """The update's record for municipality `name`: in `okres` where several
    share the name, else the most populous of that name (a statutory city,
    not its namesake village)."""
    index = data.get("_by_name")
    if index is None:
        index = {}
        for p in data.get("places", {}).values():
            index.setdefault(rpcz._words(p["name"]), []).append(p)
        data["_by_name"] = index
    found = index.get(rpcz._words(name), [])
    if okres is not None:
        found = [p for p in found if not p.get("okres") or p["okres"] == okres]
    return max(found, key=lambda p: p.get("population") or 0) if found else None


def _reading_year(place: dict | None, year: int, table: bool) -> int | None:
    """The year of `place`'s reading in force for `year` (the latest read for
    it or before), or None. For a place in the hand-checked tables, only a
    reading after TABLE_YEAR that differs from the same reading for
    TABLE_YEAR counts — a new ordinance or a population band crossed;
    otherwise the table's reading of the same ordinances stands (as it does
    when TABLE_YEAR wasn't read: there is nothing to tell a change by)."""
    if not place:
        return None
    have = [y for y in place["years"] if y <= year]
    if not have:
        return None
    y = max(have)
    if table:
        base = place["years"].get(TABLE_YEAR)
        if y <= TABLE_YEAR or base is None or base[:2] == place["years"][y][:2]:
            return None
    return y


def _how(place: dict, y: int) -> str:
    sources = place["years"][y][2]
    what = "; ".join(sources) if sources else "no ordinance: the act's defaults"
    return f" ({what}; read by 🏛️ UPDATE TAX RATES for {y})"


def _read_place(data: dict, place: dict, y: int) -> _Place:
    """`place`'s reading for `y` as a _Place. Named nowhere, it pays its own
    area's pair (Pelhřimov's k.ú. Pelhřimov), its highest where it is rated
    by city part ("Brno-střed"), else the rest of the municipality's — the
    areas an ordinance lists apart are mostly outlying villages."""
    cache = data.setdefault("_places", {})
    key = (id(place), y)
    if key not in cache:
        size, local, _ = place["years"][y]
        rest = (size[""], local[""])
        areas = {a: (size.get(a, rest[0]), local.get(a, rest[1]))
                 for a in (set(size) | set(local)) - {""}}
        own_words = rpcz._words(place["name"])
        mine = [a for a in areas if rpcz._words(a) == own_words]
        if mine:
            own = areas[mine[0]]
        elif any(rpcz._words(a).startswith(own_words + " ") for a in areas):
            own = max([rest, *areas.values()], key=_pair_key)
        else:
            own = rest
        cache[key] = _Place(place["name"], *own, areas,
                            _CITY_QUARTERS.get(place["name"], {}), rest=rest)
    return cache[key]


def _praha_pairs(place: dict, y: int) -> dict[str, tuple[float, float]]:
    """Prague's city parts → (size, local) as the update read them for `y`."""
    size, local, _ = place["years"][y]
    keys = {rpcz._words(k): k for k in (set(size) | set(local)) - {""}}
    pairs = {}
    for part in PRAHA_DISTRICTS:
        w = rpcz._words(part)
        k = keys.get(w) or keys.get("praha " + w)
        pairs[part] = (size.get(k, size[""]), local.get(k, local[""])) if k else (size[""], local[""])
    return pairs


def in_tables(name: str, okres: str = "") -> bool:
    """Whether municipality `name` (in `okres`) is charged from the
    hand-checked tables for TABLE_YEAR."""
    if name == "Praha":
        return True
    if name in CITY_COEFFICIENTS:                  # not its namesake village elsewhere
        return not okres or okres == _CITY_OKRES.get(name, okres)
    return (name, okres) in TOWN_COEFFICIENTS


def _town(name_words: str, district: str, text: str, data: dict,
          year: int) -> tuple[float, float, str]:
    rows = _MUNICIPALITIES[name_words]
    if len(rows) > 1:
        okres = rpcz.okres_for_district(district)
        rows = [r for r in rows if r[1] == okres] or rows
    results = []
    for name, okres, pop in rows:
        in_table = (name, okres) in _TOWN_PLACES
        place = _stored_place(data, name, okres) if data else None
        y = _reading_year(place, year, in_table)
        if y is not None:
            size, local, where = _read_place(data, place, y).coefficients(text)
            results.append((size, local, f"{where} (okres {okres}){_how(place, y)}"))
        elif in_table:
            size, local, where = _TOWN_PLACES[(name, okres)].coefficients(text)
            acts = TOWN_COEFFICIENTS[(name, okres)][3]
            results.append((size, local, f"{where} (okres {okres}; OZV {acts})"))
        else:
            size = 3.5 if (name, okres) in SPA_TOWNS else population_coefficient(pop)
            results.append((size, LOCAL_COEFFICIENT,
                            f"{name} (okres {okres}): size coefficient {size:g} for "
                            f"{pop:,} people; its local coefficient UNVERIFIED "
                            "(CZ_PROPERTY_TAX_LOCAL_COEF)"))
    size, local, where = max(results, key=lambda r: _pair_key(r[:2]))
    if len(results) > 1:
        where += f" — the dearest of {len(results)} municipalities of that name"
    return size, local, where


def coefficients(district: str, year: int | None = None) -> tuple[float, float, str]:
    """(size coefficient, local coefficient, where they come from) for a flat
    in `district` in tax year `year` (default config.TAX_YEAR)."""
    data = stored()
    token = data.setdefault("_token", object()) if data.get("places") else None
    return _coefficients(district or "", year or _year(), token)


@functools.lru_cache(maxsize=8192)
def _coefficients(district: str, year: int, token) -> tuple[float, float, str]:
    # `token` names the stored reading the result was worked out from, so a
    # reload is never answered from the cache.
    data = stored() if token is not None else {}
    text = rpcz._words(district)
    if _PRAHA_RE.search(text):
        place = _stored_place(data, "Praha") if data else None
        y = _reading_year(place, year, True)
        if y is not None:
            return _praha(text, district, _praha_pairs(place, y), _how(place, y))
        return _praha(text, district)
    city = _city_hit(text, district)
    town = _municipality_hit(text)
    # "Orlová - Lutyně, Karviná": the town named first, unless it is a part
    # of the city ("Nová Ves, Ostrava").
    if city and town and town[0] < city[0] and not _hits(town[1], _CITY_PLACES[city[1]].needles):
        city = None
    if city:
        place = _stored_place(data, city[1]) if data else None
        y = _reading_year(place, year, True)
        if y is not None:
            size, local, where = _read_place(data, place, y).coefficients(text)
            return size, local, where + _how(place, y)
        return _CITY_PLACES[city[1]].coefficients(text)
    if town:
        return _town(town[1], district, text, data, year)
    return (UNKNOWN_PLACE_COEFFICIENT, LOCAL_COEFFICIENT,
            "UNVERIFIED — no municipality named; 3.5 and CZ_PROPERTY_TAX_LOCAL_COEF")


coefficients.cache_clear = _coefficients.cache_clear


def size_coefficient(district: str, year: int | None = None) -> float:
    return coefficients(district, year)[0]


def annual_tax(size_m2: float, district: str = "", year: int | None = None) -> float:
    """Kč a year for a flat of `size_m2` m² in `district` in tax year `year`,
    rounded as § 11d rounds: the base up to a whole m², each product up to a
    whole crown."""
    if not size_m2 or size_m2 <= 0:
        return 0.0
    size, local, _ = coefficients(district, year)
    base = math.ceil(size_m2 * UNIT_COEFFICIENT - 1e-9)
    tax = math.ceil(base * RATE_PER_M2 * size - 1e-9)
    tax = math.ceil(tax * INFLATION_COEFFICIENT - 1e-9)
    return float(math.ceil(tax * local - 1e-9))


SOURCE = {
    "source": (
        "zákon 338/1992 Sb. as in force from 1.10.2025 (zakonyprolidi.cz): § 10 "
        "odst. 3 (× 1.22 / 1.20), § 11 odst. 1 písm. j) (3.50 Kč/m²), § 11 odst. 4–5 "
        "(size coefficients by population; 3.5 in a statutory city and Františkovy "
        "Lázně, Luhačovice, Mariánské Lázně and Poděbrady, 4.5 in Prague; one step "
        "up by ordinance), § 11d (rounding), § 11f (inflation coefficient: CPI May "
        "2025 / May 2023 = 155.0 / 147.6 per ČSÚ, rounded down → 1.0 for 2026), "
        "§ 12 (local coefficient 0.5–5.0), § 12f (population per the RUD decree in "
        "force on 1 January: ČSÚ 'Počet obyvatel v obcích' at 1.1.2025). Statutory "
        "cities per zákon 128/2000 Sb. § 4 (version from 1.1.2026). Each city's "
        "ordinances in force for 2026, read from sbirkapp.gov.cz: Praha 11/2024 as "
        "amended by 12/2025; Ostrava 8/2024; Plzeň 2/2024; Liberec 7/2024; Olomouc "
        "7/2024; Ústí nad Labem 3/2024; Hradec Králové 6/2024; Pardubice 9/2024; "
        "Havířov 3/2024; Zlín 8/2024; Most 5/2024; Karviná 7/2024; Opava 3/2024; "
        "Frýdek-Místek 4/2024; Karlovy Vary 3/2024; Teplice 1/2024; Děčín 3/2025 "
        "(from 1.1.2026); Chomutov 3/2024; Jihlava 10/2024; Jablonec nad Nisou "
        "8/2024; Přerov 7/2024; Mladá Boleslav 5/2024; Třinec 9/2024. Brno (28/2024 "
        "repealed its coefficient), Kladno (2/2025 repealed its zones), Prostějov "
        "(7/2024 repealed its coefficient) and České Budějovice have none in force. "
        "The 105 other towns over 10,000 people, each per the ordinances named in "
        "TOWN_COEFFICIENTS (sbirkapp.gov.cz; 'none' where the register holds none "
        "in force on 1.1.2026). Prague quarters and postal districts, Ostrava "
        "quarters and the cadastral areas of quarters in cities rated by area from "
        "ČÚZK RÚIAN (31.10.2026), a place under 10% of the addresses or flats left "
        "out. Every other municipality, and a table place whose reading changed "
        "after 2026: 🏛️ UPDATE TAX RATES reads its ordinances in sbirkapp.gov.cz, "
        "its population from ČSÚ and its IČO from ARES. UNVERIFIED until that has "
        "run: the local coefficient of any other municipality "
        "(CZ_PROPERTY_TAX_LOCAL_COEF, 1.0 unless set, is used); a place that names "
        "no municipality (3.5 is used)."),
    "checked": "2026-11-04 (sbirkapp.gov.cz, zakonyprolidi.cz, csu.gov.cz, vdp.cuzk.gov.cz)",
}
