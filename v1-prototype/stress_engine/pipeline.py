"""
stress_engine/pipeline.py
Main orchestrator for the news stress pipeline.

Routing
-------
    Bank          → scraper.fetch_news  → FinBERT → decay → baseline → Z-score
    Company       → scraper.fetch_news  → FinBERT → decay → baseline → Z-score
    PrioritySector → gdelt_sector.fetch_sector_stress     → baseline → Z-score
    Industry       → gdelt_sector.fetch_sector_stress     → baseline → Z-score

Write-back
----------
    fieldName:   newsStress      (float [0, 1])
    fieldName:   newsStressDate  (ISO-8601 string "YYYY-MM-DD")
    Collection:  financial_kg.banks       (matched by  bankSymbol)
                 financial_kg.companies   (matched by  cin)

CLI
---
    python -m stress_engine.pipeline --type bank
    python -m stress_engine.pipeline --type company
    python -m stress_engine.pipeline --type priority_sector
    python -m stress_engine.pipeline --type industry

    python -m stress_engine.pipeline --type bank --entity-id HDFCBANK
    python -m stress_engine.pipeline --type company --entity-id L17110MH1973PLC019786
    python -m stress_engine.pipeline --type all          # run all four types
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pymongo import MongoClient

# ------------------------------------
# Ensure project root on path so imports resolve when run directly
# ------------------------------------
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from stress_engine.config import (
    MONGODB_URI,
    DB_NAME,
    BANKS_COLLECTION,
    COMPANY_COLLECTION,
    TARGET_BANK_SYMBOLS,
    BANK_DISPLAY_NAMES,
    BASELINE_WINDOW_DAYS,
    DECAY_HALFLIFE_DAYS,
    PRIORITY_SECTOR_GDELT_TERMS,
)
from stress_engine.scraper import fetch_news
from stress_engine.finbert_scorer import score_articles
from stress_engine.decay import apply_decay
from stress_engine.baseline import BaselineStore
from stress_engine.zscore_mapper import compute_stress, stress_label
from stress_engine.gdelt_sector import fetch_sector_stress

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single-entity entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    entity_id: str,
    entity_type: str,
    entity_name: str,
    store: BaselineStore,
    tor_session=None,
    today: date | None = None,
) -> float:
    """
    Run the full news pipeline for one entity.

    Parameters
    ----------
    entity_id   : str  — primary key (bankSymbol | cin | rbiCategory | industryCode)
    entity_type : str  — "bank" | "company" | "priority_sector" | "industry"
    entity_name : str  — human-readable name used in search queries
    store       : BaselineStore  — open connection to news_baselines collection
    tor_session : TorSessionManager | None
    today       : date | None  — override "today" (useful in tests)

    Returns
    -------
    float — newsStress in [0, 1]
    """
    today = today or date.today()

    # --- 1. Fetch and score articles ---
    if entity_type in ("priority_sector", "industry"):
        scored_articles, raw_aggregate = fetch_sector_stress(entity_id, entity_type)
    else:
        articles = fetch_news(entity_name, entity_type, tor_session=tor_session)
        scored_articles = score_articles(articles)
        raw_aggregate = apply_decay(scored_articles, halflife_days=DECAY_HALFLIFE_DAYS)

    # --- 2. Persist today's aggregate ---
    store.upsert_daily(entity_id, entity_type, today, raw_aggregate)

    # --- 3. Retrieve rolling baseline ---
    mean, std, history_days = store.get_baseline(
        entity_id, entity_type, window_days=BASELINE_WINDOW_DAYS
    )

    # --- 4. Map to [0, 1] ---
    stress = compute_stress(raw_aggregate, mean, std, history_days)

    logger.info(
        "[pipeline] %-12s %-14s raw=%.4f  Z-baseline(mean=%.4f, std=%.4f, n=%d) → stress=%.4f (%s)",
        entity_id, entity_type, raw_aggregate, mean, std, history_days,
        stress, stress_label(stress),
    )
    return stress


# ---------------------------------------------------------------------------
# Baseline backfill
# ---------------------------------------------------------------------------

def backfill_entity_baseline(
    entity_id: str,
    entity_type: str,
    entity_name: str,
    store: BaselineStore,
    tor_session=None,
) -> int:
    """
    Populate the rolling baseline with per-day scores from a single
    DDG timelimit='m' fetch (~30 days of articles).

    For each unique publication date in the returned articles, compute the
    plain mean of that day's FinBERT scores and upsert it into
    news_baselines.  Already-existing records for a date are overwritten.

    Returns the number of days written.
    """
    articles = fetch_news(entity_name, entity_type, tor_session=tor_session)
    if not articles:
        logger.warning("[backfill] No articles found for %s (%s)", entity_id, entity_type)
        return 0

    scored = score_articles(articles)

    # Group FinBERT scores by publication date
    by_date: dict[date, list[float]] = defaultdict(list)
    today = date.today()
    for art in scored:
        pub = art.get("date")
        if isinstance(pub, datetime):
            pub = pub.date()
        if pub is None:
            pub = today
        by_date[pub].append(art.get("score", 0.0))

    days_written = 0
    for pub_date, scores in sorted(by_date.items()):
        daily_mean = sum(scores) / len(scores)
        store.upsert_daily(entity_id, entity_type, pub_date, daily_mean)
        days_written += 1
        logger.debug("[backfill] %s  %s  n=%d  score=%.4f", pub_date, entity_id, len(scores), daily_mean)

    logger.info(
        "[backfill] %s (%s): wrote %d days of baseline history.",
        entity_id, entity_type, days_written,
    )
    return days_written


def run_backfill_banks(
    store: BaselineStore,
    tor_session=None,
    entity_id_filter: str | None = None,
) -> dict[str, int]:
    """Backfill 30-day baseline for all target banks (or a single bank)."""
    results: dict[str, int] = {}
    bank_ids = [entity_id_filter] if entity_id_filter else TARGET_BANK_SYMBOLS
    for symbol in bank_ids:
        name = BANK_DISPLAY_NAMES.get(symbol, symbol)
        try:
            n = backfill_entity_baseline(symbol, "bank", name, store, tor_session=tor_session)
            results[symbol] = n
        except Exception as exc:
            logger.error("[backfill] Failed for bank %s: %s", symbol, exc, exc_info=True)
            results[symbol] = 0
    return results


def run_backfill_companies(
    store: BaselineStore,
    mongo_client: MongoClient,
    tor_session=None,
    entity_id_filter: str | None = None,
) -> dict[str, int]:
    """Backfill 30-day baseline for company nodes."""
    results: dict[str, int] = {}
    col = mongo_client[DB_NAME][COMPANY_COLLECTION]

    query_filter: dict = {}
    if entity_id_filter:
        query_filter = {"cin": entity_id_filter}

    cursor = col.find(query_filter, {"cin": 1, "crisilName": 1, "mcaName": 1, "dummyCIN": 1})
    for i, doc in enumerate(cursor, 1):
        cin = doc.get("cin") or doc.get("dummyCIN")
        if not cin:
            continue
        name = doc.get("crisilName") or doc.get("mcaName") or cin
        try:
            n = backfill_entity_baseline(cin, "company", name, store, tor_session=tor_session)
            results[cin] = n
        except Exception as exc:
            logger.error("[backfill] Failed for company %s: %s", cin, exc, exc_info=True)
            results[cin] = 0
        if i % 20 == 0:
            logger.info("[backfill] Progress: %d companies processed.", i)
    return results


# ---------------------------------------------------------------------------
# Batch runners
# ---------------------------------------------------------------------------

def run_batch_banks(
    store: BaselineStore,
    mongo_client: MongoClient,
    tor_session=None,
    entity_id_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, float]:
    """
    Run the news pipeline for all 3 target banks (or a single bank).
    Write ``newsStress`` back to ``financial_kg.banks``.

    Returns dict mapping bankSymbol → newsStress score.
    """
    today = date.today()
    results: dict[str, float] = {}
    col = mongo_client[DB_NAME][BANKS_COLLECTION]

    bank_ids = [entity_id_filter] if entity_id_filter else TARGET_BANK_SYMBOLS
    for symbol in bank_ids:
        name = BANK_DISPLAY_NAMES.get(symbol, symbol)
        try:
            stress = run_pipeline(symbol, "bank", name, store, tor_session=tor_session, today=today)
            results[symbol] = stress

            if not dry_run:
                col.update_one(
                    {"bankSymbol": symbol},
                    {"$set": {"newsStress": round(stress, 6), "newsStressDate": today.isoformat()}},
                )
                logger.info("[pipeline] Wrote newsStress=%.4f to banks(%s)", stress, symbol)
        except Exception as exc:
            logger.error("[pipeline] Failed for bank %s: %s", symbol, exc, exc_info=True)
            results[symbol] = None

    return results


def run_batch_companies(
    store: BaselineStore,
    mongo_client: MongoClient,
    tor_session=None,
    entity_id_filter: str | None = None,
    dry_run: bool = False,
    batch_size: int = 200,
) -> dict[str, float]:
    """
    Run the pipeline for Company nodes.  Iterates over financial_kg.companies,
    using ``cin`` as the entity_id and ``crisilName`` (or ``mcaName``) as the search name.

    Write-back: ``newsStress`` and ``newsStressDate`` on each company document.
    Returns dict mapping cin → newsStress score.
    """
    today = date.today()
    results: dict[str, float] = {}
    col = mongo_client[DB_NAME][COMPANY_COLLECTION]

    query_filter: dict = {}
    if entity_id_filter:
        query_filter = {"cin": entity_id_filter}

    total = col.count_documents(query_filter)
    logger.info("[pipeline] Processing %d company nodes …", total)

    cursor = col.find(query_filter, {"cin": 1, "crisilName": 1, "mcaName": 1, "dummyCIN": 1})
    for i, doc in enumerate(cursor, 1):
        cin = doc.get("cin") or doc.get("dummyCIN")
        if not cin:
            continue

        name = doc.get("crisilName") or doc.get("mcaName") or cin
        try:
            stress = run_pipeline(cin, "company", name, store, tor_session=tor_session, today=today)
            results[cin] = stress

            if not dry_run:
                col.update_one(
                    {"cin": cin},
                    {"$set": {"newsStress": round(stress, 6), "newsStressDate": today.isoformat()}},
                )
        except Exception as exc:
            logger.error("[pipeline] Failed for company %s (%s): %s", cin, name, exc, exc_info=True)
            results[cin] = None

        if i % 50 == 0:
            logger.info("[pipeline] Progress: %d / %d companies processed.", i, total)

    return results


def run_batch_priority_sectors(
    store: BaselineStore,
    mongo_client: MongoClient,
    entity_id_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, float]:
    """
    Compute GDELT-based stress for each RBI priority sector category.
    Results are stored only in news_baselines (no write-back to banks collection —
    priority sector stress is an edge-level multiplier, not a bank-node property).
    """
    today = date.today()
    results: dict[str, float] = {}

    sector_ids = [entity_id_filter] if entity_id_filter else list(PRIORITY_SECTOR_GDELT_TERMS.keys())
    for rbi_cat in sector_ids:
        try:
            stress = run_pipeline(rbi_cat, "priority_sector", rbi_cat, store, tor_session=None, today=today)
            results[rbi_cat] = stress
        except Exception as exc:
            logger.error("[pipeline] Failed for priority_sector %s: %s", rbi_cat, exc, exc_info=True)
            results[rbi_cat] = None

    return results


def run_batch_industries(
    store: BaselineStore,
    mongo_client: MongoClient,
    entity_id_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, float]:
    """
    Compute GDELT-based stress for all Industry nodes stored in MongoDB
    (financial_kg.companies  distinct industryCode / industryName values).
    """
    today = date.today()
    results: dict[str, float] = {}
    col = mongo_client[DB_NAME][COMPANY_COLLECTION]

    # Collect unique (industryCode, industryName) pairs
    pipeline_agg = [
        {"$match": {"industryCode": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$industryCode", "industryName": {"$first": "$industryName"}}},
    ]
    industry_docs = list(col.aggregate(pipeline_agg))
    logger.info("[pipeline] Found %d unique industry codes.", len(industry_docs))

    for doc in industry_docs:
        code = doc["_id"]
        name = doc.get("industryName") or code

        if entity_id_filter and code != entity_id_filter:
            continue

        try:
            stress = run_pipeline(code, "industry", name, store, tor_session=None, today=today)
            results[code] = stress
        except Exception as exc:
            logger.error("[pipeline] Failed for industry %s: %s", code, exc, exc_info=True)
            results[code] = None

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m stress_engine.pipeline",
        description="News stress pipeline for the Financial Knowledge Graph",
    )
    parser.add_argument(
        "--type",
        choices=["bank", "company", "priority_sector", "industry", "all"],
        default="bank",
        help="Node type to run the pipeline for (default: bank)",
    )
    parser.add_argument(
        "--entity-id",
        default=None,
        help="Run for a single entity only (e.g. HDFCBANK or a CIN string)",
    )
    parser.add_argument(
        "--no-tor",
        action="store_true",
        help="Disable Tor; use direct internet connection for scraping",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute stress scores but do NOT write back to MongoDB",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Populate the rolling baseline with per-day scores from the last "
            "~30 days of articles before running the daily pipeline. "
            "Use once on a fresh installation to avoid the cold-start period."
        ),
    )
    parser.add_argument(
        "--backfill-only",
        action="store_true",
        help="Run the backfill but skip the normal daily pipeline run.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _setup_logging(args.verbose)

    run_type    = args.type
    entity_id   = args.entity_id
    use_tor     = not args.no_tor
    dry_run     = args.dry_run
    do_backfill = args.backfill or args.backfill_only
    backfill_only = args.backfill_only

    # ---- Setup Tor (optional) ----
    tor_session = None
    if use_tor and run_type in ("bank", "company", "all"):
        try:
            from data_consolidation.tor_manager import TorSessionManager
            tor_session = TorSessionManager(
                project_root=str(_PROJECT_ROOT),
                rotation_interval=5,
                tor_enabled=True,
                auto_start_tor=True,
            )
            logger.info("[pipeline] Tor session started.")
        except Exception as exc:
            logger.warning("[pipeline] Could not start Tor (%s). Running without Tor.", exc)
            tor_session = None

    # ---- Open MongoDB + BaselineStore ----
    try:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=10_000,
            connectTimeoutMS=10_000,
        )
        store = BaselineStore()
    except Exception as exc:
        logger.error(
            "[pipeline] Cannot connect to MongoDB: %s\n"
            "Check that db_cluster_link is set in .env and that your network "
            "can resolve the Atlas SRV hostname.",
            exc,
        )
        sys.exit(1)

    try:
        # ---- Backfill (optional) ----
        if do_backfill:
            logger.info("[pipeline] Starting baseline backfill (last ~30 days) …")
            if run_type in ("bank", "all"):
                bf = run_backfill_banks(store, tor_session=tor_session, entity_id_filter=entity_id)
                for sym, n in bf.items():
                    logger.info("[backfill] %-12s  %d days written", sym, n)
            if run_type in ("company", "all"):
                bf = run_backfill_companies(store, client, tor_session=tor_session, entity_id_filter=entity_id)
                logger.info("[backfill] Companies backfilled: %d", len(bf))
            if backfill_only:
                print("\n[backfill] Done. Skipping daily pipeline run (--backfill-only).\n")
                return
            logger.info("[pipeline] Backfill complete. Proceeding with daily run …")

        results_summary: dict[str, dict] = {}

        if run_type in ("bank", "all"):
            res = run_batch_banks(store, client, tor_session=tor_session, entity_id_filter=entity_id, dry_run=dry_run)
            results_summary["bank"] = res

        if run_type in ("company", "all"):
            res = run_batch_companies(store, client, tor_session=tor_session, entity_id_filter=entity_id, dry_run=dry_run)
            results_summary["company"] = res

        if run_type in ("priority_sector", "all"):
            res = run_batch_priority_sectors(store, client, entity_id_filter=entity_id, dry_run=dry_run)
            results_summary["priority_sector"] = res

        if run_type in ("industry", "all"):
            res = run_batch_industries(store, client, entity_id_filter=entity_id, dry_run=dry_run)
            results_summary["industry"] = res

        # ---- Summary print ----
        print("\n" + "=" * 60)
        print("  NEWS STRESS PIPELINE — RESULTS SUMMARY")
        print("=" * 60)
        for node_type, scores in results_summary.items():
            print(f"\n  [{node_type.upper()}]")
            for eid, s in scores.items():
                label = stress_label(s) if s is not None else "ERROR"
                score_str = f"{s:.4f}" if s is not None else "N/A  "
                print(f"    {eid:<40}  {score_str}  ({label})")

        if dry_run:
            print("\n  [DRY RUN] No data was written to MongoDB.")
        print("=" * 60 + "\n")

    finally:
        store.close()
        client.close()
        if tor_session is not None:
            try:
                tor_session.__exit__(None, None, None)
            except Exception:
                pass


if __name__ == "__main__":
    main()
