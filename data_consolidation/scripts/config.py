"""
Configuration file for bank data consolidation
Contains bank mappings, MongoDB configuration, and constants
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bank Mappings - Symbol to Full Official Name
BANK_MAPPINGS = {
    "SBIN": {
        "symbol": "SBIN",
        "fullName": "State Bank of India",
        "excelName": "STATE BANK OF INDIA",  # Name as it appears in Excel files
        "crisilVariations": ["State Bank of India", "SBI", "STATE BANK OF INDIA"]
    },
    "HDFCBANK": {
        "symbol": "HDFCBANK",
        "fullName": "HDFC Bank Limited",
        "excelName": "HDFC BANK LTD.",  # Name as it appears in Excel files
        "crisilVariations": ["HDFC Bank Limited", "HDFC Bank Ltd", "HDFC Bank Ltd.", "HDFC BANK LIMITED"]
    },
    "ICICIBANK": {
        "symbol": "ICICIBANK",
        "fullName": "ICICI Bank Limited",
        "excelName": "ICICI BANK LIMITED",
        "crisilVariations": ["ICICI Bank Limited", "ICICI Bank Ltd", "ICICI Bank Ltd.", "ICICI BANK LIMITED"]
    }
}

# MongoDB Configuration
MONGODB_URI = os.getenv("db_cluster_link")
DB_NAME = "financial_knowledge_graph"
COLLECTION_NAME = "banks"

# Data Paths (relative to data_consolidation directory)
BASE_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

DATA_PATHS = {
    "crisil": os.path.join(BASE_DATA_PATH, "company", "crisil_reports", "crisil_ratings.rating_reports.json"),
    "balance_sheet": os.path.join(BASE_DATA_PATH, "bank", "balance_sheet", "balance_sheet.xlsx"),
    "ratios": os.path.join(BASE_DATA_PATH, "bank", "ratios", "ratios_all_banks.xlsx"),
    "outstanding_advances": os.path.join(BASE_DATA_PATH, "bank", "outstanding_advances", "outstanding_advances.xlsx"),
    "shp_dir": os.path.join(BASE_DATA_PATH, "bank", "shp"),
    "swa_dir": os.path.join(BASE_DATA_PATH, "bank", "swa")
}

# Financial Year Configuration
TARGET_YEAR = 2025  # FY25 ending March 31, 2025
YEAR_LABEL = "2025"

# XBRL Taxonomy Paths
TAXONOMY_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "taxonomies")
SHP_TAXONOMY = os.path.join(TAXONOMY_BASE, "shareholding_pattern", "SHP Taxonomy_2025-10-31")

def get_bank_config(symbol):
    """Get bank configuration by symbol"""
    return BANK_MAPPINGS.get(symbol)

def get_all_bank_symbols():
    """Get list of all bank symbols"""
    return list(BANK_MAPPINGS.keys())

def match_bank_from_crisil_name(lender_name):
    """
    Match a bank from CRISIL lender name
    Returns bank symbol if matched, None otherwise
    """
    if not lender_name or lender_name.lower() in ['not applicable', 'na', 'null']:
        return None
    
    # Check each bank's variations
    for symbol, config in BANK_MAPPINGS.items():
        for variation in config["crisilVariations"]:
            if variation.lower() in lender_name.lower():
                # Additional check for HDFC to avoid matching HDFC AMC, HDFC Life, etc.
                if symbol == "HDFCBANK":
                    if "bank" in lender_name.lower():
                        return symbol
                else:
                    return symbol
    
    return None
