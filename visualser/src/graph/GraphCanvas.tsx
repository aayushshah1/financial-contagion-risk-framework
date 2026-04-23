import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { isBankNode, isNbfcNode } from './bankLeafView';
import type { GraphEdge, GraphNode, SimulationResultByNode } from './types';
import type { Topology } from './layouts';
import { computeLayouts } from './layouts';

// ---------------------------------------------------------------------------
// Colour helpers for simulation heat overlay
// ---------------------------------------------------------------------------

const BASE_BLUE = new THREE.Color('#3b82f6');
const BASE_YELLOW = new THREE.Color('#facc15');
const BASE_WHITE = new THREE.Color('#ffffff');
const HEAT_RED = new THREE.Color('#ff2d2d');

function getBaseColor(node: GraphNode): THREE.Color {
    if (isNbfcNode(node)) return BASE_YELLOW.clone();
    if (isBankNode(node)) return BASE_BLUE.clone();
    return BASE_WHITE.clone();
}

function blendHeat(base: THREE.Color, delta: number): THREE.Color {
    if (delta <= 0) return base;
    const t = Math.min(delta * 2.5, 1);
    return base.clone().lerp(HEAT_RED, t);
}

// ---------------------------------------------------------------------------
// Node
// ---------------------------------------------------------------------------

const NodeView = ({
    node, pos, isHub, isSelected, isHovered, deltaStress, isShockedBank,
    isFocused, hasFocusMode,
    onClick, onPointerOver, onPointerOut,
}: {
    node: GraphNode; pos: THREE.Vector3; isHub: boolean; isSelected: boolean; isHovered: boolean;
    deltaStress: number; isShockedBank: boolean;
    isFocused: boolean; hasFocusMode: boolean;
    onClick: () => void; onPointerOver: () => void; onPointerOut: () => void;
}) => {
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
            if (isShockedBank) {
                const s = 1.0 + Math.sin(state.clock.elapsedTime * 4) * 0.25;
                glowRef.current.scale.set(s, s, s);
            } else if (isSelected || isHovered || isHub || deltaStress > 0.001) {
                const s = 1.0 + Math.sin(state.clock.elapsedTime * 2) * 0.1;
                glowRef.current.scale.set(s, s, s);
            }
        }
    });

    const sz = isHub ? 0.08 : 0.05;
    const baseColor = getBaseColor(node);
    const displayColor = blendHeat(baseColor, deltaStress);

    // Out-of-focus dimming
    const dimmed = hasFocusMode && !isFocused;
    const opacity = dimmed ? 0.08 : 1;

    const showGlow = !dimmed && (isSelected || isHovered || isHub || isShockedBank || deltaStress > 0.001);
    const glowColor = isShockedBank
        ? '#ff4444'
        : deltaStress > 0.001
            ? '#ff6644'
            : (isSelected || isHovered) ? '#aaaaaa' : '#555555';
    const glowOpacity = isShockedBank ? 0.5 : deltaStress > 0.001 ? (0.2 + deltaStress * 0.5) : 0.3;

    return (
        <group
            onClick={(e) => { if (!dimmed) { e.stopPropagation(); onClick(); } }}
            onPointerOver={(e) => { if (!dimmed) { e.stopPropagation(); onPointerOver(); } }}
            onPointerOut={(e) => { e.stopPropagation(); onPointerOut(); }}
        >
            {showGlow && (
                <mesh ref={glowRef} position={pos}>
                    <sphereGeometry args={[sz * (isShockedBank ? 3.5 : 2.5), 16, 16]} />
                    <meshBasicMaterial color={glowColor} transparent opacity={glowOpacity} blending={THREE.AdditiveBlending} depthWrite={false} />
                </mesh>
            )}
            <mesh ref={meshRef} position={pos} userData={{ nodeId: node.id }}>
                <sphereGeometry args={[sz, 32, 32]} />
                <meshBasicMaterial color={`#${displayColor.getHexString()}`} transparent opacity={opacity} depthWrite={!dimmed} />
            </mesh>
        </group>
    );
};

// ---------------------------------------------------------------------------
// Edge
// ---------------------------------------------------------------------------

const LineNode = 'line' as any;

const EdgeView = ({
    edge, sourcePos, targetPos, isSelected, isHovered, isHubEdge, isActiveChannel,
    isFocused, hasFocusMode,
    onPointerOver, onPointerOut,
}: {
    edge: GraphEdge; sourcePos: THREE.Vector3; targetPos: THREE.Vector3;
    isSelected: boolean; isHovered: boolean; isHubEdge: boolean; isActiveChannel: boolean;
    isFocused: boolean; hasFocusMode: boolean;
    onPointerOver: () => void; onPointerOut: () => void;
}) => {
    const geom = useMemo(() => new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3)), []);

    useFrame(() => {
        const positions = geom.attributes.position.array as Float32Array;
        positions[0] = sourcePos.x; positions[1] = sourcePos.y; positions[2] = sourcePos.z;
        positions[3] = targetPos.x; positions[4] = targetPos.y; positions[5] = targetPos.z;
        geom.attributes.position.needsUpdate = true;
    });

    const dimmed = hasFocusMode && !isFocused;
    const isHighlight = isSelected || isHovered;
    const edgeColor = isHighlight
        ? '#ffffff'
        : isActiveChannel
            ? '#ff8844'
            : isHubEdge ? '#bbbbbb' : '#888888';
    const edgeOpacity = dimmed ? 0.04 : isHighlight ? 1 : isActiveChannel ? 0.9 : 0.7;

    return (
        <group
            onPointerOver={(e) => { e.stopPropagation(); onPointerOver(); }}
            onPointerOut={(e) => { e.stopPropagation(); onPointerOut(); }}
        >
            <LineNode geometry={geom} userData={{ edgeId: edge.id }}>
                <lineBasicMaterial color={edgeColor} transparent opacity={edgeOpacity} linewidth={isHighlight ? 2 : isActiveChannel ? 2 : 1} />
            </LineNode>

            {!dimmed && (isHighlight || isActiveChannel) && (
                <LineNode geometry={geom}>
                    <lineBasicMaterial color={isActiveChannel ? '#ff6622' : '#ffffff'} transparent opacity={0.3} linewidth={4} blending={THREE.AdditiveBlending} depthWrite={false} />
                </LineNode>
            )}
        </group>
    );
};

// ---------------------------------------------------------------------------
// Canvas
// ---------------------------------------------------------------------------

export const GraphCanvas = ({
    nodes, edges, topology, onSelectNode, selectedNodeId, onHoverNode, hoveredNodeId,
    onHoverEdge, hoveredEdgeId, gesturePointer,
    simulationResults, simulationActiveEdgeIds, shockedBankId,
    focusNodeIds,
}: {
    nodes: GraphNode[]; edges: GraphEdge[]; topology: Topology;
    onSelectNode: (n: GraphNode | null) => void; selectedNodeId: number | null;
    onHoverNode: (n: GraphNode | null) => void; hoveredNodeId: number | null;
    onHoverEdge: (e: GraphEdge | null) => void; hoveredEdgeId: string | null;
    gesturePointer: { x: number; y: number } | null;
    simulationResults?: Record<number, SimulationResultByNode>;
    simulationActiveEdgeIds?: Set<string>;
    shockedBankId?: number | null;
    focusNodeIds?: Set<number> | null;
}) => {
    const layouts = useMemo(() => computeLayouts(nodes, edges), [nodes, edges]);
    const hasFocusMode = Boolean(focusNodeIds && focusNodeIds.size > 0);

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
                raycaster.current.params.Line.threshold = 0.2;
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
                                hoverStartRef.current = 0;
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

    // Hub identification
    const hubs = useMemo(() => {
        const deg: Record<number, number> = {};
        nodes.forEach(n => deg[n.id] = 0);
        edges.forEach(e => { deg[e.source]++; deg[e.target]++; });
        const groups: Record<string, GraphNode[]> = {};
        nodes.forEach(n => {
            const lb = n.labels[0] || '_';
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
        Object.entries(positions).forEach(([id, p]) => {
            activePos.current[parseInt(id)].lerp(p, 0.08);
        });
    });

    return (
        <group onPointerMissed={() => onSelectNode(null)}>
            {edges.map(e => {
                const sp = activePos.current[Number(e.source)] || new THREE.Vector3(0, 0, 0);
                const tp = activePos.current[Number(e.target)] || new THREE.Vector3(0, 0, 0);
                const edgeFocused = !hasFocusMode || (focusNodeIds!.has(e.source) && focusNodeIds!.has(e.target));
                return (
                    <EdgeView
                        key={`e-${e.id}`}
                        edge={e}
                        sourcePos={sp}
                        targetPos={tp}
                        isSelected={selectedNodeId === e.source || selectedNodeId === e.target}
                        isHovered={hoveredNodeId === e.source || hoveredNodeId === e.target || hoveredEdgeId === e.id}
                        isHubEdge={hubs.has(e.source) || hubs.has(e.target)}
                        isActiveChannel={simulationActiveEdgeIds?.has(e.id) ?? false}
                        isFocused={edgeFocused}
                        hasFocusMode={hasFocusMode}
                        onPointerOver={() => onHoverEdge(e)}
                        onPointerOut={() => onHoverEdge(null)}
                    />
                );
            })}

            {nodes.map(n => {
                const isConnectedToSelected = edges.some(e => (e.source === selectedNodeId && e.target === n.id) || (e.target === selectedNodeId && e.source === n.id));
                const isConnectedToHovered = edges.some(e => (e.source === hoveredNodeId && e.target === n.id) || (e.target === hoveredNodeId && e.source === n.id));
                const simResult = simulationResults?.[n.id];
                const nodeFocused = !hasFocusMode || focusNodeIds!.has(n.id);

                return (
                    <NodeView
                        key={`n-${n.id}`}
                        node={n}
                        pos={positions[n.id]}
                        isHub={hubs.has(n.id)}
                        isSelected={selectedNodeId === n.id || isConnectedToSelected}
                        isHovered={hoveredNodeId === n.id || isConnectedToHovered || (hoveredEdgeId !== null && (edges.find(e => e.id === hoveredEdgeId)?.source === n.id || edges.find(e => e.id === hoveredEdgeId)?.target === n.id))}
                        deltaStress={simResult?.deltaStress ?? 0}
                        isShockedBank={shockedBankId === n.id}
                        isFocused={nodeFocused}
                        hasFocusMode={hasFocusMode}
                        onClick={() => onSelectNode(n)}
                        onPointerOver={() => onHoverNode(n)}
                        onPointerOut={() => onHoverNode(null)}
                    />
                );
            })}
        </group>
    );
};
