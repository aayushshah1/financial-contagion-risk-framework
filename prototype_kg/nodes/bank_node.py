"""
prototype_kg/nodes/bank_node.py
Create or merge :Bank nodes in Neo4j.
One node per bankSymbol; properties: bankSymbol, bankName.
"""

from neo4j import Driver
from config import BANK_REGISTRY


MERGE_BANK = """
MERGE (b:Bank {bankSymbol: $bankSymbol})
SET b.bankName = $bankName
"""


def build_bank_nodes(driver: Driver, bank_docs: list[dict]) -> int:
    """
    Upsert :Bank nodes for every document in bank_docs.
    Returns the number of nodes processed.
    """
    symbols_seen: set[str] = set()

    with driver.session() as session:
        for doc in bank_docs:
            symbol = doc.get("bankSymbol")
            name   = doc.get("bankName")

            if not symbol or not name:
                print(f"[bank_node] Skipping doc with missing bankSymbol/bankName: {doc.get('_id')}")
                continue

            # Also catch any bank from BANK_REGISTRY not in db (shouldn't happen)
            session.run(MERGE_BANK, bankSymbol=symbol, bankName=name)
            symbols_seen.add(symbol)

        # Ensure all 3 target banks exist even if a doc was missing
        for symbol, data in BANK_REGISTRY.items():
            if symbol not in symbols_seen:
                print(f"[bank_node] Warning: {symbol} not found in bank_docs — seeding from registry.")
                session.run(MERGE_BANK, bankSymbol=symbol, bankName=data["bankName"])
                symbols_seen.add(symbol)

    count = len(symbols_seen)
    print(f"[bank_node] Processed {count} :Bank node(s): {sorted(symbols_seen)}")
    return count
