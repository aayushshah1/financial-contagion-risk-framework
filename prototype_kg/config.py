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
SECTOR_COLLECTION  = "sectors"        # financial_kg/sectors

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


def get_sector_stress_map(client: MongoClient) -> dict[str, float]:
    """
    Return a mapping of macro_sector -> final_stress_score from financial_kg/sectors.
    
    Returns:
        dict mapping sector names to their stress scores
    """
    sector_docs = list(client[MONGO_DB][SECTOR_COLLECTION].find({}))
    sector_map = {}
    
    for doc in sector_docs:
        macro_sector = doc.get("macro_sector")
        final_stress = doc.get("final_stress_score")
        
        if macro_sector and final_stress is not None:
            try:
                sector_map[macro_sector] = float(final_stress)
            except (TypeError, ValueError):
                pass
    
    return sector_map


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

"""
prototype_kg/sector_taxonomy.py
Maps CRISIL industry names to macro-sectors.
Used to join company industryName → macro_sector → sector stress score.
"""

TAXONOMY: dict[str, str] = {
    # Banking & Financial Services
    "Private Sector Bank":                    "Banking & Financial Services",
    "Non Banking Financial Company (NBFC)":   "Banking & Financial Services",
    "Housing Finance Company":                "Banking & Financial Services",
    "Microfinance Institutions":              "Banking & Financial Services",
    "Financial Institution":                  "Banking & Financial Services",
    "Asset Management Company":               "Banking & Financial Services",
    "Stockbroking & Allied":                  "Banking & Financial Services",
    "Other Capital Market related Services":  "Banking & Financial Services",
    "Other Financial Services":               "Banking & Financial Services",
    "Investment Company":                     "Banking & Financial Services",
    # Energy
    "Oil Exploration & Production":           "Energy",
    "Refineries & Marketing":                 "Energy",
    "Oil Equipment & Services":               "Energy",
    "Oil Storage & Transportation":           "Energy",
    "LPG/CNG/PNG/LNG Supplier":               "Energy",
    "Power Generation":                       "Energy",
    "Integrated Power Utilities":             "Energy",
    "Power Distribution":                     "Energy",
    "Power Trading":                          "Energy",
    "Power - Transmission":                   "Energy",
    "Other Utilities":                        "Energy",
    "Offshore Support Solution Drilling":     "Energy",
    # Metals & Mining
    "Iron & Steel":                           "Metals & Mining",
    "Iron & Steel Products":                  "Metals & Mining",
    "Aluminium":                              "Metals & Mining",
    "Copper":                                 "Metals & Mining",
    "Zinc":                                   "Metals & Mining",
    "Diversified Metals":                     "Metals & Mining",
    "Ferro & Silica Manganese":               "Metals & Mining",
    "Sponge Iron":                            "Metals & Mining",
    "Pig Iron":                               "Metals & Mining",
    "Precious Metals":                        "Metals & Mining",
    "Coal":                                   "Metals & Mining",
    "Trading - Metals":                       "Metals & Mining",
    "Trading - Minerals":                     "Metals & Mining",
    "Industrial Minerals":                    "Metals & Mining",
    "Aluminium, Copper & Zinc Products":      "Metals & Mining",
    "Trading - Coal":                         "Metals & Mining",
    # Automobiles & Auto Components
    "Passenger Cars & Utility Vehicles":      "Automobiles & Auto Components",
    "Commercial Vehicles":                    "Automobiles & Auto Components",
    "2/3 Wheelers":                           "Automobiles & Auto Components",
    "Auto Components & Equipments":           "Automobiles & Auto Components",
    "Tractors":                               "Automobiles & Auto Components",
    "Auto Dealer":                            "Automobiles & Auto Components",
    "Dealers-Commercial Vehicles, Tractors, Construction Vehicles": "Automobiles & Auto Components",
    "Trading - Auto Components":              "Automobiles & Auto Components",
    "Cycles":                                 "Automobiles & Auto Components",
    "Tyres & Rubber Products":                "Automobiles & Auto Components",
    # Pharmaceuticals & Healthcare
    "Pharmaceuticals":                        "Pharmaceuticals & Healthcare",
    "Biotechnology":                          "Pharmaceuticals & Healthcare",
    "Healthcare Service Provider":            "Pharmaceuticals & Healthcare",
    "Medical Equipment & Supplies":           "Pharmaceuticals & Healthcare",
    "Healthcare Research, Analytics & Technology": "Pharmaceuticals & Healthcare",
    "Hospital":                               "Pharmaceuticals & Healthcare",
    # IT & Technology
    "Computers - Software & Consulting":      "IT & Technology",
    "IT Enabled Services":                    "IT & Technology",
    "Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)": "IT & Technology",
    "Data Processing Services":               "IT & Technology",
    "Computers Hardware & Equipments":        "IT & Technology",
    "Telecom - Equipment & Accessories":      "IT & Technology",
    "Telecom - Cellular & Fixed line services": "IT & Technology",
    "Telecom - Infrastructure":               "IT & Technology",
    "Consulting Services":                    "IT & Technology",
    # Chemicals & Petrochemicals
    "Specialty Chemicals":                    "Chemicals & Petrochemicals",
    "Commodity Chemicals":                    "Chemicals & Petrochemicals",
    "Petrochemicals":                         "Chemicals & Petrochemicals",
    "Dyes And Pigments":                      "Chemicals & Petrochemicals",
    "Pesticides & Agrochemicals":             "Chemicals & Petrochemicals",
    "Fertilizers":                            "Chemicals & Petrochemicals",
    "Carbon Black":                           "Chemicals & Petrochemicals",
    "Explosives":                             "Chemicals & Petrochemicals",
    "Industrial Gases":                       "Chemicals & Petrochemicals",
    "Lubricants":                             "Chemicals & Petrochemicals",
    "Paints":                                 "Chemicals & Petrochemicals",
    "Trading - Chemicals":                    "Chemicals & Petrochemicals",
    # FMCG & Consumer Goods
    "Diversified FMCG":                       "FMCG & Consumer Goods",
    "Packaged Foods":                         "FMCG & Consumer Goods",
    "Other Food Products":                    "FMCG & Consumer Goods",
    "Personal Care":                          "FMCG & Consumer Goods",
    "Household Products":                     "FMCG & Consumer Goods",
    "Household Appliances":                   "FMCG & Consumer Goods",
    "Consumer Electronics":                   "FMCG & Consumer Goods",
    "Diversified Retail":                     "FMCG & Consumer Goods",
    "Speciality Retail":                      "FMCG & Consumer Goods",
    "Houseware":                              "FMCG & Consumer Goods",
    "Stationary":                             "FMCG & Consumer Goods",
    "Leisure Products":                       "FMCG & Consumer Goods",
    # Infrastructure & Construction
    "Civil Construction":                     "Infrastructure & Construction",
    "Cement & Cement Products":               "Infrastructure & Construction",
    "Road Assets-Toll, Annuity, Hybrid-Annuity": "Infrastructure & Construction",
    "Road Transport":                         "Infrastructure & Construction",
    "Other Construction Materials":           "Infrastructure & Construction",
    "Airport & Airport services":             "Infrastructure & Construction",
    "Railway Wagons":                         "Infrastructure & Construction",
    "Water Supply & Management":              "Infrastructure & Construction",
    "Dredging":                               "Infrastructure & Construction",
    "Waste Management":                       "Infrastructure & Construction",
    "Other Electrical Equipment":             "Infrastructure & Construction",
    "Electrodes & Refractories":              "Infrastructure & Construction",
    # Real Estate
    "Real Estate Investment Trusts (REITs)":  "Real Estate",
    "Real Estate related services":           "Real Estate",
    "Residential, Commercial Projects":       "Real Estate",
    "Furniture, Home Furnishing":             "Real Estate",
    "Granites & Marbles":                     "Real Estate",
    "Plywood Boards/ Laminates":              "Real Estate",
    "Ceramics":                               "Real Estate",
    # Media & Entertainment
    "Media & Entertainment":                  "Media & Entertainment",
    "TV Broadcasting & Software Production":  "Media & Entertainment",
    "Film Production, Distribution & Exhibition": "Media & Entertainment",
    "Print Media":                            "Media & Entertainment",
    "Advertising & Media Agencies":           "Media & Entertainment",
    "Printing & Publication":                 "Media & Entertainment",
    "Amusement Parks/ Other Recreation":      "Media & Entertainment",
    "Other Consumer Services":                "Media & Entertainment",
    # Agriculture & Food Processing
    "Sugar":                                  "Agriculture & Food Processing",
    "Tea & Coffee":                           "Agriculture & Food Processing",
    "Edible Oil":                             "Agriculture & Food Processing",
    "Dairy Products":                         "Agriculture & Food Processing",
    "Seafood":                                "Agriculture & Food Processing",
    "Meat Products including Poultry":        "Agriculture & Food Processing",
    "Animal Feed":                            "Agriculture & Food Processing",
    "Other Agricultural Products":            "Agriculture & Food Processing",
    "Other Beverages":                        "Agriculture & Food Processing",
    "Breweries & Distilleries":               "Agriculture & Food Processing",
    "Cigarettes & Tobacco Products":          "Agriculture & Food Processing",
    "Restaurants":                            "Agriculture & Food Processing",
    # Logistics & Transport
    "Logistics Solution Provider":            "Logistics & Transport",
    "Shipping":                               "Logistics & Transport",
    "Transport Related Services":             "Logistics & Transport",
    "Tour, Travel Related Services":          "Logistics & Transport",
    "Airline":                                "Logistics & Transport",
    # Textiles & Apparel
    "Garments & Apparels":                    "Textiles & Apparel",
    "Other Textile Products":                 "Textiles & Apparel",
    "Trading - Textile Products":             "Textiles & Apparel",
    "Leather And Leather Products":           "Textiles & Apparel",
    "Jute & Jute Products":                   "Textiles & Apparel",
    "Footwear":                               "Textiles & Apparel",
    "Rubber":                                 "Textiles & Apparel",
    # Capital Goods & Industrials
    "Heavy Electrical Equipment":             "Capital Goods & Industrials",
    "Compressors, Pumps & Diesel Engines":    "Capital Goods & Industrials",
    "Castings & Forgings":                    "Capital Goods & Industrials",
    "Abrasives & Bearings":                   "Capital Goods & Industrials",
    "Industrial Products":                    "Capital Goods & Industrials",
    "Other Industrial Products":              "Capital Goods & Industrials",
    "Aerospace & Defense":                    "Capital Goods & Industrials",
    "Plastic Products - Industrial":          "Capital Goods & Industrials",
    "Plastic Products - Consumer":            "Capital Goods & Industrials",
    "Packaging":                              "Capital Goods & Industrials",
    "Paper & Paper Products":                 "Capital Goods & Industrials",
    "Cables - Electricals":                   "Capital Goods & Industrials",
    # Gems, Jewellery & Luxury
    "Gems, Jewellery And Watches":            "Gems, Jewellery & Luxury",
    "Hotels & Resorts":                       "Gems, Jewellery & Luxury",
    "Education":                              "Gems, Jewellery & Luxury",
    # Diversified / Conglomerates
    "Diversified":                            "Diversified / Conglomerates",
    "Diversified Commercial Services":        "Diversified / Conglomerates",
    "Trading & Distributors":                 "Diversified / Conglomerates",
    "Distributors":                           "Diversified / Conglomerates",
}


def get_macro_sector(industry_name: str) -> str | None:
    """
    Map a CRISIL industry name to its macro sector.
    
    Args:
        industry_name: CRISIL industry name from company document
        
    Returns:
        Macro sector name if found, None otherwise
    """
    if not industry_name:
        return None
    return TAXONOMY.get(industry_name.strip())
