// src/graph/demoData.ts
export interface GraphNode {
    id: number;
    labels: string[];
    props: Record<string, any>;
}

export interface GraphEdge {
    id: string;
    source: number;
    target: number;
    type: string;
    props: Record<string, any>;
}

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

export function generateDemoGraph(): { nodes: GraphNode[], edges: GraphEdge[] } {
    const rng = new PRNG(42);
    const groups: Record<string, string[]> = {
        "Research": ["Alice", "Bob", "Carol", "Dave", "Eve"],
        "Product": ["Frank", "Grace", "Hank", "Iris", "Jake"],
        "Design": ["Kara", "Leo", "Mia", "Ned", "Ora"],
        "Strategy": ["Pete", "Quinn", "Rosa", "Sam", "Tara"],
    };

    const nodes: GraphNode[] = [];
    let nid = 0;
    const gmap: Record<string, number> = {};

    for (const [dept, members] of Object.entries(groups)) {
        for (const name of members) {
            nodes.push({
                id: nid,
                labels: [dept],
                props: { name, seniority: rng.randint(1, 10) }
            });
            gmap[name] = nid;
            nid++;
        }
    }

    const edges: GraphEdge[] = [];
    const rels = ["COLLABORATES", "REPORTS_TO", "ADVISES", "REVIEWS"];
    const all_names = Object.values(groups).flat();

    // dense within-group
    for (const [members] of Object.entries(groups)) {
        for (let i = 0; i < members.length; i++) {
            for (let j = i + 1; j < members.length; j++) {
                if (rng.next() < 0.6) {
                    edges.push({
                        id: `e-${edges.length}`,
                        source: gmap[members[i]],
                        target: gmap[members[j]],
                        type: rels[rng.randint(0, rels.length - 1)],
                        props: { weight: rng.randint(1, 5) }
                    });
                }
            }
        }
    }

    // few cross-group
    for (let i = 0; i < 12; i++) {
        const a = all_names[rng.randint(0, all_names.length - 1)];
        let b = all_names[rng.randint(0, all_names.length - 1)];
        while (a === b) b = all_names[rng.randint(0, all_names.length - 1)];
        edges.push({
            id: `e-${edges.length}`, source: gmap[a], target: gmap[b], type: "KNOWS", props: { weight: 1 }
        });
    }

    // Ensure fully connected by creating a single global cycle
    for (let i = 0; i < nodes.length; i++) {
        const source = nodes[i].id;
        const target = nodes[(i + 1) % nodes.length].id;
        edges.push({
            id: `e-cycle-${i}`, source, target, type: "CONNECTS", props: { weight: 1 }
        });
    }

    return { nodes, edges };
}
