/**
 * Pure client-side contagion propagation engine.
 *
 * No React, no side-effects — only deterministic computation on the
 * simulation payload returned by the server.
 */

import type {
  SimulationChannel,
  SimulationGraphData,
  SimulationResultByNode,
  SimulationScenario,
} from '../graph/types';
import type { IndexedSimGraph } from './types';

// ---------------------------------------------------------------------------
// Index construction
// ---------------------------------------------------------------------------

/**
 * Convert the flat server payload into lookup maps for O(1) access
 * during the iterative propagation loop.
 */
export function buildIndexMaps(payload: SimulationGraphData): IndexedSimGraph {
  const nodeIds = payload.nodes.map((n) => n.id);
  const baseStress = new Map<number, number>();

  for (const id of nodeIds) {
    baseStress.set(id, payload.nodeBaseStress[id] ?? 0);
  }

  const incomingChannels = new Map<number, SimulationChannel[]>();
  for (const id of nodeIds) {
    incomingChannels.set(id, []);
  }

  for (const ch of payload.channels) {
    const bucket = incomingChannels.get(ch.targetNodeId);
    if (bucket) {
      bucket.push(ch);
    }
  }

  return {
    nodeIds,
    baseStress,
    incomingChannels,
    allChannels: payload.channels,
  };
}

// ---------------------------------------------------------------------------
// Propagation
// ---------------------------------------------------------------------------

const MAX_ITERATIONS = 20;
const CONVERGENCE_THRESHOLD = 1e-4;
const IMPACT_THRESHOLD = 0.001;

/**
 * Run iterative stress propagation starting from {@link shockedBankId}
 * pinned at {@link shockValue}.
 *
 * Formula per iteration for every node v ≠ shocked bank:
 *   next[v] = 1 - (1 - base[v]) × Π (1 - weight(u→v) × current[u])
 *
 * The shocked bank is pinned to shockValue every iteration.
 * Stops when the max absolute delta < 1e-4 or after 20 iterations.
 */
export function runPropagation(
  indexed: IndexedSimGraph,
  shockedBankId: number,
  shockValue: number,
): SimulationScenario {
  const { nodeIds, baseStress, incomingChannels } = indexed;

  // current stress array – start from base
  const current = new Map<number, number>();
  for (const id of nodeIds) {
    current.set(id, baseStress.get(id) ?? 0);
  }
  // Pin shocked bank
  current.set(shockedBankId, shockValue);

  let iterations = 0;

  for (let iter = 0; iter < MAX_ITERATIONS; iter++) {
    let maxDelta = 0;
    const next = new Map<number, number>();

    for (const id of nodeIds) {
      if (id === shockedBankId) {
        next.set(id, shockValue);
        continue;
      }

      const base = baseStress.get(id) ?? 0;
      const incoming = incomingChannels.get(id) ?? [];

      if (incoming.length === 0) {
        next.set(id, base);
        continue;
      }

      // Π (1 - weight(u→v) × current[u])
      let product = 1;
      for (const ch of incoming) {
        const sourceStress = current.get(ch.sourceNodeId) ?? 0;
        product *= 1 - ch.weight * sourceStress;
      }

      const value = clamp01(1 - (1 - base) * product);
      next.set(id, value);

      const delta = Math.abs(value - (current.get(id) ?? 0));
      if (delta > maxDelta) {
        maxDelta = delta;
      }
    }

    // Update current
    for (const [id, v] of next) {
      current.set(id, v);
    }

    iterations = iter + 1;

    if (maxDelta < CONVERGENCE_THRESHOLD) {
      break;
    }
  }

  // Build per-node results
  const resultsByNodeId: Record<number, SimulationResultByNode> = {};
  const activeSourceEdgeIds = new Set<string>();
  let impactedCount = 0;

  for (const id of nodeIds) {
    const simulated = current.get(id) ?? 0;
    const base = baseStress.get(id) ?? 0;
    const delta = simulated - base;

    // Top contributors
    const incoming = incomingChannels.get(id) ?? [];
    const contributions: Array<{ fromNodeId: number; channelId: string; contribution: number }> = [];

    for (const ch of incoming) {
      const sourceStress = current.get(ch.sourceNodeId) ?? 0;
      const contribution = ch.weight * sourceStress;
      if (contribution > 0) {
        contributions.push({
          fromNodeId: ch.sourceNodeId,
          channelId: ch.id,
          contribution,
        });
        activeSourceEdgeIds.add(ch.sourceEdgeId);
      }
    }

    contributions.sort((a, b) => b.contribution - a.contribution);

    resultsByNodeId[id] = {
      simulatedStress: simulated,
      deltaStress: delta,
      topContributors: contributions.slice(0, 3),
    };

    if (delta > IMPACT_THRESHOLD) {
      impactedCount++;
    }
  }

  return {
    enabled: true,
    selectedBankId: shockedBankId,
    shockValue,
    resultsByNodeId,
    activeSourceEdgeIds,
    iterations,
    impactedCount,
  };
}

// ---------------------------------------------------------------------------
// Reset helper
// ---------------------------------------------------------------------------

export function createEmptyScenario(): SimulationScenario {
  return {
    enabled: false,
    selectedBankId: null,
    shockValue: 0,
    resultsByNodeId: {},
    activeSourceEdgeIds: new Set<string>(),
    iterations: 0,
    impactedCount: 0,
  };
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
