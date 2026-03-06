"""
stress_engine/config.py
Central configuration for the news stress pipeline.

All settings mirror the conventions used in:
    data_consolidation/scripts/bank/config.py
    prototype_kg/config.py
"""
import os
from dotenv import load_dotenv

# Resolve workspace root (stress_engine/ lives one level below Capstone/)
_ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(_ROOT, ".env"))

# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------
MONGODB_URI = os.getenv("db_cluster_link")
DB_NAME = "financial_kg"

BANKS_COLLECTION   = "banks"        # financial_kg.banks
COMPANY_COLLECTION = "companies"    # financial_kg.companies

# Rolling baseline storage — one doc per (entity_id, entity_type, date)
BASELINE_COLLECTION = "news_baselines"

# ---------------------------------------------------------------------------
# Target scope (mirrors prototype_kg and data_consolidation configs)
# ---------------------------------------------------------------------------
TARGET_BANK_SYMBOLS = ["SBIN", "HDFCBANK", "ICICIBANK"]

BANK_DISPLAY_NAMES = {
    "SBIN":      "State Bank of India",
    "HDFCBANK":  "HDFC Bank Limited",
    "ICICIBANK": "ICICI Bank Limited",
}

# ---------------------------------------------------------------------------
# Pipeline settings
# ---------------------------------------------------------------------------

# Rolling window used to compute mean/std for Z-score calculation
BASELINE_WINDOW_DAYS: int = 60

# Exponential half-life: stress impact halves every N days without reinforcement
DECAY_HALFLIFE_DAYS: float = 5.0

# Minimum history (days) required before using Z-score; below this, use raw score
MIN_HISTORY_DAYS: int = 7

# ---------------------------------------------------------------------------
# FinBERT
# ---------------------------------------------------------------------------
FINBERT_MODEL = "ProsusAI/finbert"

# If any of these substrings appear in a headline (case-insensitive), skip
# FinBERT and immediately assign the maximum signed stress score (1.0).
HARD_TRIGGER_KEYWORDS = [
    "default",
    "auditor resignation",
    "resignation of statutory auditor",
    "cbi raid",
    "cbi investigation",
    "ed summons",
    "ed raid",
    "enforcement directorate",
    "rbi penalty",
    "rbi imposed penalty",
    "prompt corrective action",
    "pca framework",
    "wilful defaulter",
    "fraud account",
    "insolvency",
    "liquidation",
    "nclat",
    "nclt",
]

# ---------------------------------------------------------------------------
# Web scraping — ddgs query configuration
# ---------------------------------------------------------------------------

# Financial news sites for entity-specific queries
NEWS_SITES = [
    "site:economictimes.indiatimes.com",
    "site:moneycontrol.com",
    "site:livemint.com",
    "site:business-standard.com",
    "site:financialexpress.com",
]

# Extra keywords injected alongside the entity name in search queries
NEGATIVE_KEYWORDS = [
    "default",
    "downgrade",
    "npa",
    "fraud",
    "scam",
    "notice",
    "investigation",
    "penalty",
    "rating downgrade",
    "issuer not cooperating",
    "debt restructuring",
]

# ddgs timelimit — only fetch articles no older than this
DDGS_TIMELIMIT = "m"  # "m" = last month (~30 days)

# Maximum articles to process per entity per run
# Multiple query variants are fetched and deduplicated, so set this high enough
# to accommodate articles from all variants combined.
MAX_ARTICLES_PER_ENTITY = 100

# How many results to request per individual DDG query variant.
# DDG rarely returns more than ~50 even when max_results is higher.
MAX_ARTICLES_PER_QUERY = 50

# ---------------------------------------------------------------------------
# Entity search aliases
# ---------------------------------------------------------------------------
# Maps a display-name → list of additional search terms to run alongside the
# primary query.  Auto-suffix-stripping (removing " Limited", " Ltd", etc.)
# is applied in the scraper regardless of this config.
ENTITY_SEARCH_ALIASES: dict[str, list[str]] = {
    # Banks — shorter / colloquial names that yield more DDG results
    "HDFC Bank Limited":   ["HDFC Bank"],
    "State Bank of India": ["SBI", "SBI Bank"],
    "ICICI Bank Limited":  ["ICICI Bank"],
}

# ---------------------------------------------------------------------------
# GDELT
# ---------------------------------------------------------------------------
GDELT_API_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_RECORDS = 25

# Sector terms appended to GDELT queries for PrioritySector nodes
PRIORITY_SECTOR_GDELT_TERMS = {
    "agriculture":          "sourcecountry:India agriculture bank loan (default OR overdue OR stressed)",
    "msme":                 "sourcecountry:India MSME OR \"small business\" bank loan (default OR overdue OR stressed)",
    "exportCredit":         "sourcecountry:India \"export credit\" bank (default OR risk OR stressed)",
    "education":            "sourcecountry:India \"education loan\" bank (default OR overdue OR NPA)",
    "housing":              "sourcecountry:India (\"housing loan\" OR \"home loan\") bank (default OR overdue OR NPA)",
    "renewableEnergy":      "sourcecountry:India \"renewable energy\" bank loan (default OR stressed OR NPA)",
    "socialInfrastructure": "sourcecountry:India \"social infrastructure\" bank loan (default OR stressed)",
    "weakerSections":       "sourcecountry:India bank (\"weaker section\" OR \"priority sector\") loan (default OR NPA)",
    "othersCategory":       "sourcecountry:India bank \"priority sector\" loan (default OR NPA OR overdue)",
    "prioritySectorTotal":  "sourcecountry:India bank \"priority sector lending\" RBI (NPA OR compliance OR shortfall)",
}
