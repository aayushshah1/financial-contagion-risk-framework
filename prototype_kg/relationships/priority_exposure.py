"""
prototype_kg/relationships/priority_exposure.py
Build (:Bank)-[:PRIORITY_EXPOSURE]->(:PrioritySector) edges.

Source: outstandingAdvances in each bank document (RBI priority-sector data).
One edge per (bank, rbiCategory) pair.  No NIC crosswalk or mapping is needed —
:PrioritySector nodes are keyed directly by the RBI category key string.
"""

from neo4j import Driver
from nodes.sector_node import RBI_PRIORITY_CATEGORIES

# Categories that are aggregate totals — skip creating an edge for these.
SKIP_CATEGORIES = {"prioritySectorTotal"}


MERGE_PRIORITY_EXPOSURE = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.bankSymbol})
MATCH (p:PrioritySector {rbiCategory: row.rbiCategory})
MERGE (b)-[r:PRIORITY_EXPOSURE {rbiCategory: row.rbiCategory}]->(p)
SET r.outstandingAmount = row.outstandingAmount,
    r.rbiCategoryLabel  = row.rbiCategoryLabel,
    r.sectorWeight      = row.sectorWeight,
    r.source            = 'RBI_OutstandingAdvances',
    r.dataYear          = row.dataYear
"""


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def build_priority_exposure(driver: Driver, bank_docs: list[dict]) -> int:
    """
    Create PRIORITY_EXPOSURE edges for each bank → RBI priority sector.
    sectorWeight = outstandingAmount / bank's total priority-sector outstanding.
    Returns total edges created/merged.
    """
    records: list[dict] = []

    for doc in bank_docs:
        bank_symbol = doc.get("bankSymbol")
        data_year   = doc.get("dataYear", 2025)
        oa          = doc.get("outstandingAdvances", {})

        if not bank_symbol or not oa:
            continue

        # Compute total priority exposure for this bank (denominator)
        total_priority = 0.0
        for rbi_key in RBI_PRIORITY_CATEGORIES:
            if rbi_key in SKIP_CATEGORIES:
                continue
            cat = oa.get(rbi_key)
            if cat:
                total_priority += _safe_float(cat.get("balanceOutstanding", 0))

        for rbi_key, rbi_label in RBI_PRIORITY_CATEGORIES.items():
            if rbi_key in SKIP_CATEGORIES:
                continue

            category_data = oa.get(rbi_key)
            if not category_data:
                continue

            outstanding = _safe_float(category_data.get("balanceOutstanding", 0))
            if outstanding <= 0:
                continue

            sector_weight = round(outstanding / total_priority, 6) if total_priority > 0 else None

            records.append({
                "bankSymbol":        bank_symbol,
                "rbiCategory":       rbi_key,
                "rbiCategoryLabel":  rbi_label,
                "outstandingAmount": round(outstanding, 4),
                "sectorWeight":      sector_weight,
                "dataYear":          data_year,
            })

    total = 0
    BATCH_SIZE = 100

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(MERGE_PRIORITY_EXPOSURE, batch=batch)
            total += len(batch)

    print(f"[priority_exposure] Created/merged {total} PRIORITY_EXPOSURE edge(s).")
    return total

