"""
Main Data Consolidation Program
Orchestrates all data extraction tasks and consolidates into MongoDB
"""
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from pymongo import MongoClient
from datetime import datetime
import argparse

# Import all task modules
from config import MONGODB_URI, DB_NAME, COLLECTION_NAME, get_bank_config, get_all_bank_symbols
from task1_crisil_filter import extract_bank_loans
from task2_balance_sheet import extract_balance_sheet_data
from task3_ratios import extract_ratios_data
from task4_outstanding_advances import extract_outstanding_advances
from task5_shareholding_xbrl import extract_shareholding_pattern
from task6_sector_advances import extract_sector_wise_advances


def consolidate_bank_data(bank_symbol: str, push_to_db: bool = True) -> dict:
    """
    Consolidate all data for a single bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        push_to_db: Whether to push consolidated data to MongoDB
        
    Returns:
        Consolidated bank data dictionary
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    print(f"\n{'='*60}")
    print(f"Processing: {bank_config['fullName']} ({bank_symbol})")
    print(f"{'='*60}")
    
    # Initialize consolidated data structure
    consolidated_data = {
        "bankSymbol": bank_symbol,
        "bankName": bank_config["fullName"],
        "lastUpdated": datetime.utcnow().isoformat(),
        "dataYear": 2025
    }
    
    # Task 1: Extract CRISIL loan data
    print("\n[1/6] Extracting CRISIL loan data...")
    try:
        loans = extract_bank_loans(bank_symbol)
        consolidated_data["loans"] = {
            "totalCompanies": len(loans),
            "totalExposure": sum(c['totalExposure'] for c in loans if c['totalExposure']),
            "companies": loans
        }
        print(f"  ✓ Found {len(loans)} companies with loans")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["loans"] = {"error": str(e)}
    
    # Task 2: Extract Balance Sheet data
    print("\n[2/6] Extracting Balance Sheet data...")
    try:
        balance_sheet = extract_balance_sheet_data(bank_symbol)
        consolidated_data["balanceSheet"] = balance_sheet
        print(f"  ✓ Extracted assets and liabilities for {balance_sheet['year']}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["balanceSheet"] = {"error": str(e)}
    
    # Task 3: Extract Ratios data
    print("\n[3/6] Extracting Financial Ratios...")
    try:
        ratios = extract_ratios_data(bank_symbol)
        consolidated_data["financialRatios"] = ratios
        print(f"  ✓ Extracted {len([k for k in ratios.keys() if k not in ['year', 'unit']])} ratio categories")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["financialRatios"] = {"error": str(e)}
    
    # Task 4: Extract Outstanding Advances
    print("\n[4/6] Extracting Outstanding Advances...")
    try:
        outstanding_advances = extract_outstanding_advances(bank_symbol)
        consolidated_data["outstandingAdvances"] = outstanding_advances
        print(f"  ✓ Extracted outstanding advances data")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["outstandingAdvances"] = {"error": str(e)}
    
    # Task 5: Extract Shareholding Pattern
    print("\n[5/6] Extracting Shareholding Pattern...")
    try:
        shareholding = extract_shareholding_pattern(bank_symbol)
        consolidated_data["shareholdingPattern"] = shareholding
        print(f"  ✓ Extracted shareholding pattern with {len(shareholding.get('topShareholders', []))} top shareholders")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["shareholdingPattern"] = {"error": str(e)}
    
    # Task 6: Extract Sector-wise Advances
    print("\n[6/6] Extracting Sector-wise Advances...")
    try:
        sector_advances = extract_sector_wise_advances(bank_symbol)
        consolidated_data["sectorWiseAdvances"] = sector_advances
        print(f"  ✓ Extracted sector-wise advances")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["sectorWiseAdvances"] = {"error": str(e)}
    
    # Push to MongoDB if requested
    if push_to_db:
        print("\n[DB] Pushing consolidated data to MongoDB...")
        try:
            save_to_mongodb(consolidated_data)
            print(f"  ✓ Successfully saved to MongoDB")
        except Exception as e:
            print(f"  ✗ MongoDB Error: {e}")
    
    print(f"\n{'='*60}")
    print(f"Consolidation completed for {bank_config['fullName']}")
    print(f"{'='*60}\n")
    
    return consolidated_data


def save_to_mongodb(data: dict):
    """Save consolidated data to MongoDB"""
    if not MONGODB_URI:
        raise ValueError("MongoDB URI not found in environment variables")
    
    # Parse the URI and add TLS parameters if not present
    connection_uri = MONGODB_URI
    
    # Check if URI already has query parameters
    if '?' in connection_uri:
        # Add parameters to existing query string
        if 'tls=' not in connection_uri.lower() and 'ssl=' not in connection_uri.lower():
            connection_uri += '&tls=true'
        if 'tlsAllowInvalidCertificates=' not in connection_uri.lower():
            # For development: allow invalid certificates
            # Remove this in production and fix certificate issues properly
            connection_uri += '&tlsAllowInvalidCertificates=true'
        if 'retryWrites=' not in connection_uri.lower():
            connection_uri += '&retryWrites=true'
    else:
        # Add query parameters
        connection_uri += '?tls=true&tlsAllowInvalidCertificates=true&retryWrites=true'
    
    # Connect to MongoDB with additional options for SSL compatibility
    try:
        client = MongoClient(
            connection_uri,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            # Force TLS 1.2 or higher
            tls=True,
            tlsAllowInvalidCertificates=True  # Development only - remove for production
        )
        
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        # Use upsert to update if bank already exists
        collection.update_one(
            {"bankSymbol": data["bankSymbol"]},
            {"$set": data},
            upsert=True
        )
        
        client.close()
        
    except Exception as e:
        # More specific error handling
        error_msg = str(e)
        if 'SSL' in error_msg or 'TLS' in error_msg or 'handshake' in error_msg:
            raise ConnectionError(
                f"MongoDB SSL/TLS Connection Failed. This may be due to:\n"
                f"  1. Incompatible SSL/TLS version (requires TLS 1.2+)\n"
                f"  2. Certificate validation issues\n"
                f"  3. Network/firewall blocking MongoDB Atlas\n"
                f"  4. Python SSL library compatibility issues\n\n"
                f"Original error: {error_msg}\n\n"
                f"Try running: pip install --upgrade pymongo[srv] certifi"
            )
        else:
            raise


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Consolidate bank data from multiple sources')
    parser.add_argument('--banks', nargs='+', help='Bank symbols to process (e.g., SBIN HDFCBANK ICICIBANK)')
    parser.add_argument('--all', action='store_true', help='Process all configured banks')
    parser.add_argument('--no-db', action='store_true', help='Skip MongoDB upload')
    
    args = parser.parse_args()
    
    # Determine which banks to process
    if args.all:
        banks_to_process = get_all_bank_symbols()
    elif args.banks:
        banks_to_process = args.banks
    else:
        # Interactive mode
        print("Available banks:")
        all_banks = get_all_bank_symbols()
        for i, symbol in enumerate(all_banks, 1):
            config = get_bank_config(symbol)
            print(f"  {i}. {symbol} - {config['fullName']}")
        
        print("\nEnter bank symbols separated by spaces (or 'all' for all banks):")
        user_input = input("> ").strip()
        
        if user_input.lower() == 'all':
            banks_to_process = all_banks
        else:
            banks_to_process = user_input.split()
    
    # Process each bank
    push_to_db = not args.no_db
    results = {}
    
    print(f"\n{'#'*60}")
    print(f"# DATA CONSOLIDATION STARTED")
    print(f"# Banks to process: {', '.join(banks_to_process)}")
    print(f"# MongoDB upload: {'Enabled' if push_to_db else 'Disabled'}")
    print(f"{'#'*60}\n")
    
    for bank_symbol in banks_to_process:
        try:
            result = consolidate_bank_data(bank_symbol, push_to_db)
            results[bank_symbol] = {"status": "success", "data": result}
        except Exception as e:
            print(f"\n✗ Failed to process {bank_symbol}: {e}")
            results[bank_symbol] = {"status": "failed", "error": str(e)}
    
    # Print summary
    print(f"\n{'#'*60}")
    print(f"# CONSOLIDATION SUMMARY")
    print(f"{'#'*60}")
    success_count = sum(1 for r in results.values() if r["status"] == "success")
    failed_count = len(results) - success_count
    print(f"  Total banks processed: {len(results)}")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failed_count}")
    
    if failed_count > 0:
        print(f"\n  Failed banks:")
        for symbol, result in results.items():
            if result["status"] == "failed":
                print(f"    - {symbol}: {result['error']}")
    
    print(f"\n{'#'*60}\n")


if __name__ == "__main__":
    main()
