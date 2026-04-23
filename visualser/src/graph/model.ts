import type {
  EnrichedGraphData,
  EnrichedGraphEdge,
  EnrichedGraphNode,
  GraphData,
  GraphNode,
  GraphValue,
  NodeKind,
  RiskCluster,
} from './types';

export const APP_COLORS = {
  bg: '#0d0d0f',
  teal: '#00f5d4',
  red: '#ff4d6d',
  gold: '#ffd60a',
  white: '#e0e0e0',
  muted: '#7d7f87',
  panel: 'rgba(13, 13, 15, 0.86)',
} as const;

const BANK_ACCENTS = [
  '#00f5d4',
  '#4ff5d4',
  '#ffd60a',
  '#ffb703',
  '#ff4d6d',
  '#ff758f',
  '#89fcf3',
  '#ffe066',
];

const DISPLAY_NAME_KEYS = [
  'bankName',
  'crisilName',
  'name',
  'companyName',
  'shareholderName',
  'sectorName',
  'title',
  'cin',
  'bankSymbol',
] as const;

const RISK_KEYS = [
  'flagged',
  'isRisk',
  'riskFlag',
  'highRisk',
  'watchlist',
  'atRisk',
] as const;

function readNumeric(value: GraphValue | undefined): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function percentile(values: number[], ratio: number): number {
  if (values.length === 0) {
    return 0;
  }

  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * ratio)));
  return sorted[index];
}

function flagFromProps(props: Record<string, GraphValue>): boolean {
  return RISK_KEYS.some((key) => {
    const value = props[key];
    if (typeof value === 'boolean') {
      return value;
    }

    if (typeof value === 'number') {
      return value > 0;
    }

    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      return normalized === 'true' || normalized === 'risk' || normalized === 'high';
    }

    return false;
  });
}

export function getNodeDisplayName(node: GraphNode): string {
  for (const key of DISPLAY_NAME_KEYS) {
    const value = node.props[key];
    if (typeof value === 'string' && value.trim().length > 0) {
      return value;
    }
  }

  return `${node.labels[0] ?? 'Node'} ${node.id}`;
}

export function classifyNodeKind(node: GraphNode): NodeKind {
  if (node.labels.includes('CentralBank')) {
    return 'CentralBank';
  }

  if (node.labels.includes('CommercialBank') || node.labels.includes('Bank')) {
    return 'CommercialBank';
  }

  if (node.labels.includes('Company')) {
    return 'Company';
  }

  return 'Leaf';
}

export function getNodeFillColor(node: Pick<EnrichedGraphNode, 'kind' | 'isRisk'>, riskHighlightEnabled = true): string {
  if (riskHighlightEnabled && node.isRisk) {
    return APP_COLORS.red;
  }

  switch (node.kind) {
    case 'CentralBank':
      return APP_COLORS.gold;
    case 'CommercialBank':
      return APP_COLORS.teal;
    case 'Company':
    case 'Leaf':
      return APP_COLORS.white;
    default:
      return APP_COLORS.white;
  }
}

export function getEdgeBaseColor(edge: Pick<EnrichedGraphEdge, 'isRiskEdge' | 'accentColor'>, riskHighlightEnabled = true): string {
  if (riskHighlightEnabled && edge.isRiskEdge) {
    return APP_COLORS.red;
  }

  return edge.accentColor;
}

export function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace('#', '');
  const chunk = normalized.length === 3
    ? normalized.split('').map((part) => part + part).join('')
    : normalized;

  const value = Number.parseInt(chunk, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function enrichGraphData(graphData: GraphData): EnrichedGraphData {
  const inDegree = new Map<number, number>();
  const outDegree = new Map<number, number>();

  for (const node of graphData.nodes) {
    inDegree.set(node.id, 0);
    outDegree.set(node.id, 0);
  }

  for (const edge of graphData.edges) {
    outDegree.set(edge.source, (outDegree.get(edge.source) ?? 0) + 1);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }

  const allInDegrees = graphData.nodes.map((node) => inDegree.get(node.id) ?? 0);
  const inDegreeThreshold = Math.max(2, percentile(allInDegrees, 0.8));
  const stressValues = graphData.nodes
    .map((node) => readNumeric(node.props.stress))
    .filter((value): value is number => value !== null);
  const stressThreshold = Math.max(0.22, percentile(stressValues, 0.85));

  const groupIds = [...new Set(graphData.nodes.map((node) => node.bankGroup).filter((value): value is string => Boolean(value)))];
  const accentMap = new Map<string, string>();
  groupIds.forEach((groupId, index) => {
    accentMap.set(groupId, BANK_ACCENTS[index % BANK_ACCENTS.length]);
  });

  const enrichedNodes: EnrichedGraphNode[] = graphData.nodes.map((node) => {
    const indegree = inDegree.get(node.id) ?? 0;
    const outdegree = outDegree.get(node.id) ?? 0;
    const degree = indegree + outdegree;
    const stress = readNumeric(node.props.stress);
    const kind = classifyNodeKind(node);
    const isRisk = node.labels.includes('Risk')
      || flagFromProps(node.props)
      || indegree >= inDegreeThreshold
      || (stress !== null && stress >= stressThreshold);

    return {
      ...node,
      kind,
      displayName: getNodeDisplayName(node),
      degree,
      indegree,
      outdegree,
      isRisk,
      accentColor: node.bankGroup ? accentMap.get(node.bankGroup) ?? APP_COLORS.teal : APP_COLORS.muted,
    };
  });

  const nodeMap = new Map(enrichedNodes.map((node) => [node.id, node]));
  const adjacency = new Map<number, Set<number>>();

  for (const node of enrichedNodes) {
    adjacency.set(node.id, new Set<number>());
  }

  const enrichedEdges: EnrichedGraphEdge[] = graphData.edges
    .filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
    .map((edge) => {
      adjacency.get(edge.source)?.add(edge.target);
      adjacency.get(edge.target)?.add(edge.source);

      const source = nodeMap.get(edge.source)!;
      const target = nodeMap.get(edge.target)!;
      const accentColor = edge.bankGroup
        ? accentMap.get(edge.bankGroup) ?? source.accentColor
        : source.accentColor !== APP_COLORS.muted
          ? source.accentColor
          : target.accentColor;

      return {
        ...edge,
        bankGroup: edge.bankGroup ?? source.bankGroup ?? target.bankGroup,
        accentColor,
        isRiskEdge: source.isRisk || target.isRisk,
      };
    });

  const clusters: RiskCluster[] = [];
  const clusterGroups = new Map<string, Set<number>>();

  for (const node of enrichedNodes.filter((candidate) => candidate.isRisk)) {
    const clusterKey = node.bankGroup ?? `ungrouped:${node.kind}`;
    const members = clusterGroups.get(clusterKey) ?? new Set<number>();
    members.add(node.id);

    const neighbors = adjacency.get(node.id) ?? new Set<number>();
    for (const neighborId of neighbors) {
      const neighbor = nodeMap.get(neighborId);
      if (!neighbor) {
        continue;
      }

      if (neighbor.bankGroup === node.bankGroup || neighbor.isRisk) {
        members.add(neighborId);
      }
    }

    clusterGroups.set(clusterKey, members);
  }

  for (const [clusterKey, memberIds] of clusterGroups.entries()) {
    if (memberIds.size < 2) {
      continue;
    }

    const firstMember = nodeMap.get([...memberIds][0]);
    if (!firstMember) {
      continue;
    }

    clusters.push({
      id: `cluster:${clusterKey}`,
      label: firstMember.bankGroup ? `${firstMember.bankGroup} risk group` : 'Risk group',
      bankGroup: firstMember.bankGroup,
      accentColor: firstMember.accentColor,
      nodeIds: [...memberIds],
    });
  }

  return {
    nodes: enrichedNodes,
    edges: enrichedEdges,
    clusters,
    edgeTypes: [...new Set(enrichedEdges.map((edge) => edge.type))].sort(),
    nodeKinds: [...new Set(enrichedNodes.map((node) => node.kind))],
  };
}

export function filterGraphData(
  graphData: EnrichedGraphData,
  visibleKinds: Set<NodeKind>,
): EnrichedGraphData {
  const visibleNodes = graphData.nodes.filter((node) => visibleKinds.has(node.kind));
  const nodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = graphData.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const visibleClusters = graphData.clusters
    .map((cluster) => ({
      ...cluster,
      nodeIds: cluster.nodeIds.filter((id) => nodeIds.has(id)),
    }))
    .filter((cluster) => cluster.nodeIds.length >= 2);

  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    clusters: visibleClusters,
    edgeTypes: [...new Set(visibleEdges.map((edge) => edge.type))].sort(),
    nodeKinds: graphData.nodeKinds,
  };
}
