/**
 * simBfsGraph — BFS subgraph builder for the Simulator page.
 *
 * Starting from a centerBankId, traverses ALL edges (both directions)
 * up to `depth` hops and returns the induced subgraph.
 */

import type { GraphData, GraphEdge, GraphNode } from './types';

export interface BfsSubgraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** depth-distance from center for each node id */
  depthMap: Map<number, number>;
}

/**
 * Build a subgraph via bidirectional BFS from `centerBankId`.
 *
 * Example: depth=5 means show the center bank, all its direct
 * neighbours (depth 1), their neighbours (depth 2), … up to depth 5.
 * Every node and every edge whose both endpoints are in the visited
 * set are included.
 */
export function buildSimBfsGraph(
  graphData: GraphData,
  centerBankId: number,
  depth = 5,
): BfsSubgraph {
  const nodeById = new Map(graphData.nodes.map((n) => [n.id, n]));

  // Build bidirectional adjacency list
  const adj = new Map<number, number[]>();
  for (const n of graphData.nodes) adj.set(n.id, []);
  for (const e of graphData.edges) {
    adj.get(e.source)?.push(e.target);
    adj.get(e.target)?.push(e.source);
  }

  // BFS
  const depthMap = new Map<number, number>();
  if (!nodeById.has(centerBankId)) {
    return { nodes: [], edges: [], depthMap };
  }

  depthMap.set(centerBankId, 0);
  const queue: { id: number; d: number }[] = [{ id: centerBankId, d: 0 }];

  while (queue.length > 0) {
    const { id, d } = queue.shift()!;
    if (d >= depth) continue;
    for (const neighbour of adj.get(id) ?? []) {
      if (!depthMap.has(neighbour)) {
        depthMap.set(neighbour, d + 1);
        queue.push({ id: neighbour, d: d + 1 });
      }
    }
  }

  const visitedIds = new Set(depthMap.keys());

  const nodes = [...visitedIds]
    .map((id) => nodeById.get(id))
    .filter((n): n is GraphNode => Boolean(n));

  const edges = graphData.edges.filter(
    (e) => visitedIds.has(e.source) && visitedIds.has(e.target),
  );

  return { nodes, edges, depthMap };
}
