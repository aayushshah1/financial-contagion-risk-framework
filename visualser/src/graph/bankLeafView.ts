import type { GraphData, GraphEdge, GraphNode } from './types';

export const MAX_LEAVES_PER_BANK = 5;
export const DEFAULT_NBFC_LIMIT = 20;

interface CandidateLeaf {
  leafId: number;
  edge: GraphEdge;
}

interface LeafSelection {
  leafIds: Set<number>;
  edges: GraphEdge[];
  leafOwnerById: Map<number, number>;
}

export interface BankLeafGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  availableBlueCount: number;
  maxWhiteForCurrentBlue: number;
  appliedBlueCount: number;
  appliedWhiteCount: number;
}

export function isNbfcNode(node: GraphNode): boolean {
  const hasNbfcLabel = node.labels.some((label) => label.toLowerCase().includes('nbfc'));
  const hasNbfcType = typeof node.type === 'string' && node.type.toLowerCase().includes('nbfc');
  const kindProp = node.props.kind;
  const hasNbfcKind = typeof kindProp === 'string' && kindProp.toLowerCase().includes('nbfc');
  const industryName = node.props.industryName;
  const hasNbfcIndustry = typeof industryName === 'string'
    && industryName.toLowerCase().includes('non banking financial company')
    && industryName.toLowerCase().includes('nbfc');
  return hasNbfcLabel || hasNbfcType || hasNbfcKind || hasNbfcIndustry;
}

export function isBankNode(node: GraphNode): boolean {
  const hasBankLabel = node.labels.some((label) => label.toLowerCase().includes('bank'));
  const hasBankType = typeof node.type === 'string' && node.type.toLowerCase().includes('bank');
  // NOTE: NBFCs are NOT banks — isNbfcNode is intentionally excluded here
  return (hasBankLabel || hasBankType) && !isNbfcNode(node);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function buildCandidatesByBank(
  graphData: GraphData,
  selectedBankIds: Set<number>,
): Map<number, CandidateLeaf[]> {
  const nodeById = new Map(graphData.nodes.map((node) => [node.id, node]));
  const perBank = new Map<number, Map<number, GraphEdge>>();

  for (const edge of graphData.edges) {
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) {
      continue;
    }

    const sourceIsBank = isBankNode(sourceNode);
    const targetIsBank = isBankNode(targetNode);
    if (sourceIsBank === targetIsBank) {
      continue;
    }

    const bankId = sourceIsBank ? edge.source : edge.target;
    const leafId = sourceIsBank ? edge.target : edge.source;
    if (!selectedBankIds.has(bankId)) {
      continue;
    }

    const leafNode = nodeById.get(leafId);
    if (!leafNode || isBankNode(leafNode)) {
      continue;
    }

    const bucket = perBank.get(bankId) ?? new Map<number, GraphEdge>();
    if (!bucket.has(leafId)) {
      bucket.set(leafId, edge);
    }
    perBank.set(bankId, bucket);
  }

  const result = new Map<number, CandidateLeaf[]>();
  for (const [bankId, leafMap] of perBank.entries()) {
    const leaves = [...leafMap.entries()]
      .sort(([left], [right]) => left - right)
      .map(([leafId, edge]) => ({ leafId, edge }));
    result.set(bankId, leaves);
  }

  return result;
}

function runLeafSelection(
  selectedBanks: GraphNode[],
  candidatesByBank: Map<number, CandidateLeaf[]>,
  targetWhiteCount: number,
): LeafSelection {
  const selectedLeafIds = new Set<number>();
  const selectedEdges: GraphEdge[] = [];
  const leafOwnerById = new Map<number, number>();
  const perBankCount = new Map<number, number>();
  const cursor = new Map<number, number>();

  while (selectedLeafIds.size < targetWhiteCount) {
    let progressed = false;

    for (const bank of selectedBanks) {
      if (selectedLeafIds.size >= targetWhiteCount) {
        break;
      }

      const used = perBankCount.get(bank.id) ?? 0;
      if (used >= MAX_LEAVES_PER_BANK) {
        continue;
      }

      const candidates = candidatesByBank.get(bank.id) ?? [];
      let index = cursor.get(bank.id) ?? 0;
      while (index < candidates.length && selectedLeafIds.has(candidates[index].leafId)) {
        index += 1;
      }
      cursor.set(bank.id, index);

      if (index >= candidates.length) {
        continue;
      }

      const candidate = candidates[index];
      cursor.set(bank.id, index + 1);
      selectedLeafIds.add(candidate.leafId);
      selectedEdges.push(candidate.edge);
      leafOwnerById.set(candidate.leafId, bank.id);
      perBankCount.set(bank.id, used + 1);
      progressed = true;
    }

    if (!progressed) {
      break;
    }
  }

  return { leafIds: selectedLeafIds, edges: selectedEdges, leafOwnerById };
}

function edgePairKey(left: number, right: number): string {
  return left < right ? `${left}|${right}` : `${right}|${left}`;
}

function buildBankNetworkEdges(
  graphData: GraphData,
  selectedBankIds: Set<number>,
  selectedLeafIds: Set<number>,
  leafOwnerById: Map<number, number>,
): GraphEdge[] {
  const edgeByBankPair = new Map<string, GraphEdge>();
  const nodeById = new Map(graphData.nodes.map((node) => [node.id, node]));

  const resolveBankOwner = (nodeId: number): number | null => {
    if (selectedBankIds.has(nodeId)) {
      return nodeId;
    }

    if (selectedLeafIds.has(nodeId)) {
      return leafOwnerById.get(nodeId) ?? null;
    }

    return null;
  };

  for (const edge of graphData.edges) {
    const sourceOwner = resolveBankOwner(edge.source);
    const targetOwner = resolveBankOwner(edge.target);
    if (sourceOwner === null || targetOwner === null || sourceOwner === targetOwner) {
      continue;
    }

    const pairKey = edgePairKey(sourceOwner, targetOwner);
    if (edgeByBankPair.has(pairKey)) {
      continue;
    }

    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    const directBankEdge = sourceNode && targetNode
      && isBankNode(sourceNode)
      && isBankNode(targetNode)
      && selectedBankIds.has(edge.source)
      && selectedBankIds.has(edge.target);

    if (directBankEdge) {
      edgeByBankPair.set(pairKey, edge);
    } else {
      edgeByBankPair.set(pairKey, {
        id: `bank-link-${pairKey}`,
        source: sourceOwner,
        target: targetOwner,
        type: 'BANK_NETWORK',
        props: {
          derived: true,
          viaEdgeType: edge.type,
        },
        bankGroup: null,
      });
    }
  }

  return [...edgeByBankPair.values()];
}

export function buildBankLeafGraph(
  graphData: GraphData,
  requestedBlueCount: number,
  requestedWhiteCount: number,
  nbfcLimit = DEFAULT_NBFC_LIMIT,
): BankLeafGraph {
  const banks = graphData.nodes.filter(isBankNode).sort((left, right) => left.id - right.id);
  if (banks.length === 0) {
    return {
      nodes: [],
      edges: [],
      availableBlueCount: 0,
      maxWhiteForCurrentBlue: 0,
      appliedBlueCount: 0,
      appliedWhiteCount: 0,
    };
  }

  const clampedBlueCount = clamp(Math.floor(requestedBlueCount), 1, banks.length);
  const selectedBanks = banks.slice(0, clampedBlueCount);
  const selectedBankIds = new Set(selectedBanks.map((bank) => bank.id));
  const candidatesByBank = buildCandidatesByBank(graphData, selectedBankIds);

  const maxSelection = runLeafSelection(selectedBanks, candidatesByBank, Number.MAX_SAFE_INTEGER);
  const maxWhiteForCurrentBlue = maxSelection.leafIds.size;
  const clampedWhiteCount = clamp(Math.floor(requestedWhiteCount), 0, maxWhiteForCurrentBlue);
  const activeSelection = runLeafSelection(selectedBanks, candidatesByBank, clampedWhiteCount);

  const nodeById = new Map(graphData.nodes.map((node) => [node.id, node]));
  let selectedLeaves = [...activeSelection.leafIds]
    .map((leafId) => nodeById.get(leafId))
    .filter((node): node is GraphNode => Boolean(node))
    .sort((left, right) => left.id - right.id);

  // Cap NBFC nodes independently
  let nbfcCount = 0;
  selectedLeaves = selectedLeaves.filter((node) => {
    if (isNbfcNode(node)) {
      if (nbfcCount >= nbfcLimit) return false;
      nbfcCount++;
    }
    return true;
  });

  const nodes = [...selectedBanks, ...selectedLeaves];
  const visibleNodeIds = new Set(nodes.map((node) => node.id));
  const leafEdges = activeSelection.edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
  );
  const bankNetworkEdges = buildBankNetworkEdges(
    graphData,
    selectedBankIds,
    activeSelection.leafIds,
    activeSelection.leafOwnerById,
  ).filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target));
  const edges = [...leafEdges, ...bankNetworkEdges];

  return {
    nodes,
    edges,
    availableBlueCount: banks.length,
    maxWhiteForCurrentBlue,
    appliedBlueCount: selectedBanks.length,
    appliedWhiteCount: selectedLeaves.length,
  };
}
