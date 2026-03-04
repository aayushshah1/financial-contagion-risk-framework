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
    """Return all 3 consolidated bank documents from MongoDB (financial_kg/bank)."""
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
# Target banks
# ---------------------------------------------------------------------------

TARGET_BANK_SYMBOLS = ["SBIN", "HDFCBANK", "ICICIBANK"]

BANK_REGISTRY = {
    "SBIN": {
        "bankSymbol": "SBIN",
        "bankName": "State Bank of India",
        # All known name variants (lowercase) that should resolve to this bank
        "nameVariants": [
            "state bank of india",
            "sbi",
            "s.b.i.",
            "state bank",
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
})
