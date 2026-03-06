"""
prototype_kg/relationships/related_party.py
Build RELATED_PARTY edges from RPT data in bank documents.

Filtering rules:
1. Only counter-parties whose name contains at least one CORPORATE_KEYWORD
   (eliminates individual directors / executives).
2. Counter-party resolves to a target Bank → create (:Bank)-[:RELATED_PARTY]->(:Bank).
3. Counter-party resolves to a Company → use existing :Company node (matched by CIN).
4. Unresolved → create placeholder :Company stub (cin = synthetic RPT code,
   resolved=false) and store top-3 fuzzy candidates for manual review.
"""

from __future__ import annotations

from neo4j import Driver
from config import CORPORATE_KEYWORDS
from resolution.entity_resolver import GlobalEntityRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_corporate_entity(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in CORPORATE_KEYWORDS)


def _safe_number(val) -> float:
    if isinstance(val, dict) and "$numberLong" in val:
        return float(val["$numberLong"])
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Cypher — company stub upsert (for unresolved RPT counterparties)
# ---------------------------------------------------------------------------

MERGE_RPT_COMPANY = """
UNWIND $batch AS row
MERGE (c:Company {cin: row.cin})
ON CREATE SET
    c.crisilName    = row.companyName,
    c.resolved      = false,
    c.topCandidates = row.topCandidates
ON MATCH SET
    c.resolved = false
"""

# ---------------------------------------------------------------------------
# Cypher — RELATED_PARTY edge: Bank → Company
# ---------------------------------------------------------------------------

MERGE_RPT_BANK_TO_COMPANY = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.bankSymbol})
MATCH (c:Company {cin: row.cin})
MERGE (b)-[r:RELATED_PARTY {
    relationship:    row.relationship,
    transactionType: row.transactionType,
    reportingPeriod: row.reportingPeriod
}]->(c)
SET r.actualAmount = row.actualAmount,
    r.source       = 'Integrated_XBRL'
"""

# ---------------------------------------------------------------------------
# Cypher — RELATED_PARTY edge: Bank → Bank
# ---------------------------------------------------------------------------

MERGE_RPT_BANK_TO_BANK = """
UNWIND $batch AS row
MATCH (b1:Bank {bankSymbol: row.bankSymbol})
MATCH (b2:Bank {bankSymbol: row.targetBankSymbol})
MERGE (b1)-[r:RELATED_PARTY {
    relationship:    row.relationship,
    transactionType: row.transactionType,
    reportingPeriod: row.reportingPeriod
}]->(b2)
SET r.actualAmount = row.actualAmount,
    r.source       = 'Integrated_XBRL'
"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_related_party(
    driver: Driver,
    bank_docs: list[dict],
    registry: GlobalEntityRegistry,
) -> dict[str, int]:
    """
    Build RELATED_PARTY edges from RPT data in bank documents.

    Args:
        driver   : Neo4j driver
        bank_docs: consolidated bank documents
        registry : GlobalEntityRegistry for resolving counterparty names

    Returns:
        {'resolved_company': N, 'resolved_bank': B, 'unresolved': M, 'skipped': K}
    """
    RPT_PREFIX = "RPT_"
    unresolved_name_to_cin: dict[str, str] = {}   # dedup key → synthetic CIN
    unresolved_seq = 0

    company_records: dict[str, dict] = {}   # cin → stub record
    bank_to_company_edges:  list[dict] = []
    bank_to_bank_edges:     list[dict] = []

    resolved_company_count = 0
    resolved_bank_count    = 0
    unresolved_count       = 0
    skipped_count          = 0

    for doc in bank_docs:
        bank_symbol      = doc.get("bankSymbol")
        rpt_data         = doc.get("relatedPartyTransactions", {})
        transactions     = rpt_data.get("relatedPartyTransactions", [])
        reporting_period = rpt_data.get("reportingPeriod", {}).get("quarter", "")

        for txn in transactions:
            cp      = txn.get("counterParty", {})
            cp_name = (cp.get("name") or "").strip()

            if not cp_name:
                skipped_count += 1
                continue

            # Filter: must look like a company (eliminates individuals)
            if not _is_corporate_entity(cp_name):
                skipped_count += 1
                continue

            relationship = cp.get("relationship", "Unknown")
            txn_info     = txn.get("transaction", {})
            txn_type     = txn_info.get("type", "Unknown")
            actual_amt   = _safe_number(txn_info.get("actualAmount", 0))

            edge_base = {
                "bankSymbol":      bank_symbol,
                "relationship":    relationship,
                "transactionType": txn_type,
                "actualAmount":    actual_amt,
                "reportingPeriod": reporting_period,
            }

            # Resolve counterparty via GER
            node_type, canonical_id, confidence, candidates = \
                registry.resolve_with_candidates(cp_name)

            if node_type == "Bank":
                # Bank-to-bank RPT — create Bank→Bank edge
                if canonical_id != bank_symbol:   # skip self-loop
                    bank_to_bank_edges.append({
                        **edge_base,
                        "targetBankSymbol": canonical_id,
                    })
                resolved_bank_count += 1

            elif node_type == "Company":
                bank_to_company_edges.append({**edge_base, "cin": canonical_id})
                resolved_company_count += 1

            else:
                # Unresolved — create placeholder :Company stub
                dedup_key = f"{bank_symbol}::{cp_name.lower()}"
                if dedup_key in unresolved_name_to_cin:
                    cin = unresolved_name_to_cin[dedup_key]
                else:
                    unresolved_seq += 1
                    cin = f"{RPT_PREFIX}{bank_symbol}_{unresolved_seq:04d}"
                    unresolved_name_to_cin[dedup_key] = cin
                    top_cands = [
                        f"{c['normalizedName']}:{c.get('cin', '')}:{c['score']}"
                        for c in candidates
                    ]
                    company_records[cin] = {
                        "cin":           cin,
                        "companyName":   cp_name,
                        "topCandidates": top_cands,
                    }
                    unresolved_count += 1

                bank_to_company_edges.append({**edge_base, "cin": cin})

    BATCH_SIZE = 200

    company_list = list(company_records.values())
    with driver.session() as session:
        for i in range(0, len(company_list), BATCH_SIZE):
            session.run(MERGE_RPT_COMPANY, batch=company_list[i : i + BATCH_SIZE])
        for i in range(0, len(bank_to_company_edges), BATCH_SIZE):
            session.run(MERGE_RPT_BANK_TO_COMPANY, batch=bank_to_company_edges[i : i + BATCH_SIZE])
        for i in range(0, len(bank_to_bank_edges), BATCH_SIZE):
            session.run(MERGE_RPT_BANK_TO_BANK, batch=bank_to_bank_edges[i : i + BATCH_SIZE])

    print(
        f"[related_party] Resolved: company={resolved_company_count}, "
        f"bank={resolved_bank_count} | "
        f"Unresolved stubs={unresolved_count} | Skipped (non-corporate)={skipped_count}"
    )
    print(f"[related_party] Edges: Bank→Company={len(bank_to_company_edges)}, "
          f"Bank→Bank={len(bank_to_bank_edges)}")

    return {
        "resolved_company": resolved_company_count,
        "resolved_bank":    resolved_bank_count,
        "unresolved":       unresolved_count,
        "skipped":          skipped_count,
    }
