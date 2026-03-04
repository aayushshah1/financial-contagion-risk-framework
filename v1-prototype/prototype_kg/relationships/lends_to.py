"""
prototype_kg/relationships/lends_to.py
Build (:Bank)-[:LENDS_TO]->(:Company) edges.

One aggregated edge per bank-company pair.
All facility amounts for that pair are summed into totalAmount.
facilityTypes lists the canonical categories present in the pair.

:Company nodes are keyed by CIN.  Each advances.companies record carries a
'cin' field (real MCA CIN or generated dummy CIN).  Records where cin is
missing/empty are the only ones skipped — dummy CINs (dummyCIN=True) are
processed exactly like real CINs provided the corresponding :Company node
exists in the graph.
"""

from neo4j import Driver


# Map from bankFacilityMapping canonical keys → short labels stored on edge
FACILITY_LABEL_MAP = {
    "Bills Purchased & Discounted": "Bills Discounting",
    "Cash Credits, Overdrafts & Loans": "Working Capital",
    "Term Loans": "Term Loan",
}


def _canonical_facility_type(raw_type: str) -> str:
    return FACILITY_LABEL_MAP.get(raw_type, raw_type)


MERGE_LENDS_TO = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.bankSymbol})
MATCH (c:Company {cin: row.cin})
MERGE (b)-[r:LENDS_TO]->(c)
SET r.totalAmount    = row.totalAmount,
    r.facilityCount  = row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL',
    r.dataYear       = row.dataYear
"""


def build_lends_to(
    driver: Driver,
    bank_docs: list[dict],
) -> int:
    """
    Create LENDS_TO edges from all bank docs.
    Skips records where hasCIN is False or cin is absent/empty.
    Returns total number of edges created/merged.
    """
    records: list[dict] = []
    skipped_no_cin = 0

    for doc in bank_docs:
        bank_symbol = doc.get("bankSymbol")
        data_year   = doc.get("dataYear", 2025)

        if not bank_symbol:
            continue

        companies = doc.get("advances", {}).get("companies", [])

        for company in companies:
            # Use cin directly — hasCIN / dummyCIN are NOT checked here;
            # all records with a non-empty cin are included.
            cin = company.get("cin", "")
            if not cin:
                skipped_no_cin += 1
                continue

            facilities = company.get("facilities", [])
            total_amount   = 0.0
            facility_count = 0
            types_seen: set[str] = set()

            for fac in facilities:
                amount = fac.get("amount")
                if amount is None:
                    continue
                try:
                    amt = float(amount)
                except (TypeError, ValueError):
                    continue
                total_amount   += amt
                facility_count += 1
                raw_type = fac.get("facilityType", "")
                if raw_type:
                    types_seen.add(_canonical_facility_type(raw_type))

            if facility_count == 0:
                total_amount = float(company.get("totalExposure", 0) or 0)

            records.append({
                "bankSymbol":    bank_symbol,
                "cin":           cin,
                "totalAmount":   round(total_amount, 4),
                "facilityCount": facility_count,
                "facilityTypes": sorted(types_seen),
                "dataYear":      data_year,
            })

    BATCH_SIZE = 500
    total = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(MERGE_LENDS_TO, batch=batch)
            total += len(batch)

    if skipped_no_cin:
        print(f"[lends_to] Skipped {skipped_no_cin} advance record(s) with no CIN mapping.")
    print(f"[lends_to] Created/merged {total} LENDS_TO edge(s).")
    return total
