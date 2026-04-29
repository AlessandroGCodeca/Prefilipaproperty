#!/usr/bin/env python3
"""
Download every <script src="..."> referenced in new_url.html and search
those JS bundle files for API endpoint URLs and fetch() patterns.
The real listing API will be hardcoded in one of these bundles.

  python3 find_api_in_bundle.py
"""
import re, requests, sys, os
from urllib.parse import urljoin

PAGE = "https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj?page=1"
HTML_FILE = "new_url.html"

if not os.path.exists(HTML_FILE):
    print(f"Run test_new_url.py first to create {HTML_FILE}")
    sys.exit(1)

with open(HTML_FILE, encoding="utf-8") as f:
    html = f.read()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": PAGE,
}

# Find all <script src="..."> tags (both relative and absolute)
script_srcs = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html)
script_srcs = list(dict.fromkeys(script_srcs))  # dedupe, preserve order

print(f"Found {len(script_srcs)} <script src=...> tags\n")

# Also include any obvious app-bundle paths in the HTML (covers Next.js _next/static)
extra = re.findall(r'/_next/static/[^\s"\']+\.js', html)
for e in extra:
    if e not in script_srcs:
        script_srcs.append(e)

print(f"After adding _next/static refs: {len(script_srcs)} URLs\n")

# Filter to likely-app bundles (skip 3rd-party trackers)
app_bundles = [
    s for s in script_srcs
    if any(t in s for t in ["nehnutel", "_next", "/static/", "/chunks/", "main", "app", "page"])
    and not any(t in s for t in ["googletag", "doubleclick", "facebook", "hotjar", "criteo", "google-analytics", "gtag", "smartad"])
]
print(f"Likely app bundles: {len(app_bundles)}")
for s in app_bundles[:20]:
    print(f"  {s[:120]}")

print("\n" + "=" * 60)
print("Downloading and searching bundles...")
print("=" * 60)

# Patterns to search for in JS code
api_patterns = [
    (r'["\'`]((?:https?:)?//[^"\'`\s]*nehnutelnosti\.sk/[^"\'`\s]{5,150})["\'\`]', "nehnutelnosti URL"),
    (r'["\'`](/api/[^"\'`\s]{3,120})["\'\`]', "/api/ path"),
    (r'["\'`]([^"\'`\s]*api\.nehnutelnosti[^"\'`\s]*)["\'\`]', "api.nehnutelnosti"),
    (r'["\'`](https?://[^"\'`\s]+(?:adverts?|listings?|search|results?)[^"\'`\s]{0,80})["\'\`]', "adverts/search URL"),
    (r'["\'`](/v\d+/[^"\'`\s]{3,120})["\'\`]', "/v1/ /v2/ path"),
    (r'["\'`](/graphql[^"\'`\s]*)["\'\`]', "graphql path"),
    (r'fetch\(["\'`]([^"\'`\s)]+)["\'\`]', "fetch() call"),
    (r'axios\.[a-z]+\(["\'`]([^"\'`\s)]+)["\'\`]', "axios call"),
]

all_findings: dict[str, set[str]] = {label: set() for _, label in api_patterns}

for i, src in enumerate(app_bundles):
    full = src if src.startswith("http") else urljoin(PAGE, src)
    try:
        r = requests.get(full, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  [{i+1}/{len(app_bundles)}] HTTP {r.status_code}  {full[-60:]}")
            continue
        js = r.text
        print(f"  [{i+1}/{len(app_bundles)}] {len(js):>8,} chars  {full[-60:]}")
        for regex, label in api_patterns:
            for match in re.findall(regex, js):
                if 5 < len(match) < 200:
                    all_findings[label].add(match)
    except Exception as e:
        print(f"  [{i+1}/{len(app_bundles)}] ERROR  {full[-60:]}: {e}")

print("\n" + "=" * 60)
print("FINDINGS")
print("=" * 60)

for label, urls in all_findings.items():
    if not urls:
        continue
    # Filter out static asset paths and trackers
    filtered = sorted(u for u in urls if not any(
        t in u for t in [".jpg", ".png", ".svg", ".css", ".woff",
                         "facebook.com", "google", "doubleclick",
                         "/static/", "/_next/static/", "/_next/image"]
    ))
    print(f"\n{label} ({len(filtered)} unique):")
    for u in filtered[:25]:
        print(f"  {u}")
