export type GraphValue =
  | string
  | number
  | boolean
  | null
  | GraphValue[]
  | { [key: string]: GraphValue };

export interface GraphNode {
  id: number;
  labels: string[];
  props: Record<string, GraphValue>;
  bankGroup: string | null;
  type?: string;
}

export interface GraphEdge {
  id: string;
  source: number;
  target: number;
  type: string;
  props: Record<string, GraphValue>;
  bankGroup: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type NodeKind = 'CentralBank' | 'CommercialBank' | 'Company' | 'Leaf';

export interface EnrichedGraphNode extends GraphNode {
  kind: NodeKind;
  displayName: string;
  degree: number;
  indegree: number;
  outdegree: number;
  isRisk: boolean;
  accentColor: string;
}

export interface EnrichedGraphEdge extends GraphEdge {
  accentColor: string;
  isRiskEdge: boolean;
}

export interface RiskCluster {
  id: string;
  label: string;
  bankGroup: string | null;
  accentColor: string;
  nodeIds: number[];
}

export interface EnrichedGraphData {
  nodes: EnrichedGraphNode[];
  edges: EnrichedGraphEdge[];
  clusters: RiskCluster[];
  edgeTypes: string[];
  nodeKinds: NodeKind[];
}

// ---------------------------------------------------------------------------
// Simulation types
// ---------------------------------------------------------------------------

/** A directed propagation link derived from a KG edge. */
export interface SimulationChannel {
  id: string;
  sourceNodeId: number;
  targetNodeId: number;
  /** The original GraphEdge.id this channel was derived from. */
  sourceEdgeId: string;
  /** SHAREHOLDER_OF | SUBSIDIARY_OF | LENDS_TO */
  relationType: string;
  /** Weight in [0, 1]. */
  weight: number;
}

/** Extended graph payload returned by GET /api/graph?variant=simulation. */
export interface SimulationGraphData extends GraphData {
  /** Normalised base stress per node id, values in [0, 1]. */
  nodeBaseStress: Record<number, number>;
  /** Bank node ids that can be shocked. */
  shockableNodeIds: number[];
  /** Directed propagation channels derived from KG edges. */
  channels: SimulationChannel[];
}

/** Per-node simulation result produced by the client-side engine. */
export interface SimulationResultByNode {
  simulatedStress: number;
  deltaStress: number;
  topContributors: Array<{
    fromNodeId: number;
    channelId: string;
    contribution: number;
  }>;
}

/** Full client-side simulation scenario state. */
export interface SimulationScenario {
  enabled: boolean;
  selectedBankId: number | null;
  shockValue: number;
  resultsByNodeId: Record<number, SimulationResultByNode>;
  activeSourceEdgeIds: Set<string>;
  iterations: number;
  impactedCount: number;
}
