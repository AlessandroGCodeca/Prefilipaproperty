#!/usr/bin/env python3
"""Quick test: does the new URL serve listings without JS rendering?"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
import requests

URL = "https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj?page=1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
}

print(f"Fetching: {URL}")
r = requests.get(URL, headers=HEADERS, timeout=15)
print(f"HTTP {r.status_code}, {len(r.text):,} chars")
html = r.text

with open("new_url.html", "w", encoding="utf-8") as f:
    f.write(html)
print("saved → new_url.html")

# Check for listing links (multiple possible patterns)
patterns = [
    ("href to /nehnutelnost/",        r'href="[^"]*nehnutelnost/'),
    ("href to /detail/",              r'href="[^"]*/detail/'),
    ("href to /inzerat/",             r'href="[^"]*/inzerat/'),
    ("href to /vysledky/.../detail",  r'href="[^"]*/vysledky/[^"]*/detail'),
    ("Bratislava text occurrences",   r'Bratislava'),
    ("€ price patterns",              r'\d{4,7}\s*€'),
    ("'izbový' (room) mentions",      r'izbov'),
    ("__NEXT_DATA__ JSON blob",       r'__NEXT_DATA__'),
    ("__NUXT__ blob",                 r'__NUXT__'),
    ("'apolloState'",                 r'apolloState'),
    ("'initialState'",                r'initialState'),
]

print()
for label, regex in patterns:
    matches = re.findall(regex, html)
    print(f"  {len(matches):4d}  {label}")

# If __NEXT_DATA__ is present, show its keys
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)
if m:
    import json
    try:
        data = json.loads(m.group(1))
        print(f"\n__NEXT_DATA__ top-level keys: {list(data.keys())}")
        if "props" in data:
            print(f"  props keys: {list(data['props'].keys())}")
            if "pageProps" in data.get("props", {}):
                pp = data["props"]["pageProps"]
                print(f"  pageProps keys: {list(pp.keys()) if isinstance(pp, dict) else type(pp)}")
    except Exception as e:
        print(f"\n__NEXT_DATA__ parse error: {e}")

# Show first listing link if any
m = re.search(r'href="(/[^"]*(?:nehnutelnost|detail|inzerat)[^"]+)"', html)
if m:
    print(f"\nFirst listing href: {m.group(1)[:120]}")
