"""
task_company_consolidate.py
============================
Final company-level data consolidation.

Merges four data sources into every document in the local MongoDB
`company/mca_crisil_match` collection:

  1. **Cloud CRISIL** (crisil_ratings/rating_reports)
        ratingDate, ratingFileName, heading, instruments, bankFacilities
        — most recent report per companyCode (by ratingDate)

  2. **cleaned_test.json** (local JSON, CRISIL industry/ratings metadata)
        industryName, industryCode  (first non-empty entry per company)
        crisilRatings               (array with one entry per instrument)

  3. **Local MCA data** (company/mca data)
        All MCA fields not already present in the document
        — joined by CIN

  4. **NSE Shareholding XBRL** (data_consolidation/data/company/shareholding/)
        shareholdingPattern — extracted via Arelle (taxonomy-validated) with ET fallback
        — only for documents that already have a nseSymbol

Usage
-----
    python task_company_consolidate.py [--dry-run] [--skip-shp]

Author: auto-generated  |  Date: February 2026
"""

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from arelle import Cntlr as _ArelleCntlr
    ARELLE_AVAILABLE = True
except ImportError:
    _ArelleCntlr = None  # type: ignore
    ARELLE_AVAILABLE = False

from pymongo import MongoClient, UpdateOne

try:
    from tqdm import tqdm
    TQDM = True
except ImportError:
    TQDM = False
    print("Warning: tqdm not installed; no progress bar.")

# ============================================================================
# Config
# ============================================================================

LOCAL_URI  = "mongodb://127.0.0.1:27108/?directConnection=true"
CLOUD_URI  = "mongodb+srv://prabirkalwani:prabirkalwani%40123@maincluster.tvef4tx.mongodb.net/"

LOCAL_DB   = "company"
LOCAL_COL  = "mca_crisil_match"
MCA_COL    = "mca data"

CLOUD_DB   = "crisil_ratings"
CLOUD_COL  = "rating_reports"

_REPO_ROOT      = Path(__file__).resolve().parents[2]
CLEANED_TEST    = _REPO_ROOT / "data_analysis" / "outputs" / "cleaned_test.json"
SHP_DIR         = _REPO_ROOT / "data_consolidation" / "data" / "company" / "shareholding"

# ============================================================================
# Logging
# ============================================================================

LOG_FILE = Path(__file__).parent / "task_company_consolidate.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ============================================================================
# Helper utilities
# ============================================================================

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def parse_rating_date(date_str: str) -> Optional[datetime]:
    """
    Try to parse CRISIL rating date strings like 'Dec 17, 2025' or 'January 31, 2026'.
    Returns a datetime or None on failure.
    """
    if not date_str:
        return None
    try:
        # Normalise: remove extra spaces
        s = re.sub(r"\s+", " ", date_str.strip())
        # dateutil is not always available; use manual approach
        parts = s.replace(",", "").split()
        if len(parts) == 3:
            month = _MONTH_MAP.get(parts[0][:3].lower())
            if month:
                return datetime(int(parts[2]), month, int(parts[1]))
    except Exception:
        pass
    return None


def _to_camel(pascal: str) -> str:
    """PascalCase → camelCase"""
    return pascal[0].lower() + pascal[1:] if pascal else pascal


def _coerce(value: Optional[str]) -> Any:
    """Try to convert strings to int/float; keep as str otherwise."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if "." not in s:
            return int(s)
        return float(s)
    except (ValueError, TypeError):
        return s

# ============================================================================
# Source 1: Cloud CRISIL → most-recent report per companyCode
# ============================================================================

def load_cloud_crisil(company_codes: set) -> Dict[str, Dict]:
    """
    Fetch from cloud MongoDB:  crisil_ratings / rating_reports

    For each companyCode present in `company_codes`, keep the document with
    the latest ratingDate.

    Returns:  {companyCode: {ratingDate, ratingFileName, heading,
                              instruments, bankFacilities}}
    """
    log.info("Connecting to cloud MongoDB …")
    cloud = MongoClient(CLOUD_URI, serverSelectionTimeoutMS=12000)
    col   = cloud[CLOUD_DB][CLOUD_COL]

    log.info("Fetching CRISIL rating_reports from cloud …")
    cursor = col.find(
        {"companyCode": {"$in": list(company_codes)},
         "processingStatus": "completed"},
        {"companyCode": 1, "ratingDate": 1, "ratingFileName": 1,
         "heading": 1, "instruments": 1, "bankFacilities": 1},
    )

    # Keep only most-recent per companyCode
    best: Dict[str, Dict] = {}
    for doc in cursor:
        code = doc["companyCode"]
        dt   = parse_rating_date(doc.get("ratingDate", ""))
        prev = best.get(code)
        prev_dt = parse_rating_date(prev.get("ratingDate", "")) if prev else None
        if prev is None or (dt and prev_dt and dt > prev_dt):
            best[code] = {
                "ratingDate":     doc.get("ratingDate"),
                "ratingFileName": doc.get("ratingFileName"),
                "crisilHeading":  doc.get("heading"),
                "instruments":    doc.get("instruments", []),
                "bankFacilities": doc.get("bankFacilities", []),
            }

    cloud.close()
    log.info(f"Cloud CRISIL loaded: {len(best):,} companies matched")
    return best

# ============================================================================
# Source 2: cleaned_test.json → industryName/Code + crisilRatings per code
# ============================================================================

def load_cleaned_test(company_codes: set) -> Dict[str, Dict]:
    """
    Parse data_analysis/outputs/cleaned_test.json.

    Returns:
        {companyCode: {
            industryName: str,
            industryCode: str,
            crisilRatings: [{instrumentName, rating, outlook, product}, ...]
        }}
    """
    log.info(f"Loading cleaned_test.json from {CLEANED_TEST} …")
    with open(CLEANED_TEST, encoding="utf-8") as f:
        raw = json.load(f)

    docs = raw.get("docs", {})
    result: Dict[str, Dict] = {}

    for code, instruments in docs.items():
        if code not in company_codes:
            continue
        if not instruments:
            continue

        # Pick industryName/Code from first entry that has a non-empty value
        industry_name = ""
        industry_code = ""
        for inst in instruments:
            if not industry_name and inst.get("industryName"):
                industry_name = inst["industryName"]
                industry_code = str(inst.get("industryCode", ""))
            if industry_name:
                break

        # Collect unique ratings (deduplicated on instrumentName)
        seen_instruments = set()
        ratings = []
        for inst in instruments:
            name = inst.get("instrumentName", "")
            key  = (name, inst.get("rating", ""), inst.get("outlook", ""))
            if key not in seen_instruments:
                seen_instruments.add(key)
                ratings.append({
                    "instrumentName": name,
                    "rating":         inst.get("rating", ""),
                    "outlook":        inst.get("outlook", ""),
                    "product":        inst.get("product", ""),
                    "industryCode":   str(inst.get("industryCode", "")),
                    "industryName":   inst.get("industryName", ""),
                })

        result[code] = {
            "industryName":  industry_name,
            "industryCode":  industry_code,
            "crisilRatings": ratings,
        }

    log.info(f"cleaned_test.json: {len(result):,} company codes matched out of {len(docs):,} total")
    return result

# ============================================================================
# Source 3: Local MCA data → full MCA record per CIN
# ============================================================================

def load_mca_data(cin_list: List[str]) -> Dict[str, Dict]:
    """
    Load all MCA records for the given CIN list from local MongoDB.

    Returns:  {CIN: mca_record_dict}
    """
    log.info(f"Loading MCA data for {len(cin_list):,} CINs from local MongoDB …")
    local = MongoClient(LOCAL_URI, directConnection=True)
    col   = local[LOCAL_DB][MCA_COL]

    records: Dict[str, Dict] = {}
    cursor = col.find(
        {"CIN": {"$in": cin_list}},
        {"_id": 0},   # exclude internal Mongo _id
    )
    for doc in cursor:
        cin = doc.get("CIN", "")
        if cin:
            records[cin] = doc

    local.close()
    log.info(f"MCA data: {len(records):,} records loaded")
    return records

# ============================================================================
# Source 4: NSE Shareholding XBRL — exact structure mirroring task5_shareholding_xbrl.py
# ============================================================================

def _shp_extract_context_facts(root, context_id: str) -> Optional[Dict]:
    """
    Extract all facts for a specific XBRL context ID.
    Matches both instant (context_id) and duration (D_context_id) variants.
    """
    data: Dict[str, Any] = {}
    for elem in root:
        ctx = elem.get("contextRef", "")
        if ctx != context_id and ctx != f"D_{context_id}":
            continue
        local = elem.tag.split("}")[1] if "}" in elem.tag else elem.tag
        key   = _to_camel(local)
        value = elem.text
        try:
            if value is not None:
                data[key] = int(value) if "." not in str(value) else float(value)
            else:
                data[key] = None
        except (ValueError, TypeError):
            data[key] = value
    return data if data else None


def _shp_extract_entity_group(root, category_prefix: str) -> List[Dict]:
    """
    Extract individual shareholder entities for a given category prefix.
    Scans for NameOfTheShareholder facts whose contextRef matches
    `{category_prefix}_Context<digits>`, then pulls all facts for each context.
    """
    entities: List[Dict] = []
    context_pattern = re.compile(rf"^{category_prefix}_Context\d+$")
    entity_contexts: List[Dict[str, str]] = []

    for elem in root:
        local = elem.tag.split("}")[1] if "}" in elem.tag else elem.tag
        if local != "NameOfTheShareholder":
            continue
        ctx = elem.get("contextRef", "").replace("D_", "")
        if not context_pattern.match(ctx):
            continue
        name = elem.text
        if name and name not in ("******", "NA", "", "Not Applicable"):
            entity_contexts.append({"context": ctx, "name": name})

    for ec in entity_contexts:
        facts = _shp_extract_context_facts(root, ec["context"])
        if not facts:
            continue
        entity: Dict[str, Any] = {
            "name":                   ec["name"],
            "numberOfShares":         facts.get("numberOfShares") or facts.get("numberOfFullyPaidUpEquityShares"),
            "shareholdingPercentage": facts.get("shareholdingAsAPercentageOfTotalNumberOfShares"),
            "numberOfVotingRights":   facts.get("numberOfVotingRights"),
            "votingRightsPercentage": facts.get("percentageOfTotalVotingRights"),
            "pan":                    facts.get("permanentAccountNumberOfShareholder"),
            "dematerializedShares":   facts.get("numberOfEquitySharesHeldInDematerializedForm"),
            "numberOfShareholders":   facts.get("numberOfShareholders"),
        }
        # Strip None values
        entity = {k: v for k, v in entity.items() if v is not None}
        # Optional typed fields
        if facts.get("typeOfPromoterShareholding"):
            entity["type"] = facts["typeOfPromoterShareholding"]
        if facts.get("categoryOfOtherInstitutions"):
            entity["category"] = facts["categoryOfOtherInstitutions"]
        if facts.get("categoryOfOtherNonInstitutions"):
            entity["category"] = facts["categoryOfOtherNonInstitutions"]
        entities.append(entity)

    entities.sort(key=lambda x: x.get("shareholdingPercentage", 0), reverse=True)
    return entities


def _shp_extract_pattern(root) -> Dict:
    """
    Build the complete hierarchical shareholding pattern — identical structure
    to _extract_complete_shareholding_pattern() in task5_shareholding_xbrl.py.
    """
    cf = _shp_extract_context_facts  # shorthand
    eg = _shp_extract_entity_group

    # ------------------------------------------------------------------ #
    # 1. PROMOTER AND PROMOTER GROUP
    # ------------------------------------------------------------------ #
    promoter: Dict[str, Any] = {
        "aggregate": cf(root, "ShareholdingOfPromoterAndPromoterGroup_ContextI"),
        "entities":  [],
    }
    gov_entities = eg(root, "CentralGovernmentOrStateGovernments")
    if gov_entities:
        promoter["government"] = {
            "aggregate": cf(root, "CentralGovernmentOrStateGovernments_ContextI"),
            "entities":  gov_entities,
        }

    # ------------------------------------------------------------------ #
    # 2. PUBLIC SHAREHOLDING
    # ------------------------------------------------------------------ #
    public: Dict[str, Any] = {
        "aggregate":       cf(root, "PublicShareholding_ContextI"),
        "institutions":    {},
        "nonInstitutions": {},
    }

    # — Institutions — #
    fpi1_entities = eg(root, "InstitutionsForeignPortfolioInvestorCategoryOne")
    fpi2_entities = eg(root, "InstitutionsForeignPortfolioInvestorCategoryTwo")
    institutions: Dict[str, Any] = {
        "mutualFunds": {
            "aggregate": cf(root, "MutualFundsOrUTI_ContextI"),
            "entities":  eg(root, "MutualFundsOrUTI"),
        },
        "foreignPortfolioInvestors": {
            "category1": {
                "aggregate": cf(root, "InstitutionsForeignPortfolioInvestorCategoryOne_ContextI"),
                "entities":  fpi1_entities,
            },
            "category2": {
                "aggregate": cf(root, "InstitutionsForeignPortfolioInvestorCategoryTwo_ContextI"),
                "entities":  fpi2_entities,
            },
        },
        "insuranceCompanies": {
            "aggregate": cf(root, "InsuranceCompanies_ContextI"),
            "entities":  eg(root, "InsuranceCompanies"),
        },
        "banks": {
            "aggregate": cf(root, "Banks_ContextI"),
            "entities":  eg(root, "Banks"),
        },
        "providentFunds": {
            "aggregate": cf(root, "ProvidentFundsOrPensionFunds_ContextI"),
            "entities":  eg(root, "ProvidentFundsOrPensionFunds"),
        },
        "otherInstitutionsDomestic": {
            "aggregate": cf(root, "OtherInstitutionsDomestic_ContextI"),
            "entities":  eg(root, "OtherInstitutionsDomestic"),
        },
        "otherInstitutionsForeign": {
            "aggregate": cf(root, "OtherInstitutionsForeign_ContextI"),
            "entities":  eg(root, "OtherInstitutionsForeign"),
        },
    }
    public["institutions"] = institutions

    # — Non-Institutions — #
    non_institutions: Dict[str, Any] = {
        "residentIndividuals": {
            "aggregate": cf(root, "ResidentIndividuals_ContextI"),
            "entities":  eg(root, "ResidentIndividuals"),
        },
        "nonResidentIndians": {
            "aggregate": cf(root, "NonResidentIndians_ContextI"),
            "entities":  eg(root, "NonResidentIndians"),
        },
        "bodiesCorporate": {
            "aggregate": cf(root, "BodiesCorporate_ContextI"),
            "entities":  eg(root, "BodiesCorporate"),
        },
        "otherNonInstitutions": {
            "aggregate": cf(root, "OtherNonInstitutions_ContextI"),
            "entities":  eg(root, "OtherNonInstitutions"),
        },
    }
    public["nonInstitutions"] = non_institutions

    # ------------------------------------------------------------------ #
    # 3. NON-PROMOTER NON-PUBLIC
    # ------------------------------------------------------------------ #
    npnp: Dict[str, Any] = {
        "aggregate": cf(root, "SharesHeldByNonPromoterNonPublicShareholders_ContextI"),
        "entities":  [],
    }
    cust_entities = eg(root, "CustodianOrDRHolder")
    if cust_entities:
        npnp["custodian"] = {
            "aggregate": cf(root, "CustodianOrDRHolder_ContextI"),
            "entities":  cust_entities,
        }

    return {
        "promoterHolding":          promoter,
        "publicHolding":            public,
        "nonPromoterNonPublicHolding": npnp,
    }


def _shp_extract_with_root(root) -> Dict:
    """Build the result dict from any XML/lxml root element."""
    total_facts = (
        _shp_extract_context_facts(root, "ShareholdingPattern_ContextI")
        or _shp_extract_context_facts(root, "MainI")
        or {}
    )
    return {
        "totalShares":         total_facts.get("numberOfShares") or total_facts.get("totalNumberOfShares"),
        "totalShareholders":   total_facts.get("numberOfShareholders"),
        "shareholdingPattern": _shp_extract_pattern(root),
    }


def _parse_shp_xml(xml_path: Path, ctrl=None) -> Dict:
    """
    Parse a SEBI Shareholding Pattern XBRL file.

    Preferred path  : Arelle (taxonomy-validated; pass a shared Cntlr instance).
    Fallback path   : raw ElementTree (fast, no validation).

    Returns the same hierarchical structure as task5_shareholding_xbrl.py.
    """
    # ---- Arelle path -------------------------------------------------------
    if ctrl is not None:
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        model = None
        try:
            model = ctrl.modelManager.load(str(xml_path))
            sys.stdout = old_stdout
            if model is None:
                raise ValueError("Arelle returned no model")
            root = model.modelDocument.xmlRootElement
            result = _shp_extract_with_root(root)
            return result
        except Exception as exc:
            sys.stdout = old_stdout
            log.warning(f"Arelle parse failed for {xml_path.name}: {exc} — retrying with ElementTree")
            # fall through to ET
        finally:
            if model is not None:
                try:
                    model.close()
                except Exception:
                    pass
            sys.stdout = old_stdout

    # ---- ElementTree fallback ----------------------------------------------
    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError as exc:
        log.warning(f"XML parse error for {xml_path.name}: {exc}")
        return {}
    return _shp_extract_with_root(tree.getroot())


def _load_all_shp(symbols: List[str]) -> Dict[str, Dict]:
    """
    Load and parse SHP XBRL for all given NSE symbols.

    A single Arelle Cntlr is created once and reused for every file so the
    taxonomy is loaded only once.  Falls back to ElementTree if Arelle is not
    installed or fails to initialise.

    Returns {symbol: shareholding_dict}  (missing files are silently skipped).
    """
    results: Dict[str, Dict] = {}
    missing = 0
    failed  = 0

    # -- create one shared Arelle controller --------------------------------
    ctrl = None
    if ARELLE_AVAILABLE:
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            ctrl = _ArelleCntlr.Cntlr(logFileName="logToPrint")
            ctrl.webCache.workOffline = True
            sys.stdout = old_stdout
            log.info("SHP: using Arelle (taxonomy-validated)")
        except Exception as exc:
            sys.stdout = old_stdout
            ctrl = None
            log.warning(f"Arelle init failed ({exc}); falling back to ElementTree")
    else:
        log.info("SHP: Arelle not installed — using ElementTree")

    # -- parse each file -----------------------------------------------------
    iterator = tqdm(symbols, desc="Parsing SHP XMLs", unit="file") if TQDM else symbols
    for sym in iterator:
        xml_path = SHP_DIR / f"shareholding_{sym}_2025-12-31.xml"
        if not xml_path.exists():
            missing += 1
            continue
        try:
            data = _parse_shp_xml(xml_path, ctrl=ctrl)
            if data:
                results[sym] = data
        except Exception as exc:
            log.warning(f"SHP extraction failed for {sym}: {exc}")
            failed += 1

    log.info(f"SHP loaded: {len(results)} OK  |  {missing} file-not-found  |  {failed} parse-errors")
    return results

# ============================================================================
# Unmatched report
# ============================================================================

UNMATCHED_REPORT = Path(__file__).parent / "unmatched_consolidation.md"


def _write_unmatched_report(
    records: List[Dict],
    cloud_crisil: Dict,
    cleaned: Dict,
    mca_lookup: Dict,
    shp_lookup: Dict,
) -> None:
    """
    Write a Markdown report of every mca_crisil_match document that could not
    be enriched from one or more data sources.

    Sections
    --------
    1. Missing from Cloud CRISIL (rating_reports)  – matched by companyCode
    2. Missing from cleaned_test.json              – matched by companyCode
    3. Missing MCA record                          – matched by CIN
    4. Missing NSE Shareholding file               – has nseSymbol but no SHP XML
    """
    # ----- collect misses per source -----
    no_crisil: List[Dict] = []
    no_cleaned: List[Dict] = []
    no_mca: List[Dict] = []
    no_shp: List[Dict] = []

    for rec in records:
        code   = rec.get("companyCode", "")
        cin    = rec.get("cin", "")
        symbol = rec.get("nseSymbol")
        cname  = rec.get("crisilName", "")
        mname  = rec.get("mcaName", "")

        base = {
            "companyCode":  code,
            "crisilName":   cname,
            "mcaName":      mname,
            "cin":          cin,
            "nseSymbol":    symbol or "",
            "nseMatchType": rec.get("nseMatchType", ""),
        }

        if code and code not in cloud_crisil:
            no_crisil.append(base)
        if code and code not in cleaned:
            no_cleaned.append(base)
        if cin and cin not in mca_lookup:
            no_mca.append({**base, "cin": cin})
        if symbol and symbol not in shp_lookup:
            no_shp.append({**base, "nseSymbol": symbol})

    # ----- helper to render a table -----
    def table(rows: List[Dict], cols: List[str]) -> str:
        if not rows:
            return "_None — all matched._\n"
        header = "| " + " | ".join(cols) + " |"
        sep    = "| " + " | ".join(["---"] * len(cols)) + " |"
        lines  = [header, sep]
        for r in rows:
            lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
        return "\n".join(lines) + "\n"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Consolidation Unmatched Report",
        f"",
        f"Generated: {now}  ",
        f"Source collection: `company/mca_crisil_match` ({len(records):,} documents)",
        f"",
        f"---",
        f"",
        f"## 1. Missing from Cloud CRISIL (`crisil_ratings/rating_reports`)",
        f"",
        f"Matched by `companyCode`. {len(no_crisil)} unmatched of {len(records)}.",
        f"",
        table(no_crisil, ["companyCode", "crisilName", "mcaName"]),
        f"",
        f"---",
        f"",
        f"## 2. Missing from `cleaned_test.json` (industry / ratings metadata)",
        f"",
        f"Matched by `companyCode`. {len(no_cleaned)} unmatched of {len(records)}.",
        f"",
        table(no_cleaned, ["companyCode", "crisilName", "mcaName"]),
        f"",
        f"---",
        f"",
        f"## 3. Missing MCA record (`company/mca data`)",
        f"",
        f"Matched by `cin`. {len(no_mca)} unmatched of {len(records)}.",
        f"",
        table(no_mca, ["companyCode", "crisilName", "cin"]),
        f"",
        f"---",
        f"",
        f"## 4. Missing NSE Shareholding XBRL",
        f"",
        f"Has `nseSymbol` but no corresponding XML in `shareholding/`. {len(no_shp)} unmatched.",
        f"",
        table(no_shp, ["companyCode", "crisilName", "nseSymbol", "nseMatchType"]),
    ]

    report_text = "\n".join(lines)
    with open(UNMATCHED_REPORT, "w", encoding="utf-8") as f:
        f.write(report_text)

    log.info(
        f"Unmatched report written to {UNMATCHED_REPORT}  "
        f"(CRISIL:{len(no_crisil)} | CleanedTest:{len(no_cleaned)} | "
        f"MCA:{len(no_mca)} | SHP:{len(no_shp)})"
    )


# ============================================================================
# Main consolidation
# ============================================================================

def run(dry_run: bool = False, skip_shp: bool = False) -> None:
    # ------------------------------------------------------------------
    # Load mca_crisil_match records
    # ------------------------------------------------------------------
    log.info("Loading mca_crisil_match documents …")
    local      = MongoClient(LOCAL_URI, directConnection=True)
    match_col  = local[LOCAL_DB][LOCAL_COL]

    records = list(match_col.find({}, {
        "_id": 1, "companyCode": 1, "crisilName": 1, "mcaName": 1,
        "cin": 1, "nseSymbol": 1, "nseMatchType": 1,
    }))
    log.info(f"mca_crisil_match: {len(records):,} documents")

    company_codes = {r["companyCode"] for r in records if r.get("companyCode")}
    cin_list      = [r["cin"] for r in records if r.get("cin")]
    nse_symbols   = [r["nseSymbol"] for r in records if r.get("nseSymbol")]

    # ------------------------------------------------------------------
    # Load all data sources
    # ------------------------------------------------------------------
    cloud_crisil = load_cloud_crisil(company_codes)
    cleaned      = load_cleaned_test(company_codes)
    mca_lookup   = load_mca_data(cin_list)
    shp_lookup   = _load_all_shp(nse_symbols) if not skip_shp else {}

    # ------------------------------------------------------------------
    # Build bulk update operations
    # ------------------------------------------------------------------
    log.info("Building update operations …")
    ops = []

    for rec in records:
        code   = rec.get("companyCode", "")
        cin    = rec.get("cin",        "")
        symbol = rec.get("nseSymbol")
        update: Dict[str, Any] = {}

        # ---- Source 1: Cloud CRISIL ----
        if code in cloud_crisil:
            cr = cloud_crisil[code]
            update["ratingDate"]     = cr.get("ratingDate")
            update["ratingFileName"] = cr.get("ratingFileName")
            update["crisilHeading"]  = cr.get("crisilHeading")
            update["instruments"]    = cr.get("instruments", [])
            update["bankFacilities"] = cr.get("bankFacilities", [])

        # ---- Source 2: cleaned_test.json ----
        if code in cleaned:
            ct = cleaned[code]
            update["industryName"]  = ct.get("industryName")
            update["industryCode"]  = ct.get("industryCode")
            update["crisilRatings"] = ct.get("crisilRatings", [])

        # ---- Source 3: MCA data ----
        if cin and cin in mca_lookup:
            mca = mca_lookup[cin]
            # Store all MCA fields not already represented in the schema
            update["mcaROCCode"]                = mca.get("CompanyROCcode")
            update["mcaCategory"]               = mca.get("CompanyCategory")
            update["mcaSubCategory"]            = mca.get("CompanySubCategory")
            update["mcaClass"]                  = mca.get("CompanyClass")
            update["mcaAuthorizedCapital"]      = mca.get("AuthorizedCapital")
            update["mcaPaidupCapital"]          = mca.get("PaidupCapital")
            update["mcaRegistrationDate"]       = mca.get("CompanyRegistrationdate_date")
            update["mcaAddress"]                = mca.get("Registered_Office_Address")
            update["mcaCompanyStatus"]          = mca.get("CompanyStatus")
            update["mcaStateCode"]              = mca.get("CompanyStateCode")
            update["mcaIndianForeign"]          = mca.get("CompanyIndian/Foreign Company")
            update["mcaIndustrialClassification"] = mca.get("CompanyIndustrialClassification")

        # ---- Source 4: NSE Shareholding ----
        if symbol and symbol in shp_lookup:
            shp = shp_lookup[symbol]
            update["shpTotalShares"]       = shp.get("totalShares")
            update["shpTotalShareholders"] = shp.get("totalShareholders")
            update["shareholdingPattern"]  = shp.get("shareholdingPattern")

        if update:
            ops.append(UpdateOne({"_id": rec["_id"]}, {"$set": update}))

    log.info(f"Built {len(ops):,} update operations")

    # ------------------------------------------------------------------
    # Stats breakdown
    # ------------------------------------------------------------------
    crisil_hits = sum(1 for r in records if r.get("companyCode", "") in cloud_crisil)
    ct_hits     = sum(1 for r in records if r.get("companyCode", "") in cleaned)
    mca_hits    = sum(1 for r in records if r.get("cin", "") in mca_lookup)
    shp_hits    = sum(1 for r in records if r.get("nseSymbol") in shp_lookup)

    log.info(
        f"Source coverage — "
        f"CloudCRISIL: {crisil_hits}/{len(records)}  | "
        f"CleanedTest: {ct_hits}/{len(records)}  | "
        f"MCA: {mca_hits}/{len(records)}  | "
        f"SHP: {shp_hits}/{len(records)}"
    )

    # ------------------------------------------------------------------
    # Write unmatched report
    # ------------------------------------------------------------------
    _write_unmatched_report(records, cloud_crisil, cleaned, mca_lookup, shp_lookup)

    if dry_run:
        log.info("DRY-RUN: no writes performed.")
        local.close()
        return

    # ------------------------------------------------------------------
    # Execute bulk write
    # ------------------------------------------------------------------
    if ops:
        result = match_col.bulk_write(ops, ordered=False)
        log.info(
            f"Bulk write complete — "
            f"matched: {result.matched_count:,}  "
            f"modified: {result.modified_count:,}"
        )
    else:
        log.info("No update operations to write.")

    local.close()
    log.info("Done.")


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consolidate CRISIL, MCA, and NSE SHP data into mca_crisil_match."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the full pipeline without writing to MongoDB."
    )
    parser.add_argument(
        "--skip-shp", action="store_true",
        help="Skip NSE shareholding XBRL extraction (much faster)."
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, skip_shp=args.skip_shp)
