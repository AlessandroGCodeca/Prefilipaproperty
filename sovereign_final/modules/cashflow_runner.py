"""
modules/cashflow_runner.py — Sovereign Investor Dashboard
Runs the financial engine on all unscored PASS listings — each in its own
market (listings.market): a Czech listing is scored in CZK under the Czech
rules, a Slovak one exactly as before.
"""

import logging
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import (
    get_unscored_cashflow, upsert_cashflow, init_db, requeue_scores_without_benchmark,
    requeue_scores_with_stale_class, requeue_scores_from_older_model,
)
from engine.financial import analyse, result_to_db_dict, deal_extras, base_rent_rate
import markets

log = logging.getLogger(__name__)


def _mkw(market: str) -> dict:
    return {} if market == "sk" else {"market": market}


def run_scoring(progress_callback=None, market: str | None = None) -> int:
    """Score every unscored listing — of `market` only, or of every market
    (None) — and return how many were scored."""
    requeued = requeue_scores_without_benchmark()
    if requeued:
        log.info(f"♻️  {requeued} listings now have a regional median — re-scoring them.")
    stale = requeue_scores_with_stale_class()
    if stale:
        log.info(f"♻️  {stale} scores no longer match the current class rules — re-scoring them.")
    older = requeue_scores_from_older_model()
    if older:
        log.info(f"♻️  {older} scores came from an older model or tax table — re-scoring them.")
    listings = get_unscored_cashflow(market=market)
    if not listings:
        log.info("✅ No new listings to score.")
        return 0

    # Live €/m² from prenájom comps (engine/rent_comps), read once per run and
    # market. Empty when no rentals have been scraped yet — the baseline then
    # applies.
    from engine.rent_comps import load_live_rates
    rates_by_market: dict[str, dict] = {}

    def rates_for(m: str) -> dict:
        if m not in rates_by_market:
            rates_by_market[m] = load_live_rates() if m == "sk" else load_live_rates(market=m)
            if rates_by_market[m]:
                log.info(f"🏘️  Using live rent comps for {len(rates_by_market[m])} "
                         f"districts ({m.upper()}).")
        return rates_by_market[m]

    log.info(f"💰 Scoring {len(listings)} listings...")
    scored = 0
    # A market figure that isn't in markets.py yet (a Czech place with no rent
    # figure): those listings wait, counted and named once at the end.
    waiting: dict[str, list] = {}
    emojis = {"GREEN": "🟢", "YELLOW": "🟡", "WHITE": "⚪"}

    for i, row in enumerate(listings):
        if progress_callback:
            progress_callback(i + 1, len(listings))

        try:
            district = row.get("district") or ""
            m = markets.of_row(row)
            rates = rates_for(m)
            result = analyse(
                price_eur  = row["price_eur"],
                size_m2    = row["size_m2"],
                district   = district,
                listing_id = row["id"],
                rooms      = row.get("rooms"),
                parking    = row.get("has_parking"),
                furnished  = row.get("furnished"),
                balcony    = row.get("has_balcony"),
                rent_rates = rates,
                **_mkw(m),
            )
            db_data = result_to_db_dict(result)
            db_data.update(deal_extras(result))
            db_data["rent_source"] = base_rent_rate(district, rates, **_mkw(m))[2]
            upsert_cashflow(db_data)
            scored += 1
            e = emojis.get(result.classification, "")
            if m == "sk":
                log.info(f"  {e} {result.classification} | €{result.price_eur:,.0f} | "
                         f"s.r.o. surplus €{result.surplus_sro:+,.0f}/mo | "
                         f"{row.get('district','?')}")
            else:
                cur = result.currency
                log.info(f"  {e} [{m.upper()}] {result.classification} | "
                         f"{markets.format_money(result.price_eur, cur)} | s.r.o. surplus "
                         f"{markets.format_money(result.surplus_sro, cur, signed=True)}/mo | "
                         f"{row.get('district','?')}")
        except LookupError as ex:
            waiting.setdefault(markets.of_row(row), []).append(str(ex))
        except Exception as ex:
            log.warning(f"  ⚠️ Score error for {row['id']}: {ex}")

    for m, why in waiting.items():
        log.info(f"  ℹ️ {len(why)} {m.upper()} listing(s) not scored — {why[0]}"
                 + (f" (and {len(set(why)) - 1} other reason(s))" if len(set(why)) > 1 else ""))
    log.info(f"✅ Cash-flow scoring done. {scored} scored.")
    return scored


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    run_scoring()
