"""
Run this on your Mac to capture the actual HTML both sites return.
  cd sovereign_final
  source venv/bin/activate
  python3 debug_html.py

It saves nehnutelnosti.html and bazos.html so we can inspect the real structure.
"""
import requests, sys, os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

tests = [
    ("nehnutelnosti_p1", "https://www.nehnutelnosti.sk/slovensko/byty/predaj/?p[page]=1"),
    ("bazos_root",       "https://reality.bazos.sk/"),
    ("bazos_byty",       "https://reality.bazos.sk/byty/predaj/"),
    ("bazos_predaj",     "https://reality.bazos.sk/predaj/byty/"),
    ("bazos_inzeraty",   "https://reality.bazos.sk/inzeraty/"),
]

for name, url in tests:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        fname = f"{name}_{r.status_code}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"{r.status_code}  {url}")
        print(f"       → saved {fname} ({len(r.text)} chars)")
        # Show first 3 class names found to hint at structure
        import re
        classes = re.findall(r'class="([^"]{5,40})"', r.text)[:5]
        print(f"       → sample classes: {classes}")
    except Exception as e:
        print(f"ERR  {url}: {e}")
    print()
