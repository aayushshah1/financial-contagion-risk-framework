import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { motion, AnimatePresence } from 'framer-motion';
import { useHandTracking } from './gestures/useHandTracking';
import type { HandState } from './gestures/useHandTracking';
import { GraphCanvas } from './graph/GraphCanvas';
import { GraphPlane2D } from './graph/GraphPlane2D';
import type { GraphPlane2DHandle } from './graph/GraphPlane2D';
import { generateDemoGraph } from './graph/demoData';
import { fetchGraphFromNeo4j, fetchSimulationGraph } from './graph/neo4jData';
import { buildBankLeafGraph, isBankNode } from './graph/bankLeafView';
import type { GraphData, GraphEdge, GraphNode, GraphValue, SimulationGraphData, SimulationScenario } from './graph/types';
import { buildIndexMaps, createEmptyScenario, runPropagation } from './simulation/engine';
import type { IndexedSimGraph } from './simulation/types';

const EMPTY_NODES: GraphNode[] = [];
const EMPTY_EDGES: GraphEdge[] = [];

const CameraController = ({ gestureState, isAutoRotate }: { gestureState: HandState, isAutoRotate: boolean }) => {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  useFrame(() => {
    if (!controlsRef.current) return;

    if (isAutoRotate) {
      controlsRef.current.autoRotate = true;
      controlsRef.current.autoRotateSpeed = 0.5;
    } else {
      controlsRef.current.autoRotate = false;
    }

    // Handle Orbit Gesture
    if (gestureState.gesture === 'orbit' && gestureState.orbitDelta) {
      controlsRef.current.setAzimuthalAngle(controlsRef.current.getAzimuthalAngle() - gestureState.orbitDelta.dx * 12.0);
      controlsRef.current.setPolarAngle(controlsRef.current.getPolarAngle() + gestureState.orbitDelta.dy * 12.0);
    }

    controlsRef.current.update();
  });

  return <OrbitControls ref={controlsRef} enableDamping dampingFactor={0.05} />;
};

function hasNeo4jLowValue(value: GraphValue): value is { low: GraphValue } {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && 'low' in value;
}

function formatGraphValue(value: GraphValue): string {
  if (hasNeo4jLowValue(value)) {
    return String(value.low);
  }

  if (Array.isArray(value)) {
    return value.map((item) => formatGraphValue(item)).join(', ');
  }

  if (typeof value === 'object' && value !== null) {
    return JSON.stringify(value);
  }

  return String(value);
}

function getNodeTextProp(node: GraphNode, key: string): string | null {
  const value = node.props[key];
  return typeof value === 'string' && value.trim().length > 0 ? value : null;
}

function getBankSymbol(node: GraphNode | null): string | null {
  if (!node || !isBankNode(node)) {
    return null;
  }

  return getNodeTextProp(node, 'bankSymbol')
    ?? getNodeTextProp(node, 'bankName')
    ?? getNodeTextProp(node, 'name');
}

function getNodeDisplayName(node: GraphNode): string {
  return getNodeTextProp(node, 'bankName')
    ?? getNodeTextProp(node, 'crisilName')
    ?? getNodeTextProp(node, 'name')
    ?? getNodeTextProp(node, 'bankSymbol')
    ?? `${node.labels[0] ?? 'Node'} #${node.id}`;
}

function stressColor(delta: number): string {
  if (delta <= 0.001) return '#4ade80';
  if (delta < 0.15) return '#facc15';
  return '#ff4d6d';
}

function App() {
  const videoRef = useRef<HTMLVideoElement>(null!);
  const graph2DRef = useRef<GraphPlane2DHandle | null>(null);
  const handState = useHandTracking(videoRef);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [blueNodeLimit, setBlueNodeLimit] = useState<number>(1);
  const [whiteNodeLimit, setWhiteNodeLimit] = useState<number>(0);
  const [cameraZoom, setCameraZoom] = useState<number>(5);
  const [dataSource, setDataSource] = useState<'neo4j' | 'demo'>('neo4j');
  const [viewMode, setViewMode] = useState<'3d' | '2d'>('3d');
  const [show2DLabels, setShow2DLabels] = useState<boolean>(true);
  const [twoDEdgeVisibility] = useState<'important' | 'all' | 'hidden'>('all');
  const [twoDNodeFilter, setTwoDNodeFilter] = useState<'all' | 'banks' | 'nbfc' | 'leaves'>('all');
  const [twoDFocusMode, setTwoDFocusMode] = useState<boolean>(true);
  const [twoDZoom, setTwoDZoom] = useState<number>(1);
  const [twoDDensity, setTwoDDensity] = useState<number>(12);
  const [isCameraEnabled, setIsCameraEnabled] = useState<boolean>(true);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [threeDLayout, setThreeDLayout] = useState<'centralized' | 'decentralized' | 'separated'>('centralized');
  const [simFocusDepth] = useState<number>(10);

  // --- Simulation state ---
  const [simEnabled, setSimEnabled] = useState(false);
  const [simPayload, setSimPayload] = useState<SimulationGraphData | null>(null);
  const [simIndex, setSimIndex] = useState<IndexedSimGraph | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simSelectedBankId, setSimSelectedBankId] = useState<number | null>(null);
  const [simShockValue, setSimShockValue] = useState<number>(50);

  // Wrap dataSource change to also clear simulation state
  const switchDataSource = useCallback((next: 'neo4j' | 'demo') => {
    setDataSource(next);
    setSimEnabled(false);
    setSimPayload(null);
    setSimIndex(null);
    setSimSelectedBankId(null);
    setSimShockValue(50);
  }, []);

  useEffect(() => {
    let active = true;
    const applyGraphData = (nextGraphData: GraphData) => {
      if (!active) {
        return;
      }

      const bankCount = nextGraphData.nodes.filter(isBankNode).length;
      const leafCount = nextGraphData.nodes.length - bankCount;
      setGraphData(nextGraphData);
      setBlueNodeLimit(Math.max(1, bankCount));
      setWhiteNodeLimit(Math.max(0, leafCount));
      setSelectedNode(null);
      setHoveredNode(null);
      setHoveredEdge(null);
    };

    if (dataSource === 'neo4j') {
      fetchGraphFromNeo4j().then(applyGraphData).catch(err => console.error("Neo4j error:", err));
    } else {
      applyGraphData(generateDemoGraph());
    }

    return () => {
      active = false;
    };
  }, [dataSource]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        setSelectedNode(null);
        setHoveredEdge(null);
      } else if (e.key.toLowerCase() === 'p') {
        switchDataSource('neo4j');
      } else if (e.key.toLowerCase() === 'd') {
        switchDataSource('demo');
      } else if (e.key === '2') {
        setViewMode('2d');
      } else if (e.key === '3') {
        setViewMode('3d');
      } else if (e.key.toLowerCase() === 'l') {
        setShow2DLabels((current) => !current);
      } else if (e.key.toLowerCase() === 'c') {
        setIsCameraEnabled((current) => !current);
      }
    };

    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('keydown', handleKey);
    };
  }, [switchDataSource]);

  useEffect(() => {
    let mediaStream: MediaStream | null = null;
    const videoElement = videoRef.current;

    if (!isCameraEnabled) {
      if (videoElement) {
        videoElement.srcObject = null;
      }
      return () => undefined;
    }

    navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
      mediaStream = stream;
      if (videoElement) {
        videoElement.srcObject = mediaStream;
      }
    }).catch(err => console.error(err));

    return () => {
      mediaStream?.getTracks().forEach((track) => track.stop());
      if (videoElement) {
        videoElement.srcObject = null;
      }
    };
  }, [isCameraEnabled]);

  // --- Simulation: lazy-fetch helper ---
  const fetchSimPayloadOnce = useCallback(() => {
    if (simPayload !== null || simLoading) return;
    setSimLoading(true);
    fetchSimulationGraph()
      .then((payload) => {
        setSimPayload(payload);
        const indexed = buildIndexMaps(payload);
        setSimIndex(indexed);
        if (payload.shockableNodeIds.length > 0) {
          setSimSelectedBankId((prev) => prev ?? payload.shockableNodeIds[0]);
        }
      })
      .catch((err) => {
        console.error('Simulation fetch failed:', err);
        setSimEnabled(false);
      })
      .finally(() => {
        setSimLoading(false);
      });
  }, [simPayload, simLoading]);

  // --- Simulation: toggle handler (also triggers fetch on first enable) ---
  const handleSimToggle = useCallback(() => {
    if (dataSource === 'demo') return;
    setSimEnabled((prev) => {
      const next = !prev;
      if (next) {
        // Trigger fetch on next tick (after state updates)
        queueMicrotask(() => fetchSimPayloadOnce());
      }
      return next;
    });
  }, [dataSource, fetchSimPayloadOnce]);

  // --- Simulation: compute result via useMemo (no effect setState) ---
  const simScenario: SimulationScenario = useMemo(() => {
    if (!simEnabled || !simIndex || simSelectedBankId === null) {
      return createEmptyScenario();
    }
    return runPropagation(simIndex, simSelectedBankId, simShockValue / 100);
  }, [simEnabled, simIndex, simSelectedBankId, simShockValue]);

  // --- Simulation: bank selection with auto-raise blue limit ---
  const handleSimBankChange = useCallback((bankId: number) => {
    setSimSelectedBankId(bankId);
    // Auto-raise blue-bank limit if needed
    if (graphData) {
      const banks = graphData.nodes.filter(isBankNode).sort((a, b) => a.id - b.id);
      const bankIndex = banks.findIndex((b) => b.id === bankId);
      if (bankIndex >= 0) {
        setBlueNodeLimit((prev) => Math.max(prev, bankIndex + 1));
      }
    }
  }, [graphData]);

  const filteredGraph = useMemo(() => {
    if (!graphData) {
      return null;
    }

    return buildBankLeafGraph(graphData, blueNodeLimit, whiteNodeLimit);
  }, [graphData, blueNodeLimit, whiteNodeLimit]);

  // Translate Hand Point to Screen Coordinates
  const pointerPos = handState.indexNorm ? {
    x: handState.indexNorm.x * window.innerWidth,
    y: handState.indexNorm.y * window.innerHeight
  } : null;

  const displayNodes = filteredGraph?.nodes ?? EMPTY_NODES;
  const displayEdges = filteredGraph?.edges ?? EMPTY_EDGES;
  const displayNodeIds = useMemo(() => new Set(displayNodes.map((node) => node.id)), [displayNodes]);
  const displayEdgeIds = useMemo(() => new Set(displayEdges.map((edge) => edge.id)), [displayEdges]);

  const visibleSelectedNode = selectedNode && displayNodeIds.has(selectedNode.id) ? selectedNode : null;
  const visibleHoveredNode = hoveredNode && displayNodeIds.has(hoveredNode.id) ? hoveredNode : null;
  const visibleHoveredEdge = hoveredEdge && displayEdgeIds.has(hoveredEdge.id) ? hoveredEdge : null;
  const activeNode = visibleHoveredNode || visibleSelectedNode;
  const blueSliderMax = filteredGraph?.availableBlueCount ?? 0;
  const whiteSliderMax = filteredGraph?.maxWhiteForCurrentBlue ?? 0;
  const blueSliderValue = blueSliderMax > 0 ? Math.min(Math.max(blueNodeLimit, 1), blueSliderMax) : 0;
  const whiteSliderValue = Math.min(Math.max(whiteNodeLimit, 0), whiteSliderMax);
  const titleSymbol = useMemo(() => {
    const focusedBank = activeNode && isBankNode(activeNode) ? activeNode : null;
    const fallbackBank = displayNodes.find((node) => isBankNode(node)) ?? null;
    return getBankSymbol(focusedBank ?? fallbackBank) ?? 'BANK NETWORK';
  }, [activeNode, displayNodes]);

  // --- Simulation: build bank list for dropdown ---
  const shockableBanks = useMemo(() => {
    if (!simPayload) return [];
    const nodeById = new Map(simPayload.nodes.map((n) => [n.id, n]));
    return simPayload.shockableNodeIds
      .map((id) => nodeById.get(id))
      .filter((n): n is GraphNode => Boolean(n))
      .map((n) => ({ id: n.id, name: getNodeDisplayName(n) }));
  }, [simPayload]);

  // --- Simulation: ranked impact list (visible nodes only) ---
  const rankedImpact = useMemo(() => {
    if (!simEnabled || !simScenario.resultsByNodeId) return [];
    return displayNodes
      .filter((n) => n.id !== simScenario.selectedBankId)
      .map((n) => {
        const r = simScenario.resultsByNodeId[n.id];
        if (!r || r.deltaStress <= 0.001) return null;
        return {
          node: n,
          name: getNodeDisplayName(n),
          type: isBankNode(n) ? 'Bank' : 'Company',
          base: (simScenario.resultsByNodeId[n.id]?.simulatedStress ?? 0) - r.deltaStress,
          simulated: r.simulatedStress,
          delta: r.deltaStress,
        };
      })
      .filter((r): r is NonNullable<typeof r> => r !== null)
      .sort((a, b) => b.delta - a.delta)
      .slice(0, 15);
  }, [simEnabled, simScenario, displayNodes]);

  // --- Simulation: BFS focus subgraph (depth simFocusDepth from shocked bank via channels) ---
  const simFocusNodeIds = useMemo((): Set<number> | null => {
    if (!simEnabled || simScenario.selectedBankId === null || !simPayload) return null;
    const { channels, nodes: simNodes } = simPayload;
    const nodeSet = new Set(simNodes.map((n) => n.id));
    // Build adjacency from channels (bidirectional for BFS scope)
    const adj = new Map<number, number[]>();
    nodeSet.forEach((id) => adj.set(id, []));
    channels.forEach((ch) => {
      adj.get(ch.sourceNodeId)?.push(ch.targetNodeId);
      adj.get(ch.targetNodeId)?.push(ch.sourceNodeId);
    });
    // BFS
    const visited = new Set<number>();
    const queue: Array<{ id: number; depth: number }> = [{ id: simScenario.selectedBankId, depth: 0 }];
    while (queue.length > 0) {
      const { id, depth } = queue.shift()!;
      if (visited.has(id)) continue;
      visited.add(id);
      if (depth < simFocusDepth) {
        for (const neighbour of (adj.get(id) ?? [])) {
          if (!visited.has(neighbour)) queue.push({ id: neighbour, depth: depth + 1 });
        }
      }
    }
    // Also include any displayNodes that have a non-trivial delta (belt-and-suspenders)
    displayNodes.forEach((n) => {
      const r = simScenario.resultsByNodeId[n.id];
      if (r && r.deltaStress > 0.001) visited.add(n.id);
    });
    return visited;
  }, [simEnabled, simScenario, simPayload, simFocusDepth, displayNodes]);

  // MediaPipe Hand Connections
  const connections = [
    [0, 1], [1, 2], [2, 3], [3, 4], // Thumb
    [0, 5], [5, 6], [6, 7], [7, 8], // Index
    [5, 9], [9, 10], [10, 11], [11, 12], // Middle
    [9, 13], [13, 14], [14, 15], [15, 16], // Ring
    [13, 17], [0, 17], [17, 18], [18, 19], [19, 20] // Pinky & Palm
  ];

  // --- Simulation: data card extension for active node ---
  const simActiveNodeResult = activeNode && simEnabled
    ? simScenario.resultsByNodeId[activeNode.id] ?? null
    : null;

  return (
    <div style={{ width: '100vw', height: '100vh', background: isCameraEnabled ? '#050505' : '#000000', position: 'relative' }}>

      {/* Fullscreen Webcam Background */}
      {isCameraEnabled ? (
        <>
          <video ref={videoRef} autoPlay playsInline muted className="video-background" />
          <div className="video-overlay" />
        </>
      ) : (
        <div style={{ position: 'absolute', inset: 0, zIndex: 1, background: '#000000' }} />
      )}

      {/* Hand Tracking SVG Overlay */}
      {isCameraEnabled && handState.landmarks && (
        <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 99 }}>
          {connections.map(([start, end], i) => {
            const p1 = handState.landmarks![start];
            const p2 = handState.landmarks![end];
            // Mirror X to match the webcam
            const x1 = (1.0 - p1.x) * window.innerWidth;
            const y1 = p1.y * window.innerHeight;
            const x2 = (1.0 - p2.x) * window.innerWidth;
            const y2 = p2.y * window.innerHeight;
            return <line key={`conn-${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#00ffcc" strokeWidth="2" opacity="0.6" />;
          })}
          {handState.landmarks.map((p, i) => (
            <circle key={`lm-${i}`} cx={(1.0 - p.x) * window.innerWidth} cy={p.y * window.innerHeight} r="3" fill="#ffffff" />
          ))}
        </svg>
      )}

      {/* Gesture Cursor */}
      {isCameraEnabled && pointerPos && handState.gesture === 'pointing' && (
        <div className="cursor-crosshair" style={{ left: pointerPos.x, top: pointerPos.y, zIndex: 100 }} />
      )}

      {viewMode === '3d' ? (
        <Canvas style={{ position: 'absolute', top: 0, left: 0, zIndex: 3, width: '100%', height: '100%' }}>
          <PerspectiveCamera makeDefault position={[0, 0, cameraZoom]} fov={50} />
          <ambientLight intensity={0.5} />
          <pointLight position={[10, 10, 10]} intensity={1} />

          <CameraController
            gestureState={handState}
            isAutoRotate={handState.gesture === 'none' && !visibleSelectedNode}
          />

          {graphData ? (
            <GraphCanvas
              nodes={displayNodes}
              edges={displayEdges}
              topology={threeDLayout}
              selectedNodeId={visibleSelectedNode?.id ?? null}
              onSelectNode={setSelectedNode}
              onHoverNode={setHoveredNode}
              hoveredNodeId={visibleHoveredNode?.id ?? null}
              onHoverEdge={setHoveredEdge}
              hoveredEdgeId={visibleHoveredEdge?.id ?? null}
              gesturePointer={handState.gesture === 'pointing' ? handState.indexNorm : null}
              simulationResults={simEnabled ? simScenario.resultsByNodeId : undefined}
              simulationActiveEdgeIds={simEnabled ? simScenario.activeSourceEdgeIds : undefined}
              shockedBankId={simEnabled ? simScenario.selectedBankId : undefined}
              focusNodeIds={simEnabled ? simFocusNodeIds : null}
            />
          ) : (
            <mesh>
              <sphereGeometry args={[0.5, 32, 32]} />
              <meshBasicMaterial color="#ffffff" wireframe />
            </mesh>
          )}
        </Canvas>
      ) : (
        graphData && (
          <GraphPlane2D
            ref={graph2DRef}
            nodes={displayNodes}
            edges={displayEdges}
            showLabels={show2DLabels}
            edgeVisibility={twoDEdgeVisibility}
            nodeTypeFilter={twoDNodeFilter}
            focusMode={twoDFocusMode}
            zoomLevel={twoDZoom}
            densityLevel={twoDDensity}
            selectedNodeId={visibleSelectedNode?.id ?? null}
            hoveredNodeId={visibleHoveredNode?.id ?? null}
            hoveredEdgeId={visibleHoveredEdge?.id ?? null}
            onSelectNode={setSelectedNode}
            onHoverNode={setHoveredNode}
            onHoverEdge={setHoveredEdge}
          />
        )
      )}

      {/* UI Overlay */}
      <div className="bottom-bar">
        <div className="controls-hint">
          <span><kbd>Space</kbd> Reset</span>
          <span><kbd>2</kbd> 2D</span>
          <span><kbd>3</kbd> 3D</span>
          {viewMode === '2d' && <span><kbd>L</kbd> Labels</span>}
          {viewMode === '2d' && <span>🖱️ Drag background to pan</span>}
          {viewMode === '2d' && <span>🖱️ Right-drag Rotate 360°</span>}
          {viewMode === '3d' && <span>✋ 4-Finger Orbit</span>}
          {viewMode === '3d' && <span>☝️ Index Point</span>}
        </div>
      </div>
      <div className="overlay">
        <div className="top-bar">
          <div className="webcam-container">
            <div className="status-badge">
              {!isCameraEnabled && <><span>📷</span> Camera Off</>}
              {isCameraEnabled && handState.gesture === 'v_zoom' && <><span>✌️</span> Zooming</>}
              {isCameraEnabled && handState.gesture === 'orbit' && <><span>✋</span> Orbiting</>}
              {isCameraEnabled && handState.gesture === 'pointing' && <><span>☝️</span> Pointing</>}
              {isCameraEnabled && handState.gesture === 'none' && <><span>🖱️</span> Mouse Mode</>}
            </div>
          </div>

          <div className="title-block">
            <h1>{titleSymbol}</h1>
            <div className="subtitle">Neo4J Capstone Bank Contagion</div>
            <div className="stats" style={{ marginBottom: '10px' }}>
              {graphData
                ? `${filteredGraph?.appliedBlueCount ?? 0} blue nodes • ${filteredGraph?.appliedWhiteCount ?? 0} white nodes • ${displayEdges.length} edges`
                : "Loading Graph Data..."}
            </div>

            <AnimatePresence>
              {activeNode && (
                <motion.div
                  initial={{ opacity: 0, x: 20, filter: 'blur(10px)' }}
                  animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                  exit={{ opacity: 0, scale: 0.95, filter: 'blur(10px)' }}
                  className="data-card"
                >
                  <div className="data-card-title">
                    {activeNode.labels[0]} #{activeNode.id}
                  </div>
                    {Object.entries(activeNode.props).map(([key, val]) => (
                      <div className="data-row" key={key}>
                        <span className="data-key" style={{ textTransform: 'capitalize' }}>{key}</span>
                        <span className="data-val">{formatGraphValue(val)}</span>
                      </div>
                    ))}

                    {/* Simulation stress extension */}
                    {simActiveNodeResult && (
                      <div className="sim-card-section">
                        <div className="sim-card-divider" />
                        <div className="data-row">
                          <span className="data-key">Base Stress</span>
                          <span className="data-val">{(simActiveNodeResult.simulatedStress - simActiveNodeResult.deltaStress).toFixed(3)}</span>
                        </div>
                        <div className="data-row">
                          <span className="data-key">Simulated Stress</span>
                          <span className="data-val" style={{ color: stressColor(simActiveNodeResult.deltaStress) }}>
                            {simActiveNodeResult.simulatedStress.toFixed(3)}
                          </span>
                        </div>
                        <div className="data-row">
                          <span className="data-key">Delta</span>
                          <span className="data-val" style={{ color: stressColor(simActiveNodeResult.deltaStress) }}>
                            +{simActiveNodeResult.deltaStress.toFixed(4)}
                          </span>
                        </div>
                        {simActiveNodeResult.topContributors.length > 0 && (
                          <>
                            <div className="sim-contributors-label">Top Contributors</div>
                            {simActiveNodeResult.topContributors.map((c, i) => {
                              const contributorNode = simPayload?.nodes.find((n) => n.id === c.fromNodeId);
                              return (
                                <div className="data-row" key={`contrib-${i}`}>
                                  <span className="data-key" style={{ fontSize: '11px' }}>
                                    {contributorNode ? getNodeDisplayName(contributorNode) : `#${c.fromNodeId}`}
                                  </span>
                                  <span className="data-val" style={{ fontSize: '11px' }}>{c.contribution.toFixed(3)}</span>
                                </div>
                              );
                            })}
                          </>
                        )}
                      </div>
                    )}
                  </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {visibleHoveredEdge && !activeNode && (
                <motion.div
                  initial={{ opacity: 0, x: 20, filter: 'blur(10px)' }}
                  animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                  exit={{ opacity: 0, scale: 0.95, filter: 'blur(10px)' }}
                  className="data-card"
                >
                  <div className="data-card-title">
                    EDGE: {visibleHoveredEdge.type}
                  </div>
                  {Object.entries(visibleHoveredEdge.props).map(([key, val]) => (
                    <div className="data-row" key={key}>
                      <span className="data-key" style={{ textTransform: 'capitalize' }}>{key}</span>
                      <span className="data-val">{formatGraphValue(val)}</span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {graphData && (
        <div style={{ position: 'absolute', bottom: '20px', right: '20px', zIndex: 100, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>

          {/* Always-visible collapse toggle */}
          <button
            onClick={() => setSidebarOpen((o) => !o)}
            title={sidebarOpen ? 'Hide controls' : 'Show controls'}
            style={{
              background: 'rgba(0,0,0,0.7)',
              border: '1px solid rgba(255,255,255,0.15)',
              color: '#ccc',
              borderRadius: '8px',
              width: '32px',
              height: '32px',
              fontSize: '16px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {sidebarOpen ? '›' : '‹'}
          </button>

          {sidebarOpen && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '15px',
            background: 'rgba(0,0,0,0.6)',
            padding: '15px',
            borderRadius: '10px',
            border: '1px solid rgba(255,255,255,0.1)',
            maxHeight: 'calc(100vh - 80px)',
            overflowY: 'auto',
            width: '240px',
          }}>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <label style={{ fontSize: '12px', color: '#aaaaaa', display: 'flex', justifyContent: 'space-between' }}>
              <span>Data Source:</span>
              <span style={{ fontSize: '10px', color: '#fff', background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: '4px' }}>
                {dataSource === 'neo4j' ? 'PROD (Neo4j)' : 'DEMO'} Mode
              </span>
            </label>
            <span style={{ fontSize: '10px', color: '#888' }}>Press 'P' for Prod, 'D' for Demo</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
              Camera: {isCameraEnabled ? 'ON' : 'OFF'}
            </label>
            <button
              onClick={() => setIsCameraEnabled((current) => !current)}
              style={{
                background: isCameraEnabled ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.2)',
                color: '#fff',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              {isCameraEnabled ? 'Disable Camera' : 'Enable Camera'}
            </button>
            <span style={{ fontSize: '10px', color: '#888' }}>Press 'C' to toggle</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
              Mode: {viewMode === '3d' ? '3D (existing)' : '2D network layout'}
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setViewMode('3d')}
                style={{
                  background: viewMode === '3d' ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                3D
              </button>
              <button
                onClick={() => setViewMode('2d')}
                style={{
                  background: viewMode === '2d' ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                2D
              </button>
            </div>
          </div>

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
                Labels: {show2DLabels ? 'ON' : 'OFF'}
              </label>
              <button
                onClick={() => setShow2DLabels((current) => !current)}
                style={{
                  background: show2DLabels ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {show2DLabels ? 'Turn Labels Off' : 'Turn Labels On'}
              </button>
            </div>
          )}

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
                Node Filter
              </label>
              <select
                value={twoDNodeFilter}
                onChange={(e) => setTwoDNodeFilter(e.target.value as 'all' | 'banks' | 'nbfc' | 'leaves')}
                style={{
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 8px',
                  fontSize: '11px',
                }}
              >
                <option value="all">All</option>
                <option value="banks">Banks + NBFC</option>
                <option value="nbfc">NBFC only</option>
                <option value="leaves">Leaf nodes</option>
              </select>
            </div>
          )}

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
                Focus Mode: {twoDFocusMode ? 'ON' : 'OFF'}
              </label>
              <button
                onClick={() => setTwoDFocusMode((current) => !current)}
                style={{
                  background: twoDFocusMode ? 'rgba(59,130,246,0.25)' : 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                {twoDFocusMode ? 'Disable Focus Mode' : 'Enable Focus Mode'}
              </button>
            </div>
          )}

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
                Export
              </label>
              <button
                onClick={() => graph2DRef.current?.downloadImage()}
                style={{
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  cursor: 'pointer',
                }}
              >
                Download 2D Image
              </button>
            </div>
          )}

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
                Density (signal nodes): {Math.round(twoDDensity)}
              </label>
              <input
                type="range"
                min={10}
                max={40}
                step={1}
                value={twoDDensity}
                onChange={(e) => setTwoDDensity(parseInt(e.target.value, 10))}
                style={{ width: '200px' }}
              />
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
              Blue bank nodes: {filteredGraph?.appliedBlueCount ?? 0} / {blueSliderMax}
            </label>
            <input
              type="range"
              min={blueSliderMax > 0 ? 1 : 0}
              max={Math.max(blueSliderMax, 1)}
              value={blueSliderValue}
              onChange={(e) => {
                const nextBlueCount = parseInt(e.target.value, 10);
                setBlueNodeLimit(nextBlueCount);
                if (graphData) {
                  const nextGraph = buildBankLeafGraph(graphData, nextBlueCount, whiteNodeLimit);
                  if (whiteNodeLimit > nextGraph.maxWhiteForCurrentBlue) {
                    setWhiteNodeLimit(nextGraph.maxWhiteForCurrentBlue);
                  }
                }
              }}
              style={{ width: '200px' }}
              disabled={blueSliderMax === 0}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            <label style={{ fontSize: '12px', color: '#aaaaaa' }}>
              White leaf nodes: {filteredGraph?.appliedWhiteCount ?? 0} / {whiteSliderMax}
            </label>
            <input
              type="range"
              min={0}
              max={Math.max(whiteSliderMax, 1)}
              value={whiteSliderValue}
              onChange={(e) => setWhiteNodeLimit(parseInt(e.target.value, 10))}
              style={{ width: '200px' }}
              disabled={whiteSliderMax === 0}
            />
            <span style={{ fontSize: '10px', color: '#888' }}>Each blue node is capped at 5 white leaves.</span>
          </div>

          {viewMode === '3d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>Zoom Level : {cameraZoom.toFixed(1)}</label>
              <input
                type="range"
                min={2}
                max={15}
                step={0.1}
                value={cameraZoom}
                onChange={(e) => setCameraZoom(parseFloat(e.target.value))}
                style={{ width: '200px' }}
              />
            </div>
          )}

          {viewMode === '3d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>3D Layout</label>
              <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                {(['centralized', 'separated', 'decentralized'] as const).map((layout) => (
                  <button
                    key={layout}
                    onClick={() => setThreeDLayout(layout)}
                    style={{
                      background: threeDLayout === layout ? 'rgba(59,130,246,0.3)' : 'rgba(255,255,255,0.06)',
                      border: `1px solid ${threeDLayout === layout ? 'rgba(59,130,246,0.6)' : 'rgba(255,255,255,0.15)'}`,
                      color: threeDLayout === layout ? '#93c5fd' : '#aaa',
                      borderRadius: '5px',
                      padding: '3px 8px',
                      fontSize: '10px',
                      cursor: 'pointer',
                      textTransform: 'capitalize',
                    }}
                  >
                    {layout === 'centralized' ? 'Cluster' : layout === 'separated' ? 'Separated' : 'Groups'}
                  </button>
                ))}
              </div>
            </div>
          )}

          {viewMode === '2d' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              <label style={{ fontSize: '12px', color: '#aaaaaa' }}>2D Zoom : {twoDZoom.toFixed(2)}x</label>
              <input
                type="range"
                min={0.6}
                max={2.2}
                step={0.05}
                value={twoDZoom}
                onChange={(e) => setTwoDZoom(parseFloat(e.target.value))}
                style={{ width: '200px' }}
              />
            </div>
          )}

          {/* ─── Simulation Section (3D + Neo4j only) ─── */}
          {viewMode === '3d' && dataSource === 'neo4j' && (
            <div className="sim-section">
              <div className="sim-section-header">
                <span className="sim-section-title">⚡ Simulation</span>
                <button
                  className={`sim-toggle ${simEnabled ? 'sim-toggle-on' : ''}`}
                  onClick={handleSimToggle}
                >
                  {simLoading ? '…' : simEnabled ? 'ON' : 'OFF'}
                </button>
              </div>

              {simEnabled && (
                <>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '11px', color: '#aaa' }}>Shock Bank</label>
                    <select
                      value={simSelectedBankId ?? ''}
                      onChange={(e) => handleSimBankChange(Number(e.target.value))}
                      style={{
                        background: 'rgba(255,255,255,0.08)',
                        border: '1px solid rgba(255,255,255,0.2)',
                        color: '#fff',
                        borderRadius: '6px',
                        padding: '4px 8px',
                        fontSize: '11px',
                      }}
                    >
                      {shockableBanks.map((b) => (
                        <option key={b.id} value={b.id}>{b.name}</option>
                      ))}
                    </select>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '11px', color: '#aaa' }}>
                      Stress Level: {simShockValue}%
                    </label>
                    <input
                      type="range"
                      className="sim-slider"
                      min={0}
                      max={100}
                      step={1}
                      value={simShockValue}
                      onChange={(e) => setSimShockValue(parseInt(e.target.value, 10))}
                      style={{ width: '100%' }}
                    />
                  </div>

                  <button
                    onClick={() => {
                      setSimShockValue(50);
                      setSimSelectedBankId(shockableBanks[0]?.id ?? null);
                    }}
                    style={{
                      background: 'rgba(255,255,255,0.06)',
                      border: '1px solid rgba(255,255,255,0.15)',
                      color: '#ccc',
                      borderRadius: '6px',
                      padding: '4px 10px',
                      fontSize: '11px',
                      cursor: 'pointer',
                    }}
                  >
                    Reset
                  </button>

                  <div className="sim-badge">
                    {simScenario.iterations} iters • {simScenario.impactedCount} impacted
                  </div>

                  {/* Ranked Impact Panel */}
                  {rankedImpact.length > 0 && (
                    <div className="sim-impact-panel">
                      <div style={{ fontSize: '11px', color: '#aaa', marginBottom: '6px', fontWeight: 600, letterSpacing: '0.5px' }}>
                        IMPACT RANKING
                      </div>
                      {rankedImpact.map((r, i) => (
                        <div
                          key={r.node.id}
                          className="sim-impact-row"
                          onClick={() => setSelectedNode(r.node)}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: 0 }}>
                            <span className="sim-impact-rank">#{i + 1}</span>
                            <span className="sim-impact-name">{r.name}</span>
                            <span className={`sim-type-badge ${r.type === 'Bank' ? 'sim-type-bank' : 'sim-type-company'}`}>
                              {r.type}
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                            <span style={{ fontSize: '10px', color: '#888' }}>{r.base.toFixed(2)}</span>
                            <span style={{ fontSize: '10px', color: '#666' }}>→</span>
                            <span style={{ fontSize: '10px', color: stressColor(r.delta), fontWeight: 700 }}>
                              {r.simulated.toFixed(2)}
                            </span>
                            <span className="sim-delta-bar" style={{ background: stressColor(r.delta), width: `${Math.min(r.delta * 200, 40)}px` }} />
                          </div>
                        </div>
                      ))}
                      <div className="sim-impact-footer">
                        {simScenario.impactedCount} impacted overall
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
