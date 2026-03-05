"""
prototype_kg/loader.py
Main orchestrator for the Knowledge Graph build pipeline.

Sequence:
  0. Apply schema (constraints + indexes) — run once; safe to re-run
  1. Build GlobalEntityRegistry (GER)
  2. Bank nodes
  3. PrioritySector nodes  (RBI categories, used by Bank→PrioritySector edges)
  4. Industry nodes         (CRISIL taxonomy, used by Company→Industry edges)
  5. Company nodes
  6. Shareholder nodes (bank SHP)
  7. Shareholder nodes (company SHP)
  8. LENDS_TO edges (bank-side: advances.companies → Bank→Company)
  8B.LENDS_TO edges (company-side: bankFacilities → Bank→Company + Company→Company + stubs)
  9. BELONGS_TO edges         (Company → Industry)
 10. SHAREHOLDER_OF edges (bank SHP)
 11. SHAREHOLDER_OF edges (company SHP)
 12. SUBSIDIARY_OF edges    (derived from RPT data)
 13. PRIORITY_EXPOSURE edges (Bank → PrioritySector)
 14. RELATED_PARTY edges     (Bank → Company and Bank → Bank)

Run:
    cd prototype_kg
    python loader.py

Optional flags:
    --skip-schema        Skip DDL step (if already applied)
    --banks SBIN HDFCBANK ...         Override which banks to process (default: all 41)
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure package root on PYTHONPATH when run directly
sys.path.insert(0, str(Path(__file__).parent))

from config import get_driver, get_mongo_client, get_bank_docs, get_company_docs, TARGET_BANK_SYMBOLS
from nodes.bank_node        import build_bank_nodes
from nodes.sector_node      import build_sector_nodes
from nodes.industry_node    import build_industry_nodes
from nodes.company_node     import build_company_nodes
from nodes.shareholder_node import build_shareholder_nodes, build_company_shareholder_nodes
from relationships.lends_to         import build_lends_to, build_lends_to_from_companies
from relationships.belongs_to       import build_belongs_to
from relationships.shareholder_of   import build_shareholder_of, build_company_shareholder_of
from relationships.subsidiary_of    import build_subsidiary_of
from relationships.priority_exposure import build_priority_exposure
from relationships.related_party    import build_related_party
from resolution.entity_resolver     import GlobalEntityRegistry


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------

def purge_graph(driver):
    """
    Delete ALL nodes and relationships from the Neo4j database.
    Run this before a fresh rebuild to avoid stale data.
    """
    with driver.session() as session:
        # Batch-delete to avoid OOM on large graphs
        session.run("""
            CALL apoc.periodic.iterate(
              'MATCH (n) RETURN n',
              'DETACH DELETE n',
              {batchSize: 10000}
            )
        """
        )
    print("[purge] All nodes and relationships deleted.")


def purge_graph_simple(driver):
    """Fallback purge without APOC (works for smaller graphs)."""
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("[purge] All nodes and relationships deleted (simple).")


# ---------------------------------------------------------------------------
# Schema application
# ---------------------------------------------------------------------------

def apply_schema(driver):
    schema_path = Path(__file__).parent / "schema.cypher"
    if not schema_path.exists():
        print("[schema] schema.cypher not found — skipping.")
        return

    statements = [
        s.strip()
        for s in schema_path.read_text(encoding="utf-8").split(";")
        if s.strip() and not s.strip().startswith("//")
    ]

    with driver.session() as session:
        for stmt in statements:
            try:
                session.run(stmt)
            except Exception as e:
                # AuraDB free tier may not support all index types; log and continue
                print(f"[schema] Warning on statement → {e}")

    print(f"[schema] Applied {len(statements)} DDL statement(s).")


# ---------------------------------------------------------------------------
# Summary query
# ---------------------------------------------------------------------------

def print_summary(driver):
    with driver.session() as session:
        print("\n── Node counts ──────────────────────────────────────")
        result = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC")
        for record in result:
            print(f"  :{record['label']:<25} {record['cnt']:>6}")

        print("\n── Edge counts ──────────────────────────────────────")
        result = session.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC")
        for record in result:
            print(f"  :{record['rel']:<30} {record['cnt']:>6}")
        print()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(bank_symbols: list[str], skip_schema: bool):
    t0 = time.time()

    print("=" * 60)
    print("  Knowledge Graph Loader — prototype_kg")
    print(f"  Banks: {len(bank_symbols)} banks selected")
    print("=" * 60)

    # ── Connections ─────────────────────────────────────────────────────────
    mongo_client = get_mongo_client()
    driver       = get_driver()

    try:
        # ── 0. Schema ───────────────────────────────────────────────────────
        if not skip_schema:
            print("\n[step 0] Applying schema …")
            apply_schema(driver)

        # ── 0B. Purge existing graph data ────────────────────────────────────
        print("\n[step 0B] Purging existing Neo4j graph data …")
        try:
            purge_graph(driver)
        except Exception:
            print("          APOC not available — using simple purge …")
            purge_graph_simple(driver)

        # ── Load bank documents from MongoDB ────────────────────────────────
        print("\n[step load] Fetching bank documents from MongoDB …")
        all_docs = get_bank_docs(mongo_client)
        # Filter to requested symbols only
        bank_docs = [d for d in all_docs if d.get("bankSymbol") in bank_symbols]

        if not bank_docs:
            print("ERROR: No bank documents found in MongoDB for the requested symbols.")
            print("       Run data_consolidation/main.py first to populate financial_kg.bank.")
            sys.exit(1)

        print(f"         Loaded {len(bank_docs)} bank document(s): "
              f"{[d.get('bankSymbol') for d in bank_docs]}")

        # ── Load company documents from MongoDB ──────────────────────────────
        print("\n[step load] Fetching company documents from MongoDB …")
        company_docs = get_company_docs(mongo_client)
        print(f"         Loaded {len(company_docs)} company document(s).")

        # ── 1. Build Global Entity Registry ──────────────────────────────────
        print("\n[step 1] Building Global Entity Registry (GER) …")
        registry = GlobalEntityRegistry(bank_docs, company_docs)

        # ── 2. Bank nodes ────────────────────────────────────────────────────
        print("\n[step 2] Building :Bank nodes …")
        build_bank_nodes(driver, bank_docs)

        # ── 3. PrioritySector nodes ──────────────────────────────────────────
        print("\n[step 3] Building :PrioritySector nodes …")
        build_sector_nodes(driver, company_docs)

        # ── 4. Industry nodes (CRISIL taxonomy) ─────────────────────────────
        print("\n[step 4] Building :Industry nodes …")
        _, industry_map = build_industry_nodes(driver, company_docs)

        # ── 5. Company nodes ─────────────────────────────────────────────────
        print("\n[step 5] Building :Company nodes …")
        _, industry_code_map = build_company_nodes(driver, bank_docs, company_docs)

        # ── 6. Shareholder nodes (bank SHP) ──────────────────────────────────
        print("\n[step 6] Building :Shareholder nodes (bank SHP) …")
        shareholders = build_shareholder_nodes(driver, bank_docs, registry)

        # ── 7. Shareholder nodes (company SHP) ───────────────────────────────
        print("\n[step 7] Building :Shareholder nodes (company SHP) …")
        company_shareholders = build_company_shareholder_nodes(driver, company_docs, registry)

        # ── 8. LENDS_TO edges (bank-side: advances.companies) ─────────────
        print("\n[step 8] Building LENDS_TO edges (bank-side) …")
        build_lends_to(driver, bank_docs)

        # ── 8B. LENDS_TO edges (company-side: bankFacilities, polymorphic) ──
        # Resolves each facility's lenderName against GER:
        #   Bank   → (Bank)-[:LENDS_TO]->(Company)
        #   Company→ (Company)-[:LENDS_TO]->(Company)
        #   Unknown→ stub :Company created, then (Company)-[:LENDS_TO]->(Company)
        print("\n[step 8B] Building LENDS_TO edges (company-side, polymorphic) …")
        build_lends_to_from_companies(driver, company_docs, registry)

        # ── 9. BELONGS_TO edges  (Company → Industry) ───────────────────────
        print("\n[step 9] Building BELONGS_TO edges …")
        build_belongs_to(driver, industry_code_map)

        # ── 10. SHAREHOLDER_OF edges (bank SHP) ──────────────────────────────
        print("\n[step 10] Building SHAREHOLDER_OF edges (bank SHP) …")
        build_shareholder_of(driver, shareholders)

        # ── 11. SHAREHOLDER_OF edges (company SHP) ───────────────────────────
        print("\n[step 11] Building SHAREHOLDER_OF edges (company SHP) …")
        build_company_shareholder_of(driver, company_shareholders)

        # ── 12. SUBSIDIARY_OF edges  (data-driven from RPT) ──────────────────
        print("\n[step 12] Building SUBSIDIARY_OF edges …")
        build_subsidiary_of(driver, bank_docs, registry)

        # ── 13. PRIORITY_EXPOSURE edges ──────────────────────────────────────
        print("\n[step 13] Building PRIORITY_EXPOSURE edges …")
        build_priority_exposure(driver, bank_docs)

        # ── 14. RELATED_PARTY edges ──────────────────────────────────────────
        print("\n[step 14] Resolving RPT counter-parties and building RELATED_PARTY edges …")
        build_related_party(driver, bank_docs, registry)

        # ── Summary ──────────────────────────────────────────────────────────
        print("\n[summary] Final graph state:")
        print_summary(driver)

        elapsed = time.time() - t0
        print(f"✓ Pipeline complete in {elapsed:.1f}s")

    finally:
        driver.close()
        mongo_client.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the financial KG in Neo4j AuraDB.")
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Skip DDL (constraints/indexes) — use if schema is already applied.",
    )
    parser.add_argument(
        "--banks",
        nargs="+",
        default=TARGET_BANK_SYMBOLS,
        metavar="SYMBOL",
        help="Bank symbols to process (default: all 41 target banks).",
    )
    args = parser.parse_args()
    run(bank_symbols=args.banks, skip_schema=args.skip_schema)
