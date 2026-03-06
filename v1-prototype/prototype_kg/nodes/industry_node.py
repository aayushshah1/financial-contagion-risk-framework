"""
prototype_kg/nodes/industry_node.py
Create or merge :Industry nodes in Neo4j.

:Industry nodes represent the CRISIL industry taxonomy harvested from the
financial_kg/company collection.  They are used by BELONGS_TO edges
(Company → Industry).

This is separate from :PrioritySector nodes (RBI categories used by banks).
NIC codes are plain attributes on :Company nodes, not separate nodes.

Returns:
    (count, industry_map)
    industry_map: {industryCode: industryName}
"""

from neo4j import Driver


_MERGE_INDUSTRY = """
UNWIND $batch AS row
MERGE (i:Industry {industryCode: row.industryCode})
SET i.industryName = row.industryName,
    i.source       = 'CRISIL'
"""


def build_industry_nodes(
    driver: Driver,
    company_docs: list[dict],
) -> tuple[int, dict[str, str]]:
    """
    Upsert :Industry nodes from CRISIL industry codes in company docs.

    Args:
        driver       : Neo4j driver
        company_docs : documents from financial_kg/company

    Returns:
        count        : number of distinct :Industry nodes upserted
        industry_map : {industryCode: industryName}
    """
    seen: dict[str, str] = {}   # industryCode → industryName

    for doc in company_docs:
        code = str(doc.get("industryCode") or "").strip()
        name = str(doc.get("industryName") or "").strip()
        if code and name and code not in seen:
            seen[code] = name

    batch = [
        {"industryCode": code, "industryName": name}
        for code, name in seen.items()
    ]

    if batch:
        with driver.session() as session:
            session.run(_MERGE_INDUSTRY, batch=batch)

    count = len(batch)
    print(f"[industry_node] Upserted {count} :Industry node(s) (CRISIL taxonomy).")
    return count, seen
