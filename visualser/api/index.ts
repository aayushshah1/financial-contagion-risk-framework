import dotenv from 'dotenv';
import express from 'express';
import fs from 'fs/promises';
import path from 'path';
import type { GraphData, GraphEdge, GraphNode, GraphValue, SimulationChannel, SimulationGraphData } from '../src/graph/types.js';

dotenv.config();

const PORT = Number(process.env.PORT ?? 3001);

const app = express();
app.use(express.json());

function normalizeNodeType(labels: string[]): string | undefined {
  if (labels.includes('CentralBank')) return 'CentralBank';
  if (labels.includes('CommercialBank') || labels.includes('Bank')) return 'CommercialBank';
  if (labels.includes('Company')) return 'Company';
  if (labels.includes('User')) return 'User';
  if (labels.includes('Shareholder')) return 'Shareholder';
  if (labels.includes('PrioritySector')) return 'PrioritySector';
  if (labels.includes('Industry')) return 'Industry';
  return labels[0];
}

function getGroupName(node: { labels: string[], properties: Record<string, any>, identity: number }): string {
  const props = node.properties;
  const candidates = [
    props.bankName,
    props.name,
    props.crisilName,
    props.bankSymbol,
  ];

  for (const value of candidates) {
    if (typeof value === 'string' && value.trim().length > 0) {
      return value;
    }
  }

  return `${node.labels[0] ?? 'Group'} ${node.identity}`;
}

let cachedGraphData: GraphData | null = null;
let graphLoadPromise: Promise<GraphData> | null = null;

async function fetchJsonGraph(): Promise<GraphData> {
  if (cachedGraphData) return cachedGraphData;
  if (!graphLoadPromise) {
    graphLoadPromise = (async () => {
      const filePath = path.join(process.cwd(), 'neo4j_export.json');
      const content = await fs.readFile(filePath, 'utf-8');
      const d = JSON.parse(content);
      
      let idCounter = 1;
      const idMap = new Map<string, number>();
      
      const getIntId = (strId: string) => {
        if (!idMap.has(strId)) {
          idMap.set(strId, idCounter++);
        }
        return idMap.get(strId)!;
      };

      const nodes = new Map<number, GraphNode>();
      const edges = new Map<string, GraphEdge>();
      
      for (const n of d.nodes) {
        const intId = getIntId(n.id);
        const rawNode = {
          identity: intId,
          labels: n.labels || [],
          properties: n.props || {}
        };
        const bankGroup = getGroupName(rawNode);
        nodes.set(intId, {
          id: intId,
          labels: n.labels || [],
          props: n.props || {},
          bankGroup,
          type: normalizeNodeType(n.labels || [])
        });
      }

      for (const r of d.relationships) {
        const startIntId = getIntId(r.start_node);
        const endIntId = getIntId(r.end_node);
        
        const bankGroup = nodes.get(startIntId)?.bankGroup ?? null;
        
        edges.set(r.id, {
          id: r.id,
          source: startIntId,
          target: endIntId,
          type: r.type,
          props: r.props || {},
          bankGroup
        });
      }

      const validEdges = [...edges.values()].filter(e => nodes.has(e.source) && nodes.has(e.target));
      
      cachedGraphData = {
        nodes: [...nodes.values()],
        edges: validEdges
      };
      
      return cachedGraphData;
    })();
  }
  return graphLoadPromise;
}

const PROPAGATION_EDGE_TYPES = new Set(['SHAREHOLDER_OF', 'SUBSIDIARY_OF', 'LENDS_TO']);

function isBankNodeServer(node: GraphNode): boolean {
  return node.labels.some((l) => l.toLowerCase().includes('bank'));
}

function isCompanyNodeServer(node: GraphNode): boolean {
  return node.labels.includes('Company');
}

function readNumericProp(props: Record<string, GraphValue>, ...keys: string[]): number | null {
  for (const key of keys) {
    const v = props[key];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string') {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function buildSimulationPayload(graphData: GraphData): SimulationGraphData {
  const nodeBaseStress: Record<number, number> = {};
  for (const node of graphData.nodes) {
    let raw = readNumericProp(node.props, 'stress');
    if (raw === null && isBankNodeServer(node)) {
      raw = readNumericProp(node.props, 'stressScore');
    }
    if (raw === null && isCompanyNodeServer(node)) {
      raw = readNumericProp(node.props, 'crisilStressScore');
    }
    if (raw !== null) {
      if (raw > 1) raw = raw / 100;
      nodeBaseStress[node.id] = clamp01(raw);
    } else {
      nodeBaseStress[node.id] = 0;
    }
  }

  const shockableNodeIds = graphData.nodes
    .filter(isBankNodeServer)
    .map((n) => n.id);

  const lenderTotalAmount = new Map<number, number>();
  for (const edge of graphData.edges) {
    if (edge.type !== 'LENDS_TO') continue;
    const amt = readNumericProp(edge.props, 'totalAmount', 'amount', 'weight') ?? 0;
    lenderTotalAmount.set(edge.source, (lenderTotalAmount.get(edge.source) ?? 0) + amt);
  }

  // Track which (source,target) pairs already have a channel to avoid duplicates
  const channelPairs = new Set<string>();
  const channels: SimulationChannel[] = [];
  let channelIdx = 0;

  function addChannel(
    sourceNodeId: number,
    targetNodeId: number,
    sourceEdgeId: string,
    relationType: SimulationChannel['relationType'],
    weight: number,
  ) {
    const key = `${sourceNodeId}->${targetNodeId}@${sourceEdgeId}`;
    if (channelPairs.has(key)) return;
    channelPairs.add(key);
    channels.push({
      id: `ch-${channelIdx++}`,
      sourceNodeId,
      targetNodeId,
      sourceEdgeId,
      relationType,
      weight: clamp01(weight),
    });
  }

  for (const edge of graphData.edges) {
    if (edge.type === 'SHAREHOLDER_OF') {
      // A company (edge.source) is a shareholder OF edge.target (the bank/entity).
      // Classic direction: company stress → bank stress (already existed)
      const pct = readNumericProp(edge.props, 'shareholdingPercentage') ?? 5;
      const weight = clamp01(pct / 100);
      addChannel(edge.target, edge.source, edge.id, 'SHAREHOLDER_OF', weight);
      // NEW outward: if bank is stressed, its shareholding companies are also at risk
      addChannel(edge.source, edge.target, edge.id, 'SHAREHOLDER_OF', weight * 0.6);

    } else if (edge.type === 'SUBSIDIARY_OF') {
      // Fully bidirectional (already existed, just use the helper now)
      const weightUp   = readNumericProp(edge.props, 'stressWeightUp')   ?? 0.5;
      const weightDown = readNumericProp(edge.props, 'stressWeightDown') ?? 0.5;
      addChannel(edge.source, edge.target, edge.id, 'SUBSIDIARY_OF', weightUp);
      addChannel(edge.target, edge.source, edge.id, 'SUBSIDIARY_OF', weightDown);

    } else if (edge.type === 'LENDS_TO') {
      // Bank (edge.source) lends to borrower (edge.target).
      const amt   = readNumericProp(edge.props, 'totalAmount', 'amount', 'weight') ?? 0;
      const total = lenderTotalAmount.get(edge.source) ?? 1;
      const lendingShare = clamp01(total > 0 ? amt / total : 0);

      // Classic: if borrower defaults → lender (bank) is stressed
      addChannel(edge.target, edge.source, edge.id, 'LENDS_TO', lendingShare);

      // NEW outward: if bank is under stress (capital crunch) → borrowers lose credit access
      // Weight is proportional to how dependent the borrower is on this particular lender.
      // We use a fixed moderate weight since we don't have borrower-side data.
      addChannel(edge.source, edge.target, edge.id, 'LENDS_TO', Math.min(lendingShare * 0.7, 0.6));

    } else {
      // All other edges: create weak bidirectional contagion so the BFS graph
      // actually shows some propagation effect for any connected node.
      const WEAK = 0.15;
      addChannel(edge.source, edge.target, edge.id, 'LENDS_TO', WEAK);
      addChannel(edge.target, edge.source, edge.id, 'LENDS_TO', WEAK);
    }
  }

  return {
    nodes: graphData.nodes,
    edges: graphData.edges,
    nodeBaseStress,
    shockableNodeIds,
    channels,
  };
}

app.get('/api/health', (_request, response) => {
  response.json({ ok: true });
});

app.get('/api/graph', async (request, response) => {
  try {
    const graphData = await fetchJsonGraph();

    const variant = request.query.variant;
    if (variant === 'simulation') {
      const simulationPayload = buildSimulationPayload(graphData);
      response.json(simulationPayload);
    } else {
      response.json(graphData);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown graph error';
    response.status(500).json({ error: message });
  }
});

// ---------------------------------------------------------------------------
// GET /api/banks  — returns just the list of bank nodes (id + name) for the
//                  Simulator bank picker. Tiny payload (~few KB).
// ---------------------------------------------------------------------------
app.get('/api/banks', async (_request, response) => {
  try {
    const graphData = await fetchJsonGraph();
    const banks = graphData.nodes
      .filter(isBankNodeServer)
      .map((n) => {
        const p = n.props;
        const name =
          (typeof p.bankName === 'string' && p.bankName.trim() ? p.bankName.trim() : null) ??
          (typeof p.name    === 'string' && p.name.trim()     ? p.name.trim()     : null) ??
          (typeof p.crisilName === 'string' && p.crisilName.trim() ? p.crisilName.trim() : null) ??
          `Bank #${n.id}`;
        return { id: n.id, name, labels: n.labels };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
    response.json(banks);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    response.status(500).json({ error: message });
  }
});

// ---------------------------------------------------------------------------
// GET /api/sim?bankId=X&depth=N&maxNodes=M
//   Layered BFS: allocates nodes per depth level so you always get
//   second-hop nodes even when the cap is small.
//   - 60% of maxNodes budget: direct neighbors (depth 1)
//   - 40% of maxNodes budget: second-hop neighbors (depth 2+)
//   Neighbors within each layer sorted by degree (most-connected first).
// ---------------------------------------------------------------------------
app.get('/api/sim', async (request, response) => {
  try {
    const graphData = await fetchJsonGraph();

    const bankId   = parseInt(String(request.query.bankId   ?? ''), 10);
    const depth    = Math.min(Math.max(parseInt(String(request.query.depth    ?? '2'), 10), 1), 10);
    const maxNodes = Math.min(Math.max(parseInt(String(request.query.maxNodes ?? '8'), 10), 1), 500);

    if (isNaN(bankId)) {
      response.status(400).json({ error: 'bankId query param required' });
      return;
    }

    // Degree map for sorting neighbors by importance
    const degree = new Map<number, number>();
    for (const n of graphData.nodes) degree.set(n.id, 0);
    for (const e of graphData.edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }

    // Bidirectional adjacency
    const adj = new Map<number, number[]>();
    for (const n of graphData.nodes) adj.set(n.id, []);
    for (const e of graphData.edges) {
      adj.get(e.source)?.push(e.target);
      adj.get(e.target)?.push(e.source);
    }
    // Sort each list by degree descending
    for (const [, neighbors] of adj) {
      neighbors.sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0));
    }

    // Layered BFS: allocate budget per depth level
    // Level 1 gets 60%, deeper levels share the remaining 40%
    const level1Budget = Math.max(1, Math.ceil(maxNodes * 0.6));
    const deepBudget   = maxNodes - level1Budget;

    const depthMap = new Map<number, number>();
    depthMap.set(bankId, 0);

    // --- Level 1 ---
    const level1Nodes: number[] = [];
    for (const nb of adj.get(bankId) ?? []) {
      if (depthMap.has(nb)) continue;
      if (level1Nodes.length >= level1Budget) break;
      depthMap.set(nb, 1);
      level1Nodes.push(nb);
    }

    // --- Levels 2..depth ---
    let prevLevelNodes = level1Nodes;
    let remaining = deepBudget;

    for (let d = 2; d <= depth && remaining > 0; d++) {
      const thisLevelNodes: number[] = [];

      // Collect all candidates from previous level, deduplicated, sorted by degree
      const candidates: number[] = [];
      for (const pid of prevLevelNodes) {
        for (const nb of adj.get(pid) ?? []) {
          if (!depthMap.has(nb)) candidates.push(nb);
        }
      }
      // Deduplicate preserving order, then sort by degree desc
      const seen = new Set<number>();
      const uniqueCandidates = candidates.filter(id => {
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      });
      uniqueCandidates.sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0));

      // Take up to `remaining` from this level
      const takeCount = Math.min(remaining, uniqueCandidates.length);
      for (let i = 0; i < takeCount; i++) {
        const nb = uniqueCandidates[i];
        depthMap.set(nb, d);
        thisLevelNodes.push(nb);
      }

      remaining -= thisLevelNodes.length;
      prevLevelNodes = thisLevelNodes;
    }

    const visitedIds = new Set(depthMap.keys());
    const subNodes   = graphData.nodes.filter((n) => visitedIds.has(n.id));
    const subEdges   = graphData.edges.filter((e) => visitedIds.has(e.source) && visitedIds.has(e.target));

    const subGraph: GraphData = { nodes: subNodes, edges: subEdges };
    const simPayload = buildSimulationPayload(subGraph);

    response.json({
      ...simPayload,
      depthMap: Object.fromEntries(depthMap),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    response.status(500).json({ error: message });
  }
});

export default app;

if (process.env.VERCEL !== '1') {
  const server = app.listen(PORT, () => {
    console.log(`Graph proxy listening on http://localhost:${PORT}`);
  });

  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.on(signal as NodeJS.Signals, async () => {
      server.close(() => process.exit(0));
    });
  }
}
