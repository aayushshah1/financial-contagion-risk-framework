import type { GraphData, GraphEdge, GraphNode } from './types';

// Deterministic random for demo consistency
class PRNG {
    private seed: number;
    constructor(seed: number) { this.seed = seed; }
    next() {
        this.seed = (this.seed * 9301 + 49297) % 233280;
        return this.seed / 233280;
    }
    randint(min: number, max: number) {
        return Math.floor(this.next() * (max - min + 1)) + min;
    }
}

export function generateDemoGraph(): GraphData {
    const rng = new PRNG(42);
    const groups: Record<string, string[]> = {
        "Reserve Bank": ["Atlas Capital", "Birch Finance", "Cascade Trust", "Delta Credit"],
        "National Bank": ["Elm Holdings", "Fjord Energy", "Grove Retail", "Harbor Logistics"],
        "Union Bank": ["Indigo Pharma", "Juniper Foods", "Kite Telecom", "Lumen Mobility"],
    };

    const nodes: GraphNode[] = [];
    let nid = 0;
    const gmap: Record<string, number> = {};

    for (const [bankName, members] of Object.entries(groups)) {
        const bankId = nid;
        nodes.push({
            id: bankId,
            labels: ['CommercialBank'],
            props: {
                bankName,
                bankSymbol: bankName.split(' ')[0].toUpperCase(),
                stress: Number((0.12 + rng.next() * 0.22).toFixed(3)),
            },
            bankGroup: bankName,
            type: 'CommercialBank',
        });
        nid++;

        for (const name of members) {
            nodes.push({
                id: nid,
                labels: ['Company'],
                props: {
                    crisilName: name,
                    stress: Number((rng.next() * 0.36).toFixed(3)),
                    flagged: rng.next() > 0.8,
                },
                bankGroup: bankName,
                type: 'Company',
            });
            gmap[name] = nid;
            nid++;
        }

        gmap[bankName] = bankId;
    }

    const edges: GraphEdge[] = [];
    const rels = ["HOLDS_ACCOUNT", "RELATED_PARTY", "BELONGS_TO"];
    const all_names = Object.values(groups).flat();

    for (const [bankName, members] of Object.entries(groups)) {
        for (const company of members) {
            edges.push({
                id: `e-${edges.length}`,
                source: gmap[bankName],
                target: gmap[company],
                type: "LENDS_TO",
                props: { weight: rng.randint(1, 5) },
                bankGroup: bankName,
            });
        }

        for (let i = 0; i < members.length; i++) {
            for (let j = i + 1; j < members.length; j++) {
                if (rng.next() < 0.35) {
                    edges.push({
                        id: `e-${edges.length}`,
                        source: gmap[members[i]],
                        target: gmap[members[j]],
                        type: rels[rng.randint(0, rels.length - 1)],
                        props: { weight: rng.randint(1, 5) },
                        bankGroup: bankName,
                    });
                }
            }
        }
    }

    for (let i = 0; i < 12; i++) {
        const a = all_names[rng.randint(0, all_names.length - 1)];
        let b = all_names[rng.randint(0, all_names.length - 1)];
        while (a === b) b = all_names[rng.randint(0, all_names.length - 1)];
        edges.push({
            id: `e-${edges.length}`,
            source: gmap[a],
            target: gmap[b],
            type: "RELATED_PARTY",
            props: { weight: 1 },
            bankGroup: null,
        });
    }

    return { nodes, edges };
}
