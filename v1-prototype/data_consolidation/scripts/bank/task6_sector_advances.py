"""
Task 6: Extract Sector-wise Advances
Reads JSON files containing sector-wise advances data
"""
import json
import os
from typing import Dict
from config import DATA_PATHS, get_bank_config


def extract_sector_wise_advances(bank_symbol: str) -> Dict:
    """
    Extract sector-wise advances data for a specific bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with sector-wise advances data
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Construct JSON file path
    json_file = os.path.join(DATA_PATHS["swa_dir"], f"{bank_symbol}_SWA.json")
    
    if not os.path.exists(json_file):
        raise FileNotFoundError(f"Sector-wise advances file not found: {json_file}")
    
    # Load the JSON file
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            swa_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in sector-wise advances file: {e}")
    
    return swa_data


if __name__ == "__main__":
    # Test with all three banks
    for symbol in ['SBIN', 'HDFCBANK', 'ICICIBANK']:
        print(f"\nTesting Sector-wise Advances extraction for {symbol}...")
        try:
            data = extract_sector_wise_advances(symbol)
            print(f"✓ Successfully extracted sector-wise advances for {data.get('bankName', symbol)}")
            print(f"  Year Ended: {data.get('yearEnded', 'N/A')}")
            print(f"  Currency: {data.get('currency', 'N/A')}")
            
            # Print priority sector summary
            if 'sector' in data and 'prioritySector' in data['sector']:
                ps = data['sector']['prioritySector']
                print(f"  Priority Sector Categories: {len(ps)}")
                for category in list(ps.keys())[:3]:
                    cat_data = ps[category]
                    if isinstance(cat_data, dict) and 'grossAdvances' in cat_data:
                        print(f"    - {category}: {cat_data['grossAdvances']} Crore")
                        
        except Exception as e:
            print(f"✗ Error: {e}")
