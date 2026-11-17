"""
modules/auctions_sk.py — Slovak real-estate auctions as a deal source: the
notaries' central register of auctions (Notársky centrálny register dražieb,
NCRdr, www.notar.sk/drazby), where by law every voluntary auction
(dobrovoľná dražba, Act 527/2002) is announced.

  refresh()       — the register's announcements for the next weeks, one
                    week a search (it shows at most 20 rows), and each new
                    one's record: what is auctioned, when, where, by whom,
                    and its published announcement.
  read_announcement(act_id) — the announcement itself (usually a scanned
                    PDF), read by Claude (modules/doc_reader): the town,
                    whether it is a flat, its size, the lowest bid, the
                    valuation, the deposit, the LV and the viewing dates.

Auctions are not scored with the listings: you can't get a mortgage approved
before you bid, the deposit is due before the auction, viewings are one or
two set dates, and the flat may still be lived in. The AUCTIONS tab lists
them with the discount of the lowest bid to the district median.

Requests are few and slow (a pause between each), the register's robots.txt
allows them, and the data is public by law. Czech executor auctions
(portaldrazeb.cz) are not read.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

BASE = "https://www.notar.sk"
SEARCH = f"{BASE}/drazby/"
DETAIL = f"{BASE}/drazba/"
ROW_CAP = 20                 # the register shows at most this many rows a search
PAUSE_S = 1.0
TIMEOUT_S = 40
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; property-auction-check)"}


def _get(url, params=None, get=None):
    import requests
    get = get or requests.get
    r = get(url, params=params, timeout=TIMEOUT_S, headers=HEADERS)
    r.raise_for_status()
    return r


def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "lxml")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _iso(d: str) -> str | None:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def parse_results(html: str) -> list[dict]:
    """The rows of a search: act_id, ncr_no, auctioneer, auctioneer_ico,
    proposer, act_type, auction_date."""
    out = []
    table = _soup(html).select_one("table.search_results")
    for tr in (table.select("tbody tr") if table else []):
        tds = tr.find_all("td")
        a = tr.find("a", href=re.compile(r"actId="))
        if len(tds) < 6 or not a:
            continue
        act_id = re.search(r"actId=([0-9a-fA-F]+)", a["href"]).group(1)
        who = _clean(tds[1].get_text(" "))
        ico = re.search(r"IČO:\s*(\d{6,8})", who)
        out.append({
            "act_id": act_id, "ncr_no": _clean(a.get_text()),
            "auctioneer": _clean(re.sub(r"IČO:.*$", "", who)),
            "auctioneer_ico": ico.group(1) if ico else "",
            "proposer": _clean(re.sub(r"IČO:\s*\d+", "", tds[2].get_text(" "))),
            "act_type": _clean(tds[3].get_text()),
            "auction_date": _iso(tds[5].get_text()),
        })
    return out


def parse_detail(html: str) -> dict:
    """An auction's record: its key/value lines and the published
    announcement's link."""
    soup = _soup(html)
    pairs = {}
    for key in soup.select("span.key"):
        val = key.find_next_sibling("span", class_="value")
        if val is not None:
            pairs[_clean(key.get_text()).rstrip(":").strip()] = val
    def text(label):
        v = pairs.get(label)
        return _clean(v.get_text(" ")) if v is not None else ""
    doc = pairs.get("Uverejnené listiny")
    link = doc.find("a", href=True) if doc is not None else None
    opens = text("Dátum a čas otvorenia dražby")
    return {
        "subject_kind": text("Druh predmetu dražby"),
        "venue": ", ".join(x for x in (text("Miesto konania dražby"),
                                       text("Bližšie označenie miesta konania dražby")) if x),
        "opens_at": opens,
        "auction_date": _iso(opens),
        "doc_url": (BASE + link["href"]) if link and link["href"].startswith("/") else
                   (link["href"] if link else ""),
        "doc_name": _clean(link.get_text()) if link else "",
    }


def search(day_from: date, day_to: date, get=None) -> list[dict]:
    """Every auction announced for days day_from..day_to: a window that hits
    the register's 20-row cap is split in two until none does."""
    r = _get(SEARCH, params={"AuctionActType": "NEW_AUCTION",
                             "auctionDateFrom": day_from.isoformat(),
                             "auctionDateTo": day_to.isoformat(),
                             "auction-search": "Hľadať"}, get=get)
    rows = parse_results(r.text)
    if len(rows) >= ROW_CAP and day_to > day_from:
        mid = day_from + (day_to - day_from) // 2
        time.sleep(PAUSE_S)
        first = search(day_from, mid, get=get)
        time.sleep(PAUSE_S)
        return first + search(mid + timedelta(days=1), day_to, get=get)
    return rows


def refresh(days_ahead: int = 42, window_days: int = 7, max_details: int = 40,
            get=None, today: date | None = None) -> dict:
    """Read the coming weeks' announcements and the records of new ones.
    Returns {"seen", "new", "details"}."""
    from database.auctions import auctions_without_detail, upsert_auction
    today = today or date.today()
    seen = new = 0
    start = today
    while start <= today + timedelta(days=days_ahead):
        end = start + timedelta(days=window_days - 1)
        for row in search(start, end, get=get):
            seen += 1
            new += upsert_auction(row)
        start = end + timedelta(days=1)
        time.sleep(PAUSE_S)
    details = 0
    for act_id in auctions_without_detail(max_details):
        try:
            got = parse_detail(_get(DETAIL, params={"actId": act_id}, get=get).text)
        except Exception as e:
            log.warning(f"Auction {act_id}: record not read ({type(e).__name__}: {e})")
            continue
        upsert_auction({"act_id": act_id, **got})
        details += 1
        time.sleep(PAUSE_S)
    return {"seen": seen, "new": new, "details": details}


def refresh_quietly(now: datetime | None = None) -> None:
    """refresh(), for the end of a pipeline run: at most once a day, off with
    AUCTIONS_SOURCE=0, and a failure never fails the run."""
    import os
    if (os.getenv("AUCTIONS_SOURCE") or "1").strip().lower() in ("0", "false", "no"):
        return
    import database
    now = now or datetime.now()
    conn = database.get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
        last = conn.execute("SELECT value FROM app_state WHERE key='auctions_refreshed'").fetchone()
    finally:
        conn.close()
    if last and last[0] == now.date().isoformat():
        return
    try:
        got = refresh()
        log.info(f"🔨 Auctions (NCRdr): {got['seen']} announced, {got['new']} new, "
                 f"{got['details']} record(s) read")
    except Exception as e:
        log.warning(f"🔨 Auctions not read: {type(e).__name__}: {e}")
        return
    conn = database.get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES "
                     "('auctions_refreshed', ?)", (now.date().isoformat(),))
        conn.commit()
    finally:
        conn.close()


_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "is_real_estate": {"type": "boolean"},
        "is_flat": {"type": "boolean"},
        "municipality": {"type": "string"},
        "address": {"type": "string"},
        "cadastral_area": {"type": "string"},
        "lv_number": {"type": "string"},
        "size_m2": {"type": "number"},
        "rooms": {"type": "integer"},
        "minimum_bid_eur": {"type": "number"},
        "valuation_eur": {"type": "number"},
        "deposit_eur": {"type": "number"},
        "inspection": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["is_real_estate", "is_flat", "municipality", "address", "cadastral_area",
                 "lv_number", "size_m2", "rooms", "minimum_bid_eur", "valuation_eur",
                 "deposit_eur", "inspection", "notes"],
}
_SYSTEM = (
    "You read Slovak auction announcements (oznámenie o dražbe). Report only what the "
    "document states. municipality: the town or village where the property is (obec), not "
    "where the auction is held. is_flat: the subject is a flat (byt) with its share of the "
    "building. size_m2: the flat's floor area (podlahová plocha); 0 when not stated. "
    "minimum_bid_eur: najnižšie podanie; valuation_eur: the expert valuation (hodnota "
    "predmetu dražby zistená znaleckým posudkom); deposit_eur: dražobná zábezpeka; 0 when not "
    "stated. inspection: the viewing dates (obhliadka). notes: in English, one or two "
    "sentences on what stays on the property after the auction (rights that are not "
    "extinguished, tenants, occupants), or an empty string.")


def read_announcement(act_id: str, get=None) -> dict | None:
    """The auction's announcement read by Claude and stored; None when there
    is none, Claude is off, or it couldn't be read."""
    from database.auctions import get_auction, upsert_auction
    from modules import doc_reader
    row = get_auction(act_id)
    if not row or not row.get("doc_url") or not doc_reader.enabled():
        return None
    content = _get(row["doc_url"], get=get).content
    got = doc_reader.ask(content, _SYSTEM, "Read this auction announcement.", _SCHEMA)
    if not got:
        return None
    update = {
        "act_id": act_id, "is_flat": 1 if got["is_flat"] else 0,
        "municipality": got["municipality"].strip(), "address": got["address"].strip(),
        "cadastral_area": got["cadastral_area"].strip(), "lv_number": got["lv_number"].strip(),
        "size_m2": got["size_m2"] or None, "rooms": got["rooms"] or None,
        "min_bid_eur": got["minimum_bid_eur"] or None,
        "valuation_eur": got["valuation_eur"] or None,
        "deposit_eur": got["deposit_eur"] or None,
        "inspection": got["inspection"].strip(), "notes": got["notes"].strip(),
        "read_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not got["is_real_estate"]:
        update["subject_kind"] = "not real estate (announcement)"
    upsert_auction(update)
    return get_auction(act_id)


def discount_to_median(row: dict) -> float | None:
    """How far the lowest bid per m² sits under the district median (0.3 =
    30 % under); None without a town, a size or a bid."""
    if not (row.get("min_bid_eur") and row.get("size_m2") and row.get("municipality")):
        return None
    from engine.regional_prices import benchmark_median
    median = benchmark_median(row["municipality"], row.get("rooms"))
    if not median:
        return None
    return 1 - (row["min_bid_eur"] / row["size_m2"]) / median
