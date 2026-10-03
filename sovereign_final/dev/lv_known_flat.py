"""
dev/lv_known_flat.py — one-off probe, not part of the pipeline.

Checks the LV debt filter against a flat whose title deed you already know.
The filter finds the building plot under a listing's map pin, but a flat's own
LV can differ from its plot's: a flat in a bytový dom has its own entry, often
on another LV, sometimes on one LV the whole building shares. modules/debt_bot
therefore never treats the plot's LV as the flat's. This shows what the
cadastre actually returns for a real flat, so that assumption — and the
entry-by-entry screen in modules/lv_screen — can be checked against reality.

Run from sovereign_final/, from a Slovak IP (skgeodesy.sk geo-blocks many
foreign ones):

    python3 dev/lv_known_flat.py LAT LNG
    python3 dev/lv_known_flat.py LAT LNG --lv 4321 --area Petržalka

LAT LNG is a point on the building's roof (right-click → coordinates in Google
Maps). --lv / --area are the flat's own LV number and katastrálne územie, from
a výpis you hold. Both LV texts are saved to logs/ so they can be compared by
hand, or shared to tune the screen.

What to look for:
  - plot LV vs flat LV: same number or not?
  - "flats listed": 1 means the flat has an LV of its own; many means an LV
    shared by the building, where part C entries name the flat they burden.
  - screened entries: does each lien show the creditor the výpis names, and
    is every ťarcha you can see on the výpis listed?
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kataster_scraper import (                          # noqa: E402
    identify_parcels, get_parcel_by_id, parcel_at, enrich_parcel, enrich_lv,
    CadastreError,
)
from modules.lv_screen import screen_lv, describe       # noqa: E402
from modules.debt_bot import _flat_numbers, check_listing  # noqa: E402


def _show_lv(label: str, result: dict) -> str | None:
    print(f"\n── {label} " + "─" * max(0, 60 - len(label)))
    print(f"status: {result['status']} — {result['detail']}")
    text = result.get("lv_text")
    if not text:
        return None
    lv_no = (result.get("lv") or {}).get("no")
    flats = sorted(_flat_numbers(text), key=lambda x: int(x))
    print(f"LV {lv_no}: {len(text)} chars, flats listed: "
          f"{len(flats)} {flats[:15]}{' …' if len(flats) > 15 else ''}")
    entries = screen_lv(text)
    if not entries:
        print("screened entries: none")
    for e in entries:
        print(f"  {'BLOCKS' if e['blocking'] else 'ok    '} {describe(e)}")
    os.makedirs("logs", exist_ok=True)
    path = os.path.join("logs", f"lv_probe_{label.split()[0].lower()}_{lv_no}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"full text saved to {path}")
    print(f"first 400 chars: {text[:400]}")
    return str(lv_no)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("lat", type=float)
    ap.add_argument("lng", type=float)
    ap.add_argument("--lv", help="the flat's own LV number")
    ap.add_argument("--area", help="the flat's katastrálne územie (name or code)")
    args = ap.parse_args()

    print(f"# parcels at ({args.lat}, {args.lng})")
    try:
        for hit in identify_parcels(args.lat, args.lng):
            try:
                p = get_parcel_by_id(hit["parcel_id"], hit["register"])
            except CadastreError as e:
                print(f"  {hit['register']} {hit['parcel_id']}: {e}")
                continue
            ku = p.get("cadastral_unit") or {}
            print(f"  {p['register']} {p['no']:>10}  s.č. {p.get('house_no') or '—':>6}  "
                  f"{p.get('land_use') or '?'} / {p.get('utilisation') or '?'}  "
                  f"k.ú. {ku.get('name')} ({ku.get('code')})  LV {p.get('lv_no')}")
    except CadastreError as e:
        print(f"identify failed: {e}")
        return 1

    found = parcel_at(args.lat, args.lng)
    print(f"\nparcel_at → {found['status']}: {found['detail']}")
    plot_lv = None
    if found["status"] == "OK":
        parcel = found["parcel"]
        ku = parcel["cadastral_unit"] or {}
        plot = enrich_parcel(str(ku.get("code") or ku.get("name")), parcel["no"],
                             register="C", refresh=True)
        plot_lv = _show_lv("plot LV", plot)

    flat_lv = None
    if args.lv:
        if not args.area:
            print("\n--lv needs --area")
            return 1
        flat_lv = _show_lv("flat LV", enrich_lv(args.area, args.lv, refresh=True))

    print("\n── verdicts the filter would store " + "─" * 26)
    row = {"id": "probe", "district": "", "lat": args.lat, "lng": args.lng,
           "coords_source": "listing", "cadastral_area": None,
           "cadastral_number": None, "cadastral_unit_code": None,
           "plot_lv_number": None, "lv_number": None}
    pin_only = check_listing(row)
    print(f"pin only:     {pin_only['status']} — {pin_only['detail']}")
    if args.lv:
        flat = check_listing({**row, "lv_number": args.lv, "cadastral_area": args.area})
        print(f"with flat LV: {flat['status']} — {flat['detail']}")
    if plot_lv and flat_lv:
        print(f"\nplot LV {plot_lv} vs flat LV {flat_lv}: "
              f"{'SAME' if plot_lv == flat_lv else 'DIFFERENT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
