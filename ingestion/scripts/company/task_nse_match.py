"""
task_nse_match.py
=================
Match CRISIL+MCA companies (listingStatus='Listed') to NSE equity symbols.

Sources
-------
  - MongoDB company/mca_crisil_match  →  records where listingStatus == 'Listed'
  - data_analysis/outputs/EQUITY_L.csv    (NSE main board)
  - data_analysis/outputs/SME_EQUITY_L.csv (NSE SME board)

Match pipeline (in priority order)
------------------------------------
  1. exact         – normalize(crisilName)   == normalize(nse_name)   → confidence 100
  2. exact_mca     – normalize(mcaName)      == normalize(nse_name)   → confidence 100
  3. fuzzy         – token_set_ratio(crisilName, nse_name) ≥ threshold → confidence = score
  4. fuzzy_mca     – token_set_ratio(mcaName,   nse_name) ≥ threshold → confidence = score

Upsert fields added to each matched document
---------------------------------------------
  nseSymbol        – NSE ticker symbol
  nseMarket        – 'EQUITY' or 'SME'
  nseMatchType     – one of exact / exact_mca / fuzzy / fuzzy_mca
  nseMatchConfidence – integer 0–100

Documents with no match get nseSymbol=None so they can be identified later.

Usage
-----
  python task_nse_match.py [--dry-run] [--threshold 80]

Author: auto-generated  |  Date: February 2026
"""

import re
import sys
import logging
import argparse
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process
from pymongo import MongoClient, UpdateOne

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MONGO_URI        = "mongodb://127.0.0.1:27108/?directConnection=true"
DB_NAME          = "company"
COLLECTION_NAME  = "mca_crisil_match"

# __file__ is scripts/company/task_nse_match.py
# parents: company(0) → scripts(1) → data_consolidation(2) → Capstone(3)
_REPO_ROOT       = Path(__file__).resolve().parents[3]   # d:\...\Capstone
EQUITY_CSV       = _REPO_ROOT / "data_analysis" / "outputs" / "EQUITY_L.csv"
SME_CSV          = _REPO_ROOT / "data_analysis" / "outputs" / "SME_EQUITY_L.csv"

DEFAULT_THRESHOLD = 80   # minimum fuzzy confidence to accept (0-100)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "task_nse_match.log",
                            encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_BRACKETS_RE    = re.compile(r"-?\([^)]*\)")          # remove (Amalgamated) etc.
_PVT_LTD_RE     = re.compile(r"\bPRIVATE\s+LIMITED\b|\bPVT\.?\s*LTD\.?\b")
_LIMITED_RE     = re.compile(r"\bLIMITED\b")
_LTD_RE         = re.compile(r"\bLTD\.?\b")
_PUNCT_RE       = re.compile(r"[^\w\s]")
_WS_RE          = re.compile(r"\s+")


def normalize(name: str) -> str:
    """
    Normalise a company name for matching.

    Steps
    -----
    1. Strip bracketed status tags  e.g. -(Amalgamated)
    2. Upper-case
    3. Standardise PRIVATE LIMITED → PVT LTD, LIMITED → LTD
    4. Strip remaining punctuation
    5. Collapse whitespace
    """
    if not name or not isinstance(name, str):
        return ""
    name = _BRACKETS_RE.sub("", name)
    name = name.upper()
    name = _PVT_LTD_RE.sub("PVT LTD", name)
    name = _LIMITED_RE.sub("LTD", name)
    name = _LTD_RE.sub("LTD", name)
    name = _PUNCT_RE.sub(" ", name)
    name = _WS_RE.sub(" ", name)
    return name.strip()


# ---------------------------------------------------------------------------
# Load NSE data
# ---------------------------------------------------------------------------

def load_nse_data() -> dict[str, dict]:
    """
    Load both NSE CSV files and return a mapping:
        normalized_name  →  {symbol, originalName, market, isin}

    If two entries share the same normalised name the last one wins
    (duplicates across boards are extremely rare; NSE itself enforces unique symbols).
    """
    frames = []

    # ---- Main board --------------------------------------------------------
    eq_df = pd.read_csv(EQUITY_CSV, dtype=str)
    eq_df.columns = eq_df.columns.str.strip()          # remove leading/trailing spaces
    eq_df = eq_df.rename(columns={"NAME OF COMPANY": "NAME_OF_COMPANY",
                                   "ISIN NUMBER": "ISIN_NUMBER"})
    eq_df["market"] = "EQUITY"
    frames.append(eq_df[["SYMBOL", "NAME_OF_COMPANY", "market", "ISIN_NUMBER"]])

    # ---- SME board ---------------------------------------------------------
    sme_df = pd.read_csv(SME_CSV, dtype=str)
    sme_df.columns = sme_df.columns.str.strip()
    sme_df["market"] = "SME"
    frames.append(sme_df[["SYMBOL", "NAME_OF_COMPANY", "market", "ISIN_NUMBER"]])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["SYMBOL", "NAME_OF_COMPANY"])

    nse_lookup: dict[str, dict] = {}
    for _, row in combined.iterrows():
        norm_key = normalize(str(row["NAME_OF_COMPANY"]))
        if norm_key:
            nse_lookup[norm_key] = {
                "symbol":       str(row["SYMBOL"]).strip(),
                "originalName": str(row["NAME_OF_COMPANY"]).strip(),
                "market":       row["market"],
                "isin":         str(row.get("ISIN_NUMBER", "")).strip(),
            }

    log.info(f"Loaded {len(nse_lookup):,} NSE entries  "
             f"({len(eq_df):,} equity + {len(sme_df):,} SME)")
    return nse_lookup


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

class NSEMatcher:
    """Matches a company name against the NSE lookup with a 3-pass pipeline."""

    def __init__(self, nse_lookup: dict[str, dict], threshold: int = DEFAULT_THRESHOLD):
        self.lookup        = nse_lookup            # normalized → entry
        self.threshold     = threshold
        # Pre-build candidate list for rapidfuzz  (normalised names)
        self._candidates   = list(nse_lookup.keys())

    def match(self, crisil_name: str, mca_name: str) -> Optional[dict]:
        """
        Run the 4-pass pipeline and return the best match dict, or None.

        Return structure
        ----------------
        {
            "nseSymbol":          str,
            "nseMarket":          'EQUITY' | 'SME',
            "nseMatchType":       'exact' | 'exact_mca' | 'fuzzy' | 'fuzzy_mca',
            "nseMatchConfidence": int,
        }
        """
        # Pass 1 – exact on crisilName
        result = self._exact(crisil_name, match_type="exact")
        if result:
            return result

        # Pass 2 – exact on mcaName
        result = self._exact(mca_name, match_type="exact_mca")
        if result:
            return result

        # Pass 3 – fuzzy on crisilName
        result = self._fuzzy(crisil_name, match_type="fuzzy")
        if result:
            return result

        # Pass 4 – fuzzy on mcaName
        result = self._fuzzy(mca_name, match_type="fuzzy_mca")
        return result   # may be None

    # ------------------------------------------------------------------
    def _exact(self, name: str, match_type: str) -> Optional[dict]:
        norm = normalize(name)
        if not norm:
            return None
        entry = self.lookup.get(norm)
        if entry:
            return {
                "nseSymbol":          entry["symbol"],
                "nseMarket":          entry["market"],
                "nseMatchType":       match_type,
                "nseMatchConfidence": 100,
            }
        return None

    def _fuzzy(self, name: str, match_type: str) -> Optional[dict]:
        norm = normalize(name)
        if not norm or not self._candidates:
            return None
        best = process.extractOne(
            norm,
            self._candidates,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.threshold,
        )
        if best:
            matched_key, score, _ = best
            entry = self.lookup[matched_key]
            return {
                "nseSymbol":          entry["symbol"],
                "nseMarket":          entry["market"],
                "nseMatchType":       match_type,
                "nseMatchConfidence": int(score),
            }
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(threshold: int = DEFAULT_THRESHOLD, dry_run: bool = False) -> None:
    # Load NSE data
    nse_lookup = load_nse_data()
    matcher    = NSEMatcher(nse_lookup, threshold=threshold)

    # Connect to MongoDB
    client     = MongoClient(MONGO_URI, directConnection=True)
    client.admin.command("ping")
    log.info(f"Connected to MongoDB  ({MONGO_URI})")

    col = client[DB_NAME][COLLECTION_NAME]

    # Fetch only listed records
    cursor = col.find(
        {"listingStatus": "Listed"},
        {"_id": 1, "companyCode": 1, "crisilName": 1, "mcaName": 1},
    )
    records = list(cursor)
    log.info(f"Found {len(records):,} records with listingStatus='Listed'")

    # Match and build bulk update ops
    ops        = []
    matched    = 0
    unmatched  = 0

    for rec in records:
        crisil_name = rec.get("crisilName") or ""
        mca_name    = rec.get("mcaName")    or ""

        result = matcher.match(crisil_name, mca_name)

        if result:
            matched += 1
            update_doc = {"$set": result}
            log.debug(f"  ✓  {rec.get('companyCode')}  →  {result['nseSymbol']}  "
                      f"({result['nseMatchType']} @ {result['nseMatchConfidence']})")
        else:
            unmatched += 1
            # Explicitly mark as no NSE listing found so it's clear in the DB
            update_doc = {"$set": {"nseSymbol": None, "nseMatchType": "no_match",
                                   "nseMatchConfidence": 0, "nseMarket": None}}

        ops.append(UpdateOne({"_id": rec["_id"]}, update_doc))

    log.info(f"Matched: {matched:,}  |  Unmatched: {unmatched:,}  "
             f"|  Total listed: {len(records):,}")

    if dry_run:
        log.info("DRY-RUN mode – no writes performed.")
        client.close()
        return

    if ops:
        result_bulk = col.bulk_write(ops, ordered=False)
        log.info(f"Bulk write complete – modified: {result_bulk.modified_count:,}  "
                 f"matched: {result_bulk.matched_count:,}")
    else:
        log.info("No operations to write.")

    client.close()
    log.info("Done.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match listed CRISIL+MCA companies to NSE symbols.")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"Minimum fuzzy match confidence (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run matching without writing to MongoDB")
    args = parser.parse_args()

    run(threshold=args.threshold, dry_run=args.dry_run)
