#!/usr/bin/env python3
"""
Search the saved render HTML for API endpoints embedded in the JS bundle.
  python3 find_api.py
"""
import re, sys

fname = "render_default_render.html"
try:
    with open(fname, encoding="utf-8") as f:
        html = f.read()
    print(f"Loaded {fname} ({len(html):,} chars)")
except FileNotFoundError:
    # Try the plain version instead
    fname = "render_plain_(no_render).html"
    try:
        with open(fname, encoding="utf-8") as f:
            html = f.read()
        print(f"Loaded {fname} ({len(html):,} chars)")
    except FileNotFoundError:
        print("Run debug_render.py first to save the HTML files.")
        sys.exit(1)

print()

# ── 1. Any URL containing /api/ ─────────────────────────────────────────────
api_urls = re.findall(r'["\'`]((?:https?://[^"\'`\s]{0,30})?/api/[^"\'`\s]{5,120})["\'\`]', html)
api_urls = sorted(set(api_urls))
print(f"1. URLs containing /api/ ({len(api_urls)} found):")
for u in api_urls[:30]:
    print(f"   {u}")

print()

# ── 2. fetch() and axios calls ───────────────────────────────────────────────
fetches = re.findall(r'fetch\(["\'\`]([^"\'`\s)]{10,120})["\'\`]', html)
fetches = sorted(set(fetches))
print(f"2. fetch() URLs ({len(fetches)} found):")
for u in fetches[:20]:
    print(f"   {u}")

print()

# ── 3. GraphQL endpoints ─────────────────────────────────────────────────────
gql = re.findall(r'["\'`]([^"\'`\s]*graphql[^"\'`\s]*)["\'\`]', html, re.I)
gql = sorted(set(gql))
print(f"3. GraphQL endpoints ({len(gql)} found):")
for u in gql[:10]:
    print(f"   {u}")

print()

# ── 4. adverts / listings / search endpoints ─────────────────────────────────
listing_urls = re.findall(
    r'["\'`]((?:https?://[^"\'`\s]{0,40})?'
    r'/(?:adverts?|listings?|inzeraty|nehnutelnosti|search|byty|realitky)[^"\'`\s]{0,80})'
    r'["\'\`]',
    html
)
listing_urls = sorted(set(listing_urls))
print(f"4. Listing/advert/search-pattern URLs ({len(listing_urls)} found):")
for u in listing_urls[:30]:
    print(f"   {u}")

print()

# ── 5. window.* or __APP_CONFIG__ or similar state blobs ────────────────────
state = re.findall(r'window\.(\w+)\s*=\s*(\{.{10,200})', html)
print(f"5. window.* assignments ({len(state)} found):")
for name, val in state[:5]:
    print(f"   window.{name} = {val[:120]}")

print()

# ── 6. Environment / config key hints (API base URLs) ────────────────────────
env_urls = re.findall(
    r'(?:API_URL|apiUrl|baseURL|BASE_URL|endpoint|ENDPOINT)\s*[=:]\s*["\'`]([^"\'`\s]{8,100})["\'\`]',
    html, re.I
)
env_urls = sorted(set(env_urls))
print(f"6. API base URL config vars ({len(env_urls)} found):")
for u in env_urls[:10]:
    print(f"   {u}")
