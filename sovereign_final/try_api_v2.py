#!/usr/bin/env python3
"""
Test known API base https://www.nehnutelnosti.sk/api/v2 with various
listing endpoint patterns. Also tries POST since DevTools showed
'internal-filter' returning 201 (likely a POST filter endpoint).

  python3 try_api_v2.py
"""
import requests, json, sys

BASE = "https://www.nehnutelnosti.sk/api/v2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9",
    "Referer": "https://www.nehnutelnosti.sk/vysledky/byty/slovensko/predaj",
    "Origin": "https://www.nehnutelnosti.sk",
    "Content-Type": "application/json",
}

# ── GET candidates ────────────────────────────────────────────────────────────
get_tests = [
    f"{BASE}/adverts?category=BYTY&transaction=SELL&page=1&limit=24",
    f"{BASE}/adverts?categoryId=2&transactionType=SELL&page=1",
    f"{BASE}/adverts/search?category=BYTY&transaction=SELL&page=1",
    f"{BASE}/search?category=BYTY&transaction=SELL&page=1",
    f"{BASE}/listings?type=BYTY&action=SELL&page=1",
    f"{BASE}/results?category=BYTY&transaction=SELL&page=1",
    f"{BASE}/estates?category=BYTY&transaction=SELL&page=1",
    f"{BASE}/offers?category=BYTY&transaction=SELL&page=1",
    f"{BASE}/adverts?offerType=SELL&estateType=BYTY&page=1",
]

# ── POST candidates ───────────────────────────────────────────────────────────
# The 'internal-filter' and 'count' XHR calls returned 201 → likely POST
post_tests = [
    (f"{BASE}/adverts/filter", {
        "transaction": "SELL", "category": "BYTY", "page": 1, "limit": 24,
        "location": {"code": "SK", "type": "COUNTRY"}
    }),
    (f"{BASE}/adverts/search", {
        "transaction": "SELL", "categoryName": "BYTY", "page": 1, "limit": 24
    }),
    (f"{BASE}/search", {
        "category": "BYTY", "transaction": "SELL", "page": 1,
        "filters": {}, "sort": "DEFAULT"
    }),
    (f"{BASE}/filter", {
        "offerType": "SELL", "estateType": "BYTY", "page": 1
    }),
    (f"{BASE}/adverts", {
        "transaction": "SELL", "category": "BYTY", "page": 1
    }),
    (f"{BASE}/count", {
        "transaction": "SELL", "category": "BYTY"
    }),
    (f"{BASE}/internal-filter", {
        "transaction": "SELL", "category": "BYTY", "page": 1,
        "location": "SK"
    }),
]

def check_body(body: str) -> str:
    """Return a quick summary of what the body contains."""
    if not body.strip():
        return "(empty)"
    try:
        d = json.loads(body)
        if isinstance(d, list):
            return f"JSON array, {len(d)} items, first keys: {list(d[0].keys())[:5] if d else '?'}"
        if isinstance(d, dict):
            keys = list(d.keys())
            # Look for listing-like keys
            listing_keys = [k for k in keys if any(
                w in k.lower() for w in ["advert", "listing", "result", "item", "data", "offer", "estate"]
            )]
            if listing_keys:
                count_hint = ""
                for lk in listing_keys:
                    v = d[lk]
                    count_hint = f" → {lk}={len(v) if isinstance(v, list) else v!r:.40}"
                return f"JSON dict keys={keys[:6]}{count_hint}"
            return f"JSON dict keys={keys[:8]}"
    except Exception:
        pass
    return f"non-JSON ({body[:80].strip()!r})"

print("=" * 60)
print("GET requests")
print("=" * 60)
for url in get_tests:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        summary = check_body(r.text)
        print(f"\n  HTTP {r.status_code}  {url[len(BASE):]}")
        print(f"  → {summary}")
    except Exception as e:
        print(f"\n  ERR  {url[len(BASE):]}: {e}")

print()
print("=" * 60)
print("POST requests")
print("=" * 60)
for url, payload in post_tests:
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=12)
        summary = check_body(r.text)
        print(f"\n  HTTP {r.status_code}  {url[len(BASE):]}")
        print(f"  payload: {list(payload.keys())}")
        print(f"  → {summary}")
    except Exception as e:
        print(f"\n  ERR  {url[len(BASE):]}: {e}")
