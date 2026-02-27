"""
prototype_kg/nodes/company_node.py
Create or merge :Company nodes in Neo4j.

Primary key: `cin`  (every company has a CIN; synthetic ones have dummyCIN=true)
Primary data: financial_kg/company collection (rich MCA + CRISIL consolidated docs).

Node properties (trimmed to essentials):
  cin, companyCode, crisilName, mcaName, nicCode, nseSymbol,
  industryCode, industryName, ratingDate, mcaIndustrialClassification, dummyCIN,
  shpTotalShares, shpTotalShareholders

Returns:
  (count, industry_code_map)
  industry_code_map : {cin: industryCode}  — consumed by belongs_to.py
"""

from neo4j import Driver


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


# ---------------------------------------------------------------------------
# Neo4j upsert query
# ---------------------------------------------------------------------------

_UPSERT_COMPANY = """
UNWIND $batch AS row
MERGE (c:Company {cin: row.cin})
ON CREATE SET
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
    c.shpTotalShareholders        = row.shpTotalShareholders
ON MATCH SET
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
    c.shpTotalShareholders        = CASE WHEN row.shpTotalShareholders > 0 THEN row.shpTotalShareholders ELSE c.shpTotalShareholders END
"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_company_nodes(
    driver: Driver,
    bank_docs: list[dict],      # kept for signature compatibility; not used for key lookup
    company_docs: list[dict],
) -> tuple[int, dict[str, str]]:
    """
    Upsert :Company nodes from the company collection, keyed by CIN.

    Args:
        driver       : Neo4j driver
        bank_docs    : unused here (kept for loader.py signature compatibility)
        company_docs : documents from financial_kg/company

    Returns:
        count             : total :Company nodes upserted
        industry_code_map : {cin: industryCode} for belongs_to.py
    """
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

