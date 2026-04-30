#!/usr/bin/env python3
"""
Test if curl_cffi (TLS-fingerprint-mimicking library) can bypass the
Imperva/Incapsula WAF blocking our /api/v2 calls.

Install first:
  pip install curl_cffi

Then run:
  python3 try_curl_cffi.py
"""
import sys, json

try:
    from curl_cffi import requests
except ImportError:
    print("❌ curl_cffi not installed. Run: pip install curl_cffi")
    sys.exit(1)

# These are the same endpoints that returned 403 with python-requests
endpoints = [
    f"https://www.nehnutelnosti.sk/api/v2/adverts?category=BYTY&transaction=SELL&page=1&limit=24",
    f"https://www.nehnutelnosti.sk/api/v2/adverts/search?category=BYTY&transaction=SELL&page=1",
    f"https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj?page=1",
]

HEADERS = {
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
    "Referer": "https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj",
}

# Try multiple impersonation profiles
profiles = ["chrome120", "chrome131", "safari17_2_ios", "edge101"]

for profile in profiles:
    print(f"\n{'='*60}")
    print(f"Impersonation: {profile}")
    print('='*60)
    for url in endpoints:
        try:
            r = requests.get(url, headers=HEADERS, impersonate=profile, timeout=15)
            short = url.replace("https://www.nehnutelnosti.sk", "")[:80]
            print(f"\n  HTTP {r.status_code}  {short}")
            print(f"  {len(r.text):,} chars")
            if r.status_code == 200:
                try:
                    d = r.json()
                    keys = list(d.keys()) if isinstance(d, dict) else f"list[{len(d)}]"
                    print(f"  ✅ JSON: {keys}")
                    # save for inspection
                    fname = f"resp_{profile}_{short.replace('/', '_').replace('?', '_')[:40]}.json"
                    with open(fname, "w") as f:
                        json.dump(d, f, indent=2, ensure_ascii=False)
                    print(f"  saved → {fname}")
                except Exception:
                    # HTML response — count listing-link hrefs
                    nehnut_links = r.text.count('/nehnutelnost/')
                    print(f"  HTML — /nehnutelnost/ count: {nehnut_links}")
                    if nehnut_links > 0 or "Bratislava" in r.text:
                        with open(f"resp_{profile}.html", "w") as f:
                            f.write(r.text)
                        print(f"  ✅ has property data — saved")
            else:
                print(f"  body: {r.text[:120]}")
        except Exception as e:
            print(f"  ❌ {e}")
