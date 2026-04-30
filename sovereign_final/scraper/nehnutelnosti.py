"""
scraper/nehnutelnosti.py — Sovereign Investor Dashboard
Scrapes for-sale listings from nehnutelnosti.sk.

nehnutelnosti.sk uses Imperva WAF + Next.js App Router (RSC streaming).
The only working approach is Playwright (real Chromium), which:
  1. Intercepts XHR responses from any JSON API endpoint
  2. Falls back to DOM extraction via a[href*='/detail/'] links
  3. Enriches DOM-extracted links with data from RSC chunks in the page

Install once:  pip install playwright && playwright install chromium
"""

import hashlib, time, re, json
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import SCRAPE_DELAY_SEC
from database import upsert_listing, init_db

BASE        = "https://www.nehnutelnosti.sk"
SEARCH_PAGE = BASE + "/vysledky/byty/slovensko/predaj?page={page}"

ENERGY_VALID = {"A0", "A1", "A", "B", "C", "D", "E", "F", "G"}

# URL patterns that signal a listing API response worth capturing
API_SIGNALS = ("/api/v2", "/api/v1", "advertisement", "listing", "advert", "search")


def _check_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa
        return True
    except ImportError:
        return False


def _price(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text or "")
    return float(digits) if digits else 0.0


def _size(text: str) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _district(address: str) -> str:
    parts = [p.strip() for p in (address or "").split(",")]
    return parts[-1] if parts else ""


# Slovak cities/towns most likely to appear in a nehnutelnosti URL slug.
# Order matters: longer/more-specific names checked first so "bratislavske"
# doesn't get matched before "bratislava". Bratislava city parts come before
# the bare "bratislava" so suburbs resolve to their finer-grained name.
_SLUG_CITIES = (
    # Bratislava parts (most specific first)
    "stare-mesto", "ruzinov", "vrakuna", "podunajske-biskupice", "vajnory",
    "nove-mesto", "raca", "dubravka", "karlova-ves", "lamac",
    "zahorska-bystrica", "devinska-nova-ves", "petrzalka", "rusovce",
    "jarovce", "cunovo",
    # Bratislava (after parts, so parts get matched first)
    "bratislava-i", "bratislava-ii", "bratislava-iii", "bratislava-iv",
    "bratislava-v", "bratislava",
    # Košice parts and main
    "kosice-i", "kosice-ii", "kosice-iii", "kosice-iv", "kosice-okolie",
    "kosice", "tahanovce", "barca", "mestska-cast",
    # Other major cities
    "zilina", "nitra", "trnava", "trencin", "presov", "banska-bystrica",
    "poprad", "martin", "ruzomberok", "liptovsky-mikulas", "zvolen",
    "lucenec", "spisska-nova-ves", "michalovce", "humenne", "bardejov",
    "komarno", "levice", "nove-zamky", "sala", "dunajska-streda",
    "galanta", "piestany", "hlohovec", "senica", "skalica",
    "povazska-bystrica", "puchov", "partizanske", "bytca", "cadca",
    "kysucke-nove-mesto", "namestovo", "tvrdosin", "dolny-kubin",
    "brezno", "rimavska-sobota", "revuca", "rossnava", "roznava",
    "stropkov", "vranov-nad-toplou", "snina", "stara-lubovna", "kezmarok",
    "levoca", "sabinov", "trebisov", "sobrance", "topolcany",
    "zlate-moravce", "vrable", "pezinok", "senec", "malacky", "modra",
    "stupava",
)

# Map slug-form (no diacritics, hyphens) → diacritic-correct address form.
# Used to build a clean address_raw / district even when JSON-LD is missing.
_SLUG_TO_DIACRITIC = {
    "kosice": "Košice", "kosice-i": "Košice I", "kosice-ii": "Košice II",
    "kosice-iii": "Košice III", "kosice-iv": "Košice IV", "kosice-okolie": "Košice-okolie",
    "zilina": "Žilina", "presov": "Prešov", "trencin": "Trenčín",
    "ruzomberok": "Ružomberok", "liptovsky-mikulas": "Liptovský Mikuláš",
    "banska-bystrica": "Banská Bystrica", "spisska-nova-ves": "Spišská Nová Ves",
    "stara-lubovna": "Stará Ľubovňa", "vranov-nad-toplou": "Vranov nad Topľou",
    "humenne": "Humenné", "kezmarok": "Kežmarok", "levoca": "Levoča",
    "trebisov": "Trebišov", "topolcany": "Topoľčany", "zlate-moravce": "Zlaté Moravce",
    "piestany": "Piešťany", "dunajska-streda": "Dunajská Streda",
    "povazska-bystrica": "Považská Bystrica", "puchov": "Púchov",
    "bytca": "Bytča", "cadca": "Čadca", "kysucke-nove-mesto": "Kysucké Nové Mesto",
    "namestovo": "Námestovo", "tvrdosin": "Tvrdošín", "dolny-kubin": "Dolný Kubín",
    "rimavska-sobota": "Rimavská Sobota", "revuca": "Revúca", "roznava": "Rožňava",
    "petrzalka": "Petržalka", "raca": "Rača", "vrakuna": "Vrakuňa",
    "podunajske-biskupice": "Podunajské Biskupice", "stare-mesto": "Staré Mesto",
    "nove-mesto": "Nové Mesto", "dubravka": "Dúbravka", "karlova-ves": "Karlova Ves",
    "lamac": "Lamač", "zahorska-bystrica": "Záhorská Bystrica",
    "devinska-nova-ves": "Devínska Nová Ves", "rusovce": "Rusovce",
    "jarovce": "Jarovce", "cunovo": "Čunovo", "ruzinov": "Ružinov",
    "tahanovce": "Ťahanovce",
}


def _parse_slug(url: str) -> dict:
    """Pull title + city/district hints out of a nehnutelnosti.sk URL slug.

    Two URL forms to handle:
      - /detail/{id}/{slug}                       (regular listings)
      - /detail/developersky-projekt/{id}/{slug}  (developer-project pages)

    The slug is the LAST hyphenated segment, not the first non-empty one.
    """
    out: dict = {}
    if not url or "/detail/" not in url:
        return out
    tail = url.split("/detail/", 1)[1].split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in tail.split("/") if p]
    slug = ""
    for part in reversed(parts):
        if "-" in part:
            slug = part.lower()
            break
    if not slug:
        return out

    # Title: clean slug → readable text
    nice = slug.replace("-", " ").strip()
    # Drop common SEO prefixes
    nice = re.sub(r"^(predaj|na predaj|byt na predaj|predam)\s+", "", nice)
    if nice:
        out["title"] = nice[:1].upper() + nice[1:]

    # City/district: search for known city tokens with hyphen-bounded matching
    # so "raca" doesn't match "barack" and "kosice" doesn't match "kosicepiece".
    bordered = "-" + slug + "-"
    found_parts: list[str] = []
    for city_slug in _SLUG_CITIES:
        if ("-" + city_slug + "-") in bordered:
            nice_name = _SLUG_TO_DIACRITIC.get(
                city_slug, city_slug.replace("-", " ").title()
            )
            if nice_name not in found_parts:
                found_parts.append(nice_name)
            if len(found_parts) >= 2:
                break

    if found_parts:
        out["address"] = ", ".join(found_parts)
        # District holds the FULL joined address ("Petržalka, Bratislava")
        # so engine.get_rent_estimate's fuzzy matcher can find both the
        # specific suburb (when it's in RENT_PER_M2) and the city anchor
        # fallback (when the suburb isn't recognised).
        out["district"] = ", ".join(found_parts)

    return out


def _parse_api_item(item: dict, now: str) -> dict | None:
    """Convert one API response object to our DB schema."""
    try:
        url = item.get("url") or item.get("seoUrl") or item.get("link") or ""
        advert_id = item.get("id") or item.get("advertId") or ""
        if not url and advert_id:
            url = f"{BASE}/nehnutelnost/{advert_id}/"
        if not url:
            return None
        if not url.startswith("http"):
            url = BASE + url

        price = 0.0
        price_obj = item.get("price") or item.get("priceInfo") or {}
        if isinstance(price_obj, dict):
            price = float(price_obj.get("value") or price_obj.get("amount") or 0)
        elif isinstance(price_obj, (int, float)):
            price = float(price_obj)

        size = 0.0
        for key in ("usableArea", "floorArea", "area", "size"):
            v = item.get(key) or (item.get("parameters") or {}).get(key)
            if v:
                size = float(v)
                break

        title = item.get("title") or item.get("name") or item.get("heading") or ""
        addr_obj = item.get("location") or item.get("address") or {}
        addr = (addr_obj.get("fullAddress") or addr_obj.get("address") or
                addr_obj.get("city") or "") if isinstance(addr_obj, dict) else str(addr_obj)

        energy_raw = (item.get("energyRating") or item.get("energyClass") or "").upper()
        energy = energy_raw if energy_raw in ENERGY_VALID else "UNKNOWN"

        imgs = item.get("images") or item.get("photos") or []
        img = ""
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            img = (first.get("url") or first.get("src") or first) if isinstance(first, dict) else str(first)

        uid = hashlib.md5(url.encode()).hexdigest()
        return {
            "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
            "title": str(title)[:200], "description": "",
            "price_eur": price, "size_m2": size,
            "rooms": None, "floor": None, "year_built": None,
            "energy_class": energy,
            "address_raw": addr, "district": _district(addr), "city": "",
            "primary_image_url": img, "image_urls": img,
            "classification": "PENDING", "lv_status": "PENDING",
            "scraped_at": now, "last_seen_at": now,
        }
    except Exception as e:
        print(f"    ⚠️  parse error: {e}", flush=True)
        return None


def _extract_items_from_json(data) -> list[dict]:
    """Try common response shapes to find the listing array."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "adverts", "data", "listings", "offers", "advertisements"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return v
        # nested under "data" dict
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in ("items", "results", "adverts", "listings", "advertisements"):
                v = inner.get(key)
                if isinstance(v, list) and v:
                    return v
    return []


def _parse_rsc_chunks(html: str) -> list[dict]:
    """
    Extract listing URLs from Next.js RSC streaming chunks.
    The page embeds self.__next_f.push([1,"..."]) calls where each string
    is a JSON-encoded RSC payload containing the rendered component tree.
    """
    results = []
    # Extract all RSC payloads — content between the outer quotes
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        return results

    # Each chunk is a JSON-string body; wrap in quotes and parse to unescape
    decoded_parts = []
    for chunk in chunks:
        try:
            decoded_parts.append(json.loads('"' + chunk + '"'))
        except Exception:
            # Fall back: just search the raw escaped text too
            decoded_parts.append(chunk)

    raw_text = "\n".join(decoded_parts)

    # Find all /detail/ URLs embedded in the RSC payload
    detail_urls = re.findall(
        r'(https?://(?:www\.)?nehnutelnosti\.sk/detail/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/?)',
        raw_text
    )
    # Also find relative /detail/ paths
    detail_paths = re.findall(r'(/detail/[A-Za-z0-9_\-]+/[A-Za-z0-9_\-]+/?)', raw_text)

    seen_urls: set[str] = set()

    for url in detail_urls:
        if url not in seen_urls:
            seen_urls.add(url)
            uid = hashlib.md5(url.encode()).hexdigest()
            results.append({"_url": url, "_uid": uid})

    for path in detail_paths:
        url = BASE + path
        if url not in seen_urls:
            seen_urls.add(url)
            uid = hashlib.md5(url.encode()).hexdigest()
            results.append({"_url": url, "_uid": uid})

    return results


def _minimal_listing(url: str, title: str, now: str) -> dict:
    uid = hashlib.md5(url.encode()).hexdigest()
    return {
        "id": uid, "source": "nehnutelnosti", "url": url, "url_hash": uid,
        "title": title[:200] if title else "", "description": "",
        "price_eur": 0.0, "size_m2": 0.0,
        "rooms": None, "floor": None, "year_built": None,
        "energy_class": "UNKNOWN",
        "address_raw": "", "district": "", "city": "",
        "primary_image_url": "", "image_urls": "",
        "classification": "PENDING", "lv_status": "PENDING",
        "scraped_at": now, "last_seen_at": now,
    }


def _merge_ld(data: dict, ld) -> None:
    """Pull fields out of a schema.org JSON-LD blob into our flat dict."""
    if not isinstance(ld, dict):
        return
    t = ld.get("@type", "")
    if isinstance(t, list):
        t = t[0] if t else ""
    if t not in ("Product", "Apartment", "House", "Residence", "RealEstateListing",
                 "SingleFamilyResidence", "Accommodation", "Place"):
        return

    name = ld.get("name")
    if name and not data.get("title"):
        data["title"] = str(name)[:200]

    img = ld.get("image")
    if img and not data.get("image"):
        if isinstance(img, list) and img:
            img = img[0]
        if isinstance(img, dict):
            img = img.get("url", "")
        data["image"] = str(img)

    offers = ld.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        for pkey in ("price", "lowPrice", "highPrice"):
            p = offers.get(pkey)
            if p:
                try:
                    data["price"] = float(p)
                    break
                except Exception:
                    pass

    addr = ld.get("address")
    if isinstance(addr, dict):
        parts = [addr.get(k, "") for k in
                 ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
        joined = ", ".join(p for p in parts if p)
        if joined and not data.get("address"):
            data["address"] = joined
    elif isinstance(addr, str) and not data.get("address"):
        data["address"] = addr

    fs = ld.get("floorSize")
    if isinstance(fs, dict):
        v = fs.get("value")
        if v:
            try:
                data["size"] = float(v)
            except Exception:
                pass

    rooms = ld.get("numberOfRooms") or ld.get("numberOfBedrooms")
    if rooms:
        try:
            data["rooms"] = int(float(rooms))
        except Exception:
            pass


def _safe_content(page) -> str:
    """Fetch page.content(); retry once on RSC-streaming race errors."""
    for _ in range(2):
        try:
            return page.content()
        except Exception:
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
    return ""


def _safe_text(page) -> str:
    """Get fully rendered visible text from the page (more reliable than HTML)."""
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception:
        return ""


def _scrape_detail_page(page, url: str) -> dict:
    """Open one /detail/ page in the same browser session and pull structured fields."""
    data: dict = {}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(900)
    except Exception:
        return data

    html = _safe_content(page)
    if not html:
        return data

    # 1. JSON-LD schema.org (most reliable when present)
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            blob = json.loads(m.group(1).strip())
        except Exception:
            continue
        for b in (blob if isinstance(blob, list) else [blob]):
            _merge_ld(data, b)

    # 2. og:image / og:title meta fallbacks
    if not data.get("image"):
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if m:
            data["image"] = m.group(1)
    if not data.get("title"):
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if m:
            data["title"] = m.group(1)[:200]
        else:
            m = re.search(r'<title>([^<]+)</title>', html)
            if m:
                t = re.sub(r'\s*[\|\-]\s*[Nn]ehnute.*$', '', m.group(1)).strip()
                data["title"] = t[:200]

    # 3. For price/size/energy/address, regex on rendered visible text — more
    #    reliable than HTML because these fields are often split across spans.
    text = ""
    if not (data.get("price") and data.get("size") and data.get("energy")
            and data.get("address")):
        text = _safe_text(page)

    # Address — JSON-LD often omits it on PREMIUM listings. Scan the rendered
    # text for known cities/suburbs (suburbs win over their parent city).
    if not data.get("address") and text:
        addr = _extract_location_from_text(text)
        if addr:
            data["address"] = addr

    # Price — handle regular space, NBSP (\xa0), narrow NBSP (\u202f), thin space (\u2009)
    if not data.get("price"):
        m = re.search(r"(\d{1,3}(?:[\s\xa0\u202f\u2009]\d{3})+|\d{4,8})\s*€", text or html)
        if m:
            try:
                data["price"] = float(re.sub(r"[\s\xa0\u202f\u2009]", "", m.group(1)))
            except Exception:
                pass

    # Size — try labelled patterns first, then fall back to the first
    # plausible "N m²" in the rendered text. Window widened to 120 chars
    # because rendered DOM splits label from value across multiple newlines.
    if not data.get("size"):
        target = text or html
        size_value = 0.0

        # Slovak real-estate labels for apartment area, in priority order
        label_patterns = [
            r"úžitkov[áa]\s+plocha",
            r"podlahov[áa]\s+plocha",
            r"celkov[áa]\s+plocha",
            r"obytn[áa]\s+plocha",
            r"plocha\s+bytu",
            r"plocha\s+úžitkov[áa]",
            r"výmera",
            r"rozloha",
            r"\bplocha\b",
        ]
        for lbl in label_patterns:
            m = re.search(
                lbl + r"[^\d]{0,120}(\d{2,4}(?:[.,]\d+)?)\s*(?:m²|m2|m\b)",
                target, re.I,
            )
            if m:
                try:
                    v = float(m.group(1).replace(",", "."))
                    if 15 < v < 500:
                        size_value = v
                        break
                except Exception:
                    pass

        # Fallback — first plausible "N m²" anywhere in rendered text
        if not size_value:
            for m in re.finditer(r"(\d{2,4}(?:[.,]\d+)?)\s*(?:m²|m2)\b", target):
                try:
                    v = float(m.group(1).replace(",", "."))
                    if 20 < v < 300:
                        size_value = v
                        break
                except Exception:
                    pass

        # Last resort — pull "N m²" out of the title (Bazos-style headlines)
        if not size_value and data.get("title"):
            m = re.search(r"(\d{2,4}(?:[.,]\d+)?)\s*(?:m²|m2)", data["title"])
            if m:
                try:
                    v = float(m.group(1).replace(",", "."))
                    if 15 < v < 500:
                        size_value = v
                except Exception:
                    pass

        if size_value:
            data["size"] = size_value

    # Energy class — "Energetická trieda B" or similar
    if not data.get("energy"):
        m = re.search(r"energetick[aá]\s+(?:trieda|certifik\w*)[^A-Z]{0,30}\b([A-G][01]?)\b",
                      text or html, re.I)
        if m:
            cls = m.group(1).upper()
            if cls in ENERGY_VALID:
                data["energy"] = cls

    return data


_GENERIC_TITLES = {"premium", "top", "exclusive", "exkluzivne", "exkluzívne", ""}

# Suburbs (specific) → "Suburb, Parent City" so engine.get_rent_estimate
# can match either the suburb (Petržalka → 10.5 €/m²) or fall back to the
# city anchor (Bratislava → BA IV rate). Order matters: longest/most-specific
# names first so "Devínska Nová Ves" wins over "Bratislava".
_TEXT_LOCATION_PATTERNS: list[tuple[re.Pattern, str]] = []


def _build_location_patterns() -> list[tuple[re.Pattern, str]]:
    suburb_to_city = {
        "Devínska Nová Ves": "Bratislava", "Podunajské Biskupice": "Bratislava",
        "Záhorská Bystrica": "Bratislava", "Karlova Ves": "Bratislava",
        "Staré Mesto": "Bratislava", "Nové Mesto": "Bratislava",
        "Petržalka": "Bratislava", "Ružinov": "Bratislava", "Dúbravka": "Bratislava",
        "Vrakuňa": "Bratislava", "Vajnory": "Bratislava", "Rusovce": "Bratislava",
        "Jarovce": "Bratislava", "Čunovo": "Bratislava", "Lamač": "Bratislava",
        "Rača": "Bratislava", "Ťahanovce": "Košice", "Barca": "Košice",
    }
    cities = [
        "Banská Bystrica", "Liptovský Mikuláš", "Spišská Nová Ves",
        "Považská Bystrica", "Rimavská Sobota", "Vranov nad Topľou",
        "Bánovce nad Bebravou", "Kysucké Nové Mesto", "Žiar nad Hronom",
        "Nové Mesto nad Váhom", "Dunajská Streda", "Stará Ľubovňa",
        "Veľký Krtíš", "Zlaté Moravce", "Bratislava", "Košice", "Žilina",
        "Nitra", "Trnava", "Trenčín", "Prešov", "Poprad", "Martin",
        "Ružomberok", "Zvolen", "Trebišov", "Galanta", "Komárno", "Levice",
        "Nové Zámky", "Pezinok", "Senec", "Malacky", "Modra", "Piešťany",
        "Hlohovec", "Senica", "Skalica", "Púchov", "Partizánske",
        "Topoľčany", "Levoča", "Sabinov", "Bardejov", "Humenné", "Snina",
        "Kežmarok", "Stropkov", "Sobrance", "Michalovce", "Rožňava",
        "Detva", "Lučenec", "Brezno", "Námestovo", "Tvrdošín", "Dolný Kubín",
        "Bytča", "Čadca", "Revúca", "Krupina", "Hnúšťa", "Stupava", "Šaľa",
    ]
    pats: list[tuple[re.Pattern, str]] = []
    # Suburbs first (sorted by length desc so multi-word names win)
    for suburb in sorted(suburb_to_city, key=len, reverse=True):
        pats.append((
            re.compile(r"(?<!\w)" + re.escape(suburb) + r"(?!\w)"),
            f"{suburb}, {suburb_to_city[suburb]}",
        ))
    # Then cities (longest first so "Banská Bystrica" wins over "Bystrica")
    for city in sorted(cities, key=len, reverse=True):
        pats.append((re.compile(r"(?<!\w)" + re.escape(city) + r"(?!\w)"), city))
    return pats


_TEXT_LOCATION_PATTERNS = _build_location_patterns()


def _extract_location_from_text(text: str) -> str:
    """Find the first known Slovak city/suburb in rendered detail-page text.

    Address is almost always near the top of the page; trim the search window
    to keep this O(1) per listing.
    """
    if not text:
        return ""
    snippet = text[:4000]
    for pattern, address in _TEXT_LOCATION_PATTERNS:
        if pattern.search(snippet):
            return address
    return ""


def _apply_detail(listing: dict, detail: dict) -> None:
    """Overlay enrichment data onto a minimal listing record."""
    if detail.get("title") and not listing.get("title"):
        listing["title"] = detail["title"][:200]
    if detail.get("price"):
        listing["price_eur"] = detail["price"]
    if detail.get("size"):
        listing["size_m2"] = detail["size"]
    if detail.get("rooms"):
        listing["rooms"] = detail["rooms"]
    if detail.get("address"):
        listing["address_raw"] = detail["address"]
        listing["district"] = _district(detail["address"])
    if detail.get("energy"):
        listing["energy_class"] = detail["energy"]
    if detail.get("image"):
        listing["primary_image_url"] = detail["image"]
        listing["image_urls"] = detail["image"]

    # Slug fallback — covers "PREMIUM"-titled paid listings and JSON-LD blobs
    # that omit address. Always runs but only fills empty fields.
    slug_data = _parse_slug(listing.get("url", ""))
    cur_title = (listing.get("title") or "").strip().lower()
    if slug_data.get("title") and cur_title in _GENERIC_TITLES:
        listing["title"] = slug_data["title"][:200]
    if slug_data.get("address") and not listing.get("address_raw"):
        listing["address_raw"] = slug_data["address"]
    if slug_data.get("district") and not listing.get("district"):
        listing["district"] = slug_data["district"]


def _scrape_page_playwright(page_num: int) -> list[dict]:
    """Load one search page via Playwright, capture API responses + DOM links."""
    from playwright.sync_api import sync_playwright

    url = SEARCH_PAGE.format(page=page_num)
    captured_api: list[dict] = []

    def _on_response(response):
        if response.status != 200:
            return
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return
        # Capture any JSON from endpoints that look like listing APIs
        if any(sig in response.url for sig in API_SIGNALS):
            try:
                data = response.json()
                items = _extract_items_from_json(data)
                if items:
                    captured_api.extend(items)
                    print(f"    ✅ API hit: {response.url[:80]} → {len(items)} items", flush=True)
            except Exception:
                pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="sk-SK",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        # Patch navigator.webdriver before page JS runs
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',  { get: () => [1,2,3,4,5] });
            window.chrome = { runtime: {}, loadTimes: ()=>({}), csi: ()=>({}) };
        """)
        page = ctx.new_page()
        page.on("response", _on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"    ⚠️  goto error: {e}", flush=True)

        # Extra wait for any deferred XHR
        page.wait_for_timeout(3000)

        html = page.content()
        now = datetime.now(timezone.utc).isoformat()
        results: list[dict] = []

        # ── Strategy 1: API interception gave full structured items ────────────
        if captured_api:
            results = [r for r in (_parse_api_item(item, now) for item in captured_api) if r]
        else:
            # ── Strategy 2: DOM link extraction with /detail/ selector ─────────
            print(f"    No API JSON captured — trying DOM extraction...", flush=True)
            links = page.eval_on_selector_all(
                "a[href*='/detail/']",
                "els => els.map(e => ({href: e.href, text: e.innerText.trim().slice(0,200)}))"
            )
            print(f"    /detail/ links in DOM: {len(links)}", flush=True)

            # ── Strategy 3: RSC chunk parsing from HTML source ─────────────────
            rsc_items = _parse_rsc_chunks(html)
            print(f"    RSC /detail/ URLs found: {len(rsc_items)}", flush=True)

            seen: set[str] = set()
            for l in links:
                href = l.get("href", "")
                if href and "/detail/" in href and href not in seen:
                    seen.add(href)
                    results.append(_minimal_listing(href, l.get("text", ""), now))
            for item in rsc_items:
                href = item["_url"]
                if href not in seen:
                    seen.add(href)
                    results.append(_minimal_listing(href, "", now))

        # ── Enrichment: open each listing's detail page in same browser ────────
        to_enrich = [r for r in results if not r.get("price_eur")]
        if to_enrich:
            print(f"    Enriching {len(to_enrich)} listings (detail pages)...", flush=True)
            success = 0
            for i, listing in enumerate(to_enrich, 1):
                try:
                    detail = _scrape_detail_page(page, listing["url"])
                    if detail:
                        _apply_detail(listing, detail)
                        if detail.get("price"):
                            success += 1
                except Exception as e:
                    print(f"      [{i}] enrich error: {e}", flush=True)
                if i % 10 == 0 or i == len(to_enrich):
                    print(f"      progress {i}/{len(to_enrich)} (with price: {success})",
                          flush=True)

        browser.close()

    return results


def check_reachable() -> tuple[int, str]:
    try:
        import requests as _req
        r = _req.get(SEARCH_PAGE.format(page=1), timeout=10,
                     headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code, ""
    except Exception as e:
        return 0, str(e)


def run(max_pages: int = 10) -> int:
    if not _check_playwright():
        raise RuntimeError(
            "Playwright is required for nehnutelnosti.sk (Imperva WAF bypass).\n"
            "Run:  pip install playwright && playwright install chromium"
        )

    print(f"🔍 Nehnutelnosti.sk ({max_pages} pages, Playwright)...", flush=True)
    total = 0

    for p in range(1, max_pages + 1):
        listings = _scrape_page_playwright(p)
        for l in listings:
            try:
                upsert_listing(l)
                total += 1
            except Exception as e:
                print(f"    DB error: {e}", flush=True)
        print(f"  Page {p}: {len(listings)} found", flush=True)
        time.sleep(SCRAPE_DELAY_SEC)

    if total == 0:
        raise RuntimeError(
            "Nehnutelnosti: 0 listings after Playwright scrape.\n"
            "Run debug_playwright.py with headless=False to inspect live page."
        )
    print(f"✅ Nehnutelnosti done. {total} upserted.", flush=True)
    return total


if __name__ == "__main__":
    init_db()
    run(max_pages=2)
