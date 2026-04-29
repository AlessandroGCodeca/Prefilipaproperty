#!/usr/bin/env python3
"""
Inspect the rendered DOM saved by debug_playwright.py to find:
- The actual listing link pattern (since /nehnutelnost/ returns 0)
- Any embedded JSON state
- Where 'Bratislava' is mentioned (gives us the card structure)

  python3 inspect_dom.py
"""
import re, sys, json
from collections import Counter

try:
    with open("playwright_dom.html", encoding="utf-8") as f:
        html = f.read()
except FileNotFoundError:
    print("Run debug_playwright.py first")
    sys.exit(1)

print(f"Loaded playwright_dom.html ({len(html):,} chars)\n")

# ── 1. All href patterns ──────────────────────────────────────────────────────
hrefs = re.findall(r'href="([^"#?]{4,200})"', html)
print(f"Total hrefs: {len(hrefs)}")
print(f"Unique paths: {len(set(hrefs))}")

# Group by first two path segments
path_buckets = Counter()
for h in hrefs:
    if h.startswith("http"):
        path = re.sub(r'^https?://[^/]+', '', h)
    else:
        path = h
    parts = path.split("/")[:3]
    bucket = "/".join(parts)
    path_buckets[bucket] += 1

print("\nTop 20 path prefixes:")
for path, count in path_buckets.most_common(20):
    print(f"  {count:4d}  {path}")

# ── 2. Show any href that looks like a listing (numbers, long path) ──────────
listing_candidates = sorted(set(
    h for h in hrefs
    if re.search(r'/\d{6,}', h)        # has 6+ digit number
    or "detail" in h.lower()
    or "inzerat" in h.lower()
    or "advert" in h.lower()
    or "/byt" in h.lower() and len(h) > 30
))
print(f"\nListing-candidate hrefs ({len(listing_candidates)} unique):")
for h in listing_candidates[:25]:
    print(f"  {h[:150]}")

# ── 3. Find Bratislava context — what tag/attribute contains it? ─────────────
bratislava_contexts = re.findall(
    r'(<[^>]{0,150}Bratislava[^<]{0,80})', html
)
print(f"\n'Bratislava' contexts ({len(bratislava_contexts)} occurrences, showing first 6):")
for ctx in bratislava_contexts[:6]:
    print(f"  {ctx[:200]}")

# ── 4. Look for __NEXT_DATA__ or any JSON blob with listings ─────────────────
nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)
if nd:
    print("\n__NEXT_DATA__ found!")
    try:
        data = json.loads(nd.group(1))
        with open("next_data.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  saved → next_data.json")
        print(f"  top-level keys: {list(data.keys())}")
        if "props" in data:
            pp = data.get("props", {}).get("pageProps", {})
            print(f"  pageProps keys: {list(pp.keys())[:15] if isinstance(pp, dict) else type(pp)}")
    except Exception as e:
        print(f"  parse error: {e}")
else:
    print("\nNo __NEXT_DATA__ tag")

# ── 5. Look for embedded server-action data or state ─────────────────────────
sc_blobs = re.findall(r'self\.__next_f\.push\(\[1,"([^"]{50,})"\]\)', html)
print(f"\nself.__next_f.push() chunks: {len(sc_blobs)}")
for chunk in sc_blobs[:3]:
    # These are RSC payloads — look for listing-like content
    if "advert" in chunk or "byt" in chunk[:200].lower() or "Bratislava" in chunk:
        print(f"  chunk preview: {chunk[:300]}")

# ── 6. All script tags with substantial text content ─────────────────────────
script_texts = re.findall(r'<script[^>]*>([^<]{100,})</script>', html)
print(f"\nInline scripts with content: {len(script_texts)}")
for s in script_texts:
    if "advert" in s.lower() or "Bratislava" in s or "13810" in s or "predaj" in s.lower():
        print(f"  {s[:300]}")
        break

# ── 7. Find any IDs that look like advert IDs in the HTML ────────────────────
ids = re.findall(r'(?:advertId|listingId|id)["\']?\s*[:=]\s*["\']?(\d{6,12})', html)
print(f"\nNumeric IDs (6-12 digits) found: {len(set(ids))}")
print(f"  sample: {sorted(set(ids))[:10]}")
