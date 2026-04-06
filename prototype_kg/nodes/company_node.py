"""
prototype_kg/nodes/company_node.py
Create or merge :Company nodes in Neo4j.

Primary key: `cin`  (every company has a CIN; synthetic ones have dummyCIN=true)
Primary data: financial_kg/company collection (rich MCA + CRISIL consolidated docs).

Node properties (trimmed to essentials):
  cin, companyCode, crisilName, mcaName, nicCode, nseSymbol,
  industryCode, industryName, ratingDate, mcaIndustrialClassification, dummyCIN,
  shpTotalShares, shpTotalShareholders, stress

Returns:
  (count, industry_code_map)
  industry_code_map : {cin: industryCode}  — consumed by belongs_to.py
"""

from neo4j import Driver
from config import get_macro_sector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_str(val) -> str:
    return str(val).strip() if val is not None else ""


def _safe_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val) if val is not None else False


def _safe_int(val) -> int:
    """Coerce a value to int; handles MongoDB $numberLong dicts."""
    if isinstance(val, dict) and "$numberLong" in val:
        try:
            return int(val["$numberLong"])
        except (TypeError, ValueError):
            return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _safe_float(val) -> float | None:
    """Coerce value to float; returns None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _calculate_company_stress(doc: dict, sector_stress_map: dict[str, float]) -> float | None:
    """
    Calculate company stress with dynamic weighting:
    
    Base formula: 0.7 * entity_stress_fundamental + 0.2 * news_stress + 0.1 * sector_stress
    
    Dynamic weighting when components are missing:
    - If sector_stress missing:    0.8 * entity_stress + 0.2 * news_stress
    - If news_stress missing:      0.8 * entity_stress + 0.2 * sector_stress
    - If both missing:             1.0 * entity_stress
    - If entity_stress missing:    return None (required component)
    
    Args:
        doc: Company document from MongoDB
        sector_stress_map: Mapping of macro_sector -> final_stress_score
        
    Returns:
        Calculated stress score or None if entity_stress_fundamental is missing
    """
    # Get entity stress fundamental (required component)
    entity_fundamental = doc.get("entity_stress_fundamental")
    if entity_fundamental is None:
        return None
    
    entity_val = _safe_float(entity_fundamental)
    if entity_val is None:
        return None
    
    # Convert entity_fundamental from percentage to decimal
    entity_stress = entity_val / 100.0
    
    # Get news stress (optional)
    news_stress = _safe_float(doc.get("news_stress"))
    
    # Get sector stress (optional) - map industryName to macro_sector
    sector_stress = None
    industry_name = doc.get("industryName")
    if industry_name:
        macro_sector = get_macro_sector(industry_name)
        if macro_sector and macro_sector in sector_stress_map:
            sector_stress = sector_stress_map[macro_sector]
    
    # Dynamic weighting based on available components
    if news_stress is not None and sector_stress is not None:
        # All components available: 0.7 entity + 0.2 news + 0.1 sector
        return 0.7 * entity_stress + 0.2 * news_stress + 0.1 * sector_stress
    elif news_stress is not None:
        # News available, sector missing: 0.8 entity + 0.2 news
        return 0.8 * entity_stress + 0.2 * news_stress
    elif sector_stress is not None:
        # Sector available, news missing: 0.8 entity + 0.2 sector
        return 0.8 * entity_stress + 0.2 * sector_stress
    else:
        # Only entity available: use full weight
        return entity_stress


# ---------------------------------------------------------------------------
# Neo4j upsert query
# ---------------------------------------------------------------------------

_UPSERT_COMPANY = """
UNWIND $batch AS row
MERGE (c:Company {cin: row.cin})
ON CREATE SET
    c.name                        = CASE WHEN row.crisilName <> '' THEN row.crisilName ELSE row.cin END,
    c.displayName                 = CASE WHEN row.crisilName <> '' THEN row.crisilName ELSE row.cin END,
    c.companyCode                 = row.companyCode,
    c.crisilName                  = row.crisilName,
    c.mcaName                     = row.mcaName,
    c.nicCode                     = row.nicCode,
    c.nseSymbol                   = row.nseSymbol,
    c.industryCode                = row.industryCode,
    c.industryName                = row.industryName,
    c.ratingDate                  = row.ratingDate,
    c.mcaIndustrialClassification = row.mcaIndustrialClassification,
    c.dummyCIN                    = row.dummyCIN,
    c.shpTotalShares              = row.shpTotalShares,
    c.shpTotalShareholders        = row.shpTotalShareholders,
    c.stress                      = row.stress
ON MATCH SET
    c.name                        = CASE WHEN row.crisilName <> '' THEN row.crisilName ELSE coalesce(c.crisilName, c.name, c.cin, row.cin) END,
    c.displayName                 = CASE WHEN row.crisilName <> '' THEN row.crisilName ELSE coalesce(c.crisilName, c.displayName, c.cin, row.cin) END,
    c.companyCode                 = CASE WHEN row.companyCode <> ''  THEN row.companyCode  ELSE c.companyCode  END,
    c.crisilName                  = CASE WHEN row.crisilName <> ''   THEN row.crisilName   ELSE c.crisilName   END,
    c.mcaName                     = CASE WHEN row.mcaName <> ''      THEN row.mcaName      ELSE c.mcaName      END,
    c.nicCode                     = CASE WHEN row.nicCode <> ''      THEN row.nicCode      ELSE c.nicCode      END,
    c.nseSymbol                   = CASE WHEN row.nseSymbol <> ''    THEN row.nseSymbol    ELSE c.nseSymbol    END,
    c.industryCode                = CASE WHEN row.industryCode <> '' THEN row.industryCode ELSE c.industryCode END,
    c.industryName                = CASE WHEN row.industryName <> '' THEN row.industryName ELSE c.industryName END,
    c.ratingDate                  = CASE WHEN row.ratingDate <> ''   THEN row.ratingDate   ELSE c.ratingDate   END,
    c.mcaIndustrialClassification = CASE WHEN row.mcaIndustrialClassification <> '' THEN row.mcaIndustrialClassification ELSE c.mcaIndustrialClassification END,
    c.dummyCIN                    = CASE WHEN row.dummyCIN THEN true ELSE c.dummyCIN END,
    c.shpTotalShares              = CASE WHEN row.shpTotalShares > 0 THEN row.shpTotalShares ELSE c.shpTotalShares END,
    c.shpTotalShareholders        = CASE WHEN row.shpTotalShareholders > 0 THEN row.shpTotalShareholders ELSE c.shpTotalShareholders END,
    c.stress                      = CASE WHEN row.stress IS NOT NULL THEN row.stress ELSE c.stress END
"""
# NOTE: isStub and nodeSource are intentionally NOT set in _UPSERT_COMPANY.
# They are managed exclusively by _MERGE_LENDER_STUB in lends_to.py (ON CREATE only),
# so a real company node is never accidentally marked as a stub, and a stub's
# isStub/nodeSource flags survive subsequent MERGE calls from this upsert.


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_company_nodes(
    driver: Driver,
    bank_docs: list[dict],      # kept for signature compatibility; not used for key lookup
    company_docs: list[dict],
    sector_stress_map: dict[str, float] | None = None,
) -> tuple[int, dict[str, str]]:
    """
    Upsert :Company nodes from the company collection, keyed by CIN.

    Args:
        driver            : Neo4j driver
        bank_docs         : unused here (kept for loader.py signature compatibility)
        company_docs      : documents from financial_kg/company
        sector_stress_map : mapping of macro_sector -> final_stress_score (optional)

    Returns:
        count             : total :Company nodes upserted
        industry_code_map : {cin: industryCode} for belongs_to.py
    """
    if sector_stress_map is None:
        sector_stress_map = {}
    
    records: list[dict] = []
    industry_code_map: dict[str, str] = {}

    for doc in company_docs:
        cin = _safe_str(doc.get("cin"))
        if not cin:
            # Skip docs with no CIN — they cannot be merged safely
            continue

        company_code   = _safe_str(doc.get("companyCode"))
        crisil_name    = _safe_str(doc.get("crisilName"))
        mca_name       = _safe_str(doc.get("mcaName"))
        nic_code       = _safe_str(doc.get("nicCode"))
        nse_symbol     = _safe_str(doc.get("nseSymbol"))
        industry_code  = _safe_str(doc.get("industryCode"))
        industry_name  = _safe_str(doc.get("industryName"))
        rating_date    = _safe_str(doc.get("ratingDate"))
        mca_ind_class  = _safe_str(doc.get("mcaIndustrialClassification"))
        dummy_cin      = _safe_bool(doc.get("dummyCIN"))

        # SHP totals — prefer top-level shpTotal* fields; fall back to
        # shareholdingPattern.totalShares / totalShareholders if present
        shp            = doc.get("shareholdingPattern") or {}
        shp_total_shares = _safe_int(
            doc.get("shpTotalShares") or shp.get("totalShares")
        )
        shp_total_sh   = _safe_int(
            doc.get("shpTotalShareholders") or shp.get("totalShareholders")
        )

        # Calculate company stress with entity, news, and sector components
        stress_score = _calculate_company_stress(doc, sector_stress_map)

        if industry_code:
            industry_code_map[cin] = industry_code

        records.append({
            "cin":                        cin,
            "companyCode":                company_code,
            "crisilName":                 crisil_name,
            "mcaName":                    mca_name,
            "nicCode":                    nic_code,
            "nseSymbol":                  nse_symbol,
            "industryCode":               industry_code,
            "industryName":               industry_name,
            "ratingDate":                 rating_date,
            "mcaIndustrialClassification": mca_ind_class,
            "dummyCIN":                   dummy_cin,
            "shpTotalShares":             shp_total_shares,
            "shpTotalShareholders":       shp_total_sh,
            "stress":                     stress_score,
        })

    BATCH_SIZE = 500
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            session.run(_UPSERT_COMPANY, batch=records[i : i + BATCH_SIZE])

    count = len(records)
    dummy_count = sum(1 for r in records if r["dummyCIN"])
    print(f"[company_node] Upserted {count} :Company node(s) "
          f"({dummy_count} with synthetic/dummy CIN).")
    print(f"[company_node]   → {len(industry_code_map)} with CRISIL industryCode (for BELONGS_TO).")
    return count, industry_code_map

