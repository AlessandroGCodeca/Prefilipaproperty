"""
engine/regional_prices.py — Sale-price floor lookup.

Used as a sanity filter to flag listings whose price/m² is far below the
expected median — typically developer-project "od €X" starting prices,
quoting errors, or non-apartment listings that slipped past other filters.

Lookup priority (most specific wins):
  1. Bratislava sub-district (Realitná únia, April 2026)
  2. Slovak city (Realitná únia, April 2026)
  3. Kraj fallback (NBS Q1 2026)
  4. Global blank-district floor

Sources:
  - Realitná únia SR — Realitný barometer, April 2026:
    https://www.realitnaunia.sk/realitny-barometer
  - NBS — Ceny nehnuteľností na bývanie podľa krajov, Q1 2026:
    https://nbs.sk/statistiky/vybrane-makroekonomicke-ukazovatele/
"""

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

# Floor as a fraction of the lookup median. Listings priced below this are
# almost always dev-project starting prices, quoted wrong, or non-residential.
REGIONAL_PRICE_FLOOR_RATIO = 0.50

# Fallback floor in €/m² used when a listing has no district info. Set at
# 50% of the cheapest regional median (Nitriansky kraj, ~€1,627/m²) so we
# only reject listings priced below the cheapest plausible Slovak apartment.
GLOBAL_BLANK_DISTRICT_FLOOR = 800.0

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

    # Trnavský kraj
    "trnava": "TT",
    "dunajská streda": "TT", "dunajska streda": "TT",
    "galanta": "TT", "hlohovec": "TT",
    "piešťany": "TT", "piestany": "TT",
    "senica": "TT", "skalica": "TT",

    # Trenčiansky kraj
    "trenčín": "TN", "trencin": "TN",
    "bánovce": "TN", "banovce": "TN",
    "ilava": "TN", "myjava": "TN",
    "nové mesto nad váhom": "TN", "nove mesto nad vahom": "TN",
    "partizánske": "TN", "partizanske": "TN",
    "považská bystrica": "TN", "povazska bystrica": "TN",
    "púchov": "TN", "puchov": "TN",
    "prievidza": "TN",

    # Nitriansky kraj
    "nitra": "NR", "komárno": "NR", "komarno": "NR",
    "levice": "NR", "nové zámky": "NR", "nove zamky": "NR",
    "šaľa": "NR", "sala": "NR",
    "topoľčany": "NR", "topolcany": "NR",
    "zlaté moravce": "NR", "zlate moravce": "NR",
    "vráble": "NR", "vrable": "NR",

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

    # Banskobystrický kraj
    "banská bystrica": "BB", "banska bystrica": "BB",
    "brezno": "BB", "detva": "BB",
    "lučenec": "BB", "lucenec": "BB",
    "revúca": "BB", "revuca": "BB",
    "rimavská sobota": "BB", "rimavska sobota": "BB",
    "veľký krtíš": "BB", "velky krtis": "BB",
    "zvolen": "BB",
    "žiar nad hronom": "BB", "ziar nad hronom": "BB",

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

    # Košický kraj
    "košice": "KE", "kosice": "KE",
    "gelnica": "KE", "michalovce": "KE",
    "rožňava": "KE", "roznava": "KE",
    "sobrance": "KE",
    "spišská nová ves": "KE", "spisska nova ves": "KE",
    "trebišov": "KE", "trebisov": "KE",
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


def regional_price_floor(district: str) -> float:
    """Return the per-m² price floor for the listing's region.

    Lookup chain: Bratislava sub-district → city → kraj → global fallback.
    The Bratislava sub-district match requires "bratislava" to also appear
    in the district string, because suburb names like "Staré Mesto" or
    "Nové Mesto" exist in other Slovak cities too (e.g. Košice).
    """
    if not district:
        return GLOBAL_BLANK_DISTRICT_FLOOR
    key = district.lower()

    if "bratislava" in key:
        for needle in _BA_DISTRICT_KEYS_BY_LENGTH:
            if needle in key:
                return BA_DISTRICT_MEDIAN_PRICE_PER_M2[needle] * REGIONAL_PRICE_FLOOR_RATIO

    for needle in _CITY_KEYS_BY_LENGTH:
        if needle in key:
            return CITY_MEDIAN_PRICE_PER_M2[needle] * REGIONAL_PRICE_FLOOR_RATIO

    kraj = kraj_for_district(district)
    if kraj:
        return REGIONAL_MEDIAN_PRICE_PER_M2[kraj] * REGIONAL_PRICE_FLOOR_RATIO

    return GLOBAL_BLANK_DISTRICT_FLOOR


def is_plausible_regional_price(price_eur: float, size_m2: float, district: str) -> bool:
    """True when price/m² is at or above the floor for the listing's region
    (or above the global blank-district floor when the kraj is unknown)."""
    if not price_eur or not size_m2:
        return True
    return (price_eur / size_m2) >= regional_price_floor(district)


def zero_below_regional_floor(source: str) -> int:
    """Cleanup pass: zero the price (and reset to PENDING) on rows whose
    €/m² falls below the regional floor (or the global blank-district floor
    when we can't determine the kraj)."""
    from database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, district, price_eur, size_m2 FROM listings "
        "WHERE source=? AND price_eur > 0 AND size_m2 > 0",
        (source,),
    ).fetchall()
    flagged: list[str] = []
    for row_id, district, price, size in rows:
        if not is_plausible_regional_price(price, size, district or ""):
            flagged.append(row_id)
    if flagged:
        placeholders = ",".join("?" * len(flagged))
        conn.execute(
            f"UPDATE listings SET price_eur=0, classification='PENDING' "
            f"WHERE id IN ({placeholders})",
            flagged,
        )
        conn.commit()
    conn.close()
    if flagged:
        print(
            f"  ↳ zeroed {len(flagged)} {source} listings priced below "
            f"regional NBS floor (or €{int(GLOBAL_BLANK_DISTRICT_FLOOR)}/m² when district missing)"
        )
    return len(flagged)
