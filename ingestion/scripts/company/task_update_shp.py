"""
task_update_shp.py
==================
One-shot migration script — updates `shareholdingPattern` in the
`company/mca_crisil_match` collection from the legacy hierarchical format
to the new flat Arelle-driven format produced by the updated extraction code.

Old format (ElementTree fallback):
  shareholdingPattern: {
    promoterHolding:             { aggregate, entities, government, ... },
    publicHolding:               { aggregate, institutions, nonInstitutions },
    nonPromoterNonPublicHolding: { aggregate, entities }
  }

New format (Arelle path — when XBRL has bundled taxonomy):
  shareholdingPattern: {
    periodEnd:         "2025-12-31",
    totalShares:       5333332,
    totalShareholders: 8558,
    aggregates:        { MemberName: { camelCaseFacts }, ... },
    entities:          { AxisName:   [ { nameOfTheShareholder, numberOfShares, ... } ], ... }
  }

ET-fallback documents keep their nested structure (Arelle resolved 0 facts);
only the `shpTotalShares` / `shpTotalShareholders` top-level fields are refreshed
for them.

Usage
-----
    python task_update_shp.py               # update all companies with nseSymbol
    python task_update_shp.py --dry-run     # preview without writing
    python task_update_shp.py --symbol NTPC # update a single symbol
    python task_update_shp.py --old-only    # skip companies that already have new format
"""

import argparse
import logging
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

from pymongo import MongoClient, UpdateOne

try:
    from tqdm import tqdm
    TQDM = True
except ImportError:
    TQDM = False

# ---------------------------------------------------------------------------
# Resolve repo root and add data_consolidation/scripts/company to sys.path
# so we can import extraction helpers from task_company_consolidate directly.
# ---------------------------------------------------------------------------
_HERE      = Path(__file__).resolve().parent
# parents: company(0) → scripts(1) → data_consolidation(2) → Capstone(3)
_REPO_ROOT = _HERE.parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from task_company_consolidate import (   # noqa: E402
    _parse_shp_xml,
    _ArelleCntlr,
    ARELLE_AVAILABLE,
    SHP_DIR,
    LOCAL_URI,
    LOCAL_DB,
    LOCAL_COL,
    log as _parent_log,
)

# ---------------------------------------------------------------------------
# Logging — reuse parent script's handlers but give us our own logger label
# ---------------------------------------------------------------------------
log = logging.getLogger("task_update_shp")
log.setLevel(logging.INFO)
# inherit handlers already attached to root by task_company_consolidate
if not log.handlers:
    import logging as _logging
    _h = _logging.StreamHandler(sys.stdout)
    _h.setFormatter(_logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
    log.addHandler(_h)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_old_format(shp: Optional[dict]) -> bool:
    """Return True if the dict looks like the legacy hierarchical structure."""
    if not isinstance(shp, dict):
        return False
    return "promoterHolding" in shp or "publicHolding" in shp


def _is_new_format(shp: Optional[dict]) -> bool:
    """Return True if the dict is already in the new flat Arelle format."""
    if not isinstance(shp, dict):
        return False
    return "aggregates" in shp or "entities" in shp


def _build_ctrl():
    """Create and return a shared Arelle Cntlr (or None if unavailable)."""
    if not ARELLE_AVAILABLE:
        log.info("Arelle not installed — ET fallback will be used for all files")
        return None
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        ctrl = _ArelleCntlr.Cntlr(logFileName="logToPrint")
        ctrl.webCache.workOffline = True
        sys.stdout = old_stdout
        log.info("Arelle controller ready (taxonomy-validated extraction)")
        return ctrl
    except Exception as exc:
        sys.stdout = old_stdout
        log.warning(f"Arelle init failed ({exc}) — using ElementTree")
        return None


# ---------------------------------------------------------------------------
# Core update logic
# ---------------------------------------------------------------------------

def run(
    dry_run:   bool = False,
    old_only:  bool = False,
    symbol:    Optional[str] = None,
) -> None:
    """
    Re-extract SHP for target companies and push updates to MongoDB.

    Parameters
    ----------
    dry_run  : log what would be done but write nothing
    old_only : only process companies that still have the old-format `shareholdingPattern`
    symbol   : process a single NSE symbol (overrides old_only)
    """
    client    = MongoClient(LOCAL_URI)
    col       = client[LOCAL_DB][LOCAL_COL]

    # -----------------------------------------------------------------------
    # Build query — always limit to documents that have an nseSymbol
    # -----------------------------------------------------------------------
    query: dict = {"nseSymbol": {"$exists": True, "$ne": None, "$ne": ""}}

    if symbol:
        query["nseSymbol"] = symbol
        log.info(f"Single-symbol mode: {symbol}")
    elif old_only:
        # Target only documents where shareholdingPattern still has legacy keys
        query["$or"] = [
            {"shareholdingPattern.promoterHolding": {"$exists": True}},
            {"shareholdingPattern.publicHolding":   {"$exists": True}},
        ]
        log.info("old_only mode: targeting legacy shareholdingPattern documents only")

    projection = {"_id": 1, "nseSymbol": 1, "companyCode": 1, "shareholdingPattern": 1}
    records: List[dict] = list(col.find(query, projection))
    log.info(f"Found {len(records):,} document(s) to process")

    if not records:
        log.info("Nothing to do.")
        client.close()
        return

    # -----------------------------------------------------------------------
    # Initialise Arelle (shared controller for all files)
    # -----------------------------------------------------------------------
    ctrl = _build_ctrl()

    # -----------------------------------------------------------------------
    # Parse each SHP file and build update ops
    # -----------------------------------------------------------------------
    ops:         List[UpdateOne] = []
    new_fmt:     int = 0
    et_fmt:      int = 0
    missing_xml: int = 0
    parse_err:   int = 0

    iterator = (
        tqdm(records, desc="Updating SHP", unit="company") if TQDM else records
    )

    for rec in iterator:
        sym = rec.get("nseSymbol")
        if not sym:
            continue

        xml_path = SHP_DIR / f"shareholding_{sym}_2025-12-31.xml"
        if not xml_path.exists():
            missing_xml += 1
            log.debug(f"  {sym}: XML not found at {xml_path}")
            continue

        try:
            result = _parse_shp_xml(xml_path, ctrl=ctrl)
        except Exception as exc:
            parse_err += 1
            log.warning(f"  {sym}: extraction error — {exc}")
            continue

        if not result:
            log.debug(f"  {sym}: extractor returned empty result, skipping")
            continue

        update: dict = {}

        # ------------------------------------------------------------------
        # Arelle path — result has `aggregates` / `entities` keys directly
        # ------------------------------------------------------------------
        if "aggregates" in result or "entities" in result:
            # Store the full flat structure directly as shareholdingPattern
            update["shareholdingPattern"]  = result
            update["shpTotalShares"]       = result.get("totalShares")
            update["shpTotalShareholders"] = result.get("totalShareholders")
            new_fmt += 1
            log.debug(
                f"  {sym}: Arelle  — "
                f"{len(result.get('aggregates', {}))} aggregates, "
                f"{len(result.get('entities', {}))} entity-axes"
            )

        # ------------------------------------------------------------------
        # ET fallback path — result has `shareholdingPattern` key (nested)
        # ------------------------------------------------------------------
        elif "shareholdingPattern" in result:
            update["shareholdingPattern"]  = result["shareholdingPattern"]
            update["shpTotalShares"]       = result.get("totalShares")
            update["shpTotalShareholders"] = result.get("totalShareholders")
            et_fmt += 1
            log.debug(f"  {sym}: ET fallback — nested structure retained")

        else:
            log.warning(f"  {sym}: unrecognised result shape, skipping — keys: {list(result.keys())}")
            continue

        ops.append(UpdateOne({"_id": rec["_id"]}, {"$set": update}))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    log.info(
        f"Extraction complete — "
        f"Arelle (new format): {new_fmt}  |  "
        f"ET fallback: {et_fmt}  |  "
        f"XML not found: {missing_xml}  |  "
        f"Parse errors: {parse_err}"
    )
    log.info(f"Prepared {len(ops):,} update operation(s)")

    if dry_run:
        log.info("DRY-RUN: no writes performed.")
        client.close()
        return

    if not ops:
        log.info("No updates to write.")
        client.close()
        return

    # -----------------------------------------------------------------------
    # Execute bulk write
    # -----------------------------------------------------------------------
    result_bw = col.bulk_write(ops, ordered=False)
    log.info(
        f"Bulk write complete — "
        f"matched: {result_bw.matched_count:,}  "
        f"modified: {result_bw.modified_count:,}"
    )

    client.close()
    log.info("Done.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Migrate shareholdingPattern in company/mca_crisil_match "
            "from the legacy nested format to the new Arelle flat format."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run everything but skip MongoDB writes.",
    )
    parser.add_argument(
        "--old-only", action="store_true",
        help="Restrict to documents that still have the legacy shareholdingPattern structure.",
    )
    parser.add_argument(
        "--symbol", metavar="SYM", default=None,
        help="Process a single NSE symbol (e.g. NTPC, GRPLTD). Overrides --old-only.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, old_only=args.old_only, symbol=args.symbol)
