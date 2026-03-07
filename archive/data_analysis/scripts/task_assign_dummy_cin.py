"""
task_assign_dummy_cin.py
========================
Find all companies in the cloud MongoDB `financial_kg/companies` collection that have
no `cin` field (field absent, null, or empty string), assign each a deterministic
dummy CIN, persist the update back to MongoDB, and export the list as a CSV.

Dummy CIN format (21 chars, mirrors real CIN structure):
    D 00000 NA 2026 DUM {index:06d}
    │ ││││  ││ ││││ │││ └─ 6-digit sequence
    │ ││││  ││ ││││ └──── ownership marker (DUM)
    │ ││││  ││ └─────────── year placeholder (2026)
    │ ││││  └───────────── state placeholder (NA)
    │ └────────────────────── NIC placeholder (00000)
    └───────────────────────── listing marker  (D = Dummy)

Usage
-----
    python task_assign_dummy_cin.py [--dry-run]

    --dry-run   Print counts and sample rows; do NOT write to MongoDB or CSV.

Output
------
    data_analysis/outputs/list_companies_dummy_cin.csv
        Columns: crisilName, dummyCIN

Author: auto-generated  |  Date: February 2026
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()
CLOUD_URI   = os.getenv("db_cluster_link")
DB_NAME     = "financial_kg"
COLLECTION  = "companies"

OUTPUT_DIR  = Path(__file__).resolve().parents[1] / "outputs"
OUTPUT_CSV  = OUTPUT_DIR / "list_companies_dummy_cin.csv"

DUMMY_CIN_TEMPLATE = "D00000NA2026DUM{index:06d}"   # 21 chars

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_dummy_cin(index: int) -> str:
    """Return a 21-character dummy CIN for the given 1-based sequential index."""
    cin = DUMMY_CIN_TEMPLATE.format(index=index)
    assert len(cin) == 21, f"BUG: generated CIN '{cin}' is {len(cin)} chars, expected 21"
    return cin


def has_no_cin(doc: dict) -> bool:
    """Return True when the document is missing a usable CIN."""
    cin = doc.get("cin")
    return cin is None or (isinstance(cin, str) and cin.strip() == "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(dry_run: bool = False) -> None:
    log.info("Connecting to cloud MongoDB …")
    client = MongoClient(CLOUD_URI, serverSelectionTimeoutMS=15_000)
    col    = client[DB_NAME][COLLECTION]

    # -----------------------------------------------------------------
    # Query: documents where `cin` is absent OR null OR empty string.
    # The $or covers all three cases in a single round-trip.
    # -----------------------------------------------------------------
    query = {
        "$or": [
            {"cin": {"$exists": False}},
            {"cin": None},
            {"cin": ""},
        ]
    }

    projection = {"_id": 1, "companyCode": 1, "crisilName": 1, "cin": 1}

    log.info("Fetching documents with no CIN …")
    docs = list(col.find(query, projection))
    log.info("Found %d document(s) with no CIN.", len(docs))

    if not docs:
        log.info("Nothing to do — all documents already have a CIN.")
        return

    # -----------------------------------------------------------------
    # Assign dummy CINs
    # -----------------------------------------------------------------
    assignments: list[dict] = []
    ops: list[UpdateOne] = []

    for i, doc in enumerate(docs, start=1):
        dummy = make_dummy_cin(i)
        name  = doc.get("crisilName") or doc.get("companyCode") or str(doc["_id"])
        assignments.append({"crisilName": name, "dummyCIN": dummy})

        ops.append(
            UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {"cin": dummy, "dummyCIN": True}},
            )
        )

    # -----------------------------------------------------------------
    # Preview in dry-run mode
    # -----------------------------------------------------------------
    if dry_run:
        log.info("[DRY-RUN] Would update %d documents. Sample:", len(ops))
        for row in assignments[:10]:
            log.info("  %-60s  →  %s", row["crisilName"], row["dummyCIN"])
        if len(assignments) > 10:
            log.info("  … (%d more)", len(assignments) - 10)
        log.info("[DRY-RUN] No changes written to MongoDB or CSV.")
        return

    # -----------------------------------------------------------------
    # Bulk-write to MongoDB
    # -----------------------------------------------------------------
    log.info("Writing %d updates to MongoDB (bulk_write) …", len(ops))
    result = col.bulk_write(ops, ordered=False)
    log.info(
        "bulk_write complete — matched: %d, modified: %d",
        result.matched_count,
        result.modified_count,
    )

    # -----------------------------------------------------------------
    # Export CSV
    # -----------------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Writing CSV → %s", OUTPUT_CSV)

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["crisilName", "dummyCIN"])
        writer.writeheader()
        writer.writerows(assignments)

    log.info("Done. %d rows written to %s", len(assignments), OUTPUT_CSV.name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assign dummy CINs to company documents missing a CIN."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only — do not write to MongoDB or create the CSV.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
