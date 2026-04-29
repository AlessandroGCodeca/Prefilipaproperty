#!/usr/bin/env python3
"""
Save the ScraperAPI-rendered nehnutelnosti page and inspect its contents.
  source venv/bin/activate
  python3 debug_render.py
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
import requests
from config import SCRAPER_API_KEY

if not SCRAPER_API_KEY:
    print("❌ SCRAPER_API_KEY not set in .env"); sys.exit(1)

URL = "https://www.nehnutelnosti.sk/slovensko/byty/predaj/?p[page]=1"

# Try several render strategies
configs = [
    ("default render",         f"&render=true"),
    ("render + sk + wait3s",   f"&render=true&country_code=sk&wait=3000"),
    ("render + premium",       f"&render=true&premium=true"),
    ("render + wait_for href", f"&render=true&wait_for_selector=a%5Bhref*%3D%22%2Fnehnutelnost%2F%22%5D"),
    ("plain (no render)",      ""),
]

for label, suffix in configs:
    encoded = requests.utils.quote(URL, safe="")
    proxy = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={encoded}{suffix}"
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    try:
        r = requests.get(proxy, timeout=120)
        print(f"HTTP {r.status_code}, {len(r.text):,} chars")
        if r.status_code == 200:
            html = r.text
            fname = f"render_{label.replace(' ','_').replace('+','').replace('__','_')}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  saved → {fname}")

            # Quick inspection
            nehnut_links   = len(re.findall(r'href="[^"]*nehnutelnost/', html))
            href_count     = len(re.findall(r'href="', html))
            script_count   = len(re.findall(r'<script', html))
            has_loading    = "loading" in html.lower() or "skeleton" in html.lower()
            has_byty       = "izbov" in html.lower() or "byt" in html.lower()
            mentions_price = len(re.findall(r'\d{4,7}\s*(?:€|EUR)', html))
            captcha        = "captcha" in html.lower() or "cloudflare" in html.lower() or "incapsula" in html.lower()

            print(f"  /nehnutelnost/ hrefs:  {nehnut_links}")
            print(f"  total hrefs:           {href_count}")
            print(f"  script tags:           {script_count}")
            print(f"  €-prices in text:      {mentions_price}")
            print(f"  mentions byt/izbový:   {has_byty}")
            print(f"  mentions loading:      {has_loading}")
            print(f"  CAPTCHA/WAF present:   {captcha}")

            # Show first listing-link if any
            m = re.search(r'href="([^"]*nehnutelnost/[^"]+)"', html)
            if m:
                print(f"  sample listing href:   {m.group(1)[:100]}")

            # Show title to confirm we got the right page
            title = re.search(r'<title>([^<]+)</title>', html)
            if title:
                print(f"  page <title>:          {title.group(1)[:100]}")
        else:
            print(f"  body: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ {e}")
