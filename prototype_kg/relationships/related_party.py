"""
prototype_kg/relationships/related_party.py
Build consolidated RELATED_PARTY edges from RPT data in bank documents.

This module creates ONE edge per (counterparty, bank) pair with aggregated
financial metrics and stress weights. Consolidates functionality previously
split between RELATED_PARTY and SUBSIDIARY_OF.

Edge directions:
  - Company → Bank: (:Company)-[:RELATED_PARTY]->(:Bank)
  - Bank → Bank:    (:Bank)-[:RELATED_PARTY]->(:Bank)

Filtering rules:
1. Only counter-parties whose name contains at least one CORPORATE_KEYWORD
   (eliminates individual directors / executives).
2. Counter-party resolves to a target Bank → create (:Bank)-[:RELATED_PARTY]->(:Bank).
3. Counter-party resolves to a Company → use existing :Company node (matched by CIN).
4. Unresolved → create placeholder :Company stub (cin = synthetic RPT code,
   resolved=false) and store top-3 fuzzy candidates for manual review.

Financial metrics (for Company → Bank edges):
  - netOutstandingUpCrores:   cash INTO bank from company (in crores)
  - netOutstandingDownCrores: cash OUT OF bank to company (in crores)
  - stressWeightUp:   netOutstandingUpCrores / tier1CapitalCrores
                      (upward contagion risk: company default hurts bank)
  - stressWeightDown: utilization ratio [0-1]
                      (downward dependency: company relies on bank)
  - contingentExposureCrores: off-balance-sheet commitments
"""

from __future__ import annotations

from collections import defaultdict, Counter

from neo4j import Driver
from config import CORPORATE_KEYWORDS
from resolution.entity_resolver import GlobalEntityRegistry


# ---------------------------------------------------------------------------
# Transaction direction classification (copied from subsidiary_of.py)
# ---------------------------------------------------------------------------

_CASH_IN_TYPES: frozenset[str] = frozenset({
    "sale of goods or services",
})

_CASH_IN_DETAILS: frozenset[str] = frozenset({
    "interest income",
    "other income",
    "profit/loss on sale of investments",
    "dividend income",
    "dividend received",
})

_CASH_OUT_TYPES: frozenset[str] = frozenset({
    "purchase of goods or services",
    "purchase of fixed assets",
})

_CASH_OUT_DETAILS: frozenset[str] = frozenset({
    "it support charges",
    "management fees",
    "remuneration",
    "salary",
    "fees paid",
    "charges paid",
    "subscription",
})

_CONTINGENT_DETAIL = "non fund commitment"


def _classify_transaction(txn_type: str, details: str) -> str:
    """Return 'cash_in', 'cash_out', 'contingent', or 'unknown'."""
    t = txn_type.lower().strip()
    d = details.lower().strip()

    # Contingent takes priority — check details first regardless of type
    if d == _CONTINGENT_DETAIL:
        return "contingent"
    if t in _CASH_IN_TYPES:
        return "cash_in"
    if t in _CASH_OUT_TYPES:
        return "cash_out"
    # "Any other transaction" — dispatch by details
    if d in _CASH_IN_DETAILS:
        return "cash_in"
    if d in _CASH_OUT_DETAILS:
        return "cash_out"
    return "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_corporate_entity(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in CORPORATE_KEYWORDS)


def _safe_number(val) -> float:
    """Handle MongoDB $numberLong dicts and plain numerics."""
    if isinstance(val, dict) and "$numberLong" in val:
        return float(val["$numberLong"])
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _extract_tier1_capital(bank_docs: list[dict]) -> dict[str, float]:
    """Return {bankSymbol: tier1CapitalCrores} mapping."""
    tier1_map = {}
    for doc in bank_docs:
        symbol = doc.get("bankSymbol")
        t1_data = doc.get("tier1Capital", {})
        if symbol and isinstance(t1_data, dict) and "tier1CapitalCrores" in t1_data:
            try:
                tier1_map[symbol] = float(t1_data["tier1CapitalCrores"])
            except (TypeError, ValueError):
                pass
    return tier1_map


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
# Cypher — RELATED_PARTY edge: Company → Bank (NEW DIRECTION)
# ---------------------------------------------------------------------------

MERGE_RPT_COMPANY_TO_BANK = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.cin})
MATCH (b:Bank {bankSymbol: row.bankSymbol})
MERGE (c)-[r:RELATED_PARTY]->(b)
SET r.relationships               = row.relationships,
    r.primaryRelationship         = row.primaryRelationship,
    r.netOutstandingUpCrores      = row.netOutstandingUpCrores,
    r.netOutstandingDownCrores    = row.netOutstandingDownCrores,
    r.stressWeightUp              = row.stressWeightUp,
    r.stressWeightDown            = row.stressWeightDown,
    r.contingentExposureCrores    = row.contingentExposureCrores,
    r.hasContingentExposure       = row.hasContingentExposure,
    r.transactionCount            = row.transactionCount,
    r.reportingPeriods            = row.reportingPeriods,
    r.source                      = 'Integrated_XBRL'
"""

# ---------------------------------------------------------------------------
# Cypher — RELATED_PARTY edge: Bank → Bank (SAME DIRECTION, no stress weights)
# ---------------------------------------------------------------------------

MERGE_RPT_BANK_TO_BANK = """
UNWIND $batch AS row
MATCH (b1:Bank {bankSymbol: row.fromBankSymbol})
MATCH (b2:Bank {bankSymbol: row.toBankSymbol})
MERGE (b1)-[r:RELATED_PARTY]->(b2)
SET r.relationships               = row.relationships,
    r.primaryRelationship         = row.primaryRelationship,
    r.netOutstandingUpCrores      = row.netOutstandingUpCrores,
    r.netOutstandingDownCrores    = row.netOutstandingDownCrores,
    r.contingentExposureCrores    = row.contingentExposureCrores,
    r.hasContingentExposure       = row.hasContingentExposure,
    r.transactionCount            = row.transactionCount,
    r.reportingPeriods            = row.reportingPeriods,
    r.source                      = 'Integrated_XBRL'
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
    Build consolidated RELATED_PARTY edges from RPT data in bank documents.

    Creates ONE edge per (counterparty, bank) pair with aggregated financial
    metrics and stress weights. All transactions for a given pair are
    consolidated before computing metrics.

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
    company_to_bank_edges:  list[dict] = []
    bank_to_bank_edges:     list[dict] = []

    resolved_company_count = 0
    resolved_bank_count    = 0
    unresolved_count       = 0
    skipped_count          = 0

    # Extract tier1Capital for all banks (for stress weight calculations)
    tier1_capital_map = _extract_tier1_capital(bank_docs)

    for doc in bank_docs:
        bank_symbol      = doc.get("bankSymbol")
        rpt_data         = doc.get("relatedPartyTransactions", {})
        transactions     = rpt_data.get("relatedPartyTransactions", [])
        reporting_period = rpt_data.get("reportingPeriod", {}).get("quarter", "")

        if not bank_symbol:
            continue

        tier1_crores = tier1_capital_map.get(bank_symbol)

        # ── Aggregate transactions by (counterparty, bank) pair ──────────────
        # Separate aggregation for Company and Bank counterparties
        agg_company: dict[tuple[str, str], dict] = defaultdict(lambda: {
            "relationships_set":      set(),
            "relationship_counter":   Counter(),
            "cash_in_outstanding":    0.0,
            "cash_out_outstanding":   0.0,
            "cash_out_approved":      0.0,
            "contingent_outstanding": 0.0,
            "transaction_count":      0,
            "reporting_periods_set":  set(),
        })

        agg_bank: dict[tuple[str, str], dict] = defaultdict(lambda: {
            "relationships_set":      set(),
            "relationship_counter":   Counter(),
            "cash_in_outstanding":    0.0,
            "cash_out_outstanding":   0.0,
            "cash_out_approved":      0.0,  # Not used for stress weights but needed for aggregation
            "contingent_outstanding": 0.0,
            "transaction_count":      0,
            "reporting_periods_set":  set(),
        })

        # Track unresolved entities per bank
        unresolved_this_bank: dict[str, str] = {}  # dedup_key → cin

        for txn in transactions:
            cp           = txn.get("counterParty", {})
            cp_name      = (cp.get("name") or "").strip()

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
            txn_details  = txn_info.get("details", "Unknown")
            outstanding  = _safe_number(txn_info.get("outstandingCurrentPeriod", 0))
            approved     = _safe_number(txn_info.get("approvedValue", 0))

            # Classify transaction direction
            direction = _classify_transaction(txn_type, txn_details)

            # Resolve counterparty via GER
            node_type, canonical_id, confidence, candidates = \
                registry.resolve_with_candidates(cp_name)

            if node_type == "Bank":
                # Bank-to-bank RPT — skip self-loops
                if canonical_id == bank_symbol:
                    skipped_count += 1
                    continue

                resolved_bank_count += 1
                key = (bank_symbol, canonical_id)  # (from_bank, to_bank)
                bucket = agg_bank[key]

            elif node_type == "Company":
                resolved_company_count += 1
                key = (canonical_id, bank_symbol)  # (company_cin, bank_symbol)
                bucket = agg_company[key]

            else:
                # Unresolved — create placeholder :Company stub
                dedup_key = f"{bank_symbol}::{cp_name.lower()}"
                if dedup_key in unresolved_this_bank:
                    cin = unresolved_this_bank[dedup_key]
                elif dedup_key in unresolved_name_to_cin:
                    cin = unresolved_name_to_cin[dedup_key]
                else:
                    unresolved_seq += 1
                    cin = f"{RPT_PREFIX}{bank_symbol}_{unresolved_seq:04d}"
                    unresolved_name_to_cin[dedup_key] = cin
                    unresolved_this_bank[dedup_key] = cin
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

                key = (cin, bank_symbol)
                bucket = agg_company[key]

            # Accumulate into bucket
            bucket["relationships_set"].add(relationship)
            bucket["relationship_counter"][relationship] += 1
            bucket["transaction_count"] += 1
            if reporting_period:
                bucket["reporting_periods_set"].add(reporting_period)

            if direction == "cash_in":
                bucket["cash_in_outstanding"] += outstanding
            elif direction == "cash_out":
                bucket["cash_out_outstanding"] += outstanding
                bucket["cash_out_approved"] += approved
            elif direction == "contingent":
                bucket["contingent_outstanding"] += outstanding
            # "unknown" → excluded from weight calculations

        # ── Build edge records for Company → Bank ────────────────────────────
        skipped_no_tier1: list[tuple[str, str]] = []  # (cin, primary_rel)

        for (cin, bsymbol), bucket in agg_company.items():
            # Convert rupees → crores
            net_up     = bucket["cash_in_outstanding"]    / 1e7
            net_down   = bucket["cash_out_outstanding"]   / 1e7
            contingent = bucket["contingent_outstanding"] / 1e7

            # stressWeightUp = upward contagion risk
            if tier1_crores and tier1_crores > 0:
                stress_up: float | None = round(net_up / tier1_crores, 8)
            else:
                stress_up = None
                if net_up > 0:
                    primary_rel = bucket["relationship_counter"].most_common(1)[0][0]
                    skipped_no_tier1.append((cin, primary_rel))

            # stressWeightDown = downward dependency (utilization ratio)
            if bucket["cash_out_approved"] > 0:
                stress_down: float | None = round(
                    min(bucket["cash_out_outstanding"] / bucket["cash_out_approved"], 1.0),
                    6,
                )
            else:
                stress_down = None

            # Multiple relationship types
            relationships_list = sorted(bucket["relationships_set"])
            primary_relationship = bucket["relationship_counter"].most_common(1)[0][0]

            company_to_bank_edges.append({
                "cin":                      cin,
                "bankSymbol":               bsymbol,
                "relationships":            relationships_list,
                "primaryRelationship":      primary_relationship,
                "netOutstandingUpCrores":   round(net_up, 4),
                "netOutstandingDownCrores": round(net_down, 4),
                "stressWeightUp":           stress_up,
                "stressWeightDown":         stress_down,
                "contingentExposureCrores": round(contingent, 4) if contingent > 0 else None,
                "hasContingentExposure":    contingent > 0,
                "transactionCount":         bucket["transaction_count"],
                "reportingPeriods":         sorted(bucket["reporting_periods_set"]),
            })

        if skipped_no_tier1:
            print(
                f"[related_party] {bank_symbol}: stressWeightUp not computed for "
                f"{len(skipped_no_tier1)} counter-party/ies (tier1Capital missing)."
            )

        # ── Build edge records for Bank → Bank ───────────────────────────────
        for (from_bank, to_bank), bucket in agg_bank.items():
            # Convert rupees → crores (no stress weights for bank-to-bank)
            net_up     = bucket["cash_in_outstanding"]    / 1e7
            net_down   = bucket["cash_out_outstanding"]   / 1e7
            contingent = bucket["contingent_outstanding"] / 1e7

            relationships_list = sorted(bucket["relationships_set"])
            primary_relationship = bucket["relationship_counter"].most_common(1)[0][0]

            bank_to_bank_edges.append({
                "fromBankSymbol":           from_bank,
                "toBankSymbol":             to_bank,
                "relationships":            relationships_list,
                "primaryRelationship":      primary_relationship,
                "netOutstandingUpCrores":   round(net_up, 4),
                "netOutstandingDownCrores": round(net_down, 4),
                "contingentExposureCrores": round(contingent, 4) if contingent > 0 else None,
                "hasContingentExposure":    contingent > 0,
                "transactionCount":         bucket["transaction_count"],
                "reportingPeriods":         sorted(bucket["reporting_periods_set"]),
            })

    # ── Write to Neo4j ────────────────────────────────────────────────────────
    BATCH_SIZE = 200

    company_list = list(company_records.values())
    with driver.session() as session:
        # Create company stubs
        for i in range(0, len(company_list), BATCH_SIZE):
            session.run(MERGE_RPT_COMPANY, batch=company_list[i : i + BATCH_SIZE])

        # Create Company → Bank edges
        for i in range(0, len(company_to_bank_edges), BATCH_SIZE):
            session.run(MERGE_RPT_COMPANY_TO_BANK, batch=company_to_bank_edges[i : i + BATCH_SIZE])

        # Create Bank → Bank edges
        for i in range(0, len(bank_to_bank_edges), BATCH_SIZE):
            session.run(MERGE_RPT_BANK_TO_BANK, batch=bank_to_bank_edges[i : i + BATCH_SIZE])

    print(
        f"[related_party] Resolved: company={resolved_company_count}, "
        f"bank={resolved_bank_count} | "
        f"Unresolved stubs={unresolved_count} | Skipped (non-corporate)={skipped_count}"
    )
    print(f"[related_party] Edges: Company→Bank={len(company_to_bank_edges)}, "
          f"Bank→Bank={len(bank_to_bank_edges)}")

    return {
        "resolved_company": resolved_company_count,
        "resolved_bank":    resolved_bank_count,
        "unresolved":       unresolved_count,
        "skipped":          skipped_count,
    }
