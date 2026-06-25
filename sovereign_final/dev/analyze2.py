"""python3 analyze2.py"""
from bs4 import BeautifulSoup
import re, requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
}

# ── Nehnutelnosti: find embedded API/JSON ────────────────────────────────────
print("=== NEHNUTELNOSTI: script tags / API hints ===")
with open("nehnutelnosti_p1_200.html", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# All links – any href pattern
all_hrefs = [a.get("href","") for a in soup.find_all("a", href=True)]
listing_hrefs = [h for h in all_hrefs if re.search(r'/\d{6,}/', h) or 'byt' in h.lower() or 'nehnut' in h.lower()]
print(f"Total links: {len(all_hrefs)}, listing-like: {len(listing_hrefs)}")
for h in listing_hrefs[:8]:
    print(f"  {h}")

# Script tags with JSON or API hints
scripts = soup.find_all("script")
print(f"\nTotal <script> tags: {len(scripts)}")
for i, s in enumerate(scripts):
    src = s.get("src", "")
    content = s.string or ""
    if any(k in content for k in ['"advertId"', '"listings"', '"items"', '"results"', '"data":', 'apiUrl', 'graphql', '__NUXT__', 'initialState']):
        print(f"  Script {i} (src={src[:60]}): {content[:200]}")
    if src and ('api' in src or 'graphql' in src):
        print(f"  Script {i} SRC: {src}")

# Look for window.* assignments with data
window_vars = re.findall(r'window\.(\w+)\s*=\s*(\{.{0,300})', html)
print(f"\nwindow.* assignments: {len(window_vars)}")
for name, val in window_vars[:5]:
    print(f"  window.{name} = {val[:120]}")

# Any API URL patterns in the full HTML
api_hints = re.findall(r'https?://[^\s"\'<>]+(?:api|graphql|query|search|listing)[^\s"\'<>]{0,80}', html)
print(f"\nAPI URL patterns found: {len(api_hints)}")
for h in list(set(api_hints))[:10]:
    print(f"  {h}")

# ── Bazos: fetch /predam/byt/ and inspect cards ──────────────────────────────
print("\n=== BAZOS: fetching /predam/byt/ ===")
r = requests.get("https://reality.bazos.sk/predam/byt/", headers=HEADERS, timeout=15)
print(f"Status: {r.status_code}, size: {len(r.text)} chars")
soup2 = BeautifulSoup(r.text, "html.parser")

# Find inzerat cards
cards = soup2.select("div.inzerat, article.inzerat, div[class*='inzerat']")
print(f"Cards (div.inzerat etc): {len(cards)}")

# Find all links to /inzerat/
inz_links = soup2.select("a[href*='/inzerat/']")
print(f"Links to /inzerat/: {len(inz_links)}")
if inz_links:
    p = inz_links[0].parent
    print(f"First link parent: <{p.name} class='{p.get('class')}'>")
    gp = p.parent
    print(f"Grandparent: <{gp.name} class='{gp.get('class')}'>")

# Find pagination pattern
offset_links = [a.get("href","") for a in soup2.find_all("a", href=True) if "offset" in a.get("href","")]
print(f"Pagination (offset) links: {offset_links[:3]}")
