#!/usr/bin/env python3
"""
Debug topreality.sk: fetch the search page and print:
  - all unique href patterns (so we can identify the listing-detail format)
  - any 'next page' / pagination links
  - count of likely-listing links per pattern guess

  python3 debug_topreality.py
"""
import re
from collections import Counter
from urllib.parse import urlparse

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from scraper._http import get, make_session

URL = "https://www.topreality.sk/vyhladavanie/byty/predaj?page=1"
URL_P2 = "https://www.topreality.sk/vyhladavanie/byty/predaj?page=2"

print(f"Fetching {URL} ...")
sess = make_session()
r = get(URL, session=sess, timeout=25)
print(f"Page 1: HTTP {r.status_code}, {len(r.text):,} chars")

# Save for inspection
with open("topreality_p1.html", "w") as f:
    f.write(r.text)
print(f"Saved → topreality_p1.html\n")

html = r.text

# All hrefs
hrefs = re.findall(r'href="([^"#]{4,300})"', html)
hrefs = [h for h in hrefs if not h.startswith("javascript")]
print(f"Total hrefs: {len(hrefs)}")
print(f"Unique hrefs: {len(set(hrefs))}\n")

# Bucket by first two path segments (where the listing structure lives)
buckets = Counter()
for h in hrefs:
    if h.startswith("http"):
        path = urlparse(h).path
    else:
        path = h
    parts = path.split("/")[:3]
    bucket = "/".join(parts)
    buckets[bucket] += 1

print("Top 25 path prefixes:")
for path, n in buckets.most_common(25):
    print(f"  {n:4d}  {path}")

# Show samples that contain digits (likely listing IDs)
print("\nHrefs containing 4+ digits (likely listing IDs):")
samples_with_id = sorted(set(h for h in hrefs if re.search(r"\d{4,}", h)))
for h in samples_with_id[:30]:
    print(f"  {h[:140]}")

# Look for pagination — anchors with text 'Ďalšia' / next / page numbers
print("\nLikely pagination links:")
for m in re.finditer(
    r'<a[^>]+href="([^"#]+)"[^>]*>([^<]{1,30})</a>',
    html,
):
    href, txt = m.group(1), m.group(2).strip()
    if re.search(r"(strana|page|stran|další|ďalš|next|»)", txt + href, re.I):
        if len(href) < 200:
            print(f"  {txt[:30]:<30} → {href}")

# Compare with page 2 to verify pagination actually changes results
print(f"\n\nFetching {URL_P2} for comparison...")
r2 = get(URL_P2, session=sess, timeout=25)
print(f"Page 2: HTTP {r2.status_code}, {len(r2.text):,} chars")
if r.text == r2.text:
    print("⚠️  page 2 HTML is IDENTICAL to page 1 — pagination param wrong")
else:
    diff = sum(1 for a, b in zip(r.text, r2.text) if a != b)
    print(f"✓ page 2 differs from page 1 ({diff:,} char diff)")

# Try alternative pagination patterns
alt_urls = [
    "https://www.topreality.sk/vyhladavanie/byty/predaj?strana=2",
    "https://www.topreality.sk/vyhladavanie/byty/predaj/strana-2",
    "https://www.topreality.sk/vyhladavanie/byty/predaj/2",
    "https://www.topreality.sk/vyhladavanie/byty/predaj?p=2",
]
print("\nProbing alternative pagination params:")
for u in alt_urls:
    r3 = get(u, session=sess, timeout=15)
    same_as_p1 = (r3.text == r.text) if r3.status_code == 200 else None
    same_str = "SAME as p1" if same_as_p1 else ("DIFFERS" if r3.status_code == 200 else "")
    print(f"  {r3.status_code}  {u}  {same_str}")
