"""
scraper/topreality.py — Sovereign Investor Dashboard
Scrapes for-sale apartment listings from topreality.sk.

topreality.sk is a traditional server-rendered Slovak real-estate site.
First attempts via HTTP (with ScraperAPI proxy if configured), falls back
to Playwright if HTTP returns nothing or hits a WAF.

  python3 -m scraper.topreality          # direct run, 3 pages
"""

import hashlib, time, re, json
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db
from scraper._http import get, make_session

BASE = "https://www.topreality.sk"

# Try several search URL formats — first one that returns >0 detail links wins.
# topreality.sk has reorganised its URL structure several times, so we keep
# a few candidates rather than hardcoding one.
SEARCH_URL_CANDIDATES = [
    BASE + "/vyhladavanie-byty-predaj/strana-{page}.html",
    BASE + "/byty-predaj.html?strana={page}",
    BASE + "/inzercia.html?type=ponuka&action=predaj&category=byty&strana={page}",
    BASE + "/vyhladavanie/byty/predaj?page={page}",
]

# Patterns that distinguish a listing-detail link from category/footer links
DETAIL_HREF_PATTERNS = [
    re.compile(r"/byt-[^/]+\.html"),         # e.g. /byt-3-izbovy-bratislava-ID12345.html
    re.compile(r"/detail-[^/]+\.html"),
    re.compile(r"/inzerat/\d+"),
    re.compile(r"/predaj-[^/]*-byt[^/]*\.html"),
    re.compile(r"/[^/]+-byt-[^/]+\.html"),
]

ENERGY_VALID = {"A0", "A1", "A", "B", "C", "D", "E", "F", "G"}


# ── Field extraction helpers (mostly cribbed from nehnutelnosti.py) ───────────
def _price_from_text(t: str) -> float:
    if not t:
        return 0.0
    m = re.search(r"(\d{1,3}(?:[\s\xa0  ]\d{3})+|\d{4,8})\s*€", t)
    if m:
        try:
            return float(re.sub(r"[\s\xa0  ]", "", m.group(1)))
        except Exception:
            pass
    return 0.0


def _size_from_text(t: str) -> float:
    if not t:
        return 0.0
    target = t
    LABELS = [
        r"úžitkov[áa]\s+plocha", r"podlahov[áa]\s+plocha",
        r"celkov[áa]\s+plocha",  r"obytn[áa]\s+plocha",
        r"plocha\s+bytu",        r"výmera",
        r"rozloha",              r"\bplocha\b",
    ]
    for lbl in LABELS:
        m = re.search(lbl + r"[^\d]{0,120}(\d{2,4}(?:[.,]\d+)?)\s*(?:m²|m2|m\b)",
                      target, re.I)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
                if 15 < v < 500:
                    return v
            except Exception:
                pass
    for m in re.finditer(r"(\d{2,4}(?:[.,]\d+)?)\s*(?:m²|m2)\b", target):
        try:
            v = float(m.group(1).replace(",", "."))
            if 20 < v < 300:
                return v
        except Exception:
            pass
    return 0.0


def _district_from_text(t: str) -> str:
    if not t:
        return ""
    parts = [p.strip() for p in t.split(",")]
    return parts[-1] if parts else ""


def _energy_from_text(t: str) -> str:
    if not t:
        return "UNKNOWN"
    m = re.search(r"energetick[aá]\s+(?:trieda|certifik\w*)[^A-Z]{0,30}\b([A-G][01]?)\b",
                  t, re.I)
    if m:
        cls = m.group(1).upper()
        if cls in ENERGY_VALID:
            return cls
    return "UNKNOWN"


# ── Card / detail-page parsers ────────────────────────────────────────────────
def _extract_listing_links(html: str) -> list[str]:
    """Pull all detail-page hrefs from a search results page."""
    soup = BeautifulSoup(html, "lxml")
    found: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        if href.startswith("/"):
            full = BASE + href
        elif href.startswith("http"):
            full = href
        else:
            continue
        if "topreality.sk" not in full:
            continue
        path = full.replace(BASE, "")
        if any(p.search(path) for p in DETAIL_HREF_PATTERNS):
            found.add(full.split("#")[0].split("?")[0])
    return sorted(found)


def _build_listing_from_detail(url: str, html: str, now: str) -> dict | None:
    """Parse one detail-page HTML into our DB schema."""
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)

    # Title — prefer og:title / page <title>
    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title and soup.title:
        title = re.sub(r"\s*[\|\-]\s*topreality.*$", "", soup.title.text, flags=re.I).strip()

    # JSON-LD
    ld_data: dict = {}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            blob = json.loads(tag.string or "")
        except Exception:
            continue
        for b in (blob if isinstance(blob, list) else [blob]):
            if not isinstance(b, dict):
                continue
            t = b.get("@type", "")
            if isinstance(t, list):
                t = t[0] if t else ""
            if t not in ("Product", "Apartment", "House", "Residence",
                         "RealEstateListing", "Place", "Accommodation"):
                continue
            if not title and b.get("name"):
                title = str(b["name"])
            offers = b.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                p = offers.get("price") or offers.get("lowPrice")
                if p and not ld_data.get("price"):
                    try:
                        ld_data["price"] = float(p)
                    except Exception:
                        pass
            addr = b.get("address")
            if isinstance(addr, dict):
                parts = [addr.get(k, "") for k in
                         ("streetAddress", "addressLocality", "addressRegion")]
                joined = ", ".join(p for p in parts if p)
                if joined:
                    ld_data["address"] = joined
            elif isinstance(addr, str):
                ld_data["address"] = addr
            fs = b.get("floorSize")
            if isinstance(fs, dict) and fs.get("value"):
                try:
                    ld_data["size"] = float(fs["value"])
                except Exception:
                    pass

    price = ld_data.get("price") or _price_from_text(body_text)
    size = ld_data.get("size") or _size_from_text(body_text)
    address = ld_data.get("address", "")

    # Image
    img = ""
    og_img = soup.find("meta", attrs={"property": "og:image"})
    if og_img and og_img.get("content"):
        img = og_img["content"]

    energy = _energy_from_text(body_text)

    if not (price or size):
        # Listing has no usable data — likely an archived page or category link
        return None

    uid = hashlib.md5(url.encode()).hexdigest()
    return {
        "id": uid, "source": "topreality", "url": url, "url_hash": uid,
        "title": (title or "")[:200], "description": "",
        "price_eur": float(price or 0.0), "size_m2": float(size or 0.0),
        "rooms": None, "floor": None, "year_built": None,
        "energy_class": energy,
        "address_raw": address,
        "district": _district_from_text(address),
        "city": "",
        "primary_image_url": img, "image_urls": img,
        "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
    }


# ── Page fetchers ─────────────────────────────────────────────────────────────
def _fetch(url: str, sess=None) -> tuple[int, str]:
    try:
        r = get(url, session=sess, timeout=25)
        return r.status_code, r.text
    except Exception:
        return 0, ""


def _detect_search_url(sess) -> str:
    """Probe candidates until we find one returning detail-page links."""
    for fmt in SEARCH_URL_CANDIDATES:
        url = fmt.format(page=1)
        status, html = _fetch(url, sess)
        if status == 200 and len(html) > 5000:
            links = _extract_listing_links(html)
            if links:
                print(f"  ✓ search URL works: {fmt} ({len(links)} links page 1)", flush=True)
                return fmt
            else:
                print(f"  · {fmt} → 200 but 0 links", flush=True)
        else:
            print(f"  · {fmt} → HTTP {status}, len={len(html)}", flush=True)
    return ""


def check_reachable() -> tuple[int, str]:
    try:
        r = get(BASE, timeout=10)
        return r.status_code, r.text[:200].strip().replace("\n", " ")
    except Exception as e:
        return 0, str(e)


def run(max_pages: int = 5) -> int:
    print(f"🔍 Topreality.sk ({max_pages} pages)...", flush=True)
    sess = make_session(BASE)

    fmt = _detect_search_url(sess)
    if not fmt:
        raise RuntimeError(
            "Topreality: none of the candidate search URLs returned listings. "
            "The site likely changed its URL scheme — update SEARCH_URL_CANDIDATES "
            "in scraper/topreality.py."
        )

    seen_urls: set[str] = set()
    total = 0
    for p in range(1, max_pages + 1):
        url = fmt.format(page=p)
        status, html = _fetch(url, sess)
        if status != 200:
            print(f"  Page {p}: HTTP {status}, skipping", flush=True)
            continue
        links = _extract_listing_links(html)
        new_links = [u for u in links if u not in seen_urls]
        seen_urls.update(new_links)
        print(f"  Page {p}: {len(links)} links ({len(new_links)} new)", flush=True)

        page_count = 0
        now = datetime.now(timezone.utc).isoformat()
        for detail_url in new_links:
            d_status, d_html = _fetch(detail_url, sess)
            if d_status != 200:
                continue
            listing = _build_listing_from_detail(detail_url, d_html, now)
            if listing:
                try:
                    upsert_listing(listing)
                    total += 1
                    page_count += 1
                except Exception as e:
                    print(f"    DB error: {e}", flush=True)
            time.sleep(0.4)
        print(f"  Page {p}: upserted {page_count}", flush=True)
        time.sleep(SCRAPE_DELAY_SEC)

    if total == 0:
        raise RuntimeError(
            "Topreality: 0 listings parsed. Check DETAIL_HREF_PATTERNS in "
            "scraper/topreality.py — the link patterns may need updating."
        )
    print(f"✅ Topreality done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=3)
