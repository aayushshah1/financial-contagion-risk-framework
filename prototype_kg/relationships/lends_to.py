"""
prototype_kg/relationships/lends_to.py
Build LENDS_TO edges.

Two entry points:
  build_lends_to(driver, bank_docs)
      Bank-side: (:Bank)-[:LENDS_TO]->(:Company)
      Source: bank doc advances.companies (pre-resolved by CIN)

  build_lends_to_from_companies(driver, company_docs, registry)
      Company-side: polymorphic; reads each company's bankFacilities list.
      Resolves each lenderName via the GlobalEntityRegistry:
        Bank   → (:Bank)-[:LENDS_TO]->(:Company)
        Company→ (:Company)-[:LENDS_TO]->(:Company)
        None   → creates a :Company stub (isStub=true) then
                 (:Company:stub)-[:LENDS_TO]->(:Company)

This enables multi-hop chains, e.g.
  Bank X → LENDS_TO → Company B → LENDS_TO → Company A
"""

from __future__ import annotations
import re

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


# ---------------------------------------------------------------------------
# Company-side: polymorphic LENDS_TO from bankFacilities
# ---------------------------------------------------------------------------

# Upsert a stub :Company for lenders that don't resolve to a known node.
# ON CREATE only — never overwrite a real node that shares the same CIN.
_MERGE_LENDER_STUB = """
UNWIND $batch AS row
MERGE (c:Company {cin: row.cin})
ON CREATE SET
    c.name          = row.crisilName,
    c.crisilName    = row.crisilName,
    c.isStub        = true,
    c.resolved      = false,
    c.nodeSource    = 'LenderStub'
"""

# Bank → Company  (resolved lender is a target bank)
_MERGE_LENDS_TO_BANK_CO = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.lenderBankSymbol})
MATCH (c:Company {cin: row.borrowerCin})
MERGE (b)-[r:LENDS_TO]->(c)
SET r.totalAmount    = coalesce(r.totalAmount, 0.0) + row.totalAmount,
    r.facilityCount  = coalesce(r.facilityCount, 0) + row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL_CO',
    r.dataYear       = row.dataYear,
    r.lenderRawName  = row.lenderRawName,
    r.resolutionConf = row.resolutionConf
"""

# Company → Company  (resolved lender is another company, or a stub)
_MERGE_LENDS_TO_CO_CO = """
UNWIND $batch AS row
MATCH (lender:Company {cin: row.lenderCin})
MATCH (borrower:Company {cin: row.borrowerCin})
MERGE (lender)-[r:LENDS_TO]->(borrower)
SET r.totalAmount    = coalesce(r.totalAmount, 0.0) + row.totalAmount,
    r.facilityCount  = coalesce(r.facilityCount, 0) + row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL_CO',
    r.dataYear       = row.dataYear,
    r.lenderRawName  = row.lenderRawName,
    r.resolutionConf = row.resolutionConf
"""

_SLUG_RE = re.compile(r"[^a-z0-9]+")

def _slugify(name: str) -> str:
    """Deterministic lowercase slug from a lender name — used as stub CIN suffix."""
    n = name.lower().strip()
    n = _SLUG_RE.sub("_", n).strip("_")
    return n[:60]   # cap length


_SKIP_LENDER_NAMES = frozenset({
    "", "not applicable", "na", "n/a", "nil", "none", "not available",
    "tbd", "to be decided", "-",
})


def build_lends_to_from_companies(
    driver: Driver,
    company_docs: list[dict],
    registry,           # GlobalEntityRegistry
    *,
    data_year: int = 2025,
    batch_size: int = 500,
) -> int:
    """
    Build polymorphic LENDS_TO edges by walking each company's bankFacilities list.

    Two-phase approach:
      Phase 1 — upsert :Company stub nodes for unresolved lenders.
      Phase 2 — upsert LENDS_TO edges (Bank→Company or Company→Company).

    Returns total number of edges created/merged.
    """
    from resolution.entity_resolver import _normalize   # local import to avoid circular

    bank_edge_records:    list[dict] = []
    company_edge_records: list[dict] = []
    stub_records_seen:    dict[str, dict] = {}   # stub_cin → record (deduplicated)
    skipped_no_cin        = 0
    skipped_no_lender     = 0

    for doc in company_docs:
        borrower_cin = str(doc.get("cin") or "").strip()
        if not borrower_cin:
            skipped_no_cin += 1
            continue

        # Aggregate facilities per (borrowerCin, lenderName) pair
        lender_agg: dict[str, dict] = {}

        for fac in doc.get("bankFacilities", []):
            raw_lender = str(fac.get("lenderName") or "").strip()
            if _normalize(raw_lender) in _SKIP_LENDER_NAMES or not raw_lender:
                skipped_no_lender += 1
                continue

            try:
                amt = float(fac.get("amount") or 0)
            except (TypeError, ValueError):
                amt = 0.0

            facility_type = str(fac.get("facility") or "").strip()

            if raw_lender not in lender_agg:
                lender_agg[raw_lender] = {"total": 0.0, "count": 0, "types": set()}
            lender_agg[raw_lender]["total"] += amt
            lender_agg[raw_lender]["count"] += 1
            if facility_type:
                lender_agg[raw_lender]["types"].add(facility_type)

        # Resolve each aggregated lender
        for raw_lender, agg in lender_agg.items():
            node_type, canonical_id, confidence = registry.resolve(raw_lender)

            edge_base = {
                "borrowerCin":   borrower_cin,
                "totalAmount":   round(agg["total"], 4),
                "facilityCount": agg["count"],
                "facilityTypes": sorted(agg["types"]),
                "dataYear":      data_year,
                "lenderRawName": raw_lender,
                "resolutionConf": round(confidence, 3),
            }

            if node_type == "Bank":
                bank_edge_records.append({**edge_base, "lenderBankSymbol": canonical_id})

            elif node_type == "Company":
                company_edge_records.append({**edge_base, "lenderCin": canonical_id})

            else:
                # Unresolved → create a stable stub CIN
                stub_cin = "LSTUB_" + _slugify(raw_lender)
                if stub_cin not in stub_records_seen:
                    stub_records_seen[stub_cin] = {
                        "cin":        stub_cin,
                        "crisilName": raw_lender,
                    }
                company_edge_records.append({**edge_base, "lenderCin": stub_cin})

    stub_records = list(stub_records_seen.values())

    with driver.session() as session:
        # Phase 1 — upsert stubs (must exist before edge MATCH)
        for i in range(0, len(stub_records), batch_size):
            session.run(_MERGE_LENDER_STUB, batch=stub_records[i : i + batch_size])

        # Phase 2 — upsert edges
        for i in range(0, len(bank_edge_records), batch_size):
            session.run(_MERGE_LENDS_TO_BANK_CO, batch=bank_edge_records[i : i + batch_size])

        for i in range(0, len(company_edge_records), batch_size):
            session.run(_MERGE_LENDS_TO_CO_CO, batch=company_edge_records[i : i + batch_size])

    total_edges = len(bank_edge_records) + len(company_edge_records)

    print(
        f"[lends_to/co] Company-side LENDS_TO complete:\n"
        f"              Bank→Company  : {len(bank_edge_records):>6}\n"
        f"              Company→Company: {len(company_edge_records):>6}  "
        f"(incl. {len(stub_records)} lender stubs)\n"
        f"              Skipped (no borrower CIN): {skipped_no_cin}\n"
        f"              Skipped (no lender name) : {skipped_no_lender}"
    )
    return total_edges
