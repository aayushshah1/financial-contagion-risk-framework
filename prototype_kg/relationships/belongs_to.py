"""
prototype_kg/relationships/belongs_to.py
Build (:Company)-[:BELONGS_TO]->(:Industry) edges.

:Industry nodes are keyed by CRISIL industryCode.
Uses the industry_code_map {cin: industryCode} produced by company_node.build_company_nodes().
"""

from neo4j import Driver


_MERGE_BELONGS_TO = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.cin})
MATCH (i:Industry {industryCode: row.industryCode})
MERGE (c)-[r:BELONGS_TO]->(i)
SET r.source = 'CRISIL_Industry'
"""


def build_belongs_to(
    driver: Driver,
    industry_code_map: dict[str, str],
) -> int:
    """
    Create BELONGS_TO edges for all companies that have a CRISIL industryCode.

    Args:
        driver            : Neo4j driver
        industry_code_map : {cin: industryCode} from company_node

    Returns:
        Number of edges created/merged.
    """
    records = [
        {"cin": cin, "industryCode": ind_code}
        for cin, ind_code in industry_code_map.items()
        if cin and ind_code
    ]

    BATCH_SIZE = 500
    total = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(_MERGE_BELONGS_TO, batch=batch)
            total += len(batch)

    print(f"[belongs_to] Created/merged {total} BELONGS_TO (:Company→:Industry) edge(s).")
    return total


