"""
prototype_kg/stress_propagation.py

Iterative stress transmission for the financial knowledge graph.

Model choices for v1:
- Active node labels: Bank, Company, Shareholder
- Round update rule: next = min(1, base + incoming_from_prev_round)
- LENDS_TO flow: reverse stored edge direction (Borrower -> Lender)
- RELATED_PARTY flow:
    Company -> Bank uses stressWeightUp
    Bank -> Company uses stressWeightDown
- SHAREHOLDER_OF flow: Target -> Owner using shareholdingPercentage / 100
- Missing/invalid weights are skipped
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite

from neo4j import Driver


ACTIVE_NODE_FILTER = "n:Bank OR n:Company OR n:Shareholder"


FETCH_ACTIVE_NODES = f"""
MATCH (n)
WHERE {ACTIVE_NODE_FILTER}
RETURN elementId(n) AS nodeId, labels(n) AS labels, coalesce(n.stress, 0.0) AS baseStress
"""


FETCH_TRANSMISSION_EDGES = """
CALL {
    MATCH (lender)-[r:LENDS_TO]->(borrower)
    WHERE (lender:Bank OR lender:Company OR lender:Shareholder)
      AND (borrower:Bank OR borrower:Company OR borrower:Shareholder)
    RETURN elementId(borrower) AS srcId,
           elementId(lender) AS dstId,
           coalesce(r.absorption, r.transmittance) AS weight,
           'LENDS_TO' AS channel

    UNION ALL

    MATCH (c:Company)-[r:RELATED_PARTY]->(b:Bank)
    RETURN elementId(c) AS srcId,
           elementId(b) AS dstId,
           r.stressWeightUp AS weight,
           'RELATED_PARTY_UP' AS channel

    UNION ALL

    MATCH (c:Company)-[r:RELATED_PARTY]->(b:Bank)
    RETURN elementId(b) AS srcId,
           elementId(c) AS dstId,
           r.stressWeightDown AS weight,
           'RELATED_PARTY_DOWN' AS channel

    UNION ALL

    MATCH (owner)-[r:SHAREHOLDER_OF]->(target)
    WHERE (owner:Bank OR owner:Company OR owner:Shareholder)
      AND (target:Bank OR target:Company OR target:Shareholder)
    RETURN elementId(target) AS srcId,
           elementId(owner) AS dstId,
           (r.shareholdingPercentage / 100.0) AS weight,
           'SHAREHOLDER_OF' AS channel
}
RETURN srcId, dstId, weight, channel
"""


WRITE_FINAL_STRESS = """
UNWIND $batch AS row
MATCH (n)
WHERE elementId(n) = row.nodeId
SET n.stressBase = row.baseStress,
    n.stress = row.finalStress
"""


@dataclass(slots=True)
class PropagationConfig:
    max_iterations: int = 20
    epsilon: float = 1e-3
    write_batch_size: int = 1000
    clamp_weights: bool = True


@dataclass(slots=True)
class PropagationResult:
    converged: bool
    iterations_run: int
    max_delta: float
    node_count: int
    edge_count: int
    skipped_edges: int


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_weight(raw_weight, clamp_weights: bool) -> float | None:
    weight = _safe_float(raw_weight)
    if weight is None or not isfinite(weight):
        return None
    if weight <= 0:
        return None
    if clamp_weights:
        if weight > 1.0:
            return 1.0
        return weight
    return weight


def _fetch_active_nodes(driver: Driver) -> tuple[dict[str, float], dict[str, str]]:
    base_stress: dict[str, float] = {}
    node_kind: dict[str, str] = {}

    with driver.session() as session:
        for rec in session.run(FETCH_ACTIVE_NODES):
            node_id = rec["nodeId"]
            labels = rec["labels"] or []
            first_label = labels[0] if labels else "Unknown"
            base = _safe_float(rec["baseStress"]) or 0.0
            if base < 0:
                base = 0.0
            elif base > 1.0:
                base = 1.0

            base_stress[node_id] = base
            node_kind[node_id] = first_label

    return base_stress, node_kind


def _fetch_edges(driver: Driver, active_node_ids: set[str], clamp_weights: bool) -> tuple[list[tuple[str, str, float]], int, dict[str, int]]:
    edges: list[tuple[str, str, float]] = []
    skipped = 0
    channel_counts: dict[str, int] = defaultdict(int)

    with driver.session() as session:
        for rec in session.run(FETCH_TRANSMISSION_EDGES):
            src_id = rec["srcId"]
            dst_id = rec["dstId"]
            channel = rec["channel"]

            if src_id not in active_node_ids or dst_id not in active_node_ids:
                skipped += 1
                continue

            weight = _normalize_weight(rec["weight"], clamp_weights=clamp_weights)
            if weight is None:
                skipped += 1
                continue

            edges.append((src_id, dst_id, weight))
            channel_counts[channel] += 1

    return edges, skipped, dict(channel_counts)


def _write_final_stress(driver: Driver, final_stress: dict[str, float], base_stress: dict[str, float], batch_size: int) -> None:
    records = [
        {
            "nodeId": node_id,
            "baseStress": base_stress[node_id],
            "finalStress": stress,
        }
        for node_id, stress in final_stress.items()
    ]

    with driver.session() as session:
        for i in range(0, len(records), batch_size):
            session.run(WRITE_FINAL_STRESS, batch=records[i : i + batch_size])


def run_stress_propagation(driver: Driver, config: PropagationConfig | None = None) -> PropagationResult:
    """
    Execute synchronous iterative stress transmission and persist final stress.
    """
    cfg = config or PropagationConfig()

    base_stress, node_kind = _fetch_active_nodes(driver)
    active_node_ids = set(base_stress.keys())

    if not active_node_ids:
        print("[propagation] No active nodes found. Nothing to propagate.")
        return PropagationResult(
            converged=True,
            iterations_run=0,
            max_delta=0.0,
            node_count=0,
            edge_count=0,
            skipped_edges=0,
        )

    edges, skipped_edges, channel_counts = _fetch_edges(
        driver,
        active_node_ids=active_node_ids,
        clamp_weights=cfg.clamp_weights,
    )

    label_counts: dict[str, int] = defaultdict(int)
    for kind in node_kind.values():
        label_counts[kind] += 1

    print(
        "[propagation] Active nodes: "
        f"total={len(active_node_ids)} "
        f"(Bank={label_counts.get('Bank', 0)}, "
        f"Company={label_counts.get('Company', 0)}, "
        f"Shareholder={label_counts.get('Shareholder', 0)})"
    )
    print(
        "[propagation] Transmission edges: "
        f"kept={len(edges)}, skipped={skipped_edges}, "
        f"LENDS_TO={channel_counts.get('LENDS_TO', 0)}, "
        f"RELATED_PARTY_UP={channel_counts.get('RELATED_PARTY_UP', 0)}, "
        f"RELATED_PARTY_DOWN={channel_counts.get('RELATED_PARTY_DOWN', 0)}, "
        f"SHAREHOLDER_OF={channel_counts.get('SHAREHOLDER_OF', 0)}"
    )

    prev = dict(base_stress)
    converged = False
    max_delta = 0.0
    iterations_run = 0

    for iteration in range(1, cfg.max_iterations + 1):
        incoming: dict[str, float] = defaultdict(float)

        for src_id, dst_id, weight in edges:
            src_stress = prev.get(src_id, 0.0)
            if src_stress <= 0.0:
                continue
            incoming[dst_id] += src_stress * weight

        nxt: dict[str, float] = {}
        max_delta = 0.0
        changed = 0
        total_stress = 0.0

        for node_id, base in base_stress.items():
            updated = base + incoming.get(node_id, 0.0)
            if updated > 1.0:
                updated = 1.0
            elif updated < 0.0:
                updated = 0.0

            prev_val = prev[node_id]
            delta = abs(updated - prev_val)
            if delta > max_delta:
                max_delta = delta
            if delta > 0.0:
                changed += 1

            nxt[node_id] = updated
            total_stress += updated

        avg_stress = total_stress / len(base_stress)
        print(
            f"[propagation] round={iteration:02d} "
            f"max_delta={max_delta:.8f} "
            f"changed={changed} "
            f"avg_stress={avg_stress:.6f}"
        )

        prev = nxt
        iterations_run = iteration

        if max_delta < cfg.epsilon:
            converged = True
            break

    if not converged and iterations_run >= cfg.max_iterations:
        print(
            "[propagation] Reached max iterations "
            f"({cfg.max_iterations}) before epsilon convergence ({cfg.epsilon})."
        )

    _write_final_stress(
        driver,
        final_stress=prev,
        base_stress=base_stress,
        batch_size=cfg.write_batch_size,
    )

    return PropagationResult(
        converged=converged,
        iterations_run=iterations_run,
        max_delta=max_delta,
        node_count=len(active_node_ids),
        edge_count=len(edges),
        skipped_edges=skipped_edges,
    )
