"""
database — Sovereign Investor Dashboard
SQLite storage (data/sovereign.db), locally and in Docker alike.

One module per topic; this package re-exports every name, so callers keep
writing `import database` / `from database import upsert_listing`:

  schema       the schema, init_db and its column migrations, shared helpers
  listings     sale listings: upserts, active/rejected lists, duplicates
  prices       price history, price cuts, days on market
  enrichment   description and address parsing queues
  scores       cashflow and location scores, and their requeue rules
  title_deeds  LV (title deed) checks, deed text, parcel data, LV to-do
  deals        deal stages, vibe notes, contract drafts
  pipeline     the pipeline lock

The connection lives here, and every topic module opens it as
`database.get_conn()` at call time, so a test that swaps database.get_conn or
database.SQLITE_PATH reaches all of them.

There used to be a PostgreSQL mode, selected whenever DATABASE_URL was set.
It never worked: every query here is SQLite dialect (? and :name placeholders,
INSERT OR REPLACE, PRAGMA, conn.execute on the connection, which psycopg2
connections don't have), and no Postgres schema file existed. Copying
.env.example to .env set DATABASE_URL and broke even local runs. DATABASE_URL
is now ignored.
"""

import os
import sqlite3

from config import SQLITE_PATH


# ── Connection ────────────────────────────────────────────────────────────────
def get_conn():
    os.makedirs(os.path.dirname(SQLITE_PATH) or ".", exist_ok=True)
    # The dashboard and the scheduler are two processes on one file. The default
    # 5 s wait for the other's write lock is shorter than a scraper's batch
    # commit can take, and "database is locked" then kills a pipeline step.
    conn = sqlite3.connect(SQLITE_PATH, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
    except BaseException:
        # Switching to WAL needs a moment of exclusive access; when that
        # fails the caller never gets the connection to close.
        conn.close()
        raise
    return conn


# ── Topics (imported after get_conn, which they look up at call time) ─────────
from database.schema import (
    SQLITE_SCHEMA, _ensure_dev_project_column, _CASHFLOW_NEW_COLUMNS,
    _ensure_cashflow_columns, _DEAL_EXTRA_COLUMNS, _ENRICHMENT_COLUMNS,
    _ensure_enrichment_columns, _LOCATION_NEW_COLUMNS, _ensure_location_columns,
    _ensure_rent_comps_columns, _RENT_COMPS_COLS, _rebuild_rent_comps_with_market,
    _MARKET_COLUMNS, _ensure_market_columns, _market_sql, _market_kw,
    _backfill_listing_coords, _mark_legacy_lv_passes_unverified, init_db, _has_table,
)
from database.listings import (
    _DEV_PROJECT_URL_MARKERS, _DEV_PROJECT_TITLE_MARKERS,
    _DEV_PROJECT_TITLE_MARKERS_CZ, _DEV_PROJECT_FROM_CZK_RE, detect_dev_project,
    backfill_dev_project_flags, get_all_active, get_rejected, mark_duplicates,
    upsert_rental, get_stats, get_active_sources, deactivate_stale_listings,
    mark_details_enriched, touch_listings, deactivate_listings, set_listing_price,
    get_shared_price_listings, get_fresh_detail_urls, fill_blank_district,
    _PIN_MOVE_DEG, _EXISTING_COLS, _pin_moved, upsert_listing,
)
from database.prices import (
    _ensure_price_history, _record_price, _has_price_history, forget_price,
    summarize_price_history, get_price_history, get_price_drops, days_on_market,
)
from database.enrichment import (
    get_listing_description, get_unparsed_descriptions, update_description_features,
    requeue_descriptions_missing_extras, get_unnormalized_addresses, update_address,
)
from database.scores import (
    clear_cashflow_scores, _drop_cashflow_score, _drop_location_score,
    requeue_scores_without_benchmark, requeue_scores_with_stale_class,
    requeue_scores_with_stale_property_tax, requeue_scores_from_older_model,
    upsert_cashflow, upsert_location, get_location_rows_missing_risk,
    update_location_risk, get_unscored_cashflow, get_unscored_location,
    mark_location_tried,
)
from database.title_deeds import (
    set_lv_status, reset_demo_rejections, set_lv_analysis, _LV_ROW_COLUMNS,
    get_pending_lv, get_lv_row, set_parcel_data, _ensure_lv_documents_table,
    set_lv_document, get_lv_documents, get_lv_document, set_flat_lv, get_lv_todo,
    queue_lv_check,
)
from database.deals import (
    DEAL_STAGES, set_deal_stage, get_deal_stages, get_deal_stage_history,
    get_tracked_listings, add_annotation, get_annotations, latest_vibes,
    save_contract_draft, get_contract_drafts,
)
from database.pipeline import (
    try_lock_pipeline, heartbeat_pipeline_lock, unlock_pipeline, get_pipeline_lock,
)
from database.portal_runs import (
    QUIET_RUNS, count_seen_since, record_portal_run, portal_runs, quiet_portals,
)

__all__ = [
    "QUIET_RUNS",
    "count_seen_since",
    "record_portal_run",
    "portal_runs",
    "quiet_portals",
    "SQLITE_PATH",
    "get_conn",
    "SQLITE_SCHEMA",
    "_ensure_dev_project_column",
    "_CASHFLOW_NEW_COLUMNS",
    "_ensure_cashflow_columns",
    "_DEAL_EXTRA_COLUMNS",
    "_ENRICHMENT_COLUMNS",
    "_ensure_enrichment_columns",
    "_LOCATION_NEW_COLUMNS",
    "_ensure_location_columns",
    "_ensure_rent_comps_columns",
    "_RENT_COMPS_COLS",
    "_rebuild_rent_comps_with_market",
    "_MARKET_COLUMNS",
    "_ensure_market_columns",
    "_market_sql",
    "_market_kw",
    "_backfill_listing_coords",
    "_mark_legacy_lv_passes_unverified",
    "init_db",
    "_has_table",
    "_DEV_PROJECT_URL_MARKERS",
    "_DEV_PROJECT_TITLE_MARKERS",
    "_DEV_PROJECT_TITLE_MARKERS_CZ",
    "_DEV_PROJECT_FROM_CZK_RE",
    "detect_dev_project",
    "backfill_dev_project_flags",
    "get_all_active",
    "get_rejected",
    "mark_duplicates",
    "upsert_rental",
    "get_stats",
    "get_active_sources",
    "deactivate_stale_listings",
    "mark_details_enriched",
    "touch_listings",
    "deactivate_listings",
    "set_listing_price",
    "get_shared_price_listings",
    "get_fresh_detail_urls",
    "fill_blank_district",
    "_PIN_MOVE_DEG",
    "_EXISTING_COLS",
    "_pin_moved",
    "upsert_listing",
    "_ensure_price_history",
    "_record_price",
    "_has_price_history",
    "forget_price",
    "summarize_price_history",
    "get_price_history",
    "get_price_drops",
    "days_on_market",
    "get_listing_description",
    "get_unparsed_descriptions",
    "update_description_features",
    "requeue_descriptions_missing_extras",
    "get_unnormalized_addresses",
    "update_address",
    "clear_cashflow_scores",
    "_drop_cashflow_score",
    "_drop_location_score",
    "requeue_scores_without_benchmark",
    "requeue_scores_with_stale_class",
    "requeue_scores_with_stale_property_tax",
    "requeue_scores_from_older_model",
    "upsert_cashflow",
    "upsert_location",
    "get_location_rows_missing_risk",
    "update_location_risk",
    "get_unscored_cashflow",
    "get_unscored_location",
    "mark_location_tried",
    "set_lv_status",
    "reset_demo_rejections",
    "set_lv_analysis",
    "_LV_ROW_COLUMNS",
    "get_pending_lv",
    "get_lv_row",
    "set_parcel_data",
    "_ensure_lv_documents_table",
    "set_lv_document",
    "get_lv_documents",
    "get_lv_document",
    "set_flat_lv",
    "get_lv_todo",
    "queue_lv_check",
    "DEAL_STAGES",
    "set_deal_stage",
    "get_deal_stages",
    "get_deal_stage_history",
    "get_tracked_listings",
    "add_annotation",
    "get_annotations",
    "latest_vibes",
    "save_contract_draft",
    "get_contract_drafts",
    "try_lock_pipeline",
    "heartbeat_pipeline_lock",
    "unlock_pipeline",
    "get_pipeline_lock",
]
