"""
prototype_kg/update_stress_scores.py

Standalone script to update the stress attribute on existing Bank and Company
nodes in Neo4j from MongoDB source data.

Usage:
    cd prototype_kg
    python update_stress_scores.py
    python update_stress_scores.py --no-propagation
    python update_stress_scores.py --prop-max-iter 30 --prop-epsilon 1e-5
    python update_stress_scores.py --prop-debug-bank SBIN

Purpose:
    - Updates existing :Bank nodes with stress scores calculated from 
      stressScore and news_stress with dynamic weighting
    - Updates existing :Company nodes with calculated stress from
      entity_stress_fundamental, news_stress, and sector_stress with dynamic weighting
    - Removes obsolete crisilStressScore attribute from Company nodes
    - Idempotent: safe to run multiple times
"""

import sys
import argparse
from pathlib import Path

# Ensure package root on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from config import get_driver, get_mongo_client, get_bank_docs, get_company_docs, get_sector_stress_map, get_macro_sector
from neo4j import Driver
from stress_propagation import PropagationConfig, run_stress_propagation


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _safe_float(val) -> float | None:
    """
    Safely convert value to float, returning None on failure.
    """
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _calculate_bank_stress(doc: dict) -> float | None:
    """
    Calculate bank stress with dynamic weighting.
    
    Formula:
    - If news_stress available: 0.7 * stressScore + 0.3 * news_stress
    - If news_stress missing:   1.0 * stressScore

    Returns None if stressScore is missing.
    """
    stress_score = _safe_float(doc.get("stressScore"))
    news_stress = _safe_float(doc.get("news_stress"))
    
    if stress_score is None:
        return None
    
    # Dynamic weighting based on available components
    if news_stress is not None:
        # Both components available: 0.7 stress + 0.3 news
        return 0.7 * stress_score + 0.3 * news_stress
    else:
        # Only stress available: use full weight
        return stress_score


def _calculate_company_stress(doc: dict, sector_stress_map: dict[str, float]) -> float | None:
    """
    Calculate company stress with dynamic weighting.

    Formula:
    - All available:        0.7 * entity_stress + 0.2 * news_stress + 0.1 * sector_stress
    - Sector missing:       0.8 * entity_stress + 0.2 * news_stress
    - News missing:         0.8 * entity_stress + 0.2 * sector_stress
    - Both news+sector missing: 1.0 * entity_stress
    
    Returns None if entity_stress_fundamental is missing.

    Examples:
        entity_stress_fundamental=14.62, news_stress=0.4775, sector_stress=0.5779
        => 0.7*(0.1462) + 0.2*(0.4775) + 0.1*(0.5779) = 0.2552
    """
    # Get entity stress fundamental (required component)
    entity_fundamental = doc.get("entity_stress_fundamental")
    if entity_fundamental is None:
        return None

    entity_val = _safe_float(entity_fundamental)
    if entity_val is None:
        return None
    
    # Convert entity_fundamental from percentage to decimal
    entity_stress = entity_val / 100.0

    # Get news stress (optional)
    news_stress = _safe_float(doc.get("news_stress"))
    
    # Get sector stress (optional) - map industryName to macro_sector
    sector_stress = None
    industry_name = doc.get("industryName")
    if industry_name:
        macro_sector = get_macro_sector(industry_name)
        if macro_sector and macro_sector in sector_stress_map:
            sector_stress = sector_stress_map[macro_sector]
    
    # Dynamic weighting based on available components
    if news_stress is not None and sector_stress is not None:
        # All components available: 0.7 entity + 0.2 news + 0.1 sector
        return 0.7 * entity_stress + 0.2 * news_stress + 0.1 * sector_stress
    elif news_stress is not None:
        # News available, sector missing: 0.8 entity + 0.2 news
        return 0.8 * entity_stress + 0.2 * news_stress
    elif sector_stress is not None:
        # Sector available, news missing: 0.8 entity + 0.2 sector
        return 0.8 * entity_stress + 0.2 * sector_stress
    else:
        # Only entity available: use full weight
        return entity_stress


# ---------------------------------------------------------------------------
# Update functions
# ---------------------------------------------------------------------------

UPDATE_BANK_STRESS = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.bankSymbol})
SET b.stress = row.stress
"""


def update_bank_stress(driver: Driver, bank_docs: list[dict]) -> int:
    """
    Update stress attribute on existing :Bank nodes.
    
    Uses combined formula: 0.7 * stressScore + 0.3 * news_stress
    (with dynamic weighting if news_stress is missing)

    Returns number of banks processed.
    """
    records = []

    for doc in bank_docs:
        bank_symbol = doc.get("bankSymbol")
        if not bank_symbol:
            continue

        # Calculate combined stress score
        stress_combined = _calculate_bank_stress(doc)

        records.append({
            "bankSymbol": bank_symbol,
            "stress": stress_combined,
        })

    BATCH_SIZE = 500
    total_updated = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(UPDATE_BANK_STRESS, batch=batch)
            total_updated += len(batch)

    print(f"[update_stress] Updated {total_updated} :Bank node(s) with stress scores.")
    return total_updated


UPDATE_COMPANY_STRESS = """
UNWIND $batch AS row
MATCH (c:Company {cin: row.cin})
SET c.stress = row.stress
"""


def update_company_stress(driver: Driver, company_docs: list[dict], sector_stress_map: dict[str, float]) -> int:
    """
    Update stress attribute on existing :Company nodes.

    Calculates stress from entity_stress_fundamental, news_stress, and sector_stress
    with dynamic weighting.
    
    Returns number of companies processed.
    """
    records = []

    for doc in company_docs:
        cin = doc.get("cin")
        if not cin:
            continue

        # Calculate company stress with all three components
        stress_score = _calculate_company_stress(doc, sector_stress_map)

        records.append({
            "cin": cin,
            "stress": stress_score,
        })

    BATCH_SIZE = 500
    total_updated = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(UPDATE_COMPANY_STRESS, batch=batch)
            total_updated += len(batch)

    print(f"[update_stress] Updated {total_updated} :Company node(s) with stress scores.")
    return total_updated


REMOVE_CRISIL_STRESS = """
MATCH (c:Company)
WHERE c.crisilStressScore IS NOT NULL
REMOVE c.crisilStressScore
RETURN count(c) AS removed
"""


def remove_crisil_stress_attribute(driver: Driver) -> int:
    """
    Remove obsolete crisilStressScore attribute from all Company nodes.

    Returns number of nodes where attribute was removed.
    """
    with driver.session() as session:
        result = session.run(REMOVE_CRISIL_STRESS)
        record = result.single()
        count = record["removed"] if record else 0

    print(f"[update_stress] Removed crisilStressScore from {count} :Company node(s).")
    return count


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def main(
    run_propagation: bool = True,
    prop_max_iter: int = 20,
    prop_epsilon: float = 1e-4,
    prop_batch_size: int = 1000,
    prop_debug_bank: str | None = None,
    prop_debug_dir: str = "logs",
):
    """
    Main execution: update stress scores on all Bank and Company nodes.
    """
    print("=" * 60)
    print("  Updating Stress Scores — prototype_kg")
    print("=" * 60)

    # Connect to MongoDB and Neo4j
    mongo_client = get_mongo_client()
    driver = get_driver()

    try:
        # Step 1: Update Bank stress scores
        print("\n[step 1] Fetching bank documents from MongoDB...")
        bank_docs = get_bank_docs(mongo_client)
        print(f"         Loaded {len(bank_docs)} bank document(s).")

        print("\n[step 2] Updating :Bank nodes with stress scores...")
        update_bank_stress(driver, bank_docs)

        # Step 2: Load sector stress scores
        print("\n[step 3] Fetching sector stress scores from MongoDB...")
        sector_stress_map = get_sector_stress_map(mongo_client)
        print(f"         Loaded {len(sector_stress_map)} sector stress score(s).")

        # Step 3: Update Company stress scores
        print("\n[step 4] Fetching company documents from MongoDB...")
        company_docs = get_company_docs(mongo_client)
        print(f"         Loaded {len(company_docs)} company document(s).")

        print("\n[step 5] Updating :Company nodes with calculated stress scores...")
        update_company_stress(driver, company_docs, sector_stress_map)

        # Step 4: Remove obsolete crisilStressScore attribute
        print("\n[step 6] Removing obsolete crisilStressScore attribute...")
        remove_crisil_stress_attribute(driver)

        if run_propagation:
            print("\n[step 7] Propagating stress via transmission ...")
            result = run_stress_propagation(
                driver,
                PropagationConfig(
                    max_iterations=prop_max_iter,
                    epsilon=prop_epsilon,
                    write_batch_size=prop_batch_size,
                    debug_target_bank_symbol=prop_debug_bank,
                    debug_output_dir=prop_debug_dir,
                ),
            )
            print(
                "[update_stress] Propagation summary: "
                f"converged={result.converged}, "
                f"iterations={result.iterations_run}, "
                f"max_delta={result.max_delta:.8f}, "
                f"nodes={result.node_count}, "
                f"edges={result.edge_count}, "
                f"skipped_edges={result.skipped_edges}"
            )
            if result.debug_artifacts:
                print("[update_stress] Debug artifacts:")
                for path in result.debug_artifacts:
                    print(f"               - {path}")

        print("\n✓ Stress score update complete!")

    finally:
        driver.close()
        mongo_client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update base stress scores and run stress transmission propagation."
    )
    parser.add_argument(
        "--no-propagation",
        action="store_true",
        help="Only update base stress fields from MongoDB and skip transmission step.",
    )
    parser.add_argument(
        "--prop-max-iter",
        type=int,
        default=20,
        help="Maximum propagation rounds.",
    )
    parser.add_argument(
        "--prop-epsilon",
        type=float,
        default=1e-4,
        help="Convergence threshold on max absolute node delta per round.",
    )
    parser.add_argument(
        "--prop-batch-size",
        type=int,
        default=1000,
        help="Batch size used to write final propagated stress values.",
    )
    parser.add_argument(
        "--prop-debug-bank",
        type=str,
        default=None,
        help="Capture per-round incoming stress transactions for one bank symbol (example: SBIN).",
    )
    parser.add_argument(
        "--prop-debug-dir",
        type=str,
        default="logs",
        help="Directory for propagation debug artifacts.",
    )
    args = parser.parse_args()

    main(
        run_propagation=not args.no_propagation,
        prop_max_iter=max(1, args.prop_max_iter),
        prop_epsilon=max(0.0, args.prop_epsilon),
        prop_batch_size=max(1, args.prop_batch_size),
        prop_debug_bank=args.prop_debug_bank,
        prop_debug_dir=args.prop_debug_dir,
    )