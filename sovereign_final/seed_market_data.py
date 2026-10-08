"""
seed_market_data.py — populate the DB with realistic Slovak market listings.
Run once to see the full app working.  Source is marked 'sample' so it's
distinct from live scraped data (the dashboard's Source filter lists it).

Each asking price is set against the engine's own benchmark — the regional
median adjusted for the room count (engine/regional_prices.benchmark_median)
— so the mix looks like a real feed — mostly at market, a few YELLOW, fewer
GREEN — and stays that way when the medians are updated. Fixed prices had
drifted to 34 GREEN of 50 against today's medians.
"""
import sys, os, hashlib, random
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, upsert_listing
from engine.regional_prices import benchmark_median
from modules.cashflow_runner import run_scoring
from scraper.textparse import rooms_from_title

random.seed(42)

LISTINGS = [
    # (title, district, asking €/m² as a share of the regional median, size, energy, source_url_suffix)
    ("3-izbový byt, Dúbravka",          "Bratislava IV",   1.02, 72,  "B", "ba4-dub-001"),
    ("2-izbový byt, Petržalka",          "Bratislava V",    0.96, 57,  "C", "ba5-pet-002"),
    ("4-izbový byt, Ružinov",            "Bratislava II",   1.08, 91,  "A", "ba2-ruz-003"),
    ("1-izbový byt, Nové Mesto",         "Bratislava III",  1.12, 38,  "B", "ba3-nm-004"),
    ("3-izbový byt, Vajnory",            "Bratislava II",   0.94, 68,  "C", "ba2-vaj-005"),
    ("2-izbový byt, Devínska Nová Ves",  "Bratislava IV",   0.87, 52,  "B", "ba4-dnv-006"),
    ("3-izbový byt, Vrakuňa",            "Bratislava II",   0.93, 71,  "D", "ba2-vra-007"),
    ("1-izbový byt, Staré Mesto",        "Bratislava I",    1.15, 42,  "A", "ba1-sm-008"),
    ("2-izbový byt, Lamač",              "Bratislava IV",   0.97, 55,  "B", "ba4-lam-009"),
    ("3-izbový byt, Záhorská Bystrica",  "Bratislava IV",   0.95, 74,  "C", "ba4-zb-010"),
    ("2-izbový byt, centrum",            "Žilina",          1.05, 58,  "B", "za-cen-011"),
    ("3-izbový byt, Solinky",            "Žilina",          0.98, 76,  "C", "za-sol-012"),
    ("1-izbový byt, Vlčince",            "Žilina",          1.04, 37,  "C", "za-vlc-013"),
    ("2-izbový byt, Hliny",              "Žilina",          0.96, 54,  "B", "za-hli-014"),
    ("3-izbový byt, Klokočina",          "Nitra",           0.94, 69,  "C", "ni-klo-015"),
    ("2-izbový byt, centrum",            "Nitra",           1.06, 53,  "B", "ni-cen-016"),
    ("1-izbový byt, Chrenová",           "Nitra",           0.86, 36,  "D", "ni-chr-017"),
    ("3-izbový byt, Párovce",            "Nitra",           1.01, 72,  "B", "ni-par-018"),
    ("2-izbový byt, Staré Mesto",        "Košice I",        1.09, 56,  "C", "ke1-sm-019"),
    ("3-izbový byt, Západ",              "Košice II",       0.95, 74,  "C", "ke2-zap-020"),
    ("1-izbový byt, Sever",              "Košice III",      1.00, 34,  "D", "ke3-sev-021"),
    ("2-izbový byt, Juh",                "Košice IV",       0.93, 51,  "C", "ke4-juh-022"),
    ("3-izbový byt, centrum",            "Trnava",          1.07, 73,  "B", "tt-cen-023"),
    ("2-izbový byt, Prednádražie",       "Trnava",          0.97, 55,  "C", "tt-pred-024"),
    ("1-izbový byt, Hlohovec",           "Trnava",          0.88, 35,  "C", "tt-hlo-025"),
    ("3-izbový byt, centrum",            "Trenčín",         1.03, 70,  "C", "tn-cen-026"),
    ("2-izbový byt, Juh",                "Trenčín",         0.95, 52,  "D", "tn-juh-027"),
    ("3-izbový byt, Sídlisko II",        "Prešov",          0.99, 68,  "C", "po-s2-028"),
    ("2-izbový byt, Sekčov",             "Prešov",          0.94, 50,  "D", "po-sek-029"),
    ("3-izbový byt, Banská Bystrica",    "Banská Bystrica", 1.02, 71,  "C", "bb-cen-030"),
    ("2-izbový byt, Sásová",             "Banská Bystrica", 0.96, 54,  "C", "bb-sas-031"),
    ("1-izbový byt, Fončorda",           "Banská Bystrica", 1.04, 33,  "D", "bb-fon-032"),
    ("3-izbový byt, centrum",            "Martin",          1.00, 67,  "C", "mt-cen-033"),
    ("2-izbový byt, Košúty",             "Martin",          0.93, 51,  "D", "mt-kos-034"),
    ("3-izbový byt, centrum",            "Poprad",          1.06, 66,  "C", "pp-cen-035"),
    ("2-izbový byt, Veľká",              "Poprad",          0.97, 48,  "D", "pp-vel-036"),
    ("3-izbový byt, Aupark okolie",      "Bratislava V",    1.10, 79,  "A", "ba5-aup-037"),
    ("4-izbový byt, Karlova Ves",        "Bratislava IV",   1.05, 95,  "A", "ba4-kv-038"),
    ("2-izbový byt, Nivy",               "Bratislava II",   1.18, 59,  "A", "ba2-niv-039"),
    ("3-izbový byt, Borská Nova Ves",    "Bratislava IV",   0.98, 73,  "B", "ba4-bnv-040"),
    # Below-market / foreclosure deals → expect GREEN (≤0.78) or YELLOW (0.82–0.87)
    ("1-izb. byt (rekonštrukcia), Sever",  "Košice I",      0.84, 51,  "D", "ke1-rek-041"),
    ("1-izb. byt (dražba), Západ",         "Košice II",     0.74, 47,  "D", "ke2-drb-042"),
    ("2-izb. byt (rekonštrukcia), Solinky","Žilina",        0.83, 58,  "D", "za-rek-043"),
    ("1-izb. byt (dražba), Klokočina",     "Nitra",         0.72, 36,  "D", "ni-drb-044"),
    ("2-izb. byt (rekonštrukcia), Fončorda","Banská Bystrica",0.85,53, "D", "bb-rek-045"),
    ("1-izb. byt (nízka cena), Sásová",   "Banská Bystrica",0.77, 34,  "D", "bb-low-046"),
    ("2-izb. byt (investičný), Hliny",     "Žilina",        0.87, 57,  "D", "za-inv-047"),
    ("1-izb. byt (pod trhom), Juh",        "Košice IV",     0.76, 38,  "D", "ke4-low-048"),
    ("2-izb. byt (rekonštrukcia), Párovce","Nitra",         0.82, 55,  "D", "ni-rek-049"),
    ("3-izb. byt (dražba), Košice I",      "Košice I",      0.75, 72,  "D", "ke1-drb-050"),
]

def _uid(suffix):
    return hashlib.md5(f"sample:{suffix}".encode()).hexdigest()

def seed():
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for title, district, vs_market, size, energy, suffix in LISTINGS:
        uid = _uid(suffix)
        rooms = rooms_from_title(title)
        price = round(benchmark_median(district, rooms) * size * vs_market, -3)
        upsert_listing({
            "id":                uid,
            "source":            "sample",
            "url":               f"https://www.nehnutelnosti.sk/sample/{suffix}",
            "url_hash":          uid,
            "title":             title,
            "description":       "",
            "price_eur":         float(price),
            "size_m2":           float(size),
            "rooms":             rooms,
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
