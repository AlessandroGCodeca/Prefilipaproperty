#!/usr/bin/env python3
"""
Run this from your terminal to test if scraping works from your machine:
  cd sovereign_final
  python3 test_scrape.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9",
}

print("=" * 60)
print("SITE CONNECTIVITY TEST")
print("=" * 60)

for label, url in [
    ("nehnutelnosti.sk", "https://www.nehnutelnosti.sk/slovensko/byty/predaj/?p[page]=1"),
    ("bazos.sk",          "https://reality.bazos.sk/predaj/byt/"),
]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"\n{label}: HTTP {r.status_code}")
        if r.status_code == 200:
            print(f"  ✅ Reachable! HTML length: {len(r.text)} chars")
            print(f"  First 120 chars: {r.text[:120].strip()!r}")
        else:
            print(f"  ❌ Blocked: {r.text[:100]}")
    except Exception as e:
        print(f"\n{label}: ERROR — {e}")

print()
print("=" * 60)
print("If you see ✅ above, scraping will work.")
print("Then run:  streamlit run app.py")
print("and click the NEHNUT or BAZOS buttons in the sidebar.")
print("=" * 60)
