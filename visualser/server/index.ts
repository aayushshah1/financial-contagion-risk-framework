import dotenv from 'dotenv';
import express from 'express';
import neo4j from 'neo4j-driver';
import type { GraphData, GraphEdge, GraphNode, GraphValue, SimulationChannel, SimulationGraphData } from '../src/graph/types.js';

dotenv.config();

const PORT = Number(process.env.PORT ?? 3001);
const NEO4J_URI = process.env.NEO4J_URI ?? process.env.VITE_NEO4J_URI ?? '';
const NEO4J_USERNAME = process.env.NEO4J_USERNAME ?? process.env.VITE_NEO4J_USERNAME ?? '';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD ?? process.env.VITE_NEO4J_PASSWORD ?? '';
const NEO4J_DATABASE = process.env.NEO4J_DATABASE ?? process.env.VITE_NEO4J_DATABASE;

if (!NEO4J_URI || !NEO4J_USERNAME || !NEO4J_PASSWORD) {
  throw new Error('Missing Neo4j connection details. Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD.');
}

const driver = neo4j.driver(
  NEO4J_URI,
  neo4j.auth.basic(NEO4J_USERNAME, NEO4J_PASSWORD),
  { disableLosslessIntegers: true },
);

const app = express();
app.use(express.json());

type RawNode = {
  identity: number;
  labels: string[];
  properties: Record<string, unknown>;
};

type RawRelationship = {
  elementId: string;
  start: number;
  end: number;
  type: string;
  properties: Record<string, unknown>;
};

function serializeValue(value: unknown): GraphValue {
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value as GraphValue;
  }

  if (neo4j.isInt(value)) {
    return value.toNumber();
  }

  if (Array.isArray(value)) {
    return value.map((item) => serializeValue(item));
  }

  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, nested]) => [key, serializeValue(nested)]),
    ) as { [key: string]: GraphValue };
  }

  return String(value);
}

function normalizeNodeType(labels: string[]): string | undefined {
  if (labels.includes('CentralBank')) {
    return 'CentralBank';
  }

  if (labels.includes('CommercialBank') || labels.includes('Bank')) {
    return 'CommercialBank';
  }

  if (labels.includes('Company')) {
    return 'Company';
  }

  if (labels.includes('User')) {
    return 'User';
  }

  if (labels.includes('Shareholder')) {
    return 'Shareholder';
  }

  if (labels.includes('PrioritySector')) {
    return 'PrioritySector';
  }

  if (labels.includes('Industry')) {
    return 'Industry';
  }

  return labels[0];
}

function getGroupName(node: RawNode): string {
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

function createAccumulators() {
  const nodes = new Map<number, GraphNode>();
  const edges = new Map<string, GraphEdge>();

  const addNode = (rawNode: RawNode | null | undefined, bankGroup: string | null) => {
    if (!rawNode) {
      return;
    }

    const existing = nodes.get(rawNode.identity);
    if (existing) {
      if (!existing.bankGroup && bankGroup) {
        existing.bankGroup = bankGroup;
      }
      return;
    }

    nodes.set(rawNode.identity, {
      id: rawNode.identity,
      labels: rawNode.labels,
      props: Object.fromEntries(
        Object.entries(rawNode.properties).map(([key, value]) => [key, serializeValue(value)]),
      ),
      bankGroup,
      type: normalizeNodeType(rawNode.labels),
    });
  };

  const addEdge = (rawRelationship: RawRelationship | null | undefined, bankGroup: string | null) => {
    if (!rawRelationship) {
      return;
    }

    if (!edges.has(rawRelationship.elementId)) {
      edges.set(rawRelationship.elementId, {
        id: rawRelationship.elementId,
        source: rawRelationship.start,
        target: rawRelationship.end,
        type: rawRelationship.type,
        props: Object.fromEntries(
          Object.entries(rawRelationship.properties).map(([key, value]) => [key, serializeValue(value)]),
        ),
        bankGroup,
      });
    }
  };

  const toGraphData = (): GraphData => ({
    nodes: [...nodes.values()],
    edges: [...edges.values()].filter((edge) => nodes.has(edge.source) && nodes.has(edge.target)),
  });

  return { addNode, addEdge, toGraphData, nodes };
}

async function getLabelSet() {
  const session = driver.session({ database: NEO4J_DATABASE });

  try {
    const result = await session.run('CALL db.labels() YIELD label RETURN collect(label) AS labels');
    const labels = result.records[0]?.get('labels') as string[] | undefined;
    return new Set(labels ?? []);
  } finally {
    await session.close();
  }
}

async function fetchModernGraph(): Promise<GraphData> {
  const session = driver.session({ database: NEO4J_DATABASE });
  const { addNode, addEdge, toGraphData } = createAccumulators();

  try {
    const result = await session.run(
      `
        MATCH (central:CentralBank)
        WITH central
        ORDER BY coalesce(central.stress, 0) DESC, coalesce(central.name, central.bankName, '') ASC
        LIMIT $rootLimit
        CALL {
          WITH central
          MATCH (central)-[oversight:OVERSEES]->(commercial:CommercialBank)-[loan:LENDS_TO]->(company:Company)
          WITH oversight, commercial, loan, company
          ORDER BY coalesce(company.stress, 0) DESC, coalesce(company.name, company.crisilName, '') ASC
          LIMIT $loanLimit
          CALL {
            WITH company
            OPTIONAL MATCH (user:User)-[accountRel:HOLDS_ACCOUNT]->(company)
            RETURN collect({ user: user, accountRel: accountRel })[..5] AS userRows
          }
          RETURN collect({
            oversight: oversight,
            commercial: commercial,
            loan: loan,
            company: company,
            userRows: userRows
          }) AS hierarchyRows
        }
        RETURN central, hierarchyRows
      `,
      { rootLimit: neo4j.int(6), loanLimit: neo4j.int(20) },
    );

    for (const record of result.records) {
      const central = record.get('central') as RawNode;
      const bankGroup = getGroupName(central);
      addNode(central, bankGroup);

      const hierarchyRows = record.get('hierarchyRows') as Array<{
        oversight: RawRelationship | null;
        commercial: RawNode | null;
        loan: RawRelationship | null;
        company: RawNode | null;
        userRows: Array<{ user: RawNode | null; accountRel: RawRelationship | null }>;
      }>;

      for (const row of hierarchyRows) {
        addNode(row.commercial, bankGroup);
        addNode(row.company, bankGroup);
        addEdge(row.oversight, bankGroup);
        addEdge(row.loan, bankGroup);

        for (const userRow of row.userRows ?? []) {
          addNode(userRow.user, bankGroup);
          addEdge(userRow.accountRel, bankGroup);
        }
      }
    }

    return toGraphData();
  } finally {
    await session.close();
  }
}

async function fetchLegacyGraph(): Promise<GraphData> {
  const session = driver.session({ database: NEO4J_DATABASE });
  const { addNode, addEdge, toGraphData, nodes } = createAccumulators();

  try {
    const result = await session.run(
      `
        MATCH (bank:Bank)
        WITH bank
        ORDER BY coalesce(bank.stress, 0) DESC, coalesce(bank.bankName, bank.name, '') ASC
        LIMIT $bankLimit
        OPTIONAL MATCH (bank)-[priorityRel:PRIORITY_EXPOSURE]->(sector:PrioritySector)
        WITH bank, collect({ priorityRel: priorityRel, sector: sector })[..2] AS priorityRows
        CALL {
          WITH bank
          MATCH (bank)-[loan:LENDS_TO]->(company:Company)
          WITH loan, company
          ORDER BY coalesce(company.stress, 0) DESC, coalesce(company.crisilName, company.name, '') ASC
          LIMIT $loanLimit
          CALL {
            WITH company
            OPTIONAL MATCH (company)-[industryRel:BELONGS_TO]->(industry:Industry)
            RETURN collect({ industryRel: industryRel, industry: industry })[..1] AS industryRows
          }
          CALL {
            WITH company
            OPTIONAL MATCH (shareholder:Shareholder)-[shareholderRel:SHAREHOLDER_OF]->(company)
            RETURN collect({ shareholderRel: shareholderRel, shareholder: shareholder })[..4] AS shareholderRows
          }
          RETURN collect({
            loan: loan,
            company: company,
            industryRows: industryRows,
            shareholderRows: shareholderRows
          }) AS loanRows
        }
        RETURN bank, priorityRows, loanRows
      `,
      { bankLimit: neo4j.int(8), loanLimit: neo4j.int(14) },
    );

    for (const record of result.records) {
      const bank = record.get('bank') as RawNode;
      const bankGroup = getGroupName(bank);
      addNode(bank, bankGroup);

      const priorityRows = record.get('priorityRows') as Array<{
        priorityRel: RawRelationship | null;
        sector: RawNode | null;
      }>;

      for (const row of priorityRows ?? []) {
        addNode(row.sector, bankGroup);
        addEdge(row.priorityRel, bankGroup);
      }

      const loanRows = record.get('loanRows') as Array<{
        loan: RawRelationship | null;
        company: RawNode | null;
        industryRows: Array<{ industryRel: RawRelationship | null; industry: RawNode | null }>;
        shareholderRows: Array<{ shareholderRel: RawRelationship | null; shareholder: RawNode | null }>;
      }>;

      for (const row of loanRows ?? []) {
        addNode(row.company, bankGroup);
        addEdge(row.loan, bankGroup);

        for (const industryRow of row.industryRows ?? []) {
          addNode(industryRow.industry, bankGroup);
          addEdge(industryRow.industryRel, bankGroup);
        }

        for (const shareholderRow of row.shareholderRows ?? []) {
          addNode(shareholderRow.shareholder, bankGroup);
          addEdge(shareholderRow.shareholderRel, bankGroup);
        }
      }
    }

    const selectedBankNames = [...nodes.values()]
      .filter((node) => node.labels.includes('Bank'))
      .map((node) => node.props.bankName)
      .filter((value): value is string => typeof value === 'string');

    if (selectedBankNames.length > 1) {
      const crossBankResult = await session.run(
        `
          MATCH (source:Bank)-[rel:RELATED_PARTY|SHAREHOLDER_OF]->(target:Bank)
          WHERE source.bankName IN $bankNames AND target.bankName IN $bankNames
          RETURN source, rel, target
        `,
        { bankNames: selectedBankNames },
      );

      for (const record of crossBankResult.records) {
        const source = record.get('source') as RawNode;
        const target = record.get('target') as RawNode;
        const rel = record.get('rel') as RawRelationship;
        const bankGroup = getGroupName(source);
        addNode(source, bankGroup);
        addNode(target, getGroupName(target));
        addEdge(rel, bankGroup);
      }
    }

    return toGraphData();
  } finally {
    await session.close();
  }
}

// ---------------------------------------------------------------------------
// Simulation payload builder (pure, exported for testing)
// ---------------------------------------------------------------------------

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

  // --- nodeBaseStress ---
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

  // --- shockableNodeIds ---
  const shockableNodeIds = graphData.nodes
    .filter(isBankNodeServer)
    .map((n) => n.id);

  // --- LENDS_TO denominator: total outgoing amount per lender ---
  const lenderTotalAmount = new Map<number, number>();
  for (const edge of graphData.edges) {
    if (edge.type !== 'LENDS_TO') continue;
    const amt = readNumericProp(edge.props, 'totalAmount', 'amount', 'weight') ?? 0;
    lenderTotalAmount.set(edge.source, (lenderTotalAmount.get(edge.source) ?? 0) + amt);
  }

  // --- channels ---
  const channels: SimulationChannel[] = [];
  let channelIdx = 0;

  for (const edge of graphData.edges) {
    if (!PROPAGATION_EDGE_TYPES.has(edge.type)) continue;

    if (edge.type === 'SHAREHOLDER_OF') {
      // Reverse: owned(target) → owner(source)
      const pct = readNumericProp(edge.props, 'shareholdingPercentage') ?? 0;
      channels.push({
        id: `ch-${channelIdx++}`,
        sourceNodeId: edge.target,
        targetNodeId: edge.source,
        sourceEdgeId: edge.id,
        relationType: 'SHAREHOLDER_OF',
        weight: clamp01(pct / 100),
      });
    } else if (edge.type === 'SUBSIDIARY_OF') {
      // Two-way: source→target (up) and target→source (down)
      const weightUp = readNumericProp(edge.props, 'stressWeightUp') ?? 0.5;
      const weightDown = readNumericProp(edge.props, 'stressWeightDown') ?? 0.5;
      channels.push({
        id: `ch-${channelIdx++}`,
        sourceNodeId: edge.source,
        targetNodeId: edge.target,
        sourceEdgeId: edge.id,
        relationType: 'SUBSIDIARY_OF',
        weight: clamp01(weightUp),
      });
      channels.push({
        id: `ch-${channelIdx++}`,
        sourceNodeId: edge.target,
        targetNodeId: edge.source,
        sourceEdgeId: edge.id,
        relationType: 'SUBSIDIARY_OF',
        weight: clamp01(weightDown),
      });
    } else if (edge.type === 'LENDS_TO') {
      // Reverse: borrower(target) → lender(source)
      const amt = readNumericProp(edge.props, 'totalAmount', 'amount', 'weight') ?? 0;
      const total = lenderTotalAmount.get(edge.source) ?? 1;
      channels.push({
        id: `ch-${channelIdx++}`,
        sourceNodeId: edge.target,
        targetNodeId: edge.source,
        sourceEdgeId: edge.id,
        relationType: 'LENDS_TO',
        weight: clamp01(total > 0 ? amt / total : 0),
      });
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

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

app.get('/api/health', (_request, response) => {
  response.json({ ok: true });
});

app.get('/api/graph', async (request, response) => {
  try {
    const labels = await getLabelSet();
    const hasModernHierarchy = labels.has('CentralBank') && labels.has('CommercialBank');
    const graphData = hasModernHierarchy
      ? await fetchModernGraph()
      : await fetchLegacyGraph();

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

export default app;

// Only start the HTTP server when running locally (not in a serverless environment)
if (process.env.VERCEL !== '1') {
  const server = app.listen(PORT, () => {
    console.log(`Graph proxy listening on http://localhost:${PORT}`);
  });

  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.on(signal, async () => {
      await driver.close();
      server.close(() => process.exit(0));
    });
  }
}
