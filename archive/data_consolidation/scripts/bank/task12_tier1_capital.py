"""
Task 12: Extract Tier 1 Capital Data
Reads tier1_cap.csv and returns the Tier 1 Capital figure for the specified bank
"""
import pandas as pd
from typing import Dict
from config import DATA_PATHS, get_bank_config


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
