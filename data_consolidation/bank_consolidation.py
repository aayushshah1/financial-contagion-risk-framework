"""
Main Data Consolidation Program
Orchestrates all data extraction tasks and consolidates into MongoDB
"""
import sys
import os
import json

# Add bank scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts', 'bank'))

from pymongo import MongoClient
from datetime import datetime
import argparse
from typing import List, Dict

# Import all task modules
from config import MONGODB_URI, DB_NAME, COLLECTION_NAME, get_bank_config, get_all_bank_symbols, \
    SCB_NSE_TICKER_MAP, _normalize_bank_name
from task1_crisil_filter import extract_bank_loans
from task2_balance_sheet import extract_balance_sheet_data
from task3_ratios import extract_ratios_data
from task4_outstanding_advances import extract_outstanding_advances
from task5_shareholding_xbrl import extract_shareholding_pattern
# from task6_sector_advances import extract_sector_wise_advances  # SWA data no longer needed
from task7_related_party_transactions import extract_related_party_transactions
from task12_tier1_capital import extract_tier1_capital
from task10_merton_soft_labels import compute_merton_soft_labels
from task11_stress_score import run_stress_analysis
# from task9_basel import extract_basel_data  # Commented out temporarily


# Load bank facility mapping
FACILITY_MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'bankFacilityMapping.json')
with open(FACILITY_MAPPING_PATH, 'r', encoding='utf-8') as f:
    BANK_FACILITY_MAPPING = json.load(f)


def categorize_facility_type(facility_name: str) -> str:
    """
    Categorize a facility into one of the three main types based on mapping
    
    Args:
        facility_name: Name of the facility
        
    Returns:
        Category name or 'Uncategorized'
    """
    for category, facility_list in BANK_FACILITY_MAPPING.items():
        if facility_name in facility_list:
            return category
    return "Uncategorized"


def aggregate_by_industry(companies: List[Dict]) -> Dict:
    """
    Aggregate advances by company industrial classification
    
    Args:
        companies: List of company dictionaries with advances
        
    Returns:
        Dictionary with industry-wise aggregation (totals only, no individual companies)
    """
    industry_aggregation = {}
    
    for company in companies:
        # task1 returns 'industryName'; fall back gracefully
        industry = company.get('industryName') or company.get('companyIndustrialClassification') or 'Unknown'
        exposure = company.get('totalExposure', 0)
        
        if industry not in industry_aggregation:
            industry_aggregation[industry] = {
                "totalAdvances": 0,
                "numberOfCompanies": 0
            }
        
        industry_aggregation[industry]["totalAdvances"] += exposure
        industry_aggregation[industry]["numberOfCompanies"] += 1
    
    return industry_aggregation


def aggregate_by_facility_type(companies: List[Dict]) -> Dict:
    """
    Aggregate advances by facility type category
    
    Args:
        companies: List of company dictionaries with advances
        
    Returns:
        Dictionary with facility-type-wise aggregation
    """
    facility_aggregation = {}
    
    for company in companies:
        for facility in company.get('facilities', []):
            facility_name = facility.get('facilityType')
            category = categorize_facility_type(facility_name)
            amount = facility.get('amount', 0)
            
            if category not in facility_aggregation:
                facility_aggregation[category] = {
                    "totalAdvances": 0,
                    "numberOfFacilities": 0,
                    "facilityTypes": {}
                }
            
            facility_aggregation[category]["totalAdvances"] += amount
            facility_aggregation[category]["numberOfFacilities"] += 1
            
            # Track individual facility types within category
            if facility_name not in facility_aggregation[category]["facilityTypes"]:
                facility_aggregation[category]["facilityTypes"][facility_name] = {
                    "count": 0,
                    "totalAmount": 0
                }
            
            facility_aggregation[category]["facilityTypes"][facility_name]["count"] += 1
            facility_aggregation[category]["facilityTypes"][facility_name]["totalAmount"] += amount
    
    return facility_aggregation


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
    
    # Task 1: Extract CRISIL advances data
    print("\n[1/8] Extracting CRISIL advances data...")
    try:
        advances_companies = extract_bank_loans(bank_symbol)
        
        # Calculate aggregations
        industry_agg = aggregate_by_industry(advances_companies)
        facility_agg = aggregate_by_facility_type(advances_companies)
        
        consolidated_data["advances"] = {
            "totalCompanies": len(advances_companies),
            "totalExposure": sum(c['totalExposure'] for c in advances_companies if c['totalExposure']),
            "companies": advances_companies,
            "aggregationByIndustry": industry_agg,
            "aggregationByFacilityType": facility_agg
        }
        print(f"  ✓ Found {len(advances_companies)} companies with advances")
        print(f"  ✓ Aggregated by {len(industry_agg)} industry classifications")
        print(f"  ✓ Aggregated by {len(facility_agg)} facility type categories")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["advances"] = {"error": str(e)}
    
    # Task 2: Extract Balance Sheet data
    print("\n[2/8] Extracting Balance Sheet data...")
    try:
        balance_sheet = extract_balance_sheet_data(bank_symbol)
        consolidated_data["balanceSheet"] = balance_sheet
        print(f"  ✓ Extracted assets and liabilities for {balance_sheet['year']}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["balanceSheet"] = {"error": str(e)}
    
    # Task 3: Extract Ratios data
    print("\n[3/8] Extracting Financial Ratios...")
    try:
        ratios = extract_ratios_data(bank_symbol)
        consolidated_data["financialRatios"] = ratios
        print(f"  ✓ Extracted {len([k for k in ratios.keys() if k not in ['year', 'unit']])} ratio categories")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["financialRatios"] = {"error": str(e)}
    
    # Task 4: Extract Outstanding Advances
    print("\n[4/8] Extracting Outstanding Advances...")
    try:
        outstanding_advances = extract_outstanding_advances(bank_symbol)
        consolidated_data["outstandingAdvances"] = outstanding_advances
        print(f"  ✓ Extracted outstanding advances data")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["outstandingAdvances"] = {"error": str(e)}
    
    # Task 5: Extract Shareholding Pattern
    print("\n[5/8] Extracting Shareholding Pattern...")
    try:
        shareholding = extract_shareholding_pattern(bank_symbol)
        consolidated_data["shareholdingPattern"] = shareholding
        print(f"  ✓ Extracted shareholding pattern with {len(shareholding.get('topShareholders', []))} top shareholders")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["shareholdingPattern"] = {"error": str(e)}
    
    # Task 6: Sector-wise Advances (disabled — SWA data no longer needed)
    # print("\n[6/8] Extracting Sector-wise Advances...")
    # try:
    #     sector_advances = extract_sector_wise_advances(bank_symbol)
    #     consolidated_data["sectorWiseAdvances"] = sector_advances
    #     print(f"  \u2713 Extracted sector-wise advances")
    # except Exception as e:
    #     print(f"  \u2717 Error: {e}")
    #     consolidated_data["sectorWiseAdvances"] = {"error": str(e)}
    
    # Task 7: Extract Related Party Transactions
    print("\n[7/8] Extracting Related Party Transactions...")
    try:
        rpt_data = extract_related_party_transactions(bank_symbol)
        consolidated_data["relatedPartyTransactions"] = rpt_data
        print(f"  ✓ Extracted {rpt_data['transactionSummary']['totalTransactions']} transactions")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["relatedPartyTransactions"] = {"error": str(e)}

    # Task 12: Extract Tier 1 Capital
    print("\n[8/8] Extracting Tier 1 Capital...")
    try:
        tier1_data = extract_tier1_capital(bank_symbol)
        consolidated_data["tier1Capital"] = tier1_data
        print(f"  ✓ Tier 1 Capital: Rs {tier1_data['tier1CapitalCrores']:,.2f} Cr (as of {tier1_data['reportDate']})")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        consolidated_data["tier1Capital"] = {"error": str(e)}
    
    # # Task 8 (NIC sector mapping) removed — obsolete for now

    # # Task 9: Extract Basel III Data (Commented out temporarily)
    # print("\n[9/9] Extracting Basel III Data...")
    # try:
    #     basel_data = extract_basel_data(bank_symbol)
    #     consolidated_data["baselIII"] = basel_data
    #     print(f"  ✓ Extracted Basel III compliance data")
    # except FileNotFoundError as e:
    #     print(f"  ⚠ Basel data not available: {e}")
    #     consolidated_data["baselIII"] = {"error": "Data not available", "message": str(e)}
    # except Exception as e:
    #     print(f"  ✗ Error: {e}")
    #     consolidated_data["baselIII"] = {"error": str(e)}
    
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


def run_stress_pipeline(push_to_db: bool = True) -> dict:
    """
    Run the all-bank stress scoring pipeline (Tasks 10 → 11).

    This is a cross-sectional operation that requires the full 41-bank
    ratios dataset and cannot be run per-bank. It should be called once
    after all per-bank consolidations are complete.

    Steps:
      1. Task 10 — Merton Distance-to-Default (soft labels)
      2. Task 11 — RKMSS stress scores (KPCA + Merton orientation + CAMELS)
      3. Optional MongoDB push via task11's push_stress_scores_to_mongodb()

    Returns:
        results dict from run_stress_analysis()
    """
    print(f"\n{'#'*60}")
    print(f"# STRESS SCORING PIPELINE (Tasks 10 → 11)")
    print(f"{'#'*60}")

    # Task 10: Merton Distance-to-Default soft labels
    print("\n[Stress 1/2] Computing Merton Distance-to-Default...")
    try:
        merton_results = compute_merton_soft_labels(verbose=True)
        n_computed = merton_results.get("_meta", {}).get("computed", 0)
        print(f"  ✓ Merton DTD computed for {n_computed} banks")
    except Exception as e:
        print(f"  ✗ Merton computation failed: {e}")
        print("  ⚠ Stress analysis will fall back to PC1 orientation")

    # Task 11: RKMSS stress scores
    print("\n[Stress 2/2] Running RKMSS stress analysis...")
    try:
        stress_results = run_stress_analysis(year="2025", verbose=True)
        n_banks = stress_results.get("_meta", {}).get("nBanks", 0)
        print(f"  ✓ Stress scores computed for {n_banks} banks")
    except Exception as e:
        print(f"  ✗ Stress analysis failed: {e}")
        return {}

    # Merge stress scores directly into each bank's existing MongoDB document
    if push_to_db:
        print("\n[Stress DB] Merging stress scores into bank documents...")
        try:
            # SCB_NSE_TICKER_MAP: {csv_bank_name → nse_symbol}
            # task11 result keys are Excel bank names from ratios_all_banks.xlsx
            # Use _normalize_bank_name for case/suffix-agnostic matching
            name_to_symbol = {
                _normalize_bank_name(name): symbol
                for name, symbol in SCB_NSE_TICKER_MAP.items()
            }

            merged = 0
            for bank_excel_name, data in stress_results.items():
                if bank_excel_name == "_meta":
                    continue
                symbol = name_to_symbol.get(_normalize_bank_name(bank_excel_name))
                if not symbol:
                    continue
                # Merge only stress fields — save_to_mongodb uses $set so
                # existing fields (balanceSheet, advances, etc.) are untouched
                save_to_mongodb({
                    "bankSymbol":       symbol,
                    "stressScore":      data["stressScore"],
                    "stressRank":       data["stressRank"],
                    "stressComponents": data["stressComponents"],
                    "camelsDimensions": data["camelsDimensions"],
                    "stressUpdatedAt":  datetime.utcnow().isoformat(),
                })
                merged += 1

            print(f"  \u2713 Merged stress scores into {merged} bank documents")
        except Exception as e:
            print(f"  \u2717 Merge failed: {e}")

    print(f"\n{'#'*60}")
    print(f"# STRESS PIPELINE COMPLETE")
    print(f"{'#'*60}\n")
    return stress_results


def save_to_mongodb(data: dict):
    """Save consolidated data to MongoDB Cloud"""
    if not MONGODB_URI:
        raise ValueError("MongoDB URI not configured. Check .env file for db_cluster_link")
    
    # Connect to MongoDB Cloud
    try:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000
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
        raise ConnectionError(f"MongoDB Cloud Connection Failed: {str(e)}")


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

    # Run all-bank stress pipeline after individual consolidations
    run_stress_pipeline(push_to_db=push_to_db)


if __name__ == "__main__":
    main()
