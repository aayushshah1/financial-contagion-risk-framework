import type { GraphData, SimulationGraphData } from './types';

export async function fetchGraphFromNeo4j(): Promise<GraphData> {
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ?? '';
  const graphUrl = `${apiBase}/api/graph`;
  const response = await fetch(graphUrl);

  if (!response.ok) {
    throw new Error(`Graph request failed with ${response.status} (${graphUrl})`);
  }

  return response.json() as Promise<GraphData>;
}

export async function fetchSimulationGraph(): Promise<SimulationGraphData> {
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ?? '';
  const graphUrl = `${apiBase}/api/graph?variant=simulation`;
  const response = await fetch(graphUrl);

  if (!response.ok) {
    throw new Error(`Simulation graph request failed with ${response.status} (${graphUrl})`);
  }

  return response.json() as Promise<SimulationGraphData>;
}

export interface BankListItem {
  id: number;
  name: string;
  labels: string[];
}

/** Fetch just the list of bank names + ids — tiny payload, used for the Simulator picker. */
export async function fetchBankList(): Promise<BankListItem[]> {
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ?? '';
  const url = `${apiBase}/api/banks`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Bank list request failed with ${response.status}`);
  return response.json() as Promise<BankListItem[]>;
}

export interface SimSubgraphPayload extends SimulationGraphData {
  /** depth distance from the center bank for each node id */
  depthMap: Record<number, number>;
}

/** Fetch the BFS subgraph + simulation payload for a single bank — only that bank's neighbourhood. */
export async function fetchSimForBank(bankId: number, depth = 1, maxNodes = 5): Promise<SimSubgraphPayload> {
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ?? '';
  const url = `${apiBase}/api/sim?bankId=${bankId}&depth=${depth}&maxNodes=${maxNodes}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Sim request failed with ${response.status}`);
  return response.json() as Promise<SimSubgraphPayload>;
}
