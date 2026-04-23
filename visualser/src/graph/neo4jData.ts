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

