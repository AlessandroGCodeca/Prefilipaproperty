"""
engine/regional_prices.py — NBS sale-price regional medians.

Source: NBS "Ceny nehnuteľností na bývanie podľa krajov" (1Q 2026 baseline).
Used as a sanity filter to flag listings whose price/m² is far below the
regional median — typically developer-project "od €X" starting prices,
quoting errors, or non-apartment listings that slipped past other filters.
"""

# Regional sale-price medians in €/m² (1Q 2026)
REGIONAL_MEDIAN_PRICE_PER_M2 = {
    "BA": 3_845,   # Bratislavský kraj
    "TT": 2_015,   # Trnavský kraj
    "TN": 1_878,   # Trenčiansky kraj
    "NR": 1_627,   # Nitriansky kraj
    "ZA": 2_282,   # Žilinský kraj
    "BB": 1_865,   # Banskobystrický kraj
    "PO": 2_200,   # Prešovský kraj (NBS Q1 2026 estimate)
    "KE": 2_682,   # Košický kraj
}

# Floor as a fraction of regional median. Listings priced below this are
# almost always dev-project starting prices, quoted wrong, or non-residential.
REGIONAL_PRICE_FLOOR_RATIO = 0.50

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


def regional_price_floor(district: str) -> float | None:
    """Return the per-m² price floor for the listing's region, or None when
    the kraj can't be determined."""
    kraj = kraj_for_district(district)
    if not kraj:
        return None
    return REGIONAL_MEDIAN_PRICE_PER_M2[kraj] * REGIONAL_PRICE_FLOOR_RATIO


def is_plausible_regional_price(price_eur: float, size_m2: float, district: str) -> bool:
    """True when price/m² is at or above the regional floor (or when we can't
    determine the kraj — better to keep the listing than reject it blindly)."""
    if not price_eur or not size_m2:
        return True
    floor = regional_price_floor(district)
    if floor is None:
        return True
    return (price_eur / size_m2) >= floor


def zero_below_regional_floor(source: str) -> int:
    """Cleanup pass: zero the price (and reset to PENDING) on rows whose
    €/m² falls below the regional floor. Skips rows where the kraj can't
    be inferred — those need other validation."""
    from database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, district, price_eur, size_m2 FROM listings "
        "WHERE source=? AND price_eur > 0 AND size_m2 > 0 "
        "  AND district IS NOT NULL AND district != ''",
        (source,),
    ).fetchall()
    flagged: list[str] = []
    for row_id, district, price, size in rows:
        if not is_plausible_regional_price(price, size, district):
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
            f"{int(REGIONAL_PRICE_FLOOR_RATIO * 100)}% of regional NBS median"
        )
    return len(flagged)
