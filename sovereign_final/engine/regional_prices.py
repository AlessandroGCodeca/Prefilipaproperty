"""
engine/regional_prices.py — Sale-price floor lookup.

Used as a sanity filter to flag listings whose price/m² is far below the
expected median — typically developer-project "od €X" starting prices,
quoting errors, or non-apartment listings that slipped past other filters.

Lookup priority (most specific wins):
  1. Bratislava city part (Realitná únia, April 2026); a city part with no
     median of its own, or a bare "Bratislava I"–"Bratislava V", takes the
     weighted median of its okres's city parts
  2. Slovak city (Realitná únia, April 2026) — or, for a town in
     OKRES_TOWN_FOR, the town its okres is named for
  3. Kraj fallback (NBS Q1 2026)
  4. Global blank-district floor

The medians are for older 3-room flats. benchmark_median() adjusts one for
the listing's room count before the engine compares a price with it.

Sources:
  - Realitná únia SR — Realitný barometer, April 2026:
    https://www.realitnaunia.sk/realitny-barometer
  - NBS — Ceny nehnuteľností na bývanie podľa krajov, Q1 2026:
    https://nbs.sk/statistiky/vybrane-makroekonomicke-ukazovatele/
"""

import logging
import re

log = logging.getLogger(__name__)

# Bratislava sub-district sale-price medians €/m² (Realitná únia, April 2026,
# staršie 3-izbové byty — the most representative category for typical
# investor targets; 1-izb and 2-izb run higher per m² in every district).
BA_DISTRICT_MEDIAN_PRICE_PER_M2 = {
    "staré mesto":   4_565, "stare mesto":   4_565,
    "ružinov":       3_973, "ruzinov":       3_973,
    "nové mesto":    3_842, "nove mesto":    3_842,
    "petržalka":     3_685, "petrzalka":     3_685,
    "rača":          3_528, "raca":          3_528,
    "dúbravka":      3_583, "dubravka":      3_583,
    "karlova ves":   3_633,
    "devínska":      3_402, "devinska":      3_402,
    "podunajské":    3_315, "podunajske":    3_315,
    "vrakuňa":       3_232, "vrakuna":       3_232,
}

# Bratislava's five okresy and their city parts, named as in the table above
# ("podunajské" is Podunajské Biskupice, "devínska" Devínska Nová Ves,
# "záhorská" Záhorská Bystrica). Portals often give only "Bratislava II";
# resolving that to the city-wide median read a flat at the Vrakuňa median
# 17% below market and one at the Staré Mesto median 17% above it.
BA_OKRES_PARTS = {
    "I":   ("staré mesto",),
    "II":  ("ružinov", "vrakuňa", "podunajské"),
    "III": ("nové mesto", "rača", "vajnory"),
    "IV":  ("karlova ves", "dúbravka", "devínska", "lamač", "devín", "záhorská"),
    "V":   ("petržalka", "jarovce", "rusovce", "čunovo"),
}
# Rounded populations (2021 census) — a proxy for each part's flat stock, used
# only to weight an okres's median towards where its flats are.
_BA_PART_WEIGHT = {
    "staré mesto": 37_000, "ružinov": 83_000, "vrakuňa": 20_000,
    "podunajské": 23_000, "nové mesto": 46_000, "rača": 24_000,
    "karlova ves": 34_000, "dúbravka": 34_000, "devínska": 16_000,
    "petržalka": 110_000,
}
# Diacritic-free spellings of the city parts with no median of their own.
_BA_PART_ASCII = {"lamac": "lamač", "devin": "devín", "zahorska": "záhorská",
                  "cunovo": "čunovo"}


def _okres_median(okres: str) -> int:
    parts = [p for p in BA_OKRES_PARTS[okres] if p in BA_DISTRICT_MEDIAN_PRICE_PER_M2]
    total = sum(_BA_PART_WEIGHT[p] for p in parts)
    return round(sum(BA_DISTRICT_MEDIAN_PRICE_PER_M2[p] * _BA_PART_WEIGHT[p]
                     for p in parts) / total)


BA_OKRES_MEDIAN_PRICE_PER_M2 = {o: _okres_median(o) for o in BA_OKRES_PARTS}


def _title(name: str) -> str:
    """'ivanka pri dunaji' → 'Ivanka pri Dunaji'."""
    return " ".join(w if w in ("pri", "nad", "pod") else w.capitalize()
                    for w in name.split())


def _okres_label(okres: str) -> str:
    parts = [p for p in BA_OKRES_PARTS[okres] if p in BA_DISTRICT_MEDIAN_PRICE_PER_M2]
    if len(parts) == 1:
        return f"Bratislava {okres} ({_title(parts[0])})"
    return f"Bratislava {okres}, weighted over its city parts"
_OKRES_OF_PART = {p: o for o, parts in BA_OKRES_PARTS.items() for p in parts}
_OKRES_OF_PART.update({a: _OKRES_OF_PART[p] for a, p in _BA_PART_ASCII.items()})
# "Bratislava II", "Bratislava - IV", "okres Bratislava V".
_BA_OKRES_RE = re.compile(r"bratislava\s*[-–,]?\s*(iv|v|i{1,3})(?!\w)")

# City-level sale-price medians €/m² (Realitná únia, April 2026, staršie
# 3-izbové byty). Used when district matches a city but not a Bratislava
# sub-district.
CITY_MEDIAN_PRICE_PER_M2 = {
    "bratislava":         3_914,
    "košice":             3_196, "kosice":             3_196,
    "trnava":             2_616,
    "žilina":             2_664, "zilina":             2_664,
    "banská bystrica":    2_631, "banska bystrica":    2_631,
    "nitra":              2_467,
    "prešov":             2_482, "presov":             2_482,
    "trenčín":            2_288, "trencin":            2_288,
    "senec":              2_827,
    "pezinok":            2_764,
    "liptovský mikuláš":  2_483, "liptovsky mikulas":  2_483,
    "poprad":             2_361,
}

# Towns with no published median of their own, priced as the town their okres
# is named for. Both sit in Bratislavský kraj, whose NBS figure is Bratislava's
# own market (€3,845/m²): against it an ordinary flat in Ivanka pri Dunaji or
# Svätý Jur would read as 25–30% below market — a GREEN that isn't one. Their
# okres towns' Realitná únia medians are the nearest published figure.
OKRES_TOWN_FOR = {
    "ivanka pri dunaji": "senec",       # okres Senec
    "svätý jur":         "pezinok",     # okres Pezinok
    "svaty jur":         "pezinok",
}

# Kraj-level fallback (NBS Q1 2026). Used when district matches none of the
# cities above but matches a kraj via _DISTRICT_TO_KRAJ — covers small towns
# and villages not listed individually by Realitná únia.
REGIONAL_MEDIAN_PRICE_PER_M2 = {
    "BA": 3_845,   # Bratislavský kraj
    "TT": 2_015,   # Trnavský kraj
    "TN": 1_878,   # Trenčiansky kraj
    "NR": 1_627,   # Nitriansky kraj
    "ZA": 2_282,   # Žilinský kraj
    "BB": 1_865,   # Banskobystrický kraj
    "PO": 2_200,   # Prešovský kraj
    "KE": 2_682,   # Košický kraj
}

# The medians above are for older 3-room flats, but per m² a small flat asks
# more and a large one less. Compared with the 3-room figure, a garsónka at its
# true market price read as above market and a 4-room one as a bargain. The
# benchmark a listing is judged against is its region's median times this, by
# room count; a listing whose room count is unknown keeps the 3-room median.
# Estimates of the usual spread in Slovak asking prices — replace them with
# Realitná únia's per-category medians (1-, 2-, 3-izbové) when you have them.
MEDIAN_ROOMS_MULTIPLIER = {1: 1.15, 2: 1.07, 3: 1.00, 4: 0.95}

# Floor as a fraction of the lookup median. Listings priced below this are
# almost always dev-project starting prices, quoted wrong, or non-residential.
REGIONAL_PRICE_FLOOR_RATIO = 0.50

# Fallback floor in €/m² used when a listing has no district info. Set at
# 50% of the cheapest regional median (Nitriansky kraj, ~€1,627/m²) so we
# only reject listings priced below the cheapest plausible Slovak apartment.
GLOBAL_BLANK_DISTRICT_FLOOR = 800.0

# Ceiling as a multiple of the lookup median. A price far above the local
# median is not a luxury listing, it is the wrong number: the scrapers read the
# rendered page, and a detail page also renders an agency's other listings, so
# a price can be picked up from a neighbouring card. A live run had one
# agency's €1,250,000 property attached to seven of its unrelated flats.
#
# 4× is deliberately generous. The medians are for staršie 3-izbové byty, and
# small flats, new builds and penthouses all run well above that — a Staré
# Mesto penthouse at ~€9,900/m² sits at 2.2× its district median and passes.
# Errors of this kind are an order of magnitude out, not a factor of two.
REGIONAL_PRICE_CEILING_RATIO = 4.0

# Fallback ceiling in €/m² when a listing has no district. The priciest genuine
# Slovak apartments (Staré Mesto luxury new-builds) ask ~€10–12k/m², so €20k
# clears every real listing while still catching a 10× misread.
GLOBAL_BLANK_DISTRICT_CEILING = 20_000.0

# Map of city / district / suburb names (lowercased) → kraj code.
# Built from the same set of Slovak cities used by RENT_PER_M2 in config.py.
# Substring match: any listing whose district contains one of these wins.
_DISTRICT_TO_KRAJ = {
    # Bratislavský kraj
    "bratislava": "BA",
    "staré mesto": "BA", "stare mesto": "BA",
    "ružinov": "BA", "ruzinov": "BA",
    "vrakuňa": "BA", "vrakuna": "BA",
    "podunajské": "BA", "podunajske": "BA",
    "vajnory": "BA",
    "nové mesto": "BA", "nove mesto": "BA",
    "rača": "BA", "raca": "BA",
    "dúbravka": "BA", "dubravka": "BA",
    "karlova ves": "BA",
    "lamač": "BA", "lamac": "BA",
    "záhorská": "BA", "zahorska": "BA",
    "devínska": "BA", "devinska": "BA",
    "petržalka": "BA", "petrzalka": "BA",
    "rusovce": "BA", "jarovce": "BA", "čunovo": "BA", "cunovo": "BA",
    "senec": "BA", "pezinok": "BA", "malacky": "BA",
    "stupava": "BA", "modra": "BA",
    "ivanka pri dunaji": "BA",
    "svätý jur": "BA", "svaty jur": "BA",

    # Trnavský kraj
    "trnava": "TT",
    "dunajská streda": "TT", "dunajska streda": "TT",
    "galanta": "TT", "hlohovec": "TT",
    "piešťany": "TT", "piestany": "TT",
    "senica": "TT", "skalica": "TT",
    "šamorín": "TT", "samorin": "TT",   # okres Dunajská Streda
    "sereď": "TT", "sered": "TT",       # okres Galanta
    "holíč": "TT", "holic": "TT",       # okres Skalica

    # Trenčiansky kraj
    "trenčín": "TN", "trencin": "TN",
    "bánovce": "TN", "banovce": "TN",
    "ilava": "TN", "myjava": "TN",
    "nové mesto nad váhom": "TN", "nove mesto nad vahom": "TN",
    "partizánske": "TN", "partizanske": "TN",
    "považská bystrica": "TN", "povazska bystrica": "TN",
    "púchov": "TN", "puchov": "TN",
    "prievidza": "TN",
    "stará turá": "TN", "stara tura": "TN",
    "dubnica nad váhom": "TN", "dubnica nad vahom": "TN",
    "nová dubnica": "TN", "nova dubnica": "TN",
    "handlová": "TN", "handlova": "TN",
    "bojnice": "TN", "nováky": "TN", "novaky": "TN",

    # Nitriansky kraj
    "nitra": "NR", "komárno": "NR", "komarno": "NR",
    "levice": "NR", "nové zámky": "NR", "nove zamky": "NR",
    "šaľa": "NR", "sala": "NR",
    "topoľčany": "NR", "topolcany": "NR",
    "zlaté moravce": "NR", "zlate moravce": "NR",
    "vráble": "NR", "vrable": "NR",
    "štúrovo": "NR", "sturovo": "NR",
    "kolárovo": "NR", "kolarovo": "NR",
    "hurbanovo": "NR",

    # Žilinský kraj
    "žilina": "ZA", "zilina": "ZA",
    "bytča": "ZA", "bytca": "ZA",
    "čadca": "ZA", "cadca": "ZA",
    "kysucké nové mesto": "ZA", "kysucke nove mesto": "ZA",
    "liptovský mikuláš": "ZA", "liptovsky mikulas": "ZA",
    "námestovo": "ZA", "namestovo": "ZA",
    "ružomberok": "ZA", "ruzomberok": "ZA",
    "turčianske teplice": "ZA", "turcianske teplice": "ZA",
    "tvrdošín": "ZA", "tvrdosin": "ZA",
    "martin": "ZA", "dolný kubín": "ZA", "dolny kubin": "ZA",
    "vrútky": "ZA", "vrutky": "ZA",
    "trstená": "ZA", "trstena": "ZA",
    "turzovka": "ZA",

    # Banskobystrický kraj
    "banská bystrica": "BB", "banska bystrica": "BB",
    "banská štiavnica": "BB", "banska stiavnica": "BB",
    "brezno": "BB", "detva": "BB",
    "lučenec": "BB", "lucenec": "BB",
    "revúca": "BB", "revuca": "BB",
    "rimavská sobota": "BB", "rimavska sobota": "BB",
    "veľký krtíš": "BB", "velky krtis": "BB",
    "zvolen": "BB",
    "žiar nad hronom": "BB", "ziar nad hronom": "BB",
    "kremnica": "BB",
    "fiľakovo": "BB", "filakovo": "BB",

    # Prešovský kraj
    "prešov": "PO", "presov": "PO",
    "bardejov": "PO", "humenné": "PO", "humenne": "PO",
    "kežmarok": "PO", "kezmarok": "PO",
    "levoča": "PO", "levoca": "PO",
    "medzilaborce": "PO", "poprad": "PO",
    "sabinov": "PO", "snina": "PO",
    "stará ľubovňa": "PO", "stara lubovna": "PO",
    "stropkov": "PO",
    "vranov nad topľou": "PO", "vranov nad toplou": "PO",
    "svidník": "PO", "svidnik": "PO",
    "spišská belá": "PO", "spisska bela": "PO",
    "vysoké tatry": "PO", "vysoke tatry": "PO",

    # Košický kraj
    "košice": "KE", "kosice": "KE",
    "gelnica": "KE", "michalovce": "KE",
    "rožňava": "KE", "roznava": "KE",
    "sobrance": "KE",
    "spišská nová ves": "KE", "spisska nova ves": "KE",
    "trebišov": "KE", "trebisov": "KE",
    "krompachy": "KE",
    "moldava nad bodvou": "KE",
}

# Kraj names, for labels and the kraj-level rent fallback (engine.financial).
KRAJ_NAMES = {
    "BA": "Bratislavský kraj", "TT": "Trnavský kraj", "TN": "Trenčiansky kraj",
    "NR": "Nitriansky kraj", "ZA": "Žilinský kraj", "BB": "Banskobystrický kraj",
    "PO": "Prešovský kraj", "KE": "Košický kraj",
}

# Substrings sorted longest-first so e.g. "banská bystrica" wins over "bystrica"
# implicit in any of its child entries. Important when district strings
# concatenate multiple parts (e.g. "Banská Bystrica 974 01").
_DISTRICT_KEYS_BY_LENGTH = sorted(_DISTRICT_TO_KRAJ.keys(), key=len, reverse=True)


_BA_DISTRICT_KEYS_BY_LENGTH = sorted(
    BA_DISTRICT_MEDIAN_PRICE_PER_M2.keys(), key=len, reverse=True
)
_CITY_KEYS_BY_LENGTH = sorted(
    CITY_MEDIAN_PRICE_PER_M2.keys(), key=len, reverse=True
)
_OKRES_TOWN_KEYS_BY_LENGTH = sorted(OKRES_TOWN_FOR, key=len, reverse=True)
_BA_PART_NO_MEDIAN_BY_LENGTH = sorted(
    (p for p in _OKRES_OF_PART if p not in BA_DISTRICT_MEDIAN_PRICE_PER_M2),
    key=len, reverse=True)


def kraj_for_district(district: str) -> str | None:
    """Return the kraj code (BA/TT/...) for a district string, or None if
    the district doesn't contain a recognised Slovak place name."""
    if not district:
        return None
    key = district.lower()
    for needle in _DISTRICT_KEYS_BY_LENGTH:
        if needle in key:
            return _DISTRICT_TO_KRAJ[needle]
    return None


def median_source(district: str) -> tuple[float | None, str]:
    """(per-m² sale-price median for the listing's region, what it is the
    median of). (None, "") when the district resolves to nothing.

    Lookup chain: Bratislava city part → Bratislava okres → city (a town in
    OKRES_TOWN_FOR first takes its okres town's) → kraj. The Bratislava
    matches require "bratislava" to also appear in the district string,
    because suburb names like "Staré Mesto" or "Nové Mesto" exist in other
    Slovak cities too (e.g. Košice).
    """
    if not district:
        return None, ""
    key = district.lower()

    if "bratislava" in key:
        for needle in _BA_DISTRICT_KEYS_BY_LENGTH:
            if needle in key:
                return (BA_DISTRICT_MEDIAN_PRICE_PER_M2[needle],
                        f"{_title(needle)}, Bratislava")
        for needle in _BA_PART_NO_MEDIAN_BY_LENGTH:
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", key):
                okres = _OKRES_OF_PART[needle]
                return (BA_OKRES_MEDIAN_PRICE_PER_M2[okres],
                        f"{_okres_label(okres)} "
                        f"({_title(_BA_PART_ASCII.get(needle, needle))} has no "
                        f"median of its own)")
        m = _BA_OKRES_RE.search(key)
        if m:
            okres = m.group(1).upper()
            label = _okres_label(okres)
            if "weighted" in label:
                label += " — city part not named"
            return BA_OKRES_MEDIAN_PRICE_PER_M2[okres], label

    for needle in _OKRES_TOWN_KEYS_BY_LENGTH:
        if needle in key:
            town = OKRES_TOWN_FOR[needle]
            return (CITY_MEDIAN_PRICE_PER_M2[town],
                    f"{_title(town)} (okres town — no median for {_title(needle)})")

    for needle in _CITY_KEYS_BY_LENGTH:
        if needle in key:
            where = ("Bratislava city-wide (no city part or okres named)"
                     if needle == "bratislava" else _title(needle))
            return CITY_MEDIAN_PRICE_PER_M2[needle], where

    kraj = kraj_for_district(district)
    if kraj:
        return (REGIONAL_MEDIAN_PRICE_PER_M2[kraj],
                f"{KRAJ_NAMES[kraj]} (no median for the town itself)")

    return None, ""


def regional_median_price(district: str) -> float | None:
    """The per-m² sale-price median for the listing's region (see
    median_source), or None when the district resolves to nothing. This is
    the 3-room figure the scrapers' floor and ceiling use; the engine judges
    a listing against benchmark_median()."""
    return median_source(district)[0]


def rooms_multiplier(rooms) -> float:
    """MEDIAN_ROOMS_MULTIPLIER for a room count; 1.0 (the 3-room basis) when
    it is unknown. 4 and more rooms share the 4-room figure."""
    try:
        r = int(rooms or 0)
    except (TypeError, ValueError):
        return 1.0
    if r <= 0:
        return 1.0
    return MEDIAN_ROOMS_MULTIPLIER[min(r, 4)]


def benchmark_median(district: str, rooms=None) -> float | None:
    """The €/m² a listing's price is judged against: its region's median,
    adjusted from the 3-room basis to its room count."""
    median = regional_median_price(district)
    if median is None:
        return None
    return round(median * rooms_multiplier(rooms), 2)


def benchmark_note(district: str, rooms=None) -> str:
    """One line on what the benchmark is, for the card and the memo."""
    median, where = median_source(district)
    if median is None:
        return "No regional median for this district."
    mult = rooms_multiplier(rooms)
    note = f"median of {where}: €{median:,.0f}/m² for older 3-room flats"
    if mult != 1.0:
        note += (f", ×{mult:.2f} for a {int(rooms)}-room flat = "
                 f"€{median * mult:,.0f}/m²")
    return note


def regional_price_floor(district: str) -> float:
    """Per-m² price floor for the listing's region, or the global fallback."""
    median = regional_median_price(district)
    if median is None:
        return GLOBAL_BLANK_DISTRICT_FLOOR
    return median * REGIONAL_PRICE_FLOOR_RATIO


def regional_price_ceiling(district: str) -> float:
    """Per-m² price ceiling for the listing's region, or the global fallback."""
    median = regional_median_price(district)
    if median is None:
        return GLOBAL_BLANK_DISTRICT_CEILING
    return median * REGIONAL_PRICE_CEILING_RATIO


def is_plausible_regional_price(price_eur: float, size_m2: float, district: str) -> bool:
    """True when price/m² is at or above the floor for the listing's region
    (or above the global blank-district floor when the kraj is unknown)."""
    if not price_eur or not size_m2:
        return True
    return (price_eur / size_m2) >= regional_price_floor(district)


def is_above_regional_ceiling(price_eur: float, size_m2: float, district: str) -> bool:
    """True when price/m² is far above the region's median — which in practice
    means the price belongs to a different listing, not that this one is
    expensive. See REGIONAL_PRICE_CEILING_RATIO.

    A listing with no price or no size can't be judged, so it is left alone.
    """
    if not price_eur or not size_m2:
        return False
    return (price_eur / size_m2) > regional_price_ceiling(district)


def pick_sale_price(candidates, size_m2: float = 0.0, district: str = "") -> float:
    """Choose the sale price from every € figure found on a listing page.

    The smaller figures on a page are deposits, monthly fees, parking spots and
    per-m² rates, so the sale price is the largest — except that the page also
    renders other listings, whose prices can be larger still. When the size is
    known, anything implying an absurd €/m² for the region is dropped before
    taking the largest; those are prices belonging to a different property.

    Falls back to the plain maximum when there is no size to judge against, and
    also when every candidate looks too high — better a suspect price the
    ceiling cleanup will catch than silently no price at all.
    """
    values = [float(c) for c in (candidates or [])]
    if not values:
        return 0.0
    if size_m2 and size_m2 > 0:
        ceiling = regional_price_ceiling(district)
        within = [v for v in values if (v / size_m2) <= ceiling]
        if within:
            return max(within)
    return max(values)


def _forget_misread_prices(conn, flagged) -> None:
    """`flagged` is (listing_id, zeroed price) pairs. A zeroed price was never
    the listing's asking price, so it leaves price_history, or it would be
    read as a cut once the real price arrives. Prices seen before it stay, so
    a genuine earlier cut is still one. The score worked out at the misread is
    dropped too, so the real price is scored when it arrives."""
    from database import _drop_cashflow_score, _ensure_price_history, forget_price
    _ensure_price_history(conn)
    for listing_id, price in flagged:
        forget_price(conn, listing_id, price)
        _drop_cashflow_score(conn, listing_id)


def zero_below_regional_floor(source: str) -> int:
    """Cleanup pass: zero the price (and reset to PENDING) on rows whose
    €/m² falls below the regional floor (or the global blank-district floor
    when we can't determine the kraj)."""
    from database import get_conn
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, district, price_eur, size_m2 FROM listings "
            "WHERE source=? AND price_eur > 0 AND size_m2 > 0",
            (source,),
        ).fetchall()
        flagged: list[tuple[str, float]] = []
        for row_id, district, price, size in rows:
            if not is_plausible_regional_price(price, size, district or ""):
                flagged.append((row_id, price))
        if flagged:
            placeholders = ",".join("?" * len(flagged))
            conn.execute(
                f"UPDATE listings SET price_eur=0, classification='PENDING' "
                f"WHERE id IN ({placeholders})",
                [row_id for row_id, _ in flagged],
            )
            _forget_misread_prices(conn, flagged)
            conn.commit()
    finally:
        conn.close()
    if flagged:
        log.info(
            f"  ↳ zeroed {len(flagged)} {source} listings priced below "
            f"regional NBS floor (or €{int(GLOBAL_BLANK_DISTRICT_FLOOR)}/m² when district missing)"
        )
    return len(flagged)


def zero_above_regional_ceiling(source: str) -> int:
    """Cleanup pass: zero the price (and reset to PENDING) on rows whose €/m²
    sits far above the regional median.

    The mirror of zero_below_regional_floor, and it repairs rows already in the
    database — a price picked up from a neighbouring listing stays wrong until
    something notices, and a listing the engine thinks costs €1.25M can never
    score as a deal. Zeroing sends it back to PENDING so the next scrape
    re-reads it.
    """
    from database import get_conn
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, district, price_eur, size_m2 FROM listings "
            "WHERE source=? AND price_eur > 0 AND size_m2 > 0",
            (source,),
        ).fetchall()
        flagged: list[tuple[str, float]] = []
        for row_id, district, price, size in rows:
            if is_above_regional_ceiling(price, size, district or ""):
                flagged.append((row_id, price))
        if flagged:
            placeholders = ",".join("?" * len(flagged))
            conn.execute(
                f"UPDATE listings SET price_eur=0, classification='PENDING' "
                f"WHERE id IN ({placeholders})",
                [row_id for row_id, _ in flagged],
            )
            _forget_misread_prices(conn, flagged)
            conn.commit()
    finally:
        conn.close()
    if flagged:
        log.info(
            f"  ↳ zeroed {len(flagged)} {source} listings priced above "
            f"{REGIONAL_PRICE_CEILING_RATIO:g}× the regional median "
            f"(or €{int(GLOBAL_BLANK_DISTRICT_CEILING):,}/m² when district missing)"
        )
    return len(flagged)
