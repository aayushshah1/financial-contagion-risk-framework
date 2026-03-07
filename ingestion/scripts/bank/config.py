"""
Configuration file for bank data consolidation
Contains bank mappings, MongoDB configuration, and constants
"""
import os
import re
from typing import Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env file in project root
# __file__ is scripts/bank/config.py → parents: bank → scripts → data_consolidation → Capstone
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path)

# Bank Mappings — All 41 NSE-listed Scheduled Commercial Banks
# excelName : exact string in RBI ratios_all_banks.xlsx / balance_sheet.xlsx
# crisilVariations : forms the bank name takes in CRISIL lender data
BANK_MAPPINGS = {
    # ── Public Sector Banks ───────────────────────────────────────────────────
    "BANKBARODA": {
        "symbol": "BANKBARODA",
        "fullName": "Bank of Baroda",
        "excelName": "BANK OF BARODA",
        "crisilVariations": ["Bank of Baroda", "BOB", "BANK OF BARODA"],
    },
    "BANKINDIA": {
        "symbol": "BANKINDIA",
        "fullName": "Bank of India",
        "excelName": "BANK OF INDIA",
        "crisilVariations": ["Bank of India", "BOI", "BANK OF INDIA"],
    },
    "MAHABANK": {
        "symbol": "MAHABANK",
        "fullName": "Bank of Maharashtra",
        "excelName": "BANK OF MAHARASHTRA",
        "crisilVariations": ["Bank of Maharashtra", "BANK OF MAHARASHTRA", "BOM"],
    },
    "CANBK": {
        "symbol": "CANBK",
        "fullName": "Canara Bank",
        "excelName": "CANARA BANK",
        "crisilVariations": ["Canara Bank", "CANARA BANK"],
    },
    "CENTRALBK": {
        "symbol": "CENTRALBK",
        "fullName": "Central Bank of India",
        "excelName": "CENTRAL BANK OF INDIA",
        "crisilVariations": ["Central Bank of India", "CENTRAL BANK OF INDIA", "Central Bank"],
    },
    "INDIANB": {
        "symbol": "INDIANB",
        "fullName": "Indian Bank",
        "excelName": "INDIAN BANK",
        "crisilVariations": ["Indian Bank", "INDIAN BANK"],
    },
    "IOB": {
        "symbol": "IOB",
        "fullName": "Indian Overseas Bank",
        "excelName": "INDIAN OVERSEAS BANK",
        "crisilVariations": ["Indian Overseas Bank", "IOB", "INDIAN OVERSEAS BANK"],
    },
    "PSB": {
        "symbol": "PSB",
        "fullName": "Punjab & Sind Bank",
        "excelName": "PUNJAB AND SIND BANK",
        "crisilVariations": ["Punjab and Sind Bank", "Punjab & Sind Bank", "PUNJAB AND SIND BANK"],
    },
    "PNB": {
        "symbol": "PNB",
        "fullName": "Punjab National Bank",
        "excelName": "PUNJAB NATIONAL BANK",
        "crisilVariations": ["Punjab National Bank", "PNB", "PUNJAB NATIONAL BANK"],
    },
    "SBIN": {
        "symbol": "SBIN",
        "fullName": "State Bank of India",
        "excelName": "STATE BANK OF INDIA",
        "crisilVariations": ["State Bank of India", "SBI", "STATE BANK OF INDIA"],
    },
    "UCOBANK": {
        "symbol": "UCOBANK",
        "fullName": "UCO Bank",
        "excelName": "UCO BANK",
        "crisilVariations": ["UCO Bank", "UCO BANK"],
    },
    "UNIONBANK": {
        "symbol": "UNIONBANK",
        "fullName": "Union Bank of India",
        "excelName": "UNION BANK OF INDIA",
        "crisilVariations": ["Union Bank of India", "Union Bank", "UNION BANK OF INDIA"],
    },
    # ── Private Sector Banks ──────────────────────────────────────────────────
    "AXISBANK": {
        "symbol": "AXISBANK",
        "fullName": "Axis Bank Limited",
        "excelName": "AXIS BANK LIMITED",
        "crisilVariations": ["Axis Bank Limited", "Axis Bank Ltd", "AXIS BANK LIMITED", "Axis Bank"],
    },
    "BANDHANBNK": {
        "symbol": "BANDHANBNK",
        "fullName": "Bandhan Bank Limited",
        "excelName": "BANDHAN BANK LIMITED",
        "crisilVariations": ["Bandhan Bank Limited", "Bandhan Bank", "BANDHAN BANK LIMITED"],
    },
    "CUB": {
        "symbol": "CUB",
        "fullName": "City Union Bank Limited",
        "excelName": "CITY UNION BANK LIMITED",
        "crisilVariations": ["City Union Bank Limited", "City Union Bank", "CITY UNION BANK LIMITED"],
    },
    "CSBBANK": {
        "symbol": "CSBBANK",
        "fullName": "CSB Bank Limited",
        "excelName": "CSB BANK LIMITED",
        "crisilVariations": ["CSB Bank Limited", "CSB Bank", "CSB BANK LIMITED",
                              "Catholic Syrian Bank"],
    },
    "DCBBANK": {
        "symbol": "DCBBANK",
        "fullName": "DCB Bank Limited",
        "excelName": "DCB BANK LIMITED",
        "crisilVariations": ["DCB Bank Limited", "DCB Bank", "DCB BANK LIMITED",
                              "Development Credit Bank"],
    },
    "DHANBANK": {
        "symbol": "DHANBANK",
        "fullName": "Dhanlaxmi Bank Limited",
        "excelName": "DHANLAXMI BANK LIMITED",
        "crisilVariations": ["Dhanlaxmi Bank Limited", "Dhanlaxmi Bank", "DHANLAXMI BANK LIMITED"],
    },
    "FEDERALBNK": {
        "symbol": "FEDERALBNK",
        "fullName": "Federal Bank Ltd",
        "excelName": "FEDERAL BANK LTD",
        "crisilVariations": ["Federal Bank Ltd", "Federal Bank", "FEDERAL BANK LTD",
                              "Federal Bank Limited"],
    },
    "HDFCBANK": {
        "symbol": "HDFCBANK",
        "fullName": "HDFC Bank Limited",
        "excelName": "HDFC BANK LTD.",
        "crisilVariations": ["HDFC Bank Limited", "HDFC Bank Ltd", "HDFC Bank Ltd.",
                              "HDFC BANK LIMITED"],
    },
    "ICICIBANK": {
        "symbol": "ICICIBANK",
        "fullName": "ICICI Bank Limited",
        "excelName": "ICICI BANK LIMITED",
        "crisilVariations": ["ICICI Bank Limited", "ICICI Bank Ltd", "ICICI Bank",
                              "ICICI BANK LIMITED"],
    },
    "IDBI": {
        "symbol": "IDBI",
        "fullName": "IDBI Bank Limited",
        "excelName": "IDBI BANK LIMITED",
        "crisilVariations": ["IDBI Bank Limited", "IDBI Bank", "IDBI BANK LIMITED",
                              "IDBI Bank Ltd"],
    },
    "IDFCFIRSTB": {
        "symbol": "IDFCFIRSTB",
        "fullName": "IDFC First Bank Limited",
        "excelName": "IDFC FIRST BANK LIMITED",
        "crisilVariations": ["IDFC First Bank Limited", "IDFC First Bank", "IDFC FIRST BANK LIMITED",
                              "IDFC Bank Limited"],
    },
    "INDUSINDBK": {
        "symbol": "INDUSINDBK",
        "fullName": "IndusInd Bank Ltd",
        "excelName": "INDUSIND BANK LTD",
        "crisilVariations": ["IndusInd Bank Ltd", "IndusInd Bank", "INDUSIND BANK LTD",
                              "IndusInd Bank Limited"],
    },
    "J&KBANK": {
        "symbol": "J&KBANK",
        "fullName": "Jammu & Kashmir Bank Ltd",
        "excelName": "JAMMU & KASHMIR BANK LTD",
        "crisilVariations": ["Jammu & Kashmir Bank Ltd", "J&K Bank", "JAMMU & KASHMIR BANK LTD",
                              "Jammu and Kashmir Bank"],
    },
    "KTKBANK": {
        "symbol": "KTKBANK",
        "fullName": "Karnataka Bank Ltd",
        "excelName": "KARNATAKA BANK LTD",
        "crisilVariations": ["Karnataka Bank Ltd", "Karnataka Bank", "KARNATAKA BANK LTD"],
    },
    "KARURVYSYA": {
        "symbol": "KARURVYSYA",
        "fullName": "Karur Vysya Bank Ltd",
        "excelName": "KARUR VYSYA BANK LTD",
        "crisilVariations": ["Karur Vysya Bank Ltd", "Karur Vysya Bank", "KARUR VYSYA BANK LTD",
                              "KVB"],
    },
    "KOTAKBANK": {
        "symbol": "KOTAKBANK",
        "fullName": "Kotak Mahindra Bank Ltd",
        "excelName": "KOTAK MAHINDRA BANK LTD.",
        "crisilVariations": ["Kotak Mahindra Bank Ltd", "Kotak Bank", "KOTAK MAHINDRA BANK LTD.",
                              "Kotak Mahindra Bank Limited"],
    },
    "RBLBANK": {
        "symbol": "RBLBANK",
        "fullName": "RBL Bank Ltd",
        "excelName": "RBL BANK LTD",
        "crisilVariations": ["RBL Bank Ltd", "RBL Bank", "RBL BANK LTD",
                              "Ratnakar Bank", "RBL Bank Limited"],
    },
    "SOUTHBANK": {
        "symbol": "SOUTHBANK",
        "fullName": "South Indian Bank Ltd",
        "excelName": "SOUTH INDIAN BANK LTD",
        "crisilVariations": ["South Indian Bank Ltd", "South Indian Bank", "SOUTH INDIAN BANK LTD"],
    },
    "TMB": {
        "symbol": "TMB",
        "fullName": "Tamilnad Mercantile Bank Ltd",
        "excelName": "TAMILNAD MERCANTILE BANK LTD",
        "crisilVariations": ["Tamilnad Mercantile Bank Ltd", "Tamilnad Mercantile Bank",
                              "TAMILNAD MERCANTILE BANK LTD", "TMB"],
    },
    "YESBANK": {
        "symbol": "YESBANK",
        "fullName": "Yes Bank Ltd",
        "excelName": "YES BANK LTD.",
        "crisilVariations": ["Yes Bank Ltd", "Yes Bank", "YES BANK LTD.", "Yes Bank Limited"],
    },
    # ── Small Finance Banks ───────────────────────────────────────────────────
    "AUBANK": {
        "symbol": "AUBANK",
        "fullName": "AU Small Finance Bank Limited",
        "excelName": "AU SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["AU Small Finance Bank Limited", "AU Small Finance Bank",
                              "AU SMALL FINANCE BANK LIMITED"],
    },
    "CAPITALSFB": {
        "symbol": "CAPITALSFB",
        "fullName": "Capital Small Finance Bank Limited",
        "excelName": "CAPITAL SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Capital Small Finance Bank Limited", "Capital Small Finance Bank",
                              "CAPITAL SMALL FINANCE BANK LIMITED"],
    },
    "EQUITASBNK": {
        "symbol": "EQUITASBNK",
        "fullName": "Equitas Small Finance Bank Limited",
        "excelName": "EQUITAS SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Equitas Small Finance Bank Limited", "Equitas Small Finance Bank",
                              "EQUITAS SMALL FINANCE BANK LIMITED"],
    },
    "ESAFSFB": {
        "symbol": "ESAFSFB",
        "fullName": "ESAF Small Finance Bank Limited",
        "excelName": "ESAF SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["ESAF Small Finance Bank Limited", "ESAF Small Finance Bank",
                              "ESAF SMALL FINANCE BANK LIMITED"],
    },
    "JSFB": {
        "symbol": "JFSB",
        "fullName": "Jana Small Finance Bank Limited",
        "excelName": "JANA SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Jana Small Finance Bank Limited", "Jana Small Finance Bank",
                              "JANA SMALL FINANCE BANK LIMITED"],
    },
    "SURYODAY": {
        "symbol": "SURYODAY",
        "fullName": "Suryoday Small Finance Bank Limited",
        "excelName": "SURYODAY SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Suryoday Small Finance Bank Limited", "Suryoday Small Finance Bank",
                              "SURYODAY SMALL FINANCE BANK LIMITED"],
    },
    "UJJIVANSFB": {
        "symbol": "UJJIVANSFB",
        "fullName": "Ujjivan Small Finance Bank Limited",
        "excelName": "UJJIVAN SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Ujjivan Small Finance Bank Limited", "Ujjivan Small Finance Bank",
                              "UJJIVAN SMALL FINANCE BANK LIMITED"],
    },
    "UTKARSHBNK": {
        "symbol": "UTKARSHBNK",
        "fullName": "Utkarsh Small Finance Bank Limited",
        "excelName": "UTKARSH SMALL FINANCE BANK LIMITED",
        "crisilVariations": ["Utkarsh Small Finance Bank Limited", "Utkarsh Small Finance Bank",
                              "UTKARSH SMALL FINANCE BANK LIMITED"],
    },
    # ── Payments Bank ─────────────────────────────────────────────────────────
    "FINOPB": {
        "symbol": "FINOPB",
        "fullName": "Fino Payments Bank Limited",
        "excelName": "FINO PAYMENTS BANK LIMITED",
        "crisilVariations": ["Fino Payments Bank Limited", "Fino Payments Bank",
                              "FINO PAYMENTS BANK LIMITED"],
    },
}

# ── NSE-Listed Scheduled Commercial Banks — Canonical Ticker Map ────────────
# Source: tier1_cap.csv  (copied verbatim — bank name : NSE symbol)
# All 41 NSE-listed Indian SCBs (Public Sector, Private, Small Finance, Payments).
# Used by task10 (Merton DTD), task11 (RKMSS), and the KG pipeline as the
# authoritative allowlist.  Replaces per-task NSE_TICKER_MAP / EXCLUDE lists.
SCB_NSE_TICKER_MAP: Dict[str, str] = {
    # ── Public Sector Banks (PSB) ─────────────────────────────────────────
    "Bank of Baroda":                     "BANKBARODA",
    "Bank of India":                      "BANKINDIA",
    "Bank of Maharashtra":                "MAHABANK",
    "Canara Bank":                        "CANBK",
    "Central Bank of India":              "CENTRALBK",
    "Indian Bank":                        "INDIANB",
    "Indian Overseas Bank":               "IOB",
    "Punjab & Sind Bank":                 "PSB",
    "Punjab National Bank":               "PNB",
    "State Bank of India":                "SBIN",
    "UCO Bank":                           "UCOBANK",
    "Union Bank of India":                "UNIONBANK",
    # ── Private Sector Banks ──────────────────────────────────────────────
    "Axis Bank":                          "AXISBANK",
    "Bandhan Bank":                       "BANDHANBNK",
    "City Union Bank":                    "CUB",
    "CSB Bank":                           "CSBBANK",
    "DCB Bank":                           "DCBBANK",
    "Dhanlaxmi Bank":                     "DHANBANK",
    "Federal Bank":                       "FEDERALBNK",
    "HDFC Bank":                          "HDFCBANK",
    "ICICI Bank":                         "ICICIBANK",
    "IDBI Bank":                          "IDBI",
    "IDFC First Bank":                    "IDFCFIRSTB",
    "IndusInd Bank":                      "INDUSINDBK",
    "Jammu & Kashmir Bank":               "J&KBANK",
    "Karnataka Bank":                     "KTKBANK",
    "Karur Vysya Bank":                   "KARURVYSYA",
    "Kotak Mahindra Bank":                "KOTAKBANK",
    "RBL Bank":                           "RBLBANK",
    "South Indian Bank":                  "SOUTHBANK",
    "Tamilnad Mercantile Bank":           "TMB",
    "Yes Bank":                           "YESBANK",
    # ── Small Finance Banks (SFB) ─────────────────────────────────────────
    "AU Small Finance Bank":              "AUBANK",
    "Capital Small Finance Bank":         "CAPITALSFB",
    "Equitas Small Finance Bank":         "EQUITASBNK",
    "ESAF Small Finance Bank":            "ESAFSFB",
    "Jana Small Finance Bank":            "JSFB",
    "Suryoday Small Finance Bank":        "SURYODAY",
    "Ujjivan Small Finance Bank":         "UJJIVANSFB",
    "Utkarsh Small Finance Bank":         "UTKARSHBNK",
    # ── Payments Bank ─────────────────────────────────────────────────────
    "Fino Payments Bank":                 "FINOPB",
}


def _normalize_bank_name(name: str) -> str:
    """
    Normalise a bank name for fuzzy matching across data sources.
    Steps: uppercase → replace ' & ' with ' AND ' →
           strip trailing LIMITED / LTD. / LTD.
    Shared by task10, task11, and any future task that maps Excel ↔ CSV names.
    """
    n = name.upper().strip()
    n = n.replace(" & ", " AND ")
    n = re.sub(r"\s+(LIMITED|LTD\.?)\s*$", "", n).strip()
    return n


def is_scb_bank(excel_name: str) -> bool:
    """
    Return True if *excel_name* (from ratios_all_banks.xlsx or similar) matches
    any bank in SCB_NSE_TICKER_MAP.  Matching is case-insensitive and ignores
    common suffixes (LIMITED, LTD, LTD.).
    """
    norm = _normalize_bank_name(excel_name)
    for csv_name in SCB_NSE_TICKER_MAP:
        if _normalize_bank_name(csv_name) == norm:
            return True
    return False


def get_nse_ticker_for_excel_name(excel_name: str) -> Optional[str]:
    """
    Map an Excel-format bank name to its NSE ticker symbol.
    Uses _normalize_bank_name for case-insensitive, suffix-agnostic matching.
    Returns the NSE symbol string, or None if no match is found.
    """
    norm = _normalize_bank_name(excel_name)
    for csv_name, ticker in SCB_NSE_TICKER_MAP.items():
        if _normalize_bank_name(csv_name) == norm:
            return ticker
    return None


# MongoDB Configuration - Cloud Only
MONGODB_CLOUD_URI = os.getenv('db_cluster_link')

# Use cloud URI as primary connection
MONGODB_URI = MONGODB_CLOUD_URI

# Database and Collection Names
DB_NAME = "financial_kg"
COLLECTION_NAME = "banks"

# CRISIL / Company Data Configuration (financial_kg.companies)
CRISIL_DB_NAME = "financial_kg"
CRISIL_COLLECTION_NAME = "companies"

# Data Paths (relative to repo root)
# go up: bank → scripts → ingestion → repo root
BASE_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data")

DATA_PATHS = {
    "crisil": os.path.join(BASE_DATA_PATH, "company", "crisil_reports", "crisil_ratings.rating_reports.json"),
    "balance_sheet": os.path.join(BASE_DATA_PATH, "bank", "balance_sheet", "balance_sheet.xlsx"),
    "ratios": os.path.join(BASE_DATA_PATH, "bank", "ratios", "ratios_all_banks.xlsx"),
    "outstanding_advances": os.path.join(BASE_DATA_PATH, "bank", "outstanding_advances", "outstanding_advances.xlsx"),
    "shp_dir": os.path.join(BASE_DATA_PATH, "bank", "shp"),
    "swa_dir": os.path.join(BASE_DATA_PATH, "bank", "swa"),
    "integrated_xbrl_dir": os.path.join(BASE_DATA_PATH, "bank", "integrated_xbrl"),
    "basel_dir": os.path.join(BASE_DATA_PATH, "basel"),
    "tier1_cap": os.path.join(BASE_DATA_PATH, "bank", "tier1_cap", "tier1_cap.csv")
}

# Financial Year Configuration
TARGET_YEAR = 2025  # FY25 ending March 31, 2025
YEAR_LABEL = "2025"

# XBRL Taxonomy Paths
TAXONOMY_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "taxonomies")
SHP_TAXONOMY = os.path.join(TAXONOMY_BASE, "shareholding_pattern", "SHP Taxonomy_2025-10-31")
INTEGRATED_BANK_TAXONOMY = os.path.join(TAXONOMY_BASE, "integrated_bank_filing")

def get_bank_config(symbol):
    """Get bank configuration by symbol"""
    return BANK_MAPPINGS.get(symbol)

def get_all_bank_symbols():
    """Get list of all bank symbols"""
    return list(BANK_MAPPINGS.keys())

def match_bank_from_crisil_name(lender_name):
    """
    Match a bank from CRISIL lender name.
    Multi-stage matching:
      Stage 1 — Exact match on fullName (case-insensitive equality)
      Stage 2 — Exact match on any crisilVariation (case-insensitive equality)
      Stage 3 — Longest-substring match: catches embedded/prefixed forms and
                 ensures a more specific variation (e.g. "State Bank of India")
                 always beats a shorter substring inside it ("Bank of India").
    Returns bank symbol if matched, None otherwise.
    """
    if not lender_name or lender_name.lower() in ['not applicable', 'na', 'null']:
        return None

    ln_lower = lender_name.strip().lower()

    # Stage 1: exact match on fullName
    for symbol, config in BANK_MAPPINGS.items():
        if ln_lower == config["fullName"].lower():
            return symbol

    # Stage 2: exact match on any crisilVariation
    for symbol, config in BANK_MAPPINGS.items():
        for variation in config["crisilVariations"]:
            if ln_lower == variation.lower():
                return symbol

    # Stage 3: longest-substring match
    best_symbol = None
    best_len = 0

    for symbol, config in BANK_MAPPINGS.items():
        for variation in config["crisilVariations"]:
            var_lower = variation.lower()
            if var_lower in ln_lower and len(var_lower) > best_len:
                # Additional check for HDFC to avoid matching HDFC AMC, HDFC Life, etc.
                if symbol == "HDFCBANK" and "bank" not in ln_lower:
                    continue
                best_symbol = symbol
                best_len = len(var_lower)

    return best_symbol


def get_mongodb_cloud_uri():
    """
    Get MongoDB Cloud URI from environment variables
    
    Returns:
        MongoDB Cloud connection URI
    """
    return MONGODB_CLOUD_URI


def get_crisil_db_config():
    """
    Get company/CRISIL database configuration.
    Source: financial_kg.companies (MongoDB cloud)

    Returns:
        Tuple of (database_name, collection_name)
    """
    return CRISIL_DB_NAME, CRISIL_COLLECTION_NAME
