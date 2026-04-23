import * as THREE from 'three';
import type { GraphEdge, GraphNode } from './types';
import { isBankNode, isNbfcNode } from './bankLeafView';

export type Topology = 'centralized' | 'decentralized' | 'separated';

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
    // Degree map
    const deg: Record<number, number> = {};
    nodes.forEach(n => deg[n.id] = 0);
    edges.forEach(e => { deg[e.source]++; deg[e.target]++; });

    // ─── Centralized ───
    const layoutC: Record<number, THREE.Vector3> = {};
    if (nodes.length > 0) {
        const hubId = nodes.reduce((a, b) => deg[a.id] > deg[b.id] ? a : b).id;
        layoutC[hubId] = new THREE.Vector3(0, 0, 0);

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

    // ─── Decentralized ───
    const layoutD: Record<number, THREE.Vector3> = {};
    if (nodes.length > 0) {
        const groups: Record<string, GraphNode[]> = {};
        nodes.forEach(n => {
            const lb = n.labels[0] || '_';
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

    // ─── Separated ───
    // Banks: tight inner cluster at center
    // NBFCs: mid-distance ring
    // Leaf / other nodes: outer shell, sub-grouped by label type
    const layoutS: Record<number, THREE.Vector3> = {};
    if (nodes.length > 0) {
        const banks = nodes.filter(n => isBankNode(n));
        const nbfcs = nodes.filter(n => isNbfcNode(n) && !isBankNode(n));
        const others = nodes.filter(n => !isBankNode(n) && !isNbfcNode(n));

        // Banks: inner sphere radius 0.3, sorted most-connected first
        const sortedBanks = [...banks].sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0));
        const bankPts = fibonacciSphere(Math.max(sortedBanks.length, 1), 0.3);
        sortedBanks.forEach((n, i) => {
            layoutS[n.id] = bankPts[i % bankPts.length].clone();
        });

        // NBFCs: mid-shell radius 0.75
        const sortedNbfc = [...nbfcs].sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0));
        const nbfcPts = fibonacciSphere(Math.max(sortedNbfc.length, 1), 0.75);
        sortedNbfc.forEach((n, i) => {
            layoutS[n.id] = nbfcPts[i % nbfcPts.length].clone();
        });

        // Others: outer clusters per label type
        const otherGroups: Record<string, GraphNode[]> = {};
        others.forEach(n => {
            const lb = n.labels[0] || '_';
            if (!otherGroups[lb]) otherGroups[lb] = [];
            otherGroups[lb].push(n);
        });
        const outerGroupKeys = Object.keys(otherGroups);
        const outerGroupPts = fibonacciSphere(Math.max(outerGroupKeys.length, 1), 1.3);
        outerGroupKeys.forEach((lb, gi) => {
            const members = otherGroups[lb];
            const groupCenter = outerGroupPts[gi % outerGroupPts.length].clone();
            const memberPts = fibonacciSphere(Math.max(members.length, 1), 0.2);
            members.forEach((n, mi) => {
                layoutS[n.id] = groupCenter.clone().add(memberPts[mi % memberPts.length]);
            });
        });
    }

    // Normalise all layouts to -2..2 range
    const norm = (pos: Record<number, THREE.Vector3>) => {
        const min = new THREE.Vector3(Infinity, Infinity, Infinity);
        const max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
        Object.values(pos).forEach(p => { min.min(p); max.max(p); });
        const range = Math.max(max.x - min.x, max.y - min.y, max.z - min.z) || 1;
        const res: Record<number, THREE.Vector3> = {};
        Object.entries(pos).forEach(([id, p]) => {
            res[parseInt(id)] = p.clone().sub(min).divideScalar(range).multiplyScalar(4).subScalar(2);
        });
        return res;
    };

    return {
        centralized: norm(layoutC),
        decentralized: norm(layoutD),
        separated: norm(layoutS),
    };
}
