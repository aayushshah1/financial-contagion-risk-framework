"""
prototype_kg/stress_propagation.py

Iterative stress transmission for the financial knowledge graph.

Model choices for v1:
- Active node labels: Bank, Company, Shareholder
- Round update rule: next = min(1, base + incoming_from_prev_round)
- LENDS_TO flow: reverse stored edge direction (Borrower -> Lender)
    with effective weight = base_weight * lgdMultiplier * tMultiplier
- RELATED_PARTY flow:
    Company -> Bank uses stressWeightUp
    Bank -> Company uses stressWeightDown
- SHAREHOLDER_OF flow: Target -> Owner using shareholdingPercentage / 100
- Missing/invalid weights are skipped
- Optional debug mode captures all incoming transmission transactions
    for one bank symbol (for example SBIN) and writes artifacts to disk.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from neo4j import Driver


ACTIVE_NODE_FILTER = "n:Bank OR n:Company OR n:Shareholder"


FETCH_ACTIVE_NODES = f"""
MATCH (n)
WHERE {ACTIVE_NODE_FILTER}
RETURN elementId(n) AS nodeId,
       labels(n) AS labels,
       coalesce(n.stress, 0.0) AS baseStress,
       n.bankSymbol AS bankSymbol,
       n.cin AS cin,
       n.shareholderName AS shareholderName,
       n.mcaName AS mcaName,
       n.crisilName AS crisilName
"""


FETCH_TRANSMISSION_EDGES = """
CALL () {
    MATCH (lender)-[r:LENDS_TO]->(borrower)
    WHERE (lender:Bank OR lender:Company OR lender:Shareholder)
      AND (borrower:Bank OR borrower:Company OR borrower:Shareholder)
    RETURN elementId(borrower) AS srcId,
           elementId(lender) AS dstId,
                     (
                             coalesce(r.absorption, r.transmittance)
                             * coalesce(r.lgdMultiplier, 1.0)
                             * coalesce(r.tMultiplier, 1.0)
                     ) AS weight,
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


RESET_TO_BASE_FOR_DEBUG = f"""
MATCH (n)
WHERE {ACTIVE_NODE_FILTER}
SET n.stressBase = CASE
    WHEN n:Bank OR n:Company THEN coalesce(n.stress, 0.0)
    ELSE coalesce(n.stressBase, 0.0)
END
WITH n
SET n.stress = n.stressBase
RETURN count(n) AS resetCount
"""


@dataclass(slots=True)
class PropagationConfig:
    max_iterations: int = 20
    epsilon: float = 1e-4
    write_batch_size: int = 1000
    clamp_weights: bool = True
    max_stress: float = 1.0
    debug_target_bank_symbol: str | None = None
    debug_output_dir: str = "logs"


@dataclass(slots=True)
class PropagationResult:
    converged: bool
    iterations_run: int
    max_delta: float
    node_count: int
    edge_count: int
    skipped_edges: int
    debug_artifacts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NodeMeta:
    label: str
    identifier: str
    display_name: str


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


def _clamp_stress(value: float, *, max_stress: float = 1.0) -> float:
    upper = max_stress if isfinite(max_stress) and max_stress > 0.0 else 1.0
    if value < 0.0:
        return 0.0
    if value > upper:
        return upper
    return value


def _build_node_meta(rec) -> NodeMeta:
    labels = rec["labels"] or []
    label = labels[0] if labels else "Unknown"

    if label == "Bank":
        identifier = str(rec.get("bankSymbol") or "UNKNOWN_BANK")
        display_name = identifier
    elif label == "Company":
        identifier = str(rec.get("cin") or "UNKNOWN_CIN")
        display_name = str(rec.get("crisilName") or identifier)
    elif label == "Shareholder":
        identifier = str(rec.get("shareholderName") or "UNKNOWN_SHAREHOLDER")
        display_name = identifier
    else:
        identifier = str(rec.get("nodeId") or "UNKNOWN_NODE")
        display_name = identifier

    return NodeMeta(label=label, identifier=identifier, display_name=display_name)


def _fetch_active_nodes(driver: Driver) -> tuple[dict[str, float], dict[str, NodeMeta]]:
    base_stress: dict[str, float] = {}
    node_meta: dict[str, NodeMeta] = {}

    with driver.session() as session:
        for rec in session.run(FETCH_ACTIVE_NODES):
            node_id = rec["nodeId"]
            base = _safe_float(rec["baseStress"]) or 0.0
            if base < 0:
                base = 0.0
            elif base > 1.0:
                base = 1.0

            base_stress[node_id] = base
            node_meta[node_id] = _build_node_meta(rec)

    return base_stress, node_meta


def _fetch_edges(
    driver: Driver,
    active_node_ids: set[str],
    clamp_weights: bool,
) -> tuple[list[tuple[str, str, float, str]], int, dict[str, int]]:
    edges: list[tuple[str, str, float, str]] = []
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

            edges.append((src_id, dst_id, weight, channel))
            channel_counts[channel] += 1

    return edges, skipped, dict(channel_counts)


def _resolve_output_dir(configured_dir: str) -> Path:
    path = Path(configured_dir)
    if not path.is_absolute():
        path = Path(__file__).parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_debug_artifacts(
    *,
    bank_symbol: str,
    bank_node_id: str,
    output_dir: str,
    converged: bool,
    iterations_run: int,
    epsilon: float,
    max_iterations: int,
    base_stress: float,
    final_stress: float,
    final_round_incoming: float,
    final_round_by_src: dict[str, float],
    final_round_by_channel: dict[str, float],
    cumulative_by_src: dict[str, float],
    round_rows: list[dict],
    transaction_rows: list[dict],
    node_meta: dict[str, NodeMeta],
) -> list[str]:
    out_dir = _resolve_output_dir(output_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = f"stress_debug_{bank_symbol}_{ts}"

    tx_path = out_dir / f"{prefix}_transactions.csv"
    rounds_path = out_dir / f"{prefix}_rounds.csv"
    summary_path = out_dir / f"{prefix}_summary.json"

    if transaction_rows:
        with tx_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "round",
                    "channel",
                    "sourceNodeId",
                    "sourceLabel",
                    "sourceIdentifier",
                    "sourceDisplayName",
                    "sourceStressPrev",
                    "weight",
                    "contribution",
                ],
            )
            writer.writeheader()
            writer.writerows(transaction_rows)
    else:
        with tx_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "round",
                    "channel",
                    "sourceNodeId",
                    "sourceLabel",
                    "sourceIdentifier",
                    "sourceDisplayName",
                    "sourceStressPrev",
                    "weight",
                    "contribution",
                ],
            )
            writer.writeheader()

    if round_rows:
        with rounds_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "round",
                    "targetPrevStress",
                    "targetIncoming",
                    "targetNextStress",
                    "targetDelta",
                    "targetIncreaseOverBase",
                ],
            )
            writer.writeheader()
            writer.writerows(round_rows)
    else:
        with rounds_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "round",
                    "targetPrevStress",
                    "targetIncoming",
                    "targetNextStress",
                    "targetDelta",
                    "targetIncreaseOverBase",
                ],
            )
            writer.writeheader()

    increase = max(0.0, final_stress - base_stress)
    scale = 1.0
    if final_round_incoming > 0.0 and increase < final_round_incoming:
        scale = increase / final_round_incoming

    by_source = []
    for src_id, final_contrib in sorted(final_round_by_src.items(), key=lambda kv: kv[1], reverse=True):
        meta = node_meta.get(src_id, NodeMeta(label="Unknown", identifier=src_id, display_name=src_id))
        attributed = final_contrib * scale
        pct = (attributed / increase * 100.0) if increase > 0.0 else 0.0
        by_source.append(
            {
                "sourceNodeId": src_id,
                "sourceLabel": meta.label,
                "sourceIdentifier": meta.identifier,
                "sourceDisplayName": meta.display_name,
                "finalRoundContribution": final_contrib,
                "attributedIncrease": attributed,
                "percentageOfIncrease": pct,
                "cumulativeContribution": cumulative_by_src.get(src_id, 0.0),
            }
        )

    by_channel = []
    for channel, final_contrib in sorted(final_round_by_channel.items(), key=lambda kv: kv[1], reverse=True):
        attributed = final_contrib * scale
        pct = (attributed / increase * 100.0) if increase > 0.0 else 0.0
        by_channel.append(
            {
                "channel": channel,
                "finalRoundContribution": final_contrib,
                "attributedIncrease": attributed,
                "percentageOfIncrease": pct,
            }
        )

    summary = {
        "targetBankSymbol": bank_symbol,
        "targetNodeId": bank_node_id,
        "converged": converged,
        "iterationsRun": iterations_run,
        "epsilon": epsilon,
        "maxIterations": max_iterations,
        "baseStress": base_stress,
        "finalStress": final_stress,
        "increaseFromBase": increase,
        "finalRoundIncoming": final_round_incoming,
        "capAppliedOnFinalRound": final_round_incoming > increase,
        "finalRoundScaleFactor": scale,
        "percentageDistributionBySource": by_source,
        "percentageDistributionByChannel": by_channel,
    }

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return [str(tx_path), str(rounds_path), str(summary_path)]


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


def _reset_stress_to_base_for_debug(driver: Driver) -> int:
    with driver.session() as session:
        record = session.run(RESET_TO_BASE_FOR_DEBUG).single()
    if not record:
        return 0
    return int(record["resetCount"] or 0)


def _run_propagation_iterations(
    *,
    base_stress: dict[str, float],
    edges: list[tuple[str, str, float, str]],
    cfg: PropagationConfig,
    debug_target_node_id: str | None,
    node_meta: dict[str, NodeMeta] | None,
    source_stress_overrides: dict[str, float] | None,
    log_progress: bool,
) -> tuple[
    dict[str, float],
    bool,
    int,
    float,
    list[dict],
    list[dict],
    dict[str, float],
    dict[str, float],
    float,
    dict[str, float],
]:
    if not base_stress:
        return {}, True, 0, 0.0, [], [], {}, {}, 0.0, {}

    prev = dict(base_stress)
    converged = False
    max_delta = 0.0
    iterations_run = 0
    debug_round_rows: list[dict] = []
    debug_tx_rows: list[dict] = []
    cumulative_by_src: dict[str, float] = defaultdict(float)
    final_round_by_src: dict[str, float] = {}
    final_round_by_channel: dict[str, float] = {}
    final_round_incoming = 0.0
    meta_by_id = node_meta or {}
    overrides = source_stress_overrides or {}

    for iteration in range(1, cfg.max_iterations + 1):
        incoming: dict[str, float] = defaultdict(float)
        round_by_src: dict[str, float] = defaultdict(float)
        round_by_channel: dict[str, float] = defaultdict(float)

        for src_id, dst_id, weight, channel in edges:
            override_val = overrides.get(src_id)
            if override_val is not None:
                src_stress = max(0.0, float(override_val))
            else:
                src_stress = prev.get(src_id, 0.0)
            if src_stress <= 0.0:
                continue

            contribution = src_stress * weight
            incoming[dst_id] += contribution

            if debug_target_node_id and dst_id == debug_target_node_id and contribution > 0.0:
                src_meta = meta_by_id.get(src_id, NodeMeta(label="Unknown", identifier=src_id, display_name=src_id))
                round_by_src[src_id] += contribution
                round_by_channel[channel] += contribution
                cumulative_by_src[src_id] += contribution
                debug_tx_rows.append(
                    {
                        "round": iteration,
                        "channel": channel,
                        "sourceNodeId": src_id,
                        "sourceLabel": src_meta.label,
                        "sourceIdentifier": src_meta.identifier,
                        "sourceDisplayName": src_meta.display_name,
                        "sourceStressPrev": src_stress,
                        "weight": weight,
                        "contribution": contribution,
                    }
                )

        nxt: dict[str, float] = {}
        max_delta = 0.0
        changed = 0
        total_stress = 0.0

        for node_id, base in base_stress.items():
            updated = _clamp_stress(base + incoming.get(node_id, 0.0), max_stress=cfg.max_stress)

            prev_val = prev[node_id]
            delta = abs(updated - prev_val)
            if delta > max_delta:
                max_delta = delta
            if delta > 0.0:
                changed += 1

            nxt[node_id] = updated
            total_stress += updated

        avg_stress = total_stress / len(base_stress)

        if debug_target_node_id:
            target_prev = prev.get(debug_target_node_id, 0.0)
            target_next = nxt.get(debug_target_node_id, 0.0)
            target_incoming = incoming.get(debug_target_node_id, 0.0)
            target_delta = target_next - target_prev
            target_increase = target_next - base_stress[debug_target_node_id]
            debug_round_rows.append(
                {
                    "round": iteration,
                    "targetPrevStress": target_prev,
                    "targetIncoming": target_incoming,
                    "targetNextStress": target_next,
                    "targetDelta": target_delta,
                    "targetIncreaseOverBase": target_increase,
                }
            )
            final_round_by_src = dict(round_by_src)
            final_round_by_channel = dict(round_by_channel)
            final_round_incoming = target_incoming

        if log_progress:
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

    return (
        prev,
        converged,
        iterations_run,
        max_delta,
        debug_round_rows,
        debug_tx_rows,
        final_round_by_src,
        final_round_by_channel,
        final_round_incoming,
        dict(cumulative_by_src),
    )


def run_stress_propagation_in_memory(
    *,
    base_stress: dict[str, float],
    edges: list[tuple[str, str, float, str]],
    config: PropagationConfig | None = None,
    source_stress_overrides: dict[str, float] | None = None,
    skipped_edges: int = 0,
    log_progress: bool = False,
) -> tuple[dict[str, float], PropagationResult]:
    """
    Execute iterative stress transmission on in-memory graph data.
    """
    cfg = config or PropagationConfig()
    normalized_base: dict[str, float] = {}
    normalized_overrides: dict[str, float] = {}

    for node_id, raw_stress in base_stress.items():
        stress = _safe_float(raw_stress)
        normalized_base[str(node_id)] = _clamp_stress(
            stress if stress is not None else 0.0,
            max_stress=cfg.max_stress,
        )

    if source_stress_overrides:
        for node_id, raw_stress in source_stress_overrides.items():
            stress = _safe_float(raw_stress)
            if stress is None or stress <= 0.0:
                continue
            normalized_overrides[str(node_id)] = stress

    final_stress, converged, iterations_run, max_delta, *_ = _run_propagation_iterations(
        base_stress=normalized_base,
        edges=edges,
        cfg=cfg,
        debug_target_node_id=None,
        node_meta=None,
        source_stress_overrides=normalized_overrides,
        log_progress=log_progress,
    )

    if not converged and iterations_run >= cfg.max_iterations and log_progress:
        print(
            "[propagation] Reached max iterations "
            f"({cfg.max_iterations}) before epsilon convergence ({cfg.epsilon})."
        )

    result = PropagationResult(
        converged=converged,
        iterations_run=iterations_run,
        max_delta=max_delta,
        node_count=len(normalized_base),
        edge_count=len(edges),
        skipped_edges=max(0, int(skipped_edges)),
        debug_artifacts=[],
    )
    return final_stress, result


def run_stress_propagation(driver: Driver, config: PropagationConfig | None = None) -> PropagationResult:
    """
    Execute synchronous iterative stress transmission and persist final stress.
    """
    cfg = config or PropagationConfig()

    debug_bank_symbol = (cfg.debug_target_bank_symbol or "").strip().upper()
    if debug_bank_symbol:
        reset_count = _reset_stress_to_base_for_debug(driver)
        print(
            "[propagation][debug] Reset stress to base baseline before propagation "
            f"for {reset_count} active node(s)."
        )

    base_stress, node_meta = _fetch_active_nodes(driver)
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
            debug_artifacts=[],
        )

    edges, skipped_edges, channel_counts = _fetch_edges(
        driver,
        active_node_ids=active_node_ids,
        clamp_weights=cfg.clamp_weights,
    )

    label_counts: dict[str, int] = defaultdict(int)
    for meta in node_meta.values():
        label_counts[meta.label] += 1

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

    debug_target_node_id: str | None = None
    if debug_bank_symbol:
        for node_id, meta in node_meta.items():
            if meta.label == "Bank" and meta.identifier.upper() == debug_bank_symbol:
                debug_target_node_id = node_id
                break
        if debug_target_node_id is None:
            print(
                f"[propagation][debug] Bank symbol '{debug_bank_symbol}' was not found in active nodes. "
                "Skipping debug artifact generation."
            )
        else:
            print(
                f"[propagation][debug] Capturing incoming stress transactions for bank {debug_bank_symbol}."
            )

    (
        final_stress,
        converged,
        iterations_run,
        max_delta,
        debug_round_rows,
        debug_tx_rows,
        final_round_by_src,
        final_round_by_channel,
        final_round_incoming,
        cumulative_by_src,
    ) = _run_propagation_iterations(
        base_stress=base_stress,
        edges=edges,
        cfg=cfg,
        debug_target_node_id=debug_target_node_id,
        node_meta=node_meta,
        source_stress_overrides=None,
        log_progress=True,
    )

    if not converged and iterations_run >= cfg.max_iterations:
        print(
            "[propagation] Reached max iterations "
            f"({cfg.max_iterations}) before epsilon convergence ({cfg.epsilon})."
        )

    _write_final_stress(
        driver,
        final_stress=final_stress,
        base_stress=base_stress,
        batch_size=cfg.write_batch_size,
    )

    debug_artifacts: list[str] = []
    if debug_target_node_id and debug_bank_symbol:
        debug_artifacts = _write_debug_artifacts(
            bank_symbol=debug_bank_symbol,
            bank_node_id=debug_target_node_id,
            output_dir=cfg.debug_output_dir,
            converged=converged,
            iterations_run=iterations_run,
            epsilon=cfg.epsilon,
            max_iterations=cfg.max_iterations,
            base_stress=base_stress[debug_target_node_id],
            final_stress=final_stress[debug_target_node_id],
            final_round_incoming=final_round_incoming,
            final_round_by_src=final_round_by_src,
            final_round_by_channel=final_round_by_channel,
            cumulative_by_src=cumulative_by_src,
            round_rows=debug_round_rows,
            transaction_rows=debug_tx_rows,
            node_meta=node_meta,
        )
        print("[propagation][debug] Saved debug artifacts:")
        for path in debug_artifacts:
            print(f"  - {path}")

    return PropagationResult(
        converged=converged,
        iterations_run=iterations_run,
        max_delta=max_delta,
        node_count=len(active_node_ids),
        edge_count=len(edges),
        skipped_edges=skipped_edges,
        debug_artifacts=debug_artifacts,
    )
