"""
prototype_kg/relationships/subsidiary_of.py
Build (:Company)-[:SUBSIDIARY_OF]->(:Bank) edges with consolidated stress weights.

Source: relatedPartyTransactions in each bank document.
Any RPT counter-party whose `relationship` field contains "subsidiary" or
"associate" (case-insensitive) and that resolves to a :Company node via the
GlobalEntityRegistry is considered a related-party entity.

All RPT transactions for a (subsidiary, bank) pair are consolidated into ONE
edge.  Three financial weight properties are computed:

  stressWeightUp   — Sub→Bank cash-flow exposure / Bank Tier 1 Capital
                     "How much does a sub default hurt the bank?"
                     = sum(outstandingCurrentPeriod, cash_in txns in crores)
                       / tier1CapitalCrores

  stressWeightDown — Bank→Sub utilization ratio [0–1]
                     "How dependent is the sub on this relationship?"
                     = sum(outstandingCurrentPeriod, cash_out txns)
                       / sum(approvedValue, cash_out txns)
                     (clamped to 1.0; None if approvedValue sum is zero)

  contingentExposureCrores — Off-balance-sheet guarantees / LCs / BGs
                     = sum(outstandingCurrentPeriod, "Non Fund Commitment") / 1e7
                     Only stored when > 0; hasContingentExposure flag set accordingly.

Transaction direction (always from the LISTED BANK's perspective):
  cash_in   → money flows INTO bank from sub
              types:   "Sale of goods or services"
              details: "Interest Income", "Other Income",
                       "Profit/Loss on sale of investments", "Dividend Income"
  cash_out  → money flows OUT OF bank to sub
              types:   "Purchase of goods or services", "Purchase of fixed assets"
              details: "IT Support Charges", "Management Fees", "Remuneration",
                       "Fees Paid"
  contingent → off-balance-sheet commitments
              details: "Non Fund Commitment" (regardless of type)
  unknown   → excluded from weight calculations; edge still created
"""

from __future__ import annotations

from collections import defaultdict

from neo4j import Driver
from resolution.entity_resolver import GlobalEntityRegistry


# ── Relationship filter ───────────────────────────────────────────────────────

_SUBSIDIARY_KEYWORDS = {"subsidiary", "associate", "subsidiar"}


def _is_subsidiary_relationship(relationship: str) -> bool:
    lower = relationship.lower()
    return any(kw in lower for kw in _SUBSIDIARY_KEYWORDS)


# ── Transaction direction classification ─────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_number(val) -> float:
    """Handle MongoDB $numberLong dicts and plain numerics."""
    if isinstance(val, dict) and "$numberLong" in val:
        return float(val["$numberLong"])
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ── Cypher ────────────────────────────────────────────────────────────────────

MERGE_SUBSIDIARY_OF = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.cin})
MATCH (b:Bank {bankSymbol: row.parentBankSymbol})
MERGE (c)-[r:SUBSIDIARY_OF]->(b)
SET r.relationship              = row.relationship,
    r.source                    = 'Integrated_XBRL',
    r.netOutstandingUpCrores    = row.netOutstandingUpCrores,
    r.netOutstandingDownCrores  = row.netOutstandingDownCrores,
    r.stressWeightUp            = row.stressWeightUp,
    r.stressWeightDown          = row.stressWeightDown,
    r.contingentExposureCrores  = row.contingentExposureCrores,
    r.hasContingentExposure     = row.hasContingentExposure
"""


# ── Main builder ──────────────────────────────────────────────────────────────

def build_subsidiary_of(
    driver: Driver,
    bank_docs: list[dict],
    registry: GlobalEntityRegistry,
) -> int:
    """
    Create SUBSIDIARY_OF edges with consolidated financial stress weights.

    Each unique (subsidiary CIN, bankSymbol) pair produces exactly one edge.
    All RPT transactions for that pair are aggregated before computing weights.

    Args:
        driver    : Neo4j driver
        bank_docs : consolidated bank documents (source of RPT + tier1Capital data)
        registry  : GlobalEntityRegistry for resolving counterparty names

    Returns:
        Number of edges created/merged.
    """
    records: list[dict] = []

    for doc in bank_docs:
        bank_symbol  = doc.get("bankSymbol")
        rpt_data     = doc.get("relatedPartyTransactions", {})
        transactions = rpt_data.get("relatedPartyTransactions", [])

        if not bank_symbol:
            continue

        # Tier 1 Capital (in crores) — denominator for stressWeightUp
        t1_data = doc.get("tier1Capital", {})
        tier1_crores: float | None = None
        if isinstance(t1_data, dict) and "tier1CapitalCrores" in t1_data:
            try:
                tier1_crores = float(t1_data["tier1CapitalCrores"])
            except (TypeError, ValueError):
                pass

        # ── Aggregate all transactions per (CIN, bankSymbol) pair ────────────
        # Buckets track raw rupees; conversion to crores happens after aggregation
        agg: dict[tuple[str, str], dict] = defaultdict(lambda: {
            "relationship":           "",
            "cash_in_outstanding":    0.0,
            "cash_out_outstanding":   0.0,
            "cash_out_approved":      0.0,
            "contingent_outstanding": 0.0,
        })

        for txn in transactions:
            cp           = txn.get("counterParty", {})
            cp_name      = (cp.get("name") or "").strip()
            relationship = (cp.get("relationship") or "").strip()

            if not cp_name or not _is_subsidiary_relationship(relationship):
                continue

            node_type, canonical_id, confidence = registry.resolve(cp_name)
            if node_type != "Company" or not canonical_id:
                continue

            tx          = txn.get("transaction", {})
            tx_type     = (tx.get("type")    or "").strip()
            tx_details  = (tx.get("details") or "").strip()
            outstanding = _safe_number(tx.get("outstandingCurrentPeriod", 0))
            approved    = _safe_number(tx.get("approvedValue", 0))

            direction = _classify_transaction(tx_type, tx_details)
            bucket    = agg[(canonical_id, bank_symbol)]
            bucket["relationship"] = relationship   # last-seen is fine (same entity)

            if direction == "cash_in":
                bucket["cash_in_outstanding"]    += outstanding
            elif direction == "cash_out":
                bucket["cash_out_outstanding"]   += outstanding
                bucket["cash_out_approved"]      += approved
            elif direction == "contingent":
                bucket["contingent_outstanding"] += outstanding
            # "unknown" → skipped from all weight buckets

        # ── Build one edge record per subsidiary ─────────────────────────────
        skipped_no_tier1: list[str] = []

        for (cin, bsymbol), bucket in agg.items():
            # Convert raw rupees → crores (÷ 1e7)
            net_up     = bucket["cash_in_outstanding"]    / 1e7
            net_down   = bucket["cash_out_outstanding"]   / 1e7
            contingent = bucket["contingent_outstanding"] / 1e7

            # stressWeightUp = net cash-in exposure / Tier 1 Capital
            if tier1_crores and tier1_crores > 0:
                stress_up: float | None = round(net_up / tier1_crores, 8)
            else:
                stress_up = None
                if net_up > 0:
                    skipped_no_tier1.append(cin)

            # stressWeightDown = cash-out utilization ratio [0, 1]
            if bucket["cash_out_approved"] > 0:
                stress_down: float | None = round(
                    min(bucket["cash_out_outstanding"] / bucket["cash_out_approved"], 1.0),
                    6,
                )
            else:
                stress_down = None

            records.append({
                "cin":                      cin,
                "parentBankSymbol":         bsymbol,
                "relationship":             bucket["relationship"],
                "netOutstandingUpCrores":   round(net_up,   4),
                "netOutstandingDownCrores":  round(net_down, 4),
                "stressWeightUp":           stress_up,
                "stressWeightDown":         stress_down,
                "contingentExposureCrores": round(contingent, 4) if contingent > 0 else None,
                "hasContingentExposure":    contingent > 0,
            })

        if skipped_no_tier1:
            print(
                f"[subsidiary_of] {bank_symbol}: stressWeightUp not computed for "
                f"{len(skipped_no_tier1)} subsidiary/ies (tier1Capital missing on bank doc)."
            )

    BATCH_SIZE = 500
    total = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(MERGE_SUBSIDIARY_OF, batch=batch)
            total += len(batch)

    print(f"[subsidiary_of] Created/merged {total} SUBSIDIARY_OF edge(s) with financial weights.")
    return total

