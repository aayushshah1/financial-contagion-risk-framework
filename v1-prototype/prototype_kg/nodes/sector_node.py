"""
prototype_kg/nodes/sector_node.py
Create or merge :PrioritySector nodes in Neo4j.

:PrioritySector nodes represent RBI Priority Sector categories as defined in
outstandingAdvances data.  They are used exclusively by PRIORITY_EXPOSURE edges
(Bank → PrioritySector).

NIC sections are NOT stored as nodes — NIC codes are plain attributes on
:Company nodes (nicCode property) explaining the activity a company engages in.

Company industries (CRISIL taxonomy) live in :Industry nodes — see industry_node.py.

Returns:
    (count, rbi_category_label_map)
    rbi_category_label_map: {rbiCategory: rbiCategoryLabel}
"""

from neo4j import Driver


# RBI Priority Sector categories with human-readable labels.
# This is the authoritative list; add new categories here when expanding.
RBI_PRIORITY_CATEGORIES: dict[str, str] = {
    "agriculture":          "Agriculture",
    "msme":                 "MSME",
    "exportCredit":         "Export Credit",
    "education":            "Education",
    "housing":              "Housing",
    "renewableEnergy":      "Renewable Energy",
    "socialInfrastructure": "Social Infrastructure",
    "weakerSections":       "Weaker Sections",
    "othersCategory":       "Others",
    "prioritySectorTotal":  "Priority Sector Total",
}

_MERGE_PRIORITY_SECTOR = """
UNWIND $batch AS row
MERGE (p:PrioritySector {rbiCategory: row.rbiCategory})
SET p.rbiCategoryLabel = row.rbiCategoryLabel
"""


def build_sector_nodes(
    driver: Driver,
    company_docs: list[dict],   # kept for signature compatibility; not used here
) -> tuple[int, dict[str, str]]:
    """
    Upsert :PrioritySector nodes for all RBI priority sector categories.

    Args:
        driver       : Neo4j driver
        company_docs : unused (kept so loader.py signature stays consistent)

    Returns:
        count                  : number of :PrioritySector nodes upserted
        rbi_category_label_map : {rbiCategory: rbiCategoryLabel}
    """
    batch = [
        {"rbiCategory": key, "rbiCategoryLabel": label}
        for key, label in RBI_PRIORITY_CATEGORIES.items()
    ]

    with driver.session() as session:
        session.run(_MERGE_PRIORITY_SECTOR, batch=batch)

    count = len(batch)
    print(f"[sector_node] Upserted {count} :PrioritySector node(s).")
    return count, dict(RBI_PRIORITY_CATEGORIES)
