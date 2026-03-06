"""
prototype_kg/relationships/shareholder_of.py
Build SHAREHOLDER_OF edges:
  (:Shareholder)-[:SHAREHOLDER_OF]->(:Bank)      — stub shareholder → bank
  (:Bank)-[:SHAREHOLDER_OF]->(:Bank)              — direct cross-bank ownership
  (:Shareholder)-[:SHAREHOLDER_OF]->(:Company)   — stub shareholder → company
  (:Bank)-[:SHAREHOLDER_OF]->(:Company)           — bank holding stake in a company
  (:Company)-[:SHAREHOLDER_OF]->(:Bank)           — company holding stake in a bank
  (:Company)-[:SHAREHOLDER_OF]->(:Company)        — company holding stake in a company

Uses the ExtractedShareholder / ExtractedCompanyShareholder lists produced by
shareholder_node.py.  Resolution outcomes (bank_symbol, resolved_company_cin)
determine which Cypher query is used.
"""

from neo4j import Driver
from nodes.shareholder_node import ExtractedShareholder, ExtractedCompanyShareholder


# ── Shareholder stub → Bank ──────────────────────────────────────────────────
MERGE_SH_TO_BANK = """
UNWIND $batch AS row
MATCH (s:Shareholder {shareholderName: row.shareholderName})
MATCH (b:Bank {bankSymbol: row.targetBankSymbol})
MERGE (s)-[r:SHAREHOLDER_OF]->(b)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_XBRL'
"""

# ── Bank → Bank ───────────────────────────────────────────────────────────────
MERGE_BANK_TO_BANK = """
UNWIND $batch AS row
MATCH (b1:Bank {bankSymbol: row.ownerBankSymbol})
MATCH (b2:Bank {bankSymbol: row.targetBankSymbol})
MERGE (b1)-[r:SHAREHOLDER_OF]->(b2)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_XBRL'
"""

# ── Company → Bank  (resolved company is a shareholder of a bank) ────────────
MERGE_COMPANY_TO_BANK = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.ownerCin})
MATCH (b:Bank {bankSymbol: row.targetBankSymbol})
MERGE (c)-[r:SHAREHOLDER_OF]->(b)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_XBRL'
"""

# ── Shareholder stub → Company ────────────────────────────────────────────────
MERGE_SH_TO_COMPANY = """
UNWIND $batch AS row
MATCH (s:Shareholder {shareholderName: row.shareholderName})
MATCH (c:Company {cin: row.cin})
MERGE (s)-[r:SHAREHOLDER_OF]->(c)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_NSE'
"""

# ── Bank → Company ────────────────────────────────────────────────────────────
MERGE_BANK_TO_COMPANY = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.ownerBankSymbol})
MATCH (c:Company {cin: row.cin})
MERGE (b)-[r:SHAREHOLDER_OF]->(c)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_NSE'
"""

# ── Company → Company ─────────────────────────────────────────────────────────
MERGE_COMPANY_TO_COMPANY = """
UNWIND $batch AS row
MATCH (owner:Company {cin: row.ownerCin})
MATCH (target:Company {cin: row.targetCin})
MERGE (owner)-[r:SHAREHOLDER_OF]->(target)
SET r.numberOfShares         = row.numberOfShares,
    r.shareholdingPercentage = row.shareholdingPercentage,
    r.source                 = 'SHP_NSE'
"""


def build_shareholder_of(
    driver: Driver,
    shareholders: list[ExtractedShareholder],
) -> dict[str, int]:
    """
    Build all SHAREHOLDER_OF edges for bank-level shareholding data.
    Handles three resolution outcomes for each shareholder entity.
    """
    sh_to_bank:      list[dict] = []
    bank_to_bank:    list[dict] = []
    company_to_bank: list[dict] = []

    for sh in shareholders:
        base = {
            "numberOfShares":         sh.numberOfShares,
            "shareholdingPercentage": sh.shareholdingPercentage,
        }
        if sh.bank_symbol:
            # Entity IS a target bank → Bank→Bank edge (if different)
            if sh.bank_symbol != sh.source_bank_symbol:
                bank_to_bank.append({**base,
                    "ownerBankSymbol":  sh.bank_symbol,
                    "targetBankSymbol": sh.source_bank_symbol,
                })
        elif sh.resolved_company_cin:
            # Entity resolved to a Company → Company→Bank edge
            company_to_bank.append({**base,
                "ownerCin":         sh.resolved_company_cin,
                "targetBankSymbol": sh.source_bank_symbol,
            })
        else:
            # Unresolved stub → Shareholder→Bank edge
            sh_to_bank.append({**base,
                "shareholderName":  sh.raw_name,
                "targetBankSymbol": sh.source_bank_symbol,
            })

    BATCH_SIZE = 500
    counts: dict[str, int] = {"shareholder_to_bank": 0, "bank_to_bank": 0, "company_to_bank": 0}

    with driver.session() as session:
        for i in range(0, len(sh_to_bank), BATCH_SIZE):
            session.run(MERGE_SH_TO_BANK, batch=sh_to_bank[i : i + BATCH_SIZE])
            counts["shareholder_to_bank"] += len(sh_to_bank[i : i + BATCH_SIZE])
        for i in range(0, len(bank_to_bank), BATCH_SIZE):
            session.run(MERGE_BANK_TO_BANK, batch=bank_to_bank[i : i + BATCH_SIZE])
            counts["bank_to_bank"] += len(bank_to_bank[i : i + BATCH_SIZE])
        for i in range(0, len(company_to_bank), BATCH_SIZE):
            session.run(MERGE_COMPANY_TO_BANK, batch=company_to_bank[i : i + BATCH_SIZE])
            counts["company_to_bank"] += len(company_to_bank[i : i + BATCH_SIZE])

    print(f"[shareholder_of] Bank SHP edges: "
          f"Shareholder→Bank={counts['shareholder_to_bank']}, "
          f"Bank→Bank={counts['bank_to_bank']}, "
          f"Company→Bank={counts['company_to_bank']}")
    return counts


def build_company_shareholder_of(
    driver: Driver,
    company_shareholders: list[ExtractedCompanyShareholder],
) -> dict[str, int]:
    """
    Build SHAREHOLDER_OF edges from company-level shareholding patterns.
    Handles three resolution outcomes for each shareholder entity.
    """
    sh_to_co:       list[dict] = []
    bank_to_co:     list[dict] = []
    company_to_co:  list[dict] = []

    for sh in company_shareholders:
        if not sh.source_company_cin:
            continue
        base = {
            "cin":                    sh.source_company_cin,
            "numberOfShares":         sh.numberOfShares,
            "shareholdingPercentage": sh.shareholdingPercentage,
        }
        if sh.bank_symbol:
            bank_to_co.append({**base, "ownerBankSymbol": sh.bank_symbol})
        elif sh.resolved_company_cin:
            # Self-loop guard: skip if resolved owner == target company
            if sh.resolved_company_cin == sh.source_company_cin:
                continue
            company_to_co.append({
                "ownerCin":  sh.resolved_company_cin,
                "targetCin": sh.source_company_cin,
                "numberOfShares":         sh.numberOfShares,
                "shareholdingPercentage": sh.shareholdingPercentage,
            })
        else:
            sh_to_co.append({**base, "shareholderName": sh.raw_name})

    BATCH_SIZE = 500
    counts: dict[str, int] = {"shareholder_to_company": 0, "bank_to_company": 0, "company_to_company": 0}

    with driver.session() as session:
        for i in range(0, len(sh_to_co), BATCH_SIZE):
            session.run(MERGE_SH_TO_COMPANY, batch=sh_to_co[i : i + BATCH_SIZE])
            counts["shareholder_to_company"] += len(sh_to_co[i : i + BATCH_SIZE])
        for i in range(0, len(bank_to_co), BATCH_SIZE):
            session.run(MERGE_BANK_TO_COMPANY, batch=bank_to_co[i : i + BATCH_SIZE])
            counts["bank_to_company"] += len(bank_to_co[i : i + BATCH_SIZE])
        for i in range(0, len(company_to_co), BATCH_SIZE):
            session.run(MERGE_COMPANY_TO_COMPANY, batch=company_to_co[i : i + BATCH_SIZE])
            counts["company_to_company"] += len(company_to_co[i : i + BATCH_SIZE])

    print(f"[shareholder_of/company] Company SHP edges: "
          f"Shareholder→Company={counts['shareholder_to_company']}, "
          f"Bank→Company={counts['bank_to_company']}, "
          f"Company→Company={counts['company_to_company']}")
    return counts
