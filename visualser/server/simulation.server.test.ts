/**
 * Server-side tests for the simulation metadata builder.
 * Verifies:
 *   - Base stress normalization (value > 1 → /100)
 *   - Channel direction correctness per edge type
 *   - Excluded edge types produce no channels
 *   - LENDS_TO weight denominator computed correctly
 */

import { describe, expect, it } from 'vitest';
import type { GraphData, GraphNode, GraphEdge } from '../src/graph/types';
import { buildSimulationPayload } from './index';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeNode(id: number, labels: string[], props: Record<string, unknown> = {}): GraphNode {
  return { id, labels, props: props as GraphNode['props'], bankGroup: null, type: labels[0] };
}

function makeEdge(id: string, source: number, target: number, type: string, props: Record<string, unknown> = {}): GraphEdge {
  return { id, source, target, type, props: props as GraphEdge['props'], bankGroup: null };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('buildSimulationPayload — base stress normalization', () => {
  it('uses node.props.stress as first preference', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank'], { stress: 0.42, stressScore: 0.99 })],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBeCloseTo(0.42, 4);
  });

  it('falls back to stressScore for banks', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank'], { stressScore: 0.35 })],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBeCloseTo(0.35, 4);
  });

  it('falls back to crisilStressScore for companies', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Company'], { crisilStressScore: 0.28 })],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBeCloseTo(0.28, 4);
  });

  it('divides by 100 if value > 1', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank'], { stress: 75 })],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBeCloseTo(0.75, 4);
  });

  it('defaults to 0 for unknown node kinds', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['PrioritySector'], {})],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBe(0);
  });

  it('clamps to [0, 1]', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank'], { stress: 150 })],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.nodeBaseStress[1]).toBeLessThanOrEqual(1);
    expect(result.nodeBaseStress[1]).toBeGreaterThanOrEqual(0);
  });
});

describe('buildSimulationPayload — shockableNodeIds', () => {
  it('only includes bank nodes', () => {
    const graph: GraphData = {
      nodes: [
        makeNode(1, ['Bank'], {}),
        makeNode(2, ['Company'], {}),
        makeNode(3, ['CommercialBank'], {}),
        makeNode(4, ['PrioritySector'], {}),
      ],
      edges: [],
    };
    const result = buildSimulationPayload(graph);
    expect(result.shockableNodeIds).toContain(1);
    expect(result.shockableNodeIds).toContain(3);
    expect(result.shockableNodeIds).not.toContain(2);
    expect(result.shockableNodeIds).not.toContain(4);
  });
});

describe('buildSimulationPayload — channel directions', () => {
  it('SHAREHOLDER_OF creates reverse channel (target → source)', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank']), makeNode(2, ['Company'])],
      edges: [makeEdge('e1', 1, 2, 'SHAREHOLDER_OF', { shareholdingPercentage: 50 })],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(1);
    const ch = result.channels[0];
    expect(ch.sourceNodeId).toBe(2); // target of original edge
    expect(ch.targetNodeId).toBe(1); // source of original edge
    expect(ch.weight).toBeCloseTo(0.5, 4);
    expect(ch.relationType).toBe('SHAREHOLDER_OF');
    expect(ch.sourceEdgeId).toBe('e1');
  });

  it('SUBSIDIARY_OF creates two channels (up and down)', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Company']), makeNode(2, ['Bank'])],
      edges: [makeEdge('e1', 1, 2, 'SUBSIDIARY_OF', { stressWeightUp: 0.6, stressWeightDown: 0.4 })],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(2);

    const up = result.channels.find((c) => c.sourceNodeId === 1 && c.targetNodeId === 2)!;
    expect(up).toBeDefined();
    expect(up.weight).toBeCloseTo(0.6, 4);

    const down = result.channels.find((c) => c.sourceNodeId === 2 && c.targetNodeId === 1)!;
    expect(down).toBeDefined();
    expect(down.weight).toBeCloseTo(0.4, 4);
  });

  it('SUBSIDIARY_OF defaults to 0.5 when weights are missing', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Company']), makeNode(2, ['Bank'])],
      edges: [makeEdge('e1', 1, 2, 'SUBSIDIARY_OF', {})],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(2);
    expect(result.channels[0].weight).toBeCloseTo(0.5, 4);
    expect(result.channels[1].weight).toBeCloseTo(0.5, 4);
  });

  it('LENDS_TO creates reverse channel with normalized weight', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank']), makeNode(2, ['Company']), makeNode(3, ['Company'])],
      edges: [
        makeEdge('e1', 1, 2, 'LENDS_TO', { totalAmount: 60 }),
        makeEdge('e2', 1, 3, 'LENDS_TO', { totalAmount: 40 }),
      ],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(2);

    // Total outgoing for Bank 1 = 60 + 40 = 100
    const ch1 = result.channels.find((c) => c.sourceEdgeId === 'e1')!;
    expect(ch1.sourceNodeId).toBe(2); // borrower
    expect(ch1.targetNodeId).toBe(1); // lender
    expect(ch1.weight).toBeCloseTo(0.6, 4);

    const ch2 = result.channels.find((c) => c.sourceEdgeId === 'e2')!;
    expect(ch2.weight).toBeCloseTo(0.4, 4);
  });
});

describe('buildSimulationPayload — excluded edge types', () => {
  it('does not create channels for RELATED_PARTY', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank']), makeNode(2, ['Company'])],
      edges: [makeEdge('e1', 1, 2, 'RELATED_PARTY', {})],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(0);
  });

  it('does not create channels for BELONGS_TO', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Company']), makeNode(2, ['Industry'])],
      edges: [makeEdge('e1', 1, 2, 'BELONGS_TO', {})],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(0);
  });

  it('does not create channels for PRIORITY_EXPOSURE, HOLDS_ACCOUNT, BANK_NETWORK', () => {
    const graph: GraphData = {
      nodes: [makeNode(1, ['Bank']), makeNode(2, ['PrioritySector']), makeNode(3, ['User'])],
      edges: [
        makeEdge('e1', 1, 2, 'PRIORITY_EXPOSURE', {}),
        makeEdge('e2', 3, 1, 'HOLDS_ACCOUNT', {}),
        makeEdge('e3', 1, 1, 'BANK_NETWORK', {}),
      ],
    };
    const result = buildSimulationPayload(graph);
    expect(result.channels).toHaveLength(0);
  });
});
