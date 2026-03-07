import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { GraphNode, GraphEdge } from './demoData';
import type { Topology } from './layouts';
import { computeLayouts } from './layouts';

const NodeView = ({ node, pos, isHub, isSelected, isHovered, onClick, onPointerOver, onPointerOut }: { node: GraphNode, pos: THREE.Vector3, isHub: boolean, isSelected: boolean, isHovered: boolean, onClick: () => void, onPointerOver: () => void, onPointerOut: () => void }) => {
    const meshRef = useRef<THREE.Mesh>(null);
    const glowRef = useRef<THREE.Mesh>(null);
    const targetPos = useRef(pos.clone());

    useEffect(() => {
        targetPos.current.copy(pos);
    }, [pos]);

    useFrame((state) => {
        if (meshRef.current) {
            meshRef.current.position.lerp(targetPos.current, 0.08);
        }
        if (glowRef.current) {
            glowRef.current.position.lerp(targetPos.current, 0.08);
            if (isSelected || isHovered || isHub) {
                const s = 1.0 + Math.sin(state.clock.elapsedTime * 2) * 0.1;
                glowRef.current.scale.set(s, s, s);
            }
        }
    });

    const sz = isHub ? 0.08 : 0.05;

    return (
        <group
            onClick={(e) => { e.stopPropagation(); onClick(); }}
            onPointerOver={(e) => { e.stopPropagation(); onPointerOver(); }}
            onPointerOut={(e) => { e.stopPropagation(); onPointerOut(); }}
        >
            {(isSelected || isHovered || isHub) && (
                <mesh ref={glowRef} position={pos}>
                    <sphereGeometry args={[sz * 2.5, 16, 16]} />
                    <meshBasicMaterial color={(isSelected || isHovered) ? "#aaaaaa" : "#555555"} transparent opacity={0.3} blending={THREE.AdditiveBlending} depthWrite={false} />
                </mesh>
            )}
            <mesh ref={meshRef} position={pos} userData={{ nodeId: node.id }}>
                <sphereGeometry args={[sz, 32, 32]} />
                <meshBasicMaterial color={node.labels.includes('Bank') ? "#3b82f6" : "#ffffff"} />
            </mesh>
        </group>
    );
};

const LineNode = 'line' as any;

const EdgeView = ({ edge, sourcePos, targetPos, isSelected, isHovered, isHubEdge, onPointerOver, onPointerOut }: { edge: GraphEdge, sourcePos: THREE.Vector3, targetPos: THREE.Vector3, isSelected: boolean, isHovered: boolean, isHubEdge: boolean, onPointerOver: () => void, onPointerOut: () => void }) => {
    const geom = useMemo(() => new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3)), []);

    useFrame(() => {
        const positions = geom.attributes.position.array as Float32Array;
        positions[0] = sourcePos.x; positions[1] = sourcePos.y; positions[2] = sourcePos.z;
        positions[3] = targetPos.x; positions[4] = targetPos.y; positions[5] = targetPos.z;
        geom.attributes.position.needsUpdate = true;
    });

    const isHighlight = isSelected || isHovered;

    return (
        <group
            onPointerOver={(e) => { e.stopPropagation(); onPointerOver(); }}
            onPointerOut={(e) => { e.stopPropagation(); onPointerOut(); }}
        >
            <LineNode geometry={geom} userData={{ edgeId: edge.id }}>
                <lineBasicMaterial color={isHighlight ? "#ffffff" : isHubEdge ? "#bbbbbb" : "#888888"} transparent opacity={isHighlight ? 1 : 0.7} linewidth={isHighlight ? 2 : 1} />
            </LineNode>

            {isHighlight && (
                <LineNode geometry={geom}>
                    <lineBasicMaterial color="#ffffff" transparent opacity={0.3} linewidth={4} blending={THREE.AdditiveBlending} depthWrite={false} />
                </LineNode>
            )}
        </group>
    );
};

export const GraphCanvas = ({ nodes, edges, topology, onSelectNode, selectedNodeId, onHoverNode, hoveredNodeId, onHoverEdge, hoveredEdgeId, gesturePointer }: { nodes: GraphNode[], edges: GraphEdge[], topology: Topology, onSelectNode: (n: GraphNode | null) => void, selectedNodeId: number | null, onHoverNode: (n: GraphNode | null) => void, hoveredNodeId: number | null, onHoverEdge: (e: GraphEdge | null) => void, hoveredEdgeId: string | null, gesturePointer: { x: number, y: number } | null }) => {
    const layouts = useMemo(() => computeLayouts(nodes, edges), [nodes, edges]);

    // For gesture raycasting
    const { camera, scene } = useThree();
    const raycaster = useRef(new THREE.Raycaster());
    const hoverStartRef = useRef<number>(0);

    useFrame((state) => {
        if (gesturePointer) {
            const x = (gesturePointer.x * 2) - 1;
            const y = -(gesturePointer.y * 2) + 1;
            const vector = new THREE.Vector2(x, y);
            raycaster.current.setFromCamera(vector, camera);
            if (raycaster.current.params.Line) {
                raycaster.current.params.Line.threshold = 0.2; // makes lines easier to catch
            }

            const intersects = raycaster.current.intersectObjects(scene.children, true);
            const hit = intersects.find(h => h.object.userData?.nodeId !== undefined || h.object.userData?.edgeId !== undefined);

            if (hit) {
                if (hit.object.userData.nodeId !== undefined) {
                    const nodeId = hit.object.userData.nodeId;
                    const node = nodes.find(n => n.id === nodeId);
                    if (node) {
                        if (hoveredNodeId !== nodeId) {
                            onHoverNode(node);
                            onHoverEdge(null);
                            hoverStartRef.current = state.clock.elapsedTime;
                        } else if (hoverStartRef.current > 0) {
                            if (state.clock.elapsedTime - hoverStartRef.current > 1.2) {
                                onSelectNode(node);
                                hoverStartRef.current = 0; // prevent rapid firing
                            }
                        }
                        return;
                    }
                } else if (hit.object.userData.edgeId !== undefined) {
                    const edgeId = hit.object.userData.edgeId;
                    const edge = edges.find(e => e.id === edgeId);
                    if (edge) {
                        if (hoveredEdgeId !== edgeId) {
                            onHoverEdge(edge);
                            onHoverNode(null);
                        }
                        return;
                    }
                }
            }
            if (hoveredNodeId !== null || hoveredEdgeId !== null) {
                onHoverNode(null);
                onHoverEdge(null);
            }
        } else {
            hoverStartRef.current = 0;
        }
    });

    // Ident hubs
    const hubs = useMemo(() => {
        const deg: Record<number, number> = {};
        nodes.forEach(n => deg[n.id] = 0);
        edges.forEach(e => { deg[e.source]++; deg[e.target]++; });
        const groups: Record<string, GraphNode[]> = {};
        nodes.forEach(n => {
            const lb = n.labels[0] || "_";
            if (!groups[lb]) groups[lb] = [];
            groups[lb].push(n);
        });
        const hs = new Set<number>();
        Object.values(groups).forEach(members => {
            if (members.length) hs.add(members.reduce((a, b) => deg[a.id] > deg[b.id] ? a : b).id);
        });
        return hs;
    }, [nodes, edges]);

    const positions = layouts[topology];

    const activePos = useRef<Record<number, THREE.Vector3>>({});
    useMemo(() => {
        Object.entries(positions).forEach(([id, p]) => {
            const numId = parseInt(id);
            if (!activePos.current[numId]) {
                activePos.current[numId] = p.clone();
            }
        });
    }, [positions]);

    useFrame(() => {
        // manually lerp the tracking positions for the edges to read
        Object.entries(positions).forEach(([id, p]) => {
            activePos.current[parseInt(id)].lerp(p, 0.08);
        });
    });

    return (
        <group onPointerMissed={() => onSelectNode(null)}>
            {edges.map(e => {
                const sp = activePos.current[Number(e.source)] || new THREE.Vector3(0, 0, 0);
                const tp = activePos.current[Number(e.target)] || new THREE.Vector3(0, 0, 0);
                return (
                    <EdgeView
                        key={`e-${e.id}`}
                        edge={e}
                        sourcePos={sp}
                        targetPos={tp}
                        isSelected={selectedNodeId === e.source || selectedNodeId === e.target}
                        isHovered={hoveredNodeId === e.source || hoveredNodeId === e.target || hoveredEdgeId === e.id}
                        isHubEdge={hubs.has(e.source) || hubs.has(e.target)}
                        onPointerOver={() => onHoverEdge(e)}
                        onPointerOut={() => onHoverEdge(null)}
                    />
                );
            })}

            {nodes.map(n => {
                const isConnectedToSelected = edges.some(e => (e.source === selectedNodeId && e.target === n.id) || (e.target === selectedNodeId && e.source === n.id));
                const isConnectedToHovered = edges.some(e => (e.source === hoveredNodeId && e.target === n.id) || (e.target === hoveredNodeId && e.source === n.id));

                return (
                    <NodeView
                        key={`n-${n.id}`}
                        node={n}
                        pos={positions[n.id]}
                        isHub={hubs.has(n.id)}
                        isSelected={selectedNodeId === n.id || isConnectedToSelected}
                        isHovered={hoveredNodeId === n.id || isConnectedToHovered || (hoveredEdgeId !== null && (edges.find(e => e.id === hoveredEdgeId)?.source === n.id || edges.find(e => e.id === hoveredEdgeId)?.target === n.id))}
                        onClick={() => onSelectNode(n)}
                        onPointerOver={() => onHoverNode(n)}
                        onPointerOut={() => onHoverNode(null)}
                    />
                );
            })}
        </group>
    );
};
