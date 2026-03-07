"""
prototype_kg/config.py
Central configuration: Neo4j AuraDB connection, MongoDB connection,
bank registry, known subsidiaries, and RBI-to-NIC crosswalk.
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pymongo import MongoClient

load_dotenv()

# ---------------------------------------------------------------------------
# Neo4j AuraDB
# ---------------------------------------------------------------------------

NEO4J_URI      = os.getenv("NEO4J_URI")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def get_driver():
    """Return a Neo4j driver instance. Caller is responsible for closing."""
    if not NEO4J_URI or not NEO4J_PASSWORD:
        raise EnvironmentError(
            "NEO4J_URI and NEO4J_PASSWORD must be set in the environment / .env file."
        )
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ---------------------------------------------------------------------------
# MongoDB  (source of consolidated bank documents)
# ---------------------------------------------------------------------------

MONGO_URI         = os.getenv("db_cluster_link")
MONGO_DB          = "financial_kg"
MONGO_COLLECTION  = "banks"          # financial_kg/banks
COMPANY_COLLECTION = "companies"      # financial_kg/companies

CRISIL_DB         = "crisil_reports"
CRISIL_COLLECTION = "crisil_reports_nic_ice_creams"


def get_mongo_client():
    """Return a MongoClient. Caller is responsible for closing."""
    if not MONGO_URI:
        raise EnvironmentError(
            "db_cluster_link must be set in the environment / .env file."
        )
    return MongoClient(MONGO_URI)


def get_bank_docs(client: MongoClient) -> list[dict]:
    """Return all 41 consolidated bank documents from MongoDB (financial_kg/banks)."""
    return list(
        client[MONGO_DB][MONGO_COLLECTION].find(
            {"bankSymbol": {"$in": TARGET_BANK_SYMBOLS}}
        )
    )


def get_company_docs(client: MongoClient) -> list[dict]:
    """
    Return all company documents from financial_kg/company that:
      - have at least one bankFacility from a target bank, OR
      - have a companyCode referenced in any bank's advances list.
    In practice we load all documents (the collection is already pre-filtered).
    """
    return list(client[MONGO_DB][COMPANY_COLLECTION].find({}))


# ---------------------------------------------------------------------------
# Target banks  (all 41 scheduled commercial banks)
# ---------------------------------------------------------------------------

TARGET_BANK_SYMBOLS = [
    "AUBANK", "AXISBANK", "BANDHANBNK", "BANKBARODA", "BANKINDIA",
    "CANBK", "CAPITALSFB", "CENTRALBK", "CSBBANK", "CUB",
    "DCBBANK", "DHANBANK", "EQUITASBNK", "ESAFSFB", "FEDERALBNK",
    "FINOPB", "HDFCBANK", "ICICIBANK", "IDBI", "IDFCFIRSTB",
    "INDIANB", "INDUSINDBK", "IOB", "J&KBANK", "JSFB",
    "KARURVYSYA", "KOTAKBANK", "KTKBANK", "MAHABANK", "PNB",
    "PSB", "RBLBANK", "SBIN", "SOUTHBANK", "SURYODAY",
    "TMB", "UCOBANK", "UJJIVANSFB", "UNIONBANK", "UTKARSHBNK",
    "YESBANK",
]

BANK_REGISTRY = {
    "AUBANK": {
        "bankSymbol": "AUBANK",
        "bankName": "AU Small Finance Bank Limited",
        "nameVariants": [
            "au small finance bank limited",
            "au small finance bank ltd",
            "au small finance bank",
            "au bank",
        ],
    },
    "AXISBANK": {
        "bankSymbol": "AXISBANK",
        "bankName": "Axis Bank Limited",
        "nameVariants": [
            "axis bank limited",
            "axis bank ltd",
            "axis bank ltd.",
            "axis bank",
            "axisbank",
            "axis bank limited ibu gift city branch",
        ],
    },
    "BANDHANBNK": {
        "bankSymbol": "BANDHANBNK",
        "bankName": "Bandhan Bank Limited",
        "nameVariants": [
            "bandhan bank limited",
            "bandhan bank ltd",
            "bandhan bank",
        ],
    },
    "BANKBARODA": {
        "bankSymbol": "BANKBARODA",
        "bankName": "Bank of Baroda",
        "nameVariants": [
            "bank of baroda",
            "bob",
            "bank of baroda - ifsc banking unit gift city",
        ],
    },
    "BANKINDIA": {
        "bankSymbol": "BANKINDIA",
        "bankName": "Bank of India",
        "nameVariants": [
            "bank of india",
            "bank of india limited",
            "bank of india ltd",
            "boi",
            "bank of india - singapore branch",
        ],
    },
    "CANBK": {
        "bankSymbol": "CANBK",
        "bankName": "Canara Bank",
        "nameVariants": [
            "canara bank",
            "canara bank limited",
        ],
    },
    "CAPITALSFB": {
        "bankSymbol": "CAPITALSFB",
        "bankName": "Capital Small Finance Bank Limited",
        "nameVariants": [
            "capital small finance bank limited",
            "capital small finance bank ltd",
            "capital small finance bank",
        ],
    },
    "CENTRALBK": {
        "bankSymbol": "CENTRALBK",
        "bankName": "Central Bank of India",
        "nameVariants": [
            "central bank of india",
            "central bank of india limited",
            "central bank",
        ],
    },
    "CSBBANK": {
        "bankSymbol": "CSBBANK",
        "bankName": "CSB Bank Limited",
        "nameVariants": [
            "csb bank limited",
            "csb bank ltd",
            "csb bank",
            "catholic syrian bank",
        ],
    },
    "CUB": {
        "bankSymbol": "CUB",
        "bankName": "City Union Bank Limited",
        "nameVariants": [
            "city union bank limited",
            "city union bank ltd",
            "city union bank",
        ],
    },
    "DCBBANK": {
        "bankSymbol": "DCBBANK",
        "bankName": "DCB Bank Limited",
        "nameVariants": [
            "dcb bank limited",
            "dcb bank ltd",
            "dcb bank",
            "development credit bank",
        ],
    },
    "DHANBANK": {
        "bankSymbol": "DHANBANK",
        "bankName": "Dhanlaxmi Bank Limited",
        "nameVariants": [
            "dhanlaxmi bank limited",
            "dhanlaxmi bank ltd",
            "dhanlaxmi bank",
        ],
    },
    "EQUITASBNK": {
        "bankSymbol": "EQUITASBNK",
        "bankName": "Equitas Small Finance Bank Limited",
        "nameVariants": [
            "equitas small finance bank limited",
            "equitas small finance bank ltd",
            "equitas small finance bank",
        ],
    },
    "ESAFSFB": {
        "bankSymbol": "ESAFSFB",
        "bankName": "ESAF Small Finance Bank Limited",
        "nameVariants": [
            "esaf small finance bank limited",
            "esaf small finance bank ltd",
            "esaf small finance bank",
        ],
    },
    "FEDERALBNK": {
        "bankSymbol": "FEDERALBNK",
        "bankName": "Federal Bank Ltd",
        "nameVariants": [
            "federal bank limited",
            "federal bank ltd",
            "federal bank ltd.",
            "federal bank",
            "the federal bank limited",
            "the federal bank ltd",
        ],
    },
    "FINOPB": {
        "bankSymbol": "FINOPB",
        "bankName": "Fino Payments Bank Limited",
        "nameVariants": [
            "fino payments bank limited",
            "fino payments bank ltd",
            "fino payments bank",
            "fino bank",
        ],
    },
    "HDFCBANK": {
        "bankSymbol": "HDFCBANK",
        "bankName": "HDFC Bank Limited",
        "nameVariants": [
            "hdfc bank limited",
            "hdfc bank ltd",
            "hdfc bank ltd.",
            "hdfc bank",
            "hdfcbank",
        ],
    },
    "ICICIBANK": {
        "bankSymbol": "ICICIBANK",
        "bankName": "ICICI Bank Limited",
        "nameVariants": [
            "icici bank limited",
            "icici bank ltd",
            "icici bank ltd.",
            "icici bank",
            "icicibank",
        ],
    },
    "IDBI": {
        "bankSymbol": "IDBI",
        "bankName": "IDBI Bank Limited",
        "nameVariants": [
            "idbi bank limited",
            "idbi bank ltd",
            "idbi bank ltd.",
            "idbi bank",
            "idbi",
        ],
    },
    "IDFCFIRSTB": {
        "bankSymbol": "IDFCFIRSTB",
        "bankName": "IDFC First Bank Limited",
        "nameVariants": [
            "idfc first bank limited",
            "idfc first bank ltd",
            "idfc first bank ltd.",
            "idfc first bank",
            "idfc firstbank",
            "idfc bank",
        ],
    },
    "INDIANB": {
        "bankSymbol": "INDIANB",
        "bankName": "Indian Bank",
        "nameVariants": [
            "indian bank",
            "indian bank limited",
        ],
    },
    "INDUSINDBK": {
        "bankSymbol": "INDUSINDBK",
        "bankName": "IndusInd Bank Ltd",
        "nameVariants": [
            "indusind bank limited",
            "indusind bank ltd",
            "indusind bank ltd.",
            "indusind bank",
            "indusindbk",
        ],
    },
    "IOB": {
        "bankSymbol": "IOB",
        "bankName": "Indian Overseas Bank",
        "nameVariants": [
            "indian overseas bank",
            "indian overseas bank limited",
            "iob",
        ],
    },
    "J&KBANK": {
        "bankSymbol": "J&KBANK",
        "bankName": "Jammu & Kashmir Bank Ltd",
        "nameVariants": [
            "jammu and kashmir bank limited",
            "jammu & kashmir bank limited",
            "jammu and kashmir bank ltd",
            "jammu & kashmir bank ltd",
            "j&k bank",
            "jk bank",
            "the jammu and kashmir bank limited",
        ],
    },
    "JSFB": {
        "bankSymbol": "JSFB",
        "bankName": "Jana Small Finance Bank Limited",
        "nameVariants": [
            "jana small finance bank limited",
            "jana small finance bank ltd",
            "jana small finance bank",
        ],
    },
    "KARURVYSYA": {
        "bankSymbol": "KARURVYSYA",
        "bankName": "Karur Vysya Bank Ltd",
        "nameVariants": [
            "karur vysya bank limited",
            "karur vysya bank ltd",
            "karur vysya bank ltd.",
            "karur vysya bank",
            "the karur vysya bank limited",
            "kvb",
        ],
    },
    "KOTAKBANK": {
        "bankSymbol": "KOTAKBANK",
        "bankName": "Kotak Mahindra Bank Ltd",
        "nameVariants": [
            "kotak mahindra bank limited",
            "kotak mahindra bank ltd",
            "kotak mahindra bank ltd.",
            "kotak mahindra bank",
            "kotak bank",
            "kotakbank",
        ],
    },
    "KTKBANK": {
        "bankSymbol": "KTKBANK",
        "bankName": "Karnataka Bank Ltd",
        "nameVariants": [
            "karnataka bank limited",
            "karnataka bank ltd",
            "karnataka bank ltd.",
            "karnataka bank",
            "the karnataka bank limited",
        ],
    },
    "MAHABANK": {
        "bankSymbol": "MAHABANK",
        "bankName": "Bank of Maharashtra",
        "nameVariants": [
            "bank of maharashtra",
            "bank of maharashtra limited",
        ],
    },
    "PNB": {
        "bankSymbol": "PNB",
        "bankName": "Punjab National Bank",
        "nameVariants": [
            "punjab national bank",
            "punjab national bank limited",
            "pnb",
        ],
    },
    "PSB": {
        "bankSymbol": "PSB",
        "bankName": "Punjab & Sind Bank",
        "nameVariants": [
            "punjab and sind bank",
            "punjab & sind bank",
            "punjab & sind bank limited",
            "psb",
        ],
    },
    "RBLBANK": {
        "bankSymbol": "RBLBANK",
        "bankName": "RBL Bank Ltd",
        "nameVariants": [
            "rbl bank limited",
            "rbl bank ltd",
            "rbl bank ltd.",
            "rbl bank",
            "ratnakar bank",
        ],
    },
    "SBIN": {
        "bankSymbol": "SBIN",
        "bankName": "State Bank of India",
        "nameVariants": [
            "state bank of india",
            "sbi",
            "s.b.i.",
            "state bank",
        ],
    },
    "SOUTHBANK": {
        "bankSymbol": "SOUTHBANK",
        "bankName": "South Indian Bank Ltd",
        "nameVariants": [
            "south indian bank limited",
            "south indian bank ltd",
            "south indian bank ltd.",
            "south indian bank",
            "the south indian bank limited",
            "sib",
        ],
    },
    "SURYODAY": {
        "bankSymbol": "SURYODAY",
        "bankName": "Suryoday Small Finance Bank Limited",
        "nameVariants": [
            "suryoday small finance bank limited",
            "suryoday small finance bank ltd",
            "suryoday small finance bank",
        ],
    },
    "TMB": {
        "bankSymbol": "TMB",
        "bankName": "Tamilnad Mercantile Bank Ltd",
        "nameVariants": [
            "tamilnad mercantile bank limited",
            "tamilnad mercantile bank ltd",
            "tamilnad mercantile bank ltd.",
            "tamilnad mercantile bank",
            "tmb",
        ],
    },
    "UCOBANK": {
        "bankSymbol": "UCOBANK",
        "bankName": "UCO Bank",
        "nameVariants": [
            "uco bank",
            "uco bank limited",
        ],
    },
    "UJJIVANSFB": {
        "bankSymbol": "UJJIVANSFB",
        "bankName": "Ujjivan Small Finance Bank Limited",
        "nameVariants": [
            "ujjivan small finance bank limited",
            "ujjivan small finance bank ltd",
            "ujjivan small finance bank",
        ],
    },
    "UNIONBANK": {
        "bankSymbol": "UNIONBANK",
        "bankName": "Union Bank of India",
        "nameVariants": [
            "union bank of india",
            "union bank of india limited",
            "union bank of india ltd",
            "union bank",
        ],
    },
    "UTKARSHBNK": {
        "bankSymbol": "UTKARSHBNK",
        "bankName": "Utkarsh Small Finance Bank Limited",
        "nameVariants": [
            "utkarsh small finance bank limited",
            "utkarsh small finance bank ltd",
            "utkarsh small finance bank",
        ],
    },
    "YESBANK": {
        "bankSymbol": "YESBANK",
        "bankName": "Yes Bank Ltd",
        "nameVariants": [
            "yes bank limited",
            "yes bank ltd",
            "yes bank ltd.",
            "yes bank",
            "yesbank",
        ],
    },
}

# Flat lookup: normalized name → bankSymbol (built from BANK_REGISTRY)
BANK_NAME_TO_SYMBOL: dict[str, str] = {
    variant: data["bankSymbol"]
    for data in BANK_REGISTRY.values()
    for variant in data["nameVariants"]
}

# ---------------------------------------------------------------------------
# NOTE: KNOWN_SUBSIDIARIES has been removed.
# Subsidiary relationships are now derived from relatedPartyTransactions data
# in subsidiary_of.py (data-driven, scales to all banks automatically).
# Entity resolution for all shareholder/RPT entities is handled by the
# GlobalEntityRegistry in resolution/entity_resolver.py.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# RBI Priority Sector category → NIC Section letter crosswalk
# Approximate mapping; Agriculture/Housing/Education are tight;
# MSME and others span multiple NIC sections (noted below).
# ---------------------------------------------------------------------------

RBI_TO_NIC_CROSSWALK: dict[str, list[str]] = {
    # key: outstandingAdvances sub-category key in bank document
    # value: list of NIC section letters (primary first)
    "agriculture":          ["A"],          # Agriculture, Forestry, Fishing
    "msme":                 [],  # Manufacturing, Trade, Construction, Transport
    "exportCredit":         ["C", "G"],     # Manufacturing exports, Trade
    "education":            ["P"],          # Education
    "housing":              ["L"],          # Real Estate Activities
    "renewableEnergy":      ["D"],          # Electricity, Gas, Steam (incl. renewables)
    "socialInfrastructure": ["Q", "R"],     # Health, Arts/Recreation
    "weakerSections":       [],             # Cross-cutting; skip sector mapping
    "othersCategory":       [],             # Too broad; skip sector mapping
    "prioritySectorTotal":  [],             # Aggregate total; skip
}

# ---------------------------------------------------------------------------
# NIC Section reference (used to seed :Sector nodes)
# ---------------------------------------------------------------------------

NIC_SECTIONS: dict[str, str] = {
    "A": "Agriculture, Forestry and Fishing",
    "B": "Mining and Quarrying",
    "C": "Manufacturing",
    "D": "Electricity, Gas, Steam and Air Conditioning Supply",
    "E": "Water Supply, Sewerage, Waste Management",
    "F": "Construction",
    "G": "Wholesale and Retail Trade",
    "H": "Transportation and Storage",
    "I": "Accommodation and Food Service Activities",
    "J": "Information and Communication",
    "K": "Financial and Insurance Activities",
    "L": "Real Estate Activities",
    "M": "Professional, Scientific and Technical Activities",
    "N": "Administrative and Support Service Activities",
    "O": "Public Administration and Defence",
    "P": "Education",
    "Q": "Human Health and Social Work Activities",
    "R": "Arts, Entertainment and Recreation",
    "S": "Other Service Activities",
}

# ---------------------------------------------------------------------------
# Corporate keyword filter for RPT human-entity exclusion
# An RPT counter-party is considered a company if its name contains at least
# one of these tokens (case-insensitive).
# ---------------------------------------------------------------------------

CORPORATE_KEYWORDS = {
    "ltd", "limited", "pvt", "private", "corp", "corporation", "inc",
    "bank", "finance", "insurance", "capital", "technologies", "technology",
    "investments", "ventures", "securities", "asset", "management",
    "services", "solutions", "industries", "enterprises", "holdings",
    "infrastructure", "energy", "power", "motors", "chemicals",
    "pharmaceuticals", "developers", "properties", "realty", "foundation",
    "llp"
}

# ---------------------------------------------------------------------------
# Generic name token stop-list (used for fuzzy-match token-overlap veto)
# When the tokens shared between two candidate names are mostly generic words,
# we reject the fuzzy match even if the raw score exceeds the threshold.
# This prevents common-suffix-only matches like "D. D International Private
# Limited" matching every entity that contains "International Private Limited".
# ---------------------------------------------------------------------------

GENERIC_NAME_TOKENS: frozenset[str] = frozenset({
    # Legal / entity-type suffixes
    "ltd", "limited", "pvt", "private", "llp", "llc", "inc", "incorporated",
    "corp", "corporation", "plc", "ag", "sa", "nv", "bv",
    # High-frequency words that appear in thousands of company names
    "india", "indian", "international", "national", "enterprises", "enterprise",
    "industries", "industry", "group", "holdings", "holding", "ventures",
    "venture", "solutions", "solution", "services", "service", "systems",
    "system", "technologies", "technology", "tech", "management",
    "infrastructure", "global", "universal", "united",
    "the", "and", "of", "for", "in", "at", "by",
    # Finance-domain generics
    "finance", "financial", "capital", "investment", "investments",
    "trading", "traders", "trade", "commercial", "commerce",
    "realty", "realtors", "properties", "property", "developers",
    "associates", "associate", "co", "company",
    # Securities / banking subsidiaries (extremely common in Indian company names;
    # treating as distinctive causes subset-name false positives like
    # 'SMC Global Securities' matching 'SBI-SG Global Securities Services')
    "securities", "broking", "brokerage", "wealth",
    "credit", "leasing", "insurance",
    "asset", "assets", "fund", "funds",
})
