"""
prototype_kg/relationships/subsidiary_of.py
Build (:Company)-[:SUBSIDIARY_OF]->(:Bank) edges.

Source: relatedPartyTransactions in each bank document.
Any RPT counter-party whose `relationship` field contains "subsidiary" or
"associate" (case-insensitive) and that resolves to a :Company node via the
GlobalEntityRegistry is considered a subsidiary/associate of that bank.

This replaces the old KNOWN_SUBSIDIARIES hardcoded dict, making the logic
data-driven and automatically scalable to any number of banks.
"""

from neo4j import Driver
from resolution.entity_resolver import GlobalEntityRegistry


# Relationship tokens that indicate a subsidiary / associate link
_SUBSIDIARY_KEYWORDS = {"subsidiary", "associate", "subsidiar"}


MERGE_SUBSIDIARY_OF = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.cin})
MATCH (b:Bank {bankSymbol: row.parentBankSymbol})
MERGE (c)-[r:SUBSIDIARY_OF]->(b)
SET r.relationship = row.relationship,
    r.source       = 'Integrated_XBRL'
"""


def _is_subsidiary_relationship(relationship: str) -> bool:
    lower = relationship.lower()
    return any(kw in lower for kw in _SUBSIDIARY_KEYWORDS)


def build_subsidiary_of(
    driver: Driver,
    bank_docs: list[dict],
    registry: GlobalEntityRegistry,
) -> int:
    """
    Create SUBSIDIARY_OF edges derived from RPT relationship field.

    Args:
        driver    : Neo4j driver
        bank_docs : consolidated bank documents (source of RPT data)
        registry  : GlobalEntityRegistry for resolving counterparty names

    Returns:
        Number of edges created/merged.
    """
    seen: set[tuple[str, str]] = set()    # (cin, bankSymbol)
    records: list[dict] = []

    for doc in bank_docs:
        bank_symbol  = doc.get("bankSymbol")
        rpt_data     = doc.get("relatedPartyTransactions", {})
        transactions = rpt_data.get("relatedPartyTransactions", [])

        if not bank_symbol:
            continue

        for txn in transactions:
            cp           = txn.get("counterParty", {})
            cp_name      = (cp.get("name") or "").strip()
            relationship = (cp.get("relationship") or "").strip()

            if not cp_name or not _is_subsidiary_relationship(relationship):
                continue

            node_type, canonical_id, confidence = registry.resolve(cp_name)
            if node_type != "Company" or not canonical_id:
                continue

            key = (canonical_id, bank_symbol)
            if key in seen:
                continue
            seen.add(key)

            records.append({
                "cin":             canonical_id,
                "parentBankSymbol": bank_symbol,
                "relationship":    relationship,
            })

    BATCH_SIZE = 500
    total = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(MERGE_SUBSIDIARY_OF, batch=batch)
            total += len(batch)

    print(f"[subsidiary_of] Created/merged {total} SUBSIDIARY_OF edge(s) (from RPT data).")
    return total

