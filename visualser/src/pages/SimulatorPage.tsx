/**
 * SimulatorPage — pick a bank, shock it, see only that bank's BFS subgraph.
 *
 * Data flow (lean):
 *  1. On mount: GET /api/banks → small list of bank names (< 50 KB)
 *  2. On bank select: GET /api/sim?bankId=X&depth=N → server-side BFS subgraph + sim channels
 *     Only that neighbourhood is sent to the browser.
 *  3. Stress propagation runs client-side on the subgraph index.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { motion, AnimatePresence } from 'framer-motion';
import { useHandTracking } from '../gestures/useHandTracking';
import type { HandState } from '../gestures/useHandTracking';
import { GraphCanvas } from '../graph/GraphCanvas';
import { fetchBankList, fetchSimForBank } from '../graph/neo4jData';
import type { BankListItem, SimSubgraphPayload } from '../graph/neo4jData';
import { isBankNode } from '../graph/bankLeafView';
import { buildIndexMaps, runPropagation, createEmptyScenario } from '../simulation/engine';
import type { GraphNode, GraphEdge, GraphValue, SimulationScenario } from '../graph/types';
import type { IndexedSimGraph } from '../simulation/types';
import { useTweaks } from '../store/useTweaks';

const EMPTY_NODES: GraphNode[] = [];
const EMPTY_EDGES: GraphEdge[] = [];

// Shared CameraController (same as HomePage)
const CameraController = ({
  gestureState, isAutoRotate,
}: { gestureState: HandState; isAutoRotate: boolean }) => {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  useFrame(() => {
    if (!controlsRef.current) return;
    controlsRef.current.autoRotate = isAutoRotate;
    controlsRef.current.autoRotateSpeed = 0.5;
    if (gestureState.gesture === 'orbit' && gestureState.orbitDelta) {
      controlsRef.current.setAzimuthalAngle(
        controlsRef.current.getAzimuthalAngle() - gestureState.orbitDelta.dx * 12.0,
      );
      controlsRef.current.setPolarAngle(
        controlsRef.current.getPolarAngle() + gestureState.orbitDelta.dy * 12.0,
      );
    }
    controlsRef.current.update();
  });
  return <OrbitControls ref={controlsRef} enableDamping dampingFactor={0.05} />;
};

function getDisplayName(node: GraphNode): string {
  const p = node.props;
  return (
    (typeof p.bankName    === 'string' && p.bankName.trim()    ? p.bankName.trim()    : null) ??
    (typeof p.crisilName  === 'string' && p.crisilName.trim()  ? p.crisilName.trim()  : null) ??
    (typeof p.name        === 'string' && p.name.trim()        ? p.name.trim()        : null) ??
    (typeof p.bankSymbol  === 'string' && p.bankSymbol.trim()  ? p.bankSymbol.trim()  : null) ??
    `${node.labels[0] ?? 'Node'} #${node.id}`
  );
}

function hasNeo4jLow(v: GraphValue): v is { low: GraphValue } {
  return typeof v === 'object' && v !== null && !Array.isArray(v) && 'low' in v;
}

function fmtVal(v: GraphValue): string {
  if (hasNeo4jLow(v)) return String(v.low);
  if (Array.isArray(v)) return v.map(fmtVal).join(', ');
  if (typeof v === 'object' && v !== null) return JSON.stringify(v);
  return String(v);
}

function stressColor(delta: number) {
  if (delta <= 0.001) return '#4ade80';
  if (delta < 0.15)   return '#facc15';
  return '#ff4d6d';
}

export function SimulatorPage() {
  const { tweaks, setTweak } = useTweaks();

  // ── Camera / gesture ──
  const videoRef = useRef<HTMLVideoElement>(null!);
  const handState = useHandTracking(videoRef);
  // Camera state persisted across pages via tweaks
  const isCameraEnabled = tweaks.cameraEnabled;
  const toggleCamera = () => setTweak('cameraEnabled', !isCameraEnabled);

  useEffect(() => {
    let stream: MediaStream | null = null;
    const el = videoRef.current;
    if (!isCameraEnabled) { if (el) el.srcObject = null; return; }
    navigator.mediaDevices.getUserMedia({ video: true })
      .then((s) => { stream = s; if (el) el.srcObject = s; })
      .catch(console.error);
    return () => { stream?.getTracks().forEach((t) => t.stop()); if (el) el.srcObject = null; };
  }, [isCameraEnabled]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        // space = reset selection
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const gesturePointer = (isCameraEnabled && handState.gesture === 'pointing')
    ? handState.indexNorm : null;
  const pointerScreen = gesturePointer
    ? { x: gesturePointer.x * window.innerWidth, y: gesturePointer.y * window.innerHeight }
    : null;
  const connections = [
    [0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],
    [5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],
    [13,17],[0,17],[17,18],[18,19],[19,20],
  ];

  // ── Step 1: bank list (tiny, loaded once) ──
  const [bankList, setBankList]       = useState<BankListItem[]>([]);
  const [bankListLoading, setBankListLoading] = useState(true);
  const [bankListError, setBankListError]     = useState<string | null>(null);

  useEffect(() => {
    fetchBankList()
      .then((list) => { setBankList(list); setBankListLoading(false); })
      .catch((err) => { setBankListError(String(err)); setBankListLoading(false); });
  }, []);

  // ── Step 2: per-bank subgraph (fetched only when a bank is selected) ──
  const [selectedBankId, setSelectedBankId] = useState<number | null>(null);
  const [subgraph, setSubgraph]             = useState<SimSubgraphPayload | null>(null);
  const [simIndex, setSimIndex]             = useState<IndexedSimGraph | null>(null);
  const [subgraphLoading, setSubgraphLoading] = useState(false);
  const [subgraphError, setSubgraphError]     = useState<string | null>(null);

  // Fetch subgraph whenever bank or depth/maxNodes changes
  useEffect(() => {
    if (selectedBankId === null) return;
    setSubgraphLoading(true);
    setSubgraphError(null);
    setSubgraph(null);
    setSimIndex(null);
    fetchSimForBank(selectedBankId, tweaks.simDepth, tweaks.simMaxNodes)
      .then((payload) => {
        setSubgraph(payload);
        setSimIndex(buildIndexMaps(payload));
        setSubgraphLoading(false);
      })
      .catch((err) => {
        setSubgraphError(String(err));
        setSubgraphLoading(false);
      });
  }, [selectedBankId, tweaks.simDepth, tweaks.simMaxNodes]);

  // ── Stress controls ──
  const [shockValue, setShockValue] = useState(50);
  const [filterQuery, setFilterQuery] = useState('');

  // ── Node interaction ──
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode,  setHoveredNode]  = useState<GraphNode | null>(null);
  const [hoveredEdge,  setHoveredEdge]  = useState<GraphEdge | null>(null);

  const displayNodes = subgraph?.nodes ?? EMPTY_NODES;
  const displayEdges = subgraph?.edges ?? EMPTY_EDGES;

  const displayNodeIds = useMemo(() => new Set(displayNodes.map((n) => n.id)), [displayNodes]);
  const displayEdgeIds = useMemo(() => new Set(displayEdges.map((e) => e.id)), [displayEdges]);

  const visibleSelectedNode = selectedNode && displayNodeIds.has(selectedNode.id) ? selectedNode : null;
  const visibleHoveredNode  = hoveredNode  && displayNodeIds.has(hoveredNode.id)  ? hoveredNode  : null;
  const visibleHoveredEdge  = hoveredEdge  && displayEdgeIds.has(hoveredEdge.id)  ? hoveredEdge  : null;
  const activeNode          = visibleHoveredNode || visibleSelectedNode;

  // ── Propagation (runs instantly client-side on subgraph) ──
  const simScenario: SimulationScenario = useMemo(() => {
    if (!simIndex || selectedBankId === null) return createEmptyScenario();
    return runPropagation(simIndex, selectedBankId, shockValue / 100);
  }, [simIndex, selectedBankId, shockValue]);

  // ── Filtered bank list ──
  const filteredBankList = useMemo(() => {
    if (!filterQuery.trim()) return bankList;
    const q = filterQuery.toLowerCase();
    return bankList.filter((b) => b.name.toLowerCase().includes(q));
  }, [bankList, filterQuery]);

  // ── Impact ranking ──
  const rankedImpact = useMemo(() => {
    if (!simScenario.enabled) return [];
    return displayNodes
      .filter((n) => n.id !== selectedBankId)
      .map((n) => {
        const r = simScenario.resultsByNodeId[n.id];
        if (!r || r.deltaStress <= 0.001) return null;
        return {
          node: n, name: getDisplayName(n), isBank: isBankNode(n),
          base: r.simulatedStress - r.deltaStress,
          simulated: r.simulatedStress, delta: r.deltaStress,
        };
      })
      .filter((r): r is NonNullable<typeof r> => r !== null)
      .sort((a, b) => b.delta - a.delta)
      .slice(0, 20);
  }, [simScenario, displayNodes, selectedBankId]);

  // ── Focus set ──
  const focusNodeIds = useMemo((): Set<number> | null => {
    if (!simScenario.enabled || selectedBankId === null) return null;
    const s = new Set<number>([selectedBankId]);
    displayNodes.forEach((n) => {
      const r = simScenario.resultsByNodeId[n.id];
      if (r && r.deltaStress > 0.001) s.add(n.id);
    });
    return s;
  }, [simScenario, displayNodes, selectedBankId]);

  const handleReset = useCallback(() => {
    setShockValue(50);
    setSelectedNode(null);
    setHoveredNode(null);
    setHoveredEdge(null);
  }, []);

  const handleBankSelect = useCallback((id: number) => {
    setSelectedBankId(id);
    setSelectedNode(null);
    setHoveredNode(null);
    setHoveredEdge(null);
    setShockValue(50);
  }, []);

  // Determine what to show in the panel
  const showBankListLoading = bankListLoading;
  const showBankListError   = !bankListLoading && !!bankListError;

  return (
    <div className="sim-page">

      {/* Webcam ALWAYS in DOM so videoRef is assigned before camera effect fires */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        className="video-background"
        style={{ display: isCameraEnabled ? undefined : 'none' }}
      />
      {isCameraEnabled && <div className="video-overlay" />}

      {/* Hand skeleton overlay */}
      {isCameraEnabled && handState.landmarks && (
        <svg style={{ position:'fixed', top:0, left:0, width:'100%', height:'100%', pointerEvents:'none', zIndex:99 }}>
          {connections.map(([s, e], i) => {
            const p1 = handState.landmarks![s]; const p2 = handState.landmarks![e];
            return <line key={i} x1={(1-p1.x)*window.innerWidth} y1={p1.y*window.innerHeight} x2={(1-p2.x)*window.innerWidth} y2={p2.y*window.innerHeight} stroke="#00ffcc" strokeWidth="2" opacity="0.6" />;
          })}
          {handState.landmarks.map((p, i) => (
            <circle key={i} cx={(1-p.x)*window.innerWidth} cy={p.y*window.innerHeight} r="3" fill="#fff" />
          ))}
        </svg>
      )}
      {isCameraEnabled && pointerScreen && handState.gesture === 'pointing' && (
        <div className="cursor-crosshair" style={{ left: pointerScreen.x, top: pointerScreen.y, zIndex: 100, position:'fixed' }} />
      )}

      {/* Full-screen loading overlay (bank list) */}
      {showBankListLoading && (
        <div style={{ position:'fixed', inset:0, zIndex:200, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:'14px', background:'rgba(0,0,0,0.85)', backdropFilter:'blur(8px)' }}>
          <div className="sim-loading-spinner" />
          <div className="sim-loading-text">Loading bank list…</div>
          <div className="sim-loading-sub">Fetching bank index from server</div>
        </div>
      )}
      {showBankListError && (
        <div style={{ position:'fixed', inset:0, zIndex:200, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:'12px', background:'rgba(0,0,0,0.85)', backdropFilter:'blur(8px)' }}>
          <div style={{ fontSize:'48px' }}>⚠️</div>
          <div className="sim-loading-text">Error loading banks</div>
          <div className="sim-loading-sub" style={{ color:'#ff4d6d' }}>{bankListError}</div>
        </div>
      )}

      <div className="sim-panel">
        <div className="sim-panel-header">
          <span className="sim-panel-title">⚡ Stress Simulator</span>
          <span className="sim-panel-badge">
            {simScenario.enabled
              ? `${simScenario.iterations} iters · ${simScenario.impactedCount} impacted`
              : `${bankList.length} banks`}
          </span>
        </div>

        {/* Bank picker */}
        <div className="sim-section-block">
          <div className="sim-section-label">Select Bank to Shock</div>
          <input
            className="sim-search"
            placeholder="Search banks…"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
          />
          <div className="sim-bank-list">
            {filteredBankList.map((b) => (
              <div
                key={b.id}
                className={`sim-bank-item ${selectedBankId === b.id ? 'sim-bank-item-active' : ''}`}
                onClick={() => handleBankSelect(b.id)}
              >
                <span className="sim-bank-dot" />
                <span className="sim-bank-name">{b.name}</span>
                {selectedBankId === b.id && (
                  <span className="sim-bank-selected-badge">ACTIVE</span>
                )}
              </div>
            ))}
            {filteredBankList.length === 0 && (
              <div style={{ color:'#555', fontSize:'12px', padding:'8px' }}>No matches</div>
            )}
          </div>
        </div>

        {/* Stress slider — only visible when a bank is loaded */}
        {subgraph && !subgraphLoading && (
          <>
            <div className="sim-section-block">
              <div className="sim-section-label">
                Stress Level
                <span style={{ color:stressColor(shockValue/100), fontFamily:'Space Mono, monospace', marginLeft:'8px' }}>
                  {shockValue}%
                </span>
              </div>
              <input
                type="range"
                className="sim-slider"
                min={0} max={100} step={1}
                value={shockValue}
                onChange={(e) => setShockValue(parseInt(e.target.value, 10))}
              />
              <div style={{ display:'flex', justifyContent:'space-between', fontSize:'10px', color:'#555', marginTop:'4px' }}>
                <span>0% Baseline</span>
                <span>100% Full Shock</span>
              </div>
            </div>

            {/* Bank stats */}
            <div className="sim-bank-info">
              <div className="sim-bank-info-name">
                {bankList.find((b) => b.id === selectedBankId)?.name ?? `Bank #${selectedBankId}`}
              </div>
              <div className="sim-bank-info-row">
                <span>Nodes in view</span>
                <span>{displayNodes.length}</span>
              </div>
              <div className="sim-bank-info-row">
                <span>Edges in view</span>
                <span>{displayEdges.length}</span>
              </div>
              <div className="sim-bank-info-row">
                <span>BFS depth</span>
                <span>↕️ {tweaks.simDepth} hops</span>
              </div>
              <div className="sim-bank-info-row">
                <span>Base stress</span>
                <span>{((subgraph.nodeBaseStress[selectedBankId!] ?? 0) * 100).toFixed(1)}%</span>
              </div>
            </div>

            <button className="sim-reset-btn" onClick={handleReset}>↺ Reset</button>

            {/* Impact ranking */}
            {rankedImpact.length > 0 && (
              <div className="sim-impact-block">
                <div className="sim-section-label" style={{ marginBottom:'8px' }}>🔥 Impact Ranking</div>
                <div className="sim-impact-panel">
                  {rankedImpact.map((r, i) => (
                    <div key={r.node.id} className="sim-impact-row" onClick={() => setSelectedNode(r.node)}>
                      <div style={{ display:'flex', alignItems:'center', gap:'6px', flex:1, minWidth:0 }}>
                        <span className="sim-impact-rank">#{i+1}</span>
                        <span className="sim-impact-name">{r.name}</span>
                        <span className={`sim-type-badge ${r.isBank ? 'sim-type-bank' : 'sim-type-company'}`}>
                          {r.isBank ? 'Bank' : 'Co.'}
                        </span>
                      </div>
                      <div style={{ display:'flex', alignItems:'center', gap:'6px', flexShrink:0 }}>
                        <span style={{ fontSize:'10px', color:'#888' }}>{r.base.toFixed(2)}</span>
                        <span style={{ fontSize:'10px', color:'#555' }}>→</span>
                        <span style={{ fontSize:'10px', color:stressColor(r.delta), fontWeight:700 }}>{r.simulated.toFixed(2)}</span>
                        <span className="sim-delta-bar" style={{ background:stressColor(r.delta), width:`${Math.min(r.delta*200,40)}px` }} />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="sim-impact-footer">{simScenario.impactedCount} impacted</div>
              </div>
            )}
          </>
        )}

        {/* Loading subgraph spinner */}
        {subgraphLoading && (
          <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:'10px', padding:'24px 0' }}>
            <div className="sim-loading-spinner" style={{ width:'28px', height:'28px', borderWidth:'2px' }} />
            <div style={{ fontSize:'12px', color:'#888' }}>Loading subgraph…</div>
          </div>
        )}

        {/* Subgraph error */}
        {subgraphError && (
          <div style={{ padding:'12px', background:'rgba(255,60,60,0.08)', border:'1px solid rgba(255,60,60,0.2)', borderRadius:'8px', fontSize:'12px', color:'#ff8866' }}>
            ⚠️ {subgraphError}
          </div>
        )}

        {/* Empty state */}
        {!selectedBankId && !subgraphLoading && (
          <div style={{ padding:'20px 8px', textAlign:'center', color:'#555', fontSize:'12px', lineHeight:'1.6' }}>
            ☝️ Select a bank above to load its network neighbourhood and run stress propagation.
          </div>
        )}
      </div>

      {/* Camera toggle — fixed top-right */}
      <button
        onClick={toggleCamera}
        style={{
          position: 'fixed', top: 16, right: 16, zIndex: 200,
          background: isCameraEnabled ? 'rgba(59,130,246,0.2)' : 'rgba(30,30,40,0.7)',
          border: `1px solid ${isCameraEnabled ? 'rgba(59,130,246,0.5)' : 'rgba(255,255,255,0.1)'}`,
          borderRadius: 8, padding: '6px 12px', cursor: 'pointer',
          color: isCameraEnabled ? '#93c5fd' : '#888', fontSize: 12, fontWeight: 600,
          backdropFilter: 'blur(8px)',
        }}
      >
        {isCameraEnabled ? '📷 Cam On' : '📷 Cam Off'}
      </button>

      {/* 3D canvas */}
      <div className="sim-canvas-area">
        <Canvas style={{ width:'100%', height:'100%' }}>
          <PerspectiveCamera makeDefault position={[0, 0, tweaks.cameraZoom]} fov={50} />
          <ambientLight intensity={0.5} />
          <pointLight position={[10, 10, 10]} intensity={1.2} />
          <CameraController
            gestureState={handState}
            isAutoRotate={tweaks.cameraAutoRotate && handState.gesture === 'none' && !activeNode && !subgraphLoading}
          />

          {subgraph && !subgraphLoading && selectedBankId !== null ? (
            <GraphCanvas
              nodes={displayNodes}
              edges={displayEdges}
              topology={tweaks.threeDLayout}
              selectedNodeId={visibleSelectedNode?.id ?? null}
              onSelectNode={setSelectedNode}
              onHoverNode={setHoveredNode}
              hoveredNodeId={visibleHoveredNode?.id ?? null}
              onHoverEdge={setHoveredEdge}
              hoveredEdgeId={visibleHoveredEdge?.id ?? null}
              gesturePointer={gesturePointer}
              simulationResults={simScenario.resultsByNodeId}
              simulationActiveEdgeIds={simScenario.activeSourceEdgeIds}
              shockedBankId={selectedBankId}
              focusNodeIds={focusNodeIds}
              isSimulator={true}
              nodeDepths={subgraph.depthMap}
            />
          ) : (
            // Placeholder sphere
            <mesh>
              <sphereGeometry args={[0.3, 32, 32]} />
              <meshBasicMaterial color="#222" wireframe />
            </mesh>
          )}
        </Canvas>

        {/* Info overlay */}
        <div className="sim-canvas-overlay">
          <AnimatePresence>
            {activeNode && (
              <motion.div
                initial={{ opacity:0, y:10, filter:'blur(8px)' }}
                animate={{ opacity:1, y:0, filter:'blur(0px)' }}
                exit={{ opacity:0, y:10 }}
                className="sim-info-card"
              >
                <div className="sim-info-title">{activeNode.labels[0]} #{activeNode.id}</div>
                <div className="sim-info-name">{getDisplayName(activeNode)}</div>

                {simScenario.resultsByNodeId[activeNode.id] && (() => {
                  const r = simScenario.resultsByNodeId[activeNode.id];
                  return (
                    <div className="sim-info-stress-block">
                      <div className="sim-info-stress-row"><span>Base</span><span>{(r.simulatedStress - r.deltaStress).toFixed(3)}</span></div>
                      <div className="sim-info-stress-row">
                        <span>Simulated</span>
                        <span style={{ color:stressColor(r.deltaStress) }}>{r.simulatedStress.toFixed(3)}</span>
                      </div>
                      <div className="sim-info-stress-row">
                        <span>Δ Delta</span>
                        <span style={{ color:stressColor(r.deltaStress), fontWeight:700 }}>+{r.deltaStress.toFixed(4)}</span>
                      </div>
                      {r.topContributors.length > 0 && (
                        <>
                          <div style={{ fontSize:'10px', color:'#ff8866', marginTop:'8px', fontWeight:600 }}>Top Contributors</div>
                          {r.topContributors.map((c, i) => {
                            const cn = subgraph?.nodes.find((n) => n.id === c.fromNodeId);
                            return (
                              <div className="sim-info-stress-row" key={i}>
                                <span style={{ fontSize:'11px' }}>{cn ? getDisplayName(cn) : `#${c.fromNodeId}`}</span>
                                <span style={{ fontSize:'11px' }}>{c.contribution.toFixed(3)}</span>
                              </div>
                            );
                          })}
                        </>
                      )}
                    </div>
                  );
                })()}

                {subgraph?.depthMap[activeNode.id] !== undefined && (
                  <div className="sim-info-depth">🔗 Depth {subgraph.depthMap[activeNode.id]} from center</div>
                )}

                <div className="sim-info-props">
                  {Object.entries(activeNode.props).slice(0, 6).map(([k, v]) => (
                    <div className="sim-info-stress-row" key={k}>
                      <span style={{ textTransform:'capitalize' }}>{k}</span>
                      <span style={{ fontFamily:'Space Mono, mono', fontSize:'10px' }}>{fmtVal(v)}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {visibleHoveredEdge && !activeNode && (
              <motion.div
                initial={{ opacity:0, y:10 }}
                animate={{ opacity:1, y:0 }}
                exit={{ opacity:0 }}
                className="sim-info-card"
              >
                <div className="sim-info-title">EDGE: {visibleHoveredEdge.type}</div>
                {Object.entries(visibleHoveredEdge.props).slice(0, 6).map(([k, v]) => (
                  <div className="sim-info-stress-row" key={k}>
                    <span style={{ textTransform:'capitalize' }}>{k}</span>
                    <span style={{ fontFamily:'Space Mono, mono', fontSize:'10px' }}>{fmtVal(v)}</span>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Legend */}
        <div className="sim-legend">
          <div className="sim-legend-item"><span className="sim-legend-dot" style={{ background:'#3b82f6' }} />Bank</div>
          <div className="sim-legend-item"><span className="sim-legend-dot" style={{ background:'#a78bfa' }} />NBFC</div>
          <div className="sim-legend-item"><span className="sim-legend-dot" style={{ background:'#e0e0e0' }} />Company / Leaf</div>
          <div className="sim-legend-item"><span className="sim-legend-dot" style={{ background:'#ffaa44' }} />Stressed</div>
          <div className="sim-legend-item"><span className="sim-legend-dot" style={{ background:'#ff4444', boxShadow:'0 0 8px #ff4444' }} />Shocked</div>
        </div>

        {/* Subgraph loading overlay on canvas */}
        {subgraphLoading && (
          <div style={{
            position:'absolute', inset:0, display:'flex', flexDirection:'column',
            alignItems:'center', justifyContent:'center', gap:'14px',
            background:'rgba(0,0,0,0.6)', backdropFilter:'blur(4px)', zIndex:30,
          }}>
            <div className="sim-loading-spinner" />
            <div style={{ color:'#fff', fontSize:'14px', fontWeight:600 }}>Loading subgraph…</div>
            <div style={{ color:'#888', fontSize:'12px', fontFamily:'Space Mono, monospace' }}>
              BFS depth {tweaks.simDepth} from selected bank
            </div>
          </div>
        )}

        {/* Empty state */}
        {!selectedBankId && !subgraphLoading && (
          <div style={{
            position:'absolute', inset:0, display:'flex', flexDirection:'column',
            alignItems:'center', justifyContent:'center', gap:'12px',
            pointerEvents:'none',
          }}>
            <div style={{ fontSize:'64px', opacity:0.15 }}>⚡</div>
            <div style={{ color:'#555', fontSize:'14px' }}>Select a bank in the panel to begin</div>
          </div>
        )}
      </div>
    </div>
  );
}

