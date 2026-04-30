"""
seed_market_data.py — populate the DB with realistic Slovak market listings.
Run once to see the full app working.  Source is marked 'sample' so it's
distinct from live scraped data.
"""
import sys, os, hashlib, random
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, upsert_listing
from modules.cashflow_runner import run_scoring

random.seed(42)

LISTINGS = [
    # (title, district, price, size, energy, source_url_suffix)
    ("3-izbový byt, Dúbravka",          "Bratislava IV",   155000, 72,  "B", "ba4-dub-001"),
    ("2-izbový byt, Petržalka",          "Bratislava V",    139000, 57,  "C", "ba5-pet-002"),
    ("4-izbový byt, Ružinov",            "Bratislava II",   245000, 91,  "A", "ba2-ruz-003"),
    ("1-izbový byt, Nové Mesto",         "Bratislava III",  112000, 38,  "B", "ba3-nm-004"),
    ("3-izbový byt, Vajnory",            "Bratislava II",   168000, 68,  "C", "ba2-vaj-005"),
    ("2-izbový byt, Devínska Nová Ves",  "Bratislava IV",   125000, 52,  "B", "ba4-dnv-006"),
    ("3-izbový byt, Vrakuňa",            "Bratislava II",   143000, 71,  "D", "ba2-vra-007"),
    ("1-izbový byt, Staré Mesto",        "Bratislava I",    165000, 42,  "A", "ba1-sm-008"),
    ("2-izbový byt, Lamač",              "Bratislava IV",   137000, 55,  "B", "ba4-lam-009"),
    ("3-izbový byt, Záhorská Bystrica",  "Bratislava IV",   149000, 74,  "C", "ba4-zb-010"),
    ("2-izbový byt, centrum",            "Žilina",           98000, 58,  "B", "za-cen-011"),
    ("3-izbový byt, Solinky",            "Žilina",          118000, 76,  "C", "za-sol-012"),
    ("1-izbový byt, Vlčince",            "Žilina",           72000, 37,  "C", "za-vlc-013"),
    ("2-izbový byt, Hliny",              "Žilina",           89000, 54,  "B", "za-hli-014"),
    ("3-izbový byt, Klokočina",          "Nitra",            97000, 69,  "C", "ni-klo-015"),
    ("2-izbový byt, centrum",            "Nitra",            84000, 53,  "B", "ni-cen-016"),
    ("1-izbový byt, Chrenová",           "Nitra",            64000, 36,  "D", "ni-chr-017"),
    ("3-izbový byt, Párovce",            "Nitra",           105000, 72,  "B", "ni-par-018"),
    ("2-izbový byt, Staré Mesto",        "Košice I",         88000, 56,  "C", "ke1-sm-019"),
    ("3-izbový byt, Západ",              "Košice II",        96000, 74,  "C", "ke2-zap-020"),
    ("1-izbový byt, Sever",              "Košice III",       62000, 34,  "D", "ke3-sev-021"),
    ("2-izbový byt, Juh",                "Košice IV",        79000, 51,  "C", "ke4-juh-022"),
    ("3-izbový byt, centrum",            "Trnava",          112000, 73,  "B", "tt-cen-023"),
    ("2-izbový byt, Prednádražie",       "Trnava",           92000, 55,  "C", "tt-pred-024"),
    ("1-izbový byt, Hlohovec",           "Trnava",           65000, 35,  "C", "tt-hlo-025"),
    ("3-izbový byt, centrum",            "Trenčín",          95000, 70,  "C", "tn-cen-026"),
    ("2-izbový byt, Juh",                "Trenčín",          78000, 52,  "D", "tn-juh-027"),
    ("3-izbový byt, Sídlisko II",        "Prešov",           85000, 68,  "C", "po-s2-028"),
    ("2-izbový byt, Sekčov",             "Prešov",           72000, 50,  "D", "po-sek-029"),
    ("3-izbový byt, Banská Bystrica",    "Banská Bystrica",  88000, 71,  "C", "bb-cen-030"),
    ("2-izbový byt, Sásová",             "Banská Bystrica",  74000, 54,  "C", "bb-sas-031"),
    ("1-izbový byt, Fončorda",           "Banská Bystrica",  55000, 33,  "D", "bb-fon-032"),
    ("3-izbový byt, centrum",            "Martin",           78000, 67,  "C", "mt-cen-033"),
    ("2-izbový byt, Košúty",             "Martin",           65000, 51,  "D", "mt-kos-034"),
    ("3-izbový byt, centrum",            "Poprad",           75000, 66,  "C", "pp-cen-035"),
    ("2-izbový byt, Veľká",              "Poprad",           62000, 48,  "D", "pp-vel-036"),
    ("3-izbový byt, Aupark okolie",      "Bratislava V",    189000, 79,  "A", "ba5-aup-037"),
    ("4-izbový byt, Karlova Ves",        "Bratislava IV",   268000, 95,  "A", "ba4-kv-038"),
    ("2-izbový byt, Nivy",               "Bratislava II",   162000, 59,  "A", "ba2-niv-039"),
    ("3-izbový byt, Borská Nova Ves",    "Bratislava IV",   144000, 73,  "B", "ba4-bnv-040"),
    # Below-market / foreclosure deals → expect GREEN/YELLOW
    ("1-izb. byt (rekonštrukcia), Sever",  "Košice I",      46000, 51,  "D", "ke1-rek-041"),
    ("1-izb. byt (dražba), Západ",         "Košice II",     42000, 47,  "D", "ke2-drb-042"),
    ("2-izb. byt (rekonštrukcia), Solinky","Žilina",        52000, 58,  "D", "za-rek-043"),
    ("1-izb. byt (dražba), Klokočina",     "Nitra",         38000, 36,  "D", "ni-drb-044"),
    ("2-izb. byt (rekonštrukcia), Fončorda","Banská Bystrica",47000,53, "D", "bb-rek-045"),
    ("1-izb. byt (nízka cena), Sásová",   "Banská Bystrica",40000, 34,  "D", "bb-low-046"),
    ("2-izb. byt (investičný), Hliny",     "Žilina",        58000, 57,  "D", "za-inv-047"),
    ("1-izb. byt (pod trhom), Juh",        "Košice IV",     39000, 38,  "D", "ke4-low-048"),
    ("2-izb. byt (rekonštrukcia), Párovce","Nitra",         55000, 55,  "D", "ni-rek-049"),
    ("3-izb. byt (dražba), Košice I",      "Košice I",      68000, 72,  "D", "ke1-drb-050"),
]

def _uid(suffix):
    return hashlib.md5(f"sample:{suffix}".encode()).hexdigest()

def seed():
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for title, district, price, size, energy, suffix in LISTINGS:
        uid = _uid(suffix)
        upsert_listing({
            "id":                uid,
            "source":            "sample",
            "url":               f"https://www.nehnutelnosti.sk/sample/{suffix}",
            "url_hash":          uid,
            "title":             title,
            "description":       "",
            "price_eur":         float(price),
            "size_m2":           float(size),
            "rooms":             None,
            "floor":             None,
            "year_built":        None,
            "energy_class":      energy,
            "address_raw":       f"{title}, {district}",
            "district":          district,
            "city":              district.split()[0],
            "primary_image_url": "",
            "image_urls":        "",
            "classification":    "PENDING",
            "lv_status":         "PENDING",
            "scraped_at":        now,
            "last_seen_at":      now,
        })
        inserted += 1
    print(f"✅ Inserted {inserted} sample listings")
    scored = run_scoring()
    print(f"✅ Scored {scored} listings")
    return inserted, scored

if __name__ == "__main__":
    n, s = seed()
    print(f"Done. {n} listings, {s} scored.")
