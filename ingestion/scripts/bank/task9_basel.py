"""
Task 9: Basel III Data Extraction
Extracts Basel III compliance data from JSON files
"""
import os
import json
from typing import Dict
from config import DATA_PATHS, get_bank_config


def extract_basel_data(bank_symbol: str) -> Dict:
    """
    Extract Basel III data for a specific bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary containing Basel III data
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Construct path to Basel data file
    basel_dir = DATA_PATHS.get("basel_dir")
    if not basel_dir:
        raise ValueError("Basel data directory not configured in DATA_PATHS")
    
    # Try different possible file naming conventions
    possible_filenames = [
        f"basel_{bank_symbol}.json",
        f"basel_{bank_symbol.lower()}.json",
        f"{bank_symbol}_basel.json",
        f"{bank_symbol.lower()}_basel.json"
    ]
    
    basel_file = None
    for filename in possible_filenames:
        filepath = os.path.join(basel_dir, filename)
        if os.path.exists(filepath):
            basel_file = filepath
            break
    
    if not basel_file:
        # Check if there's a combined file for all banks
        combined_file = os.path.join(basel_dir, "basel_all_banks.json")
        if os.path.exists(combined_file):
            return extract_from_combined_file(combined_file, bank_symbol, bank_config)
        else:
            raise FileNotFoundError(
                f"Basel III data file not found for {bank_symbol}. "
                f"Looked in: {basel_dir}"
            )
    
    # Load the Basel data
    try:
        with open(basel_file, 'r', encoding='utf-8') as f:
            basel_data = json.load(f)
        
        # Structure and validate the data
        return process_basel_data(basel_data, bank_symbol)
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in Basel data file: {e}")
    except Exception as e:
        raise RuntimeError(f"Error reading Basel data: {e}")


def extract_from_combined_file(filepath: str, bank_symbol: str, bank_config: Dict) -> Dict:
    """
    Extract Basel data from a combined file containing all banks
    
    Args:
        filepath: Path to combined Basel data file
        bank_symbol: Bank symbol to extract
        bank_config: Bank configuration
        
    Returns:
        Extracted Basel data for the specific bank
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        
        # Try different keys to find this bank's data
        possible_keys = [
            bank_symbol,
            bank_symbol.lower(),
            bank_config["fullName"],
            bank_config["excelName"]
        ]
        
        for key in possible_keys:
            if key in all_data:
                return process_basel_data(all_data[key], bank_symbol)
        
        raise ValueError(f"Bank {bank_symbol} not found in combined Basel file")
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in combined Basel data file: {e}")


def process_basel_data(data: Dict, bank_symbol: str) -> Dict:
    """
    Process and structure Basel III data
    
    Args:
        data: Raw Basel data
        bank_symbol: Bank symbol
        
    Returns:
        Processed Basel data with consistent structure
    """
    # If data is already properly structured, return it
    if isinstance(data, dict):
        # Add bank symbol if not present
        if "bankSymbol" not in data:
            data["bankSymbol"] = bank_symbol
        
        return data
    
    # If it's some other format, try to structure it
    return {
        "bankSymbol": bank_symbol,
        "rawData": data
    }


def get_basel_summary(bank_symbol: str) -> Dict:
    """
    Get a summary of Basel III compliance metrics
    
    Args:
        bank_symbol: Bank symbol
        
    Returns:
        Summary of key Basel III metrics
    """
    basel_data = extract_basel_data(bank_symbol)
    
    # Extract key metrics if available
    summary = {
        "bankSymbol": bank_symbol,
        "dataAvailable": True
    }
    
    # Common Basel III metrics to look for
    key_metrics = [
        "cet1_ratio",
        "tier1_ratio",
        "total_capital_ratio",
        "leverage_ratio",
        "liquidity_coverage_ratio",
        "net_stable_funding_ratio"
    ]
    
    for metric in key_metrics:
        # Try different case variations
        for key in [metric, metric.upper(), metric.replace('_', ' ').title()]:
            if key in basel_data:
                summary[metric] = basel_data[key]
                break
    
    return summary


if __name__ == "__main__":
    # Test the function
    import sys
    if len(sys.argv) > 1:
        bank = sys.argv[1]
        try:
            result = extract_basel_data(bank)
            print(f"\nBasel III Data for {bank}:")
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python task9_basel.py <BANK_SYMBOL>")
