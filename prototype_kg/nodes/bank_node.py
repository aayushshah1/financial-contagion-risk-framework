"""
prototype_kg/nodes/bank_node.py
Create or merge :Bank nodes in Neo4j.
One node per bankSymbol; properties: bankSymbol, bankName,
shpTotalShares, shpTotalShareholders, stress.
"""

from neo4j import Driver
from config import BANK_REGISTRY


def _safe_int(val) -> int:
    if isinstance(val, dict) and "$numberLong" in val:
        try:
            return int(val["$numberLong"])
        except (TypeError, ValueError):
            return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _safe_float(val) -> float | None:
    """Coerce value to float; returns None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


MERGE_BANK = """
MERGE (b:Bank {bankSymbol: $bankSymbol})
SET b.bankName             = $bankName,
    b.shpTotalShares        = CASE WHEN $shpTotalShares > 0       THEN $shpTotalShares       ELSE coalesce(b.shpTotalShares, 0) END,
    b.shpTotalShareholders  = CASE WHEN $shpTotalShareholders > 0 THEN $shpTotalShareholders ELSE coalesce(b.shpTotalShareholders, 0) END,
    b.stress                = CASE WHEN $stress IS NOT NULL       THEN $stress                ELSE b.stress END
"""


def _calculate_bank_stress(doc: dict) -> float | None:
    """
    Calculate bank stress using component-based weighting:

    0.23 * boundaryDistance
    + 0.23 * camelsComposite
    + 0.27 * mertonOriented
    + 0.27 * news_stress

    Components are read from:
    - stressComponents.boundaryDistance
    - stressComponents.camelsComposite
    - stressComponents.mertonOriented
    - news_stress

    Fallback behavior:
    - If any component is missing, use stressScore plus news_stress blend
      with the updated news weight: 0.73 * stressScore + 0.27 * news_stress.
    - If news_stress is also missing, return stressScore.
    - If stressScore is missing in fallback path, return None.
    """
    stress_components = doc.get("stressComponents") or {}

    boundary_distance = _safe_float(stress_components.get("boundaryDistance"))
    camels_score = _safe_float(stress_components.get("camelsComposite"))
    merton_oriented = _safe_float(stress_components.get("mertonOriented"))
    news_stress = _safe_float(doc.get("news_stress"))

    if (
        boundary_distance is not None
        and camels_score is not None
        and merton_oriented is not None
        and news_stress is not None
    ):
        return (
            0.23 * boundary_distance
            + 0.23 * camels_score
            + 0.27 * merton_oriented
            + 0.27 * news_stress
        )

    stress_score = _safe_float(doc.get("stressScore"))
    if stress_score is None:
        return None

    if news_stress is not None:
        return 0.73 * stress_score + 0.27 * news_stress
    return stress_score


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

            # Extract SHP totals from the outer shareholdingPattern wrapper
            shp_outer = doc.get("shareholdingPattern") or {}
            total_shares = _safe_int(shp_outer.get("totalShares"))
            total_sh     = _safe_int(shp_outer.get("totalShareholders"))

            # Calculate combined stress using component-weighted formula.
            stress_combined = _calculate_bank_stress(doc)

            session.run(
                MERGE_BANK,
                bankSymbol=symbol,
                bankName=name,
                shpTotalShares=total_shares,
                shpTotalShareholders=total_sh,
                stress=stress_combined,
            )
            symbols_seen.add(symbol)

        # Ensure all 3 target banks exist even if a doc was missing
        for symbol, data in BANK_REGISTRY.items():
            if symbol not in symbols_seen:
                print(f"[bank_node] Warning: {symbol} not found in bank_docs — seeding from registry.")
                session.run(
                    MERGE_BANK,
                    bankSymbol=symbol,
                    bankName=data["bankName"],
                    shpTotalShares=0,
                    shpTotalShareholders=0,
                    stress=None,
                )
                symbols_seen.add(symbol)

    count = len(symbols_seen)
    print(f"[bank_node] Processed {count} :Bank node(s): {sorted(symbols_seen)}")
    return count
