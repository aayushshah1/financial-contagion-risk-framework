import type { SimulationChannel } from '../graph/types';

/** Internal indexed representation for fast propagation lookups. */
export interface IndexedSimGraph {
  /** All node ids in the simulation graph. */
  nodeIds: number[];
  /** Base stress per node id, [0, 1]. */
  baseStress: Map<number, number>;
  /** Incoming channels grouped by target node id. */
  incomingChannels: Map<number, SimulationChannel[]>;
  /** All channels for edge-id resolution. */
  allChannels: SimulationChannel[];
}
