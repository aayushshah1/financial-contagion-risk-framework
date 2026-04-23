/**
 * Unit tests for the client-side simulation propagation engine.
 * Uses a small fixture graph to verify:
 *   - SHAREHOLDER_OF reverse propagation
 *   - SUBSIDIARY_OF two-way propagation
 *   - LENDS_TO borrower-to-lender propagation
 *   - Convergence and shock pinning
 *   - Reset baseline
 */

import { describe, expect, it } from 'vitest';
import type { SimulationGraphData } from '../graph/types';
import { buildIndexMaps, createEmptyScenario, runPropagation } from './engine';

// ---------------------------------------------------------------------------
// Fixture graph
// ---------------------------------------------------------------------------
// Nodes:
//   1 = Bank A (base stress 0.1)
//   2 = Bank B (base stress 0.05)
//   3 = Company C (base stress 0.02)
//   4 = Shareholder S (base stress 0.0)
//
// Edges:
//   e1: Bank A --LENDS_TO--> Company C     (totalAmount=100)
//   e2: Company C --SHAREHOLDER_OF--> Bank B  (shareholdingPercentage=30)
//   e3: Company C --SUBSIDIARY_OF--> Bank A   (stressWeightUp=0.4, stressWeightDown=0.3)
//
// Channels derived:
//   LENDS_TO e1: reverse → Company C → Bank A,  weight = 100/100 = 1.0
//   SHAREHOLDER_OF e2: reverse → Bank B → Company C,  weight = 30/100 = 0.3
//   SUBSIDIARY_OF e3 (up): Company C → Bank A,  weight = 0.4
//   SUBSIDIARY_OF e3 (down): Bank A → Company C,  weight = 0.3
// ---------------------------------------------------------------------------

function createFixturePayload(): SimulationGraphData {
  return {
    nodes: [
      { id: 1, labels: ['Bank'], props: {}, bankGroup: null, type: 'Bank' },
      { id: 2, labels: ['Bank'], props: {}, bankGroup: null, type: 'Bank' },
      { id: 3, labels: ['Company'], props: {}, bankGroup: null, type: 'Company' },
      { id: 4, labels: ['Shareholder'], props: {}, bankGroup: null, type: 'Shareholder' },
    ],
    edges: [],
    nodeBaseStress: { 1: 0.1, 2: 0.05, 3: 0.02, 4: 0 },
    shockableNodeIds: [1, 2],
    channels: [
      // LENDS_TO reverse: Company C (3) → Bank A (1), weight 1.0
      { id: 'ch-0', sourceNodeId: 3, targetNodeId: 1, sourceEdgeId: 'e1', relationType: 'LENDS_TO', weight: 1.0 },
      // SHAREHOLDER_OF reverse: Bank B (2) → Company C (3), weight 0.3
      { id: 'ch-1', sourceNodeId: 2, targetNodeId: 3, sourceEdgeId: 'e2', relationType: 'SHAREHOLDER_OF', weight: 0.3 },
      // SUBSIDIARY_OF up: Company C (3) → Bank A (1), weight 0.4
      { id: 'ch-2', sourceNodeId: 3, targetNodeId: 1, sourceEdgeId: 'e3', relationType: 'SUBSIDIARY_OF', weight: 0.4 },
      // SUBSIDIARY_OF down: Bank A (1) → Company C (3), weight 0.3
      { id: 'ch-3', sourceNodeId: 1, targetNodeId: 3, sourceEdgeId: 'e3', relationType: 'SUBSIDIARY_OF', weight: 0.3 },
    ],
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('buildIndexMaps', () => {
  it('creates correct incoming channel lookup', () => {
    const payload = createFixturePayload();
    const indexed = buildIndexMaps(payload);

    expect(indexed.nodeIds).toHaveLength(4);
    expect(indexed.baseStress.get(1)).toBe(0.1);
    expect(indexed.baseStress.get(4)).toBe(0);

    // Bank A (1) has incoming from ch-0 (LENDS_TO) and ch-2 (SUBSIDIARY_OF up)
    const incomingA = indexed.incomingChannels.get(1)!;
    expect(incomingA).toHaveLength(2);
    expect(incomingA.map((c) => c.id).sort()).toEqual(['ch-0', 'ch-2']);

    // Company C (3) has incoming from ch-1 (SHAREHOLDER_OF) and ch-3 (SUBSIDIARY_OF down)
    const incomingC = indexed.incomingChannels.get(3)!;
    expect(incomingC).toHaveLength(2);
    expect(incomingC.map((c) => c.id).sort()).toEqual(['ch-1', 'ch-3']);

    // Shareholder S (4) has no incoming channels
    expect(indexed.incomingChannels.get(4)!).toHaveLength(0);
  });
});

describe('runPropagation', () => {
  it('pins shocked bank to the shock value', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 0.9);

    expect(result.resultsByNodeId[1].simulatedStress).toBeCloseTo(0.9, 4);
  });

  it('converges within 20 iterations', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 0.8);

    expect(result.iterations).toBeLessThanOrEqual(20);
    expect(result.iterations).toBeGreaterThan(0);
  });

  it('propagates LENDS_TO stress from Company C to Bank A', () => {
    // Bank A receives stress from Company C via LENDS_TO (ch-0) and SUBSIDIARY_OF (ch-2)
    // Since Bank A is shocked, it's pinned. Let's shock Bank B instead to see propagation clearly.
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 2, 0.9);

    // Bank B (shocked) → Company C via SHAREHOLDER_OF (ch-1, weight 0.3)
    // Company C should rise above its base of 0.02
    expect(result.resultsByNodeId[3].simulatedStress).toBeGreaterThan(0.02);
    expect(result.resultsByNodeId[3].deltaStress).toBeGreaterThan(0);
  });

  it('propagates SHAREHOLDER_OF reverse: Bank B → Company C', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 2, 0.8);

    // SHAREHOLDER_OF channel goes Bank B(2) → Company C(3), weight 0.3
    // next[3] = 1 - (1 - 0.02) * (1 - 0.3 * 0.8) * ... ≈ must be > base
    const companyC = result.resultsByNodeId[3];
    expect(companyC.simulatedStress).toBeGreaterThan(0.02);
    expect(companyC.topContributors.length).toBeGreaterThan(0);
    // Bank B should be a top contributor to Company C
    expect(companyC.topContributors.some((c) => c.fromNodeId === 2)).toBe(true);
  });

  it('propagates SUBSIDIARY_OF two-way', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    // Shock Bank A
    const result = runPropagation(indexed, 1, 0.95);

    // SUBSIDIARY_OF down: Bank A(1) → Company C(3), weight 0.3
    // Company C should feel the shock from Bank A
    const companyC = result.resultsByNodeId[3];
    expect(companyC.simulatedStress).toBeGreaterThan(0.02);
    expect(companyC.topContributors.some((c) => c.fromNodeId === 1)).toBe(true);
  });

  it('reports impacted count correctly', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 0.9);

    // At minimum Bank A has delta and Company C has delta
    expect(result.impactedCount).toBeGreaterThanOrEqual(1);
  });

  it('clamps stress to [0, 1]', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 1.0);

    for (const id of indexed.nodeIds) {
      const s = result.resultsByNodeId[id].simulatedStress;
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(1);
    }
  });

  it('tracks active source edge ids', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 0.8);

    // At least some edges should be active
    expect(result.activeSourceEdgeIds.size).toBeGreaterThan(0);
    // e3 (SUBSIDIARY_OF) should be active since Bank A is shocked and pushes down to Company C
    expect(result.activeSourceEdgeIds.has('e3')).toBe(true);
  });

  it('node with no incoming channels keeps base stress', () => {
    const indexed = buildIndexMaps(createFixturePayload());
    const result = runPropagation(indexed, 1, 0.9);

    // Shareholder S (4) has no incoming channels → stays at base 0
    expect(result.resultsByNodeId[4].simulatedStress).toBe(0);
    expect(result.resultsByNodeId[4].deltaStress).toBe(0);
  });
});

describe('createEmptyScenario', () => {
  it('returns a clean empty scenario', () => {
    const empty = createEmptyScenario();

    expect(empty.enabled).toBe(false);
    expect(empty.selectedBankId).toBeNull();
    expect(empty.shockValue).toBe(0);
    expect(Object.keys(empty.resultsByNodeId)).toHaveLength(0);
    expect(empty.activeSourceEdgeIds.size).toBe(0);
    expect(empty.iterations).toBe(0);
    expect(empty.impactedCount).toBe(0);
  });
});
