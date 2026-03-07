import * as THREE from 'three';
import type { GraphNode, GraphEdge } from './demoData';

export type Topology = 'centralized' | 'decentralized';

function fibonacciSphere(n: number, radius = 1.0): THREE.Vector3[] {
    const pts: THREE.Vector3[] = [];
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
        const y = 1 - (i / Math.max(n - 1, 1)) * 2;
        const r = Math.sqrt(Math.max(0, 1 - y * y));
        const th = phi * i;
        pts.push(new THREE.Vector3(r * Math.cos(th), y, r * Math.sin(th)).multiplyScalar(radius));
    }
    return pts;
}

export function computeLayouts(nodes: GraphNode[], edges: GraphEdge[]) {
    // 1. degree array
    const deg: Record<number, number> = {};
    nodes.forEach(n => deg[n.id] = 0);
    edges.forEach(e => { deg[e.source]++; deg[e.target]++; });

    // Centralized
    const layoutC: Record<number, THREE.Vector3> = {};
    if (nodes.length > 0) {
        let hubId = nodes.reduce((a, b) => deg[a.id] > deg[b.id] ? a : b).id;
        layoutC[hubId] = new THREE.Vector3(0, 0, 0);

        // simple BFS dist
        const dist: Record<number, number> = { [hubId]: 0 };
        const q = [hubId];
        while (q.length > 0) {
            const curr = q.shift()!;
            edges.forEach(e => {
                const adj = e.source === curr ? e.target : e.target === curr ? e.source : null;
                if (adj !== null && dist[adj] === undefined) {
                    dist[adj] = dist[curr] + 1;
                    q.push(adj);
                }
            });
        }

        const others = nodes.filter(n => n.id !== hubId).sort((a, b) => (dist[a.id] || 99) - (dist[b.id] || 99));
        const spherePts = fibonacciSphere(others.length, 1.0);
        others.forEach((n, i) => {
            const d = dist[n.id] || 3;
            const r = Math.min(0.35 + d * 0.22, 1.0);
            layoutC[n.id] = spherePts[i].multiplyScalar(r);
        });
    }

    // Decentralized
    const layoutD: Record<number, THREE.Vector3> = {};
    if (nodes.length > 0) {
        const groups: Record<string, GraphNode[]> = {};
        nodes.forEach(n => {
            const lb = n.labels[0] || "_";
            if (!groups[lb]) groups[lb] = [];
            groups[lb].push(n);
        });

        const numG = Object.keys(groups).length || 1;
        const hubPts = fibonacciSphere(numG, 0.72);

        Object.values(groups).forEach((members, gi) => {
            const hubPos = hubPts[gi].clone();
            const hub = members.reduce((a, b) => deg[a.id] > deg[b.id] ? a : b);
            layoutD[hub.id] = hubPos.clone();

            const spokes = members.filter(m => m.id !== hub.id);
            if (spokes.length > 0) {
                const spokePts = fibonacciSphere(spokes.length, 0.22);
                spokes.forEach((sp, i) => {
                    layoutD[sp.id] = hubPos.clone().add(spokePts[i]);
                });
            }
        });
    }

    // Normalise
    const norm = (pos: Record<number, THREE.Vector3>) => {
        let min = new THREE.Vector3(Infinity, Infinity, Infinity);
        let max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
        Object.values(pos).forEach(p => {
            min.min(p); max.max(p);
        });
        const range = Math.max(max.x - min.x, max.y - min.y, max.z - min.z) || 1;
        const res: Record<number, THREE.Vector3> = {};
        Object.entries(pos).forEach(([id, p]) => {
            res[parseInt(id)] = p.clone().sub(min).divideScalar(range).multiplyScalar(4).subScalar(2);
            // -2 to 2 scale
        });
        return res;
    };

    return {
        centralized: norm(layoutC),
        decentralized: norm(layoutD)
    };
}
