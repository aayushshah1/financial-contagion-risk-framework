// src/graph/neo4jData.ts
import neo4j from 'neo4j-driver';
import type { GraphNode, GraphEdge } from './demoData';

const URI = import.meta.env.VITE_NEO4J_URI || '';
const USER = import.meta.env.VITE_NEO4J_USERNAME || '';
const PASSWORD = import.meta.env.VITE_NEO4J_PASSWORD || '';

const driver = neo4j.driver(URI, neo4j.auth.basic(USER, PASSWORD));

export async function fetchGraphFromNeo4j(): Promise<{ nodes: GraphNode[], edges: GraphEdge[] }> {
    const session = driver.session();
    try {
        // Fetch specifically Banks lending to Companies
        const result = await session.run(`
            MATCH (n:Bank)-[r:LENDS_TO]->(m:Company)
            RETURN n, r, m
            LIMIT 200
        `);

        const nodeMap = new Map<number, GraphNode>();
        const edges: GraphEdge[] = [];

        result.records.forEach(record => {
            const n = record.get('n');
            const r = record.get('r');
            const m = record.get('m');

            if (n && !nodeMap.has(n.identity.toNumber())) {
                nodeMap.set(n.identity.toNumber(), {
                    id: n.identity.toNumber(),
                    labels: n.labels,
                    props: n.properties
                });
            }

            if (m && !nodeMap.has(m.identity.toNumber())) {
                nodeMap.set(m.identity.toNumber(), {
                    id: m.identity.toNumber(),
                    labels: m.labels,
                    props: m.properties
                });
            }

            if (r) {
                // Avoid duplicate edges
                const relId = r.elementId;
                if (!edges.some(e => e.id === relId)) {
                    edges.push({
                        id: relId,
                        source: r.start.toNumber(),
                        target: r.end.toNumber(),
                        type: r.type,
                        props: r.properties
                    });
                }
            }
        });

        // Ensure nodes referenced in edges exist
        const finalNodes = Array.from(nodeMap.values());
        const finalEdges = edges.filter(e => nodeMap.has(e.source) && nodeMap.has(e.target));

        return { nodes: finalNodes, edges: finalEdges };
    } finally {
        await session.close();
    }
}
