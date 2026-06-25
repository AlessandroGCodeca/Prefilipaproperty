#!/usr/bin/env python3
"""
Run this from your Mac terminal to verify scraping will work:
  cd sovereign_final
  python3 test_scrape.py

It checks site reachability, nehnutelnosti API endpoints, and bazos card structure.
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8",
}

API_HEADERS = {**HEADERS, "Accept": "application/json,*/*;q=0.8"}

sep = "=" * 60


# ── 1. Site reachability ──────────────────────────────────────────────────────
print(sep)
print("1. SITE REACHABILITY")
print(sep)

sites = [
    ("nehnutelnosti.sk", "https://www.nehnutelnosti.sk/slovensko/byty/predaj/?p[page]=1"),
    ("bazos.sk",         "https://reality.bazos.sk/predam/byt/"),
]

reachable = {}
for label, url in sites:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        ok = r.status_code == 200
        reachable[label] = ok
        mark = "✅" if ok else "❌"
        print(f"\n{mark} {label}: HTTP {r.status_code}  ({len(r.text):,} chars)")
        if not ok:
            print(f"   {r.text[:120].strip()!r}")
    except Exception as e:
        reachable[label] = False
        print(f"\n❌ {label}: ERROR — {e}")


# ── 2. Nehnutelnosti API candidates ──────────────────────────────────────────
print(f"\n{sep}")
print("2. NEHNUTELNOSTI — JSON API CANDIDATES")
print(sep)
print("(The site is a React SPA; we need their JSON API to get listings)")

NEHNUT_API_CANDIDATES = [
    "https://www.nehnutelnosti.sk/api/v1/adverts/search?transaction=SELL&category=BYTY&page=1&limit=24&location=SLOVENSKO",
    "https://www.nehnutelnosti.sk/api/v2/search?offerType=SELL&estateType=BYTY&page=1&pageSize=24",
    "https://www.nehnutelnosti.sk/api/v1/search?transaction=SELL&category=BYTY&page=1",
]

working_api = None
for url in NEHNUT_API_CANDIDATES:
    try:
        r = requests.get(url, headers=API_HEADERS, timeout=12)
        print(f"\n  HTTP {r.status_code}  {url[:70]}")
        if r.status_code == 200:
            try:
                data = r.json()
                raw = json.dumps(data)
                listing_count = (
                    len(data) if isinstance(data, list)
                    else len(data.get("items") or data.get("results") or
                             data.get("adverts") or data.get("data") or [])
                )
                if listing_count > 0:
                    print(f"  ✅ WORKS! Returns {listing_count} listings")
                    if not working_api:
                        working_api = url
                else:
                    # Show top-level keys so we can adjust parsing
                    keys = list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]"
                    print(f"  ⚠️  JSON OK but 0 listings — keys: {keys}")
            except Exception:
                print(f"  ⚠️  Not JSON — first 120 chars: {r.text[:120]!r}")
        else:
            print(f"  ❌  {r.text[:80]!r}")
    except Exception as e:
        print(f"\n  ❌  {url[:70]}: {e}")

if working_api:
    print(f"\n>>> CONFIRMED API: {working_api}")
    print("    Paste this URL back to get it hardcoded into the scraper.")
else:
    print("\n>>> None of the API candidates worked.")
    print("    The scraper will fall back to ScraperAPI render=True (headless Chrome).")
    print("    Make sure SCRAPER_API_KEY is set in sovereign_final/.env")


# ── 3. Bazos card structure ───────────────────────────────────────────────────
print(f"\n{sep}")
print("3. BAZOS — CARD STRUCTURE")
print(sep)

try:
    r = requests.get("https://reality.bazos.sk/predam/byt/", headers=HEADERS, timeout=12)
    print(f"HTTP {r.status_code}  ({len(r.text):,} chars)")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")

        # Test each selector the scraper will try
        selectors = [
            "div.inzeraty div.inzerat",
            "div.maincontent div.inzerat",
            "div.inzerat",
            "div[class*='inzerat']",
            "a[href*='/inzerat/']",
        ]
        for sel in selectors:
            found = soup.select(sel)
            mark = "✅" if found else "  "
            print(f"  {mark} {sel!r:40s} → {len(found)} matches")

        # Show parent structure of first /inzerat/ link
        inz = soup.select("a[href*='/inzerat/']")
        if inz:
            link = inz[0]
            print(f"\n  First /inzerat/ link: {link.get('href','')[:60]}")
            p = link.parent
            for i in range(5):
                cls = " ".join(p.get("class") or [])[:50] if p else ""
                print(f"  {'  ' * i}<{p.name} class='{cls}'>") if p else None
                p = p.parent if p else None

        # Pagination check
        offsets = [a.get("href","") for a in soup.find_all("a", href=True)
                   if "offset" in a.get("href","")]
        print(f"\n  Offset pagination links: {offsets[:3] or 'none (may use path-based /predam/byt/20/)'}")

        # Sample first listing
        first_inz = soup.select_one("div.inzerat, a[href*='/inzerat/']")
        if first_inz:
            text = first_inz.get_text(" ", strip=True)[:150]
            print(f"\n  Sample card text: {text!r}")
    else:
        print(f"  ❌ {r.text[:120]!r}")
except Exception as e:
    print(f"❌ ERROR — {e}")


# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{sep}")
print("SUMMARY")
print(sep)
for label, ok in reachable.items():
    print(f"  {'✅' if ok else '❌'} {label} reachable")
if working_api:
    print(f"  ✅ Nehnutelnosti API confirmed — scraper will use JSON API")
else:
    print(f"  ⚠️  Nehnutelnosti API unknown — scraper will use ScraperAPI render=True")
print()
print("Next: streamlit run app.py  →  click NEHNUT or BAZOS in sidebar")
print(sep)
