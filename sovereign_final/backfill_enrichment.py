"""
backfill_enrichment.py — one-shot enrichment backfills across the existing DB.

Two independent jobs live here:

1. LLM enrichment backfill (default mode): run every LLM enricher across the
   existing DB, then rescore so the new signals actually take effect. Order
   matters — address + description enrichment run first (they fill blank
   districts and parse parking / furnished / balcony / condition), THEN the
   cashflow scores are cleared and recomputed. The enrichment steps need
   ANTHROPIC_API_KEY and no-op without it; the rescore always runs.

2. Slovak cadastre enrichment (`cadastre` / `cadastre-backfill` modes) —
   thin CLI over kataster_scraper.py, an UNOFFICIAL scraper of
   kataster.skgeodesy.sk. ÚGKK SR publishes no API and issues no API keys;
   see the warning at the top of kataster_scraper.py for what it can and
   cannot reliably return, and how it may break if the portal changes.

Modes:
  python3 backfill_enrichment.py [limit]
      LLM backfill. `limit` (default 1000) caps how many listings each
      enricher processes in one pass — run again to continue.

  python3 backfill_enrichment.py cadastre AREA PARCEL [--register C|E|auto]
                                                       [--refresh] [--no-lv]
      Look up ONE parcel: AREA is the katastrálne územie name (e.g. "Nitra")
      or its numeric code (e.g. 838365); PARCEL is the parcelné číslo
      (e.g. "1234/5"). Prints the enrichment result as JSON.

  python3 backfill_enrichment.py cadastre-backfill [limit]
      Enrich every active listing that carries cadastral_area +
      cadastral_number (default limit 100). Results land in cadastre_cache.
"""

import json
import sys, os

sys.path.insert(0, os.path.dirname(__file__))

import database
from database import init_db, clear_cashflow_scores
from modules.address_enrichment import run_address_enrichment
from modules.description_enrichment import run_description_enrichment
from modules.cashflow_runner import run_scoring
# Re-exported so existing callers can keep importing the cadastre helpers from
# here; the implementation lives in kataster_scraper.py.
from kataster_scraper import (          # noqa: F401
    CadastreError, enrich_parcel, enrich_lv, resolve_cadastral_unit,
    find_parcel, fetch_owners, fetch_lv_text, scan_risk_flags,
    identify_parcels, GENERATE_PRF, PORTAL_ODATA, GEOBLOCK_PROXY_PREFIX,
)


# ══════════════════════════════════════════════════════════════════════════
# Mode 1 — LLM enrichment backfill
# ══════════════════════════════════════════════════════════════════════════
def main(limit: int = 1000) -> dict:
    """Run the full backfill and return a summary of what changed."""
    init_db()
    print("=" * 60)
    print("BACKFILL ENRICHMENT — addresses, descriptions, then rescore")
    print("=" * 60)

    addresses    = run_address_enrichment(limit=limit)
    descriptions = run_description_enrichment(limit=limit)

    print("\n♻️  Clearing cashflow scores so the new signals take effect...")
    cleared = clear_cashflow_scores()
    scored  = run_scoring()

    summary = {
        "addresses": addresses,
        "descriptions": descriptions,
        "cleared": cleared,
        "scored": scored,
    }
    print("=" * 60)
    print(f"✅ Backfill done. {addresses} districts resolved, "
          f"{descriptions} descriptions parsed, "
          f"{cleared} scores cleared, {scored} rescored.")
    print("=" * 60)
    return summary


# ══════════════════════════════════════════════════════════════════════════
# Mode 2 — Slovak cadastre backfill (scraper lives in kataster_scraper.py)
# ══════════════════════════════════════════════════════════════════════════
def run_cadastre_backfill(limit: int = 100) -> dict:
    """Enrich every active listing that already carries a cadastral area +
    parcel number. Results are cached in cadastre_cache; risk-flag hits are
    printed so they can be verified manually (this does NOT flip lv_status —
    that stays modules/debt_bot's job)."""
    init_db()
    conn = database.get_conn()
    try:
        rows = conn.execute("""
            SELECT id, cadastral_area, cadastral_number, address_raw
            FROM listings
            WHERE is_active=1
              AND cadastral_number IS NOT NULL AND cadastral_number != ''
              AND cadastral_area   IS NOT NULL AND cadastral_area   != ''
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

    counts = {"processed": 0, "ok": 0, "not_found": 0, "errors": 0}
    if not rows:
        print("ℹ️  No active listings carry a cadastral area + parcel number — "
              "nothing to enrich. (Listing scrapers rarely provide parcel "
              "numbers; fill cadastral_area/cadastral_number where known.)")
        return counts

    print(f"🏛  Cadastre backfill on {len(rows)} listings (unofficial "
          f"skgeodesy.sk scraper — may break without notice)...")
    for row in rows:
        counts["processed"] += 1
        addr = (row["address_raw"] or "")[:55]
        res = enrich_parcel(row["cadastral_area"], row["cadastral_number"])
        if res["status"] == "OK":
            counts["ok"] += 1
            lv_no = (res.get("lv") or {}).get("no")
            flags = ", ".join(f["flag"] for f in res["risk_flags"]) or "none"
            print(f"  ✅ {addr} — LV {lv_no}, {len(res['owners'])} owner(s), "
                  f"flags: {flags} [{res['source']}]")
        elif res["status"] == "NOT_FOUND":
            counts["not_found"] += 1
            print(f"  ⚠️  {addr} — {res['detail']}")
        else:
            counts["errors"] += 1
            print(f"  ❌ {addr} — {res['detail']}")

    print(f"\n🏛  Cadastre backfill done. OK: {counts['ok']} | "
          f"not found: {counts['not_found']} | errors: {counts['errors']}")
    return counts


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli_cadastre(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="backfill_enrichment.py cadastre",
        description="Look up one parcel on the (unofficial) Slovak cadastre "
                    "portal and print the result as JSON.")
    ap.add_argument("area", help="katastrálne územie name (e.g. 'Nitra') or "
                                 "numeric code (e.g. 838365)")
    ap.add_argument("parcel", help="parcelné číslo, e.g. '1234/5'")
    ap.add_argument("--register", default="auto", choices=["C", "E", "auto"],
                    help="parcel register (default: try C then E)")
    ap.add_argument("--refresh", action="store_true",
                    help="bypass cadastre_cache and re-scrape")
    ap.add_argument("--no-lv", action="store_true",
                    help="skip downloading the LV (title deed) report text")
    args = ap.parse_args(argv)

    result = enrich_parcel(args.area, args.parcel, register=args.register,
                           refresh=args.refresh, fetch_lv=not args.no_lv)
    printable = dict(result)
    if printable.get("lv_text") and len(printable["lv_text"]) > 600:
        printable["lv_text"] = printable["lv_text"][:600] + "…"
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "cadastre":
        sys.exit(_cli_cadastre(argv[1:]))
    elif argv and argv[0] == "cadastre-backfill":
        run_cadastre_backfill(int(argv[1]) if len(argv) > 1 else 100)
    else:
        main(int(argv[0]) if argv else 1000)
