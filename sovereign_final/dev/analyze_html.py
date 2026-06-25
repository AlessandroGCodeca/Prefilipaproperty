"""
Run after debug_html.py to analyze the saved HTML files.
  python3 analyze_html.py
"""
from bs4 import BeautifulSoup
import json, re

# ── Nehnutelnosti ─────────────────────────────────────────────────────────────
print("=" * 60)
print("NEHNUTELNOSTI")
print("=" * 60)
try:
    with open("nehnutelnosti_p1_200.html", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # 1. Check for Next.js embedded JSON
    nd = soup.find("script", {"id": "__NEXT_DATA__"})
    if nd:
        print("✅ Found __NEXT_DATA__ (Next.js SSR) — extracting listings...")
        data = json.loads(nd.string)
        # Try to find listing arrays anywhere in the tree
        raw = json.dumps(data)
        urls = re.findall(r'"url"\s*:\s*"(https://www\.nehnutelnosti\.sk/nehnutelnost/[^"]+)"', raw)
        prices = re.findall(r'"price(?:Value|Amount|Eur)?"\s*:\s*(\d+)', raw)
        print(f"  Listing URLs found: {len(urls)}")
        print(f"  Prices found: {len(prices)}")
        if urls:
            print(f"  Sample URL: {urls[0]}")
        # Save trimmed JSON for inspection
        with open("next_data.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  Full JSON saved to next_data.json")
    else:
        print("❌ No __NEXT_DATA__ found")

    # 2. Count links to listing pages
    links = soup.select("a[href*='/nehnutelnost/']")
    print(f"\nLinks to /nehnutelnost/: {len(links)}")
    if links:
        p = links[0].parent
        print(f"First link parent tag: <{p.name} class='{p.get('class')}'>")
        print(f"First link href: {links[0].get('href')}")
        # Walk up to find a card container
        for _ in range(5):
            p = p.parent
            if p and p.get("class"):
                print(f"  ancestor: <{p.name} class='{' '.join(p.get('class', []))[:80]}'>")

    # 3. Check for embedded JSON in any script tag
    scripts = soup.find_all("script", type=lambda t: t != "application/json")
    json_chunks = []
    for s in scripts:
        if s.string and '"nehnutelnost"' in (s.string or ""):
            json_chunks.append(s.string[:200])
    if json_chunks:
        print(f"\nScript tags mentioning 'nehnutelnost': {len(json_chunks)}")
        print(f"  Sample: {json_chunks[0][:150]}")

except FileNotFoundError:
    print("nehnutelnosti_p1_200.html not found — run debug_html.py first")


# ── Bazos ──────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("BAZOS")
print("=" * 60)
try:
    with open("bazos_root_200.html", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Find links that look like apartment-for-sale category pages
    all_links = [(a.get_text(strip=True), a.get("href","")) for a in soup.find_all("a", href=True)]
    apt_links = [(t, h) for t, h in all_links
                 if any(k in t.lower() or k in h.lower()
                        for k in ["byt", "predaj", "byty", "flat", "apartment", "nehnut"])]
    print(f"Links related to apartments/predaj: {len(apt_links)}")
    for text, href in apt_links[:15]:
        print(f"  [{text[:40]}] → {href}")

    # Show all top-level category links
    print(f"\nAll links from root page (first 20):")
    for text, href in all_links[:20]:
        if href and href.startswith("http"):
            print(f"  [{text[:30]}] → {href}")

except FileNotFoundError:
    print("bazos_root_200.html not found — run debug_html.py first")
