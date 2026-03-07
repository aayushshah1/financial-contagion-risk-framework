"""
update_stress_scores.py
========================
Standalone script that recomputes CRISIL stress scores for all companies and
writes the results back to MongoDB.

Imports stress logic directly from task_company_consolidate so the two are
always in sync (CDR table, multipliers, weighted-median algorithm).

Usage
-----
    python update_stress_scores.py [--dry-run] [--batch-size 500]
"""

import argparse
import logging
import sys
from pathlib import Path

# Make the sibling module importable without package installation
sys.path.insert(0, str(Path(__file__).parent))
from task_company_consolidate import (
    LOCAL_URI,
    LOCAL_DB,
    LOCAL_COL,
    _compute_crisil_stress,
)

from pymongo import MongoClient, UpdateOne

try:
    from tqdm import tqdm
    TQDM = True
except ImportError:
    TQDM = False

# ============================================================================
# Logging
# ============================================================================

LOG_FILE = Path(__file__).parent / "update_stress_scores.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ============================================================================
# Main
# ============================================================================

def run(dry_run: bool = False, batch_size: int = 500) -> None:
    client = MongoClient(LOCAL_URI)
    col    = client[LOCAL_DB][LOCAL_COL]

    log.info("Fetching company documents …")
    cursor = col.find(
        {},
        {"_id": 1, "bankFacilities": 1},
    )

    docs = list(cursor)
    log.info(f"Loaded {len(docs):,} documents")

    ops     = []
    scored  = 0
    skipped = 0

    iterator = tqdm(docs, desc="Computing stress scores", unit="doc") if TQDM else docs
    for doc in iterator:
        facilities   = doc.get("bankFacilities") or []
        stress_result = _compute_crisil_stress(facilities)

        if stress_result is None:
            skipped += 1
            ops.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$unset": {"crisilStressScore": ""}},
            ))
        else:
            scored += 1
            ops.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {"crisilStressScore": stress_result}},
            ))

        # Flush in batches
        if len(ops) >= batch_size and not dry_run:
            col.bulk_write(ops, ordered=False)
            ops = []

    log.info(f"Scored: {scored:,}  |  No scoreable facilities: {skipped:,}")

    if dry_run:
        log.info(f"DRY-RUN: would write {scored + skipped:,} operations — no changes made.")
        client.close()
        return

    # Write remaining ops
    if ops:
        result = col.bulk_write(ops, ordered=False)
        log.info(
            f"Bulk write complete — "
            f"matched: {result.matched_count:,}  "
            f"modified: {result.modified_count:,}"
        )
    else:
        log.info("No operations to write.")

    client.close()
    log.info("Done.")


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recompute CRISIL stress scores and write them to MongoDB."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the full pipeline without writing to MongoDB.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, metavar="N",
        help="Number of UpdateOne operations per bulk_write call (default: 500).",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, batch_size=args.batch_size)
