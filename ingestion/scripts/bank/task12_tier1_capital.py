"""
Task 12: Extract Tier 1 Capital Data
Reads tier1_cap.csv and returns the Tier 1 Capital figure for the specified bank
"""
import argparse
import pandas as pd
from typing import Dict
from pymongo import MongoClient
from config import DATA_PATHS, get_bank_config, get_all_bank_symbols, MONGODB_URI, DB_NAME, COLLECTION_NAME


def extract_tier1_capital(bank_symbol: str) -> Dict:
    """
    Extract Tier 1 Capital for a specific bank from the CSV.

    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')

    Returns:
        Dictionary with tier1 capital details:
            {
                "tier1CapitalCrores": float,
                "reportDate": str
            }
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")

    csv_path = DATA_PATHS["tier1_cap"]

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        raise FileNotFoundError(f"Tier 1 Capital CSV not found at {csv_path}")
    except Exception as e:
        raise ValueError(f"Error reading Tier 1 Capital CSV: {e}")

    # Match row by NSE Symbol
    row = df[df["NSE Symbol"].str.strip() == bank_symbol]

    if row.empty:
        raise ValueError(
            f"Bank symbol '{bank_symbol}' not found in Tier 1 Capital CSV. "
            f"Available symbols: {df['NSE Symbol'].tolist()}"
        )

    record = row.iloc[0]

    return {
        "tier1CapitalCrores": float(record["Tier 1 Capital (Rs in Crores)"]),
        "reportDate": str(record["Latest Basel III Report Date"]).strip(),
    }


def run_tier1_capital_runner(bank_symbol: str = None, dry_run: bool = False) -> None:
    """
    Update only tier1Capital.tier1CapitalCrores in MongoDB.

    Args:
        bank_symbol: Optional single bank symbol. If None, runs for all known bank symbols.
        dry_run: If True, print intended updates without writing to MongoDB.
    """
    symbols = [bank_symbol.upper()] if bank_symbol else get_all_bank_symbols()

    if not dry_run and not MONGODB_URI:
        raise ValueError("MongoDB URI not configured. Check .env file for db_cluster_link")

    client = None
    collection = None
    if not dry_run:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        collection = client[DB_NAME][COLLECTION_NAME]

    try:
        processed = 0
        matched = 0
        modified = 0
        skipped = 0

        for symbol in symbols:
            try:
                tier1 = extract_tier1_capital(symbol)["tier1CapitalCrores"]
            except Exception as e:
                print(f"SKIP {symbol}: {e}")
                skipped += 1
                continue

            processed += 1

            if dry_run:
                print(f"DRY RUN {symbol}: tier1Capital.tier1CapitalCrores -> {tier1}")
                continue

            result = collection.update_one(
                {"bankSymbol": symbol},
                {"$set": {"tier1Capital.tier1CapitalCrores": tier1}}
            )

            if result.matched_count > 0:
                matched += 1
            if result.modified_count > 0:
                modified += 1

            print(
                f"UPDATE {symbol}: matched={result.matched_count}, "
                f"modified={result.modified_count}, value={tier1}"
            )

        print("\nSummary")
        print(f"Processed: {processed}")
        print(f"Matched:   {matched}")
        print(f"Modified:  {modified}")
        print(f"Skipped:   {skipped}")
        if dry_run:
            print("Mode:      DRY RUN")
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update only tier1Capital.tier1CapitalCrores in financial_kg.banks"
    )
    parser.add_argument("--bank", help="Optional bank symbol (e.g., SBIN)")
    parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing")
    args = parser.parse_args()

    run_tier1_capital_runner(bank_symbol=args.bank, dry_run=args.dry_run)
