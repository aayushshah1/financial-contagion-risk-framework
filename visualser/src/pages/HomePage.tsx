/**
 * HomePage — 3D network visualisation with bank/leaf/NBFC limits from Tweaks.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { motion, AnimatePresence } from 'framer-motion';
import { useHandTracking } from '../gestures/useHandTracking';
import type { HandState } from '../gestures/useHandTracking';
import { GraphCanvas } from '../graph/GraphCanvas';
import { fetchGraphFromNeo4j } from '../graph/neo4jData';
import { buildBankLeafGraph, isBankNode } from '../graph/bankLeafView';
import type { GraphData, GraphEdge, GraphNode, GraphValue } from '../graph/types';
import { useTweaks } from '../store/useTweaks';

const EMPTY_NODES: GraphNode[] = [];
const EMPTY_EDGES: GraphEdge[] = [];

const CameraController = ({
  gestureState,
  isAutoRotate,
}: {
  gestureState: HandState;
  isAutoRotate: boolean;
}) => {
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

function hasNeo4jLowValue(value: GraphValue): value is { low: GraphValue } {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    'low' in value
  );
}

function formatGraphValue(value: GraphValue): string {
  if (hasNeo4jLowValue(value)) return String(value.low);
  if (Array.isArray(value)) return value.map(formatGraphValue).join(', ');
  if (typeof value === 'object' && value !== null) return JSON.stringify(value);
  return String(value);
}

function getNodeTextProp(node: GraphNode, key: string): string | null {
  const value = node.props[key];
  return typeof value === 'string' && value.trim().length > 0 ? value : null;
}


export function HomePage() {
  const videoRef = useRef<HTMLVideoElement>(null!);
  const handState = useHandTracking(videoRef);
  const { tweaks } = useTweaks();

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isCameraEnabled, setIsCameraEnabled] = useState(true);

  // Derived slider state from tweaks (tweak slider values)
  const [bankLimit, setBankLimit] = useState(tweaks.bankLimit);
  const [leafLimit, setLeafLimit] = useState(tweaks.leafLimit);

  // Sync when tweaks change externally
  useEffect(() => { setBankLimit(tweaks.bankLimit); }, [tweaks.bankLimit]);
  useEffect(() => { setLeafLimit(tweaks.leafLimit); }, [tweaks.leafLimit]);

  useEffect(() => {
    setLoading(true);
    fetchGraphFromNeo4j()
      .then((data) => {
        setGraphData(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Graph fetch error:', err);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        setSelectedNode(null);
        setHoveredEdge(null);
      } else if (e.key.toLowerCase() === 'c') {
        setIsCameraEnabled((v) => !v);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  // Camera / webcam
  useEffect(() => {
    let stream: MediaStream | null = null;
    const el = videoRef.current;
    if (!isCameraEnabled) {
      if (el) el.srcObject = null;
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ video: true })
      .then((s) => {
        stream = s;
        if (el) el.srcObject = s;
      })
      .catch(console.error);
    return () => {
      stream?.getTracks().forEach((t) => t.stop());
      if (el) el.srcObject = null;
    };
  }, [isCameraEnabled]);

  const filteredGraph = useMemo(() => {
    if (!graphData) return null;
    // leafLimit from tweaks = max leaves total = bankLimit * leafLimit
    return buildBankLeafGraph(
      graphData,
      bankLimit,
      bankLimit * leafLimit,
      tweaks.nbfcLimit,
    );
  }, [graphData, bankLimit, leafLimit, tweaks.nbfcLimit]);

  const displayNodes = filteredGraph?.nodes ?? EMPTY_NODES;
  const displayEdges = filteredGraph?.edges ?? EMPTY_EDGES;
  const displayNodeIds = useMemo(
    () => new Set(displayNodes.map((n) => n.id)),
    [displayNodes],
  );
  const displayEdgeIds = useMemo(
    () => new Set(displayEdges.map((e) => e.id)),
    [displayEdges],
  );

  const visibleSelectedNode =
    selectedNode && displayNodeIds.has(selectedNode.id) ? selectedNode : null;
  const visibleHoveredNode =
    hoveredNode && displayNodeIds.has(hoveredNode.id) ? hoveredNode : null;
  const visibleHoveredEdge =
    hoveredEdge && displayEdgeIds.has(hoveredEdge.id) ? hoveredEdge : null;
  const activeNode = visibleHoveredNode || visibleSelectedNode;

  const titleSymbol = useMemo(() => {
    const focused = activeNode && isBankNode(activeNode) ? activeNode : null;
    const fallback = displayNodes.find(isBankNode) ?? null;
    const node = focused ?? fallback;
    if (!node) return 'BANK NETWORK';
    return (
      getNodeTextProp(node, 'bankSymbol') ??
      getNodeTextProp(node, 'bankName') ??
      getNodeTextProp(node, 'name') ??
      'BANK NETWORK'
    );
  }, [activeNode, displayNodes]);

  const pointerPos =
    handState.indexNorm
      ? {
          x: handState.indexNorm.x * window.innerWidth,
          y: handState.indexNorm.y * window.innerHeight,
        }
      : null;

  const connections = [
    [0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],
    [5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],
    [13,17],[0,17],[17,18],[18,19],[19,20],
  ];

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#000', position: 'relative' }}>
      {/* Webcam */}
      {isCameraEnabled && (
        <>
          <video ref={videoRef} autoPlay playsInline muted className="video-background" />
          <div className="video-overlay" />
        </>
      )}

      {/* Hand skeleton */}
      {isCameraEnabled && handState.landmarks && (
        <svg style={{ position:'absolute',top:0,left:0,width:'100%',height:'100%',pointerEvents:'none',zIndex:99 }}>
          {connections.map(([s, e], i) => {
            const p1 = handState.landmarks![s];
            const p2 = handState.landmarks![e];
            return (
              <line key={i}
                x1={(1-p1.x)*window.innerWidth} y1={p1.y*window.innerHeight}
                x2={(1-p2.x)*window.innerWidth} y2={p2.y*window.innerHeight}
                stroke="#00ffcc" strokeWidth="2" opacity="0.6"
              />
            );
          })}
          {handState.landmarks.map((p, i) => (
            <circle key={i} cx={(1-p.x)*window.innerWidth} cy={p.y*window.innerHeight} r="3" fill="#fff" />
          ))}
        </svg>
      )}

      {/* Gesture cursor */}
      {isCameraEnabled && pointerPos && handState.gesture === 'pointing' && (
        <div className="cursor-crosshair" style={{ left: pointerPos.x, top: pointerPos.y, zIndex: 100 }} />
      )}

      {/* Nav bar */}
      <nav className="app-nav">
        <div className="nav-logo">⚠️ FCRF</div>
        <div className="nav-links">
          <Link to="/" className="nav-link nav-link-active">Home</Link>
          <Link to="/simulator" className="nav-link">Simulator</Link>
          <Link to="/tweaks" className="nav-link">Tweaks</Link>
        </div>
        <div className="nav-meta">
          {filteredGraph
            ? `${filteredGraph.appliedBlueCount} banks · ${filteredGraph.appliedWhiteCount} leaves · ${displayEdges.length} edges`
            : loading ? 'Loading…' : '—'}
        </div>
      </nav>

      {/* 3D Canvas */}
      <Canvas style={{ position:'absolute',top:0,left:0,zIndex:3,width:'100%',height:'100%' }}>
        <PerspectiveCamera makeDefault position={[0, 0, tweaks.cameraZoom]} fov={50} />
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={1} />
        <CameraController
          gestureState={handState}
          isAutoRotate={tweaks.cameraAutoRotate && handState.gesture === 'none' && !visibleSelectedNode}
        />
        {graphData ? (
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
            gesturePointer={handState.gesture === 'pointing' ? handState.indexNorm : null}
          />
        ) : (
          <mesh>
            <sphereGeometry args={[0.5, 32, 32]} />
            <meshBasicMaterial color="#ffffff" wireframe />
          </mesh>
        )}
      </Canvas>

      {/* Top-right info overlay */}
      <div className="overlay">
        <div className="top-bar">
          <div className="webcam-container">
            <div className="status-badge">
              {!isCameraEnabled && <><span>📷</span> Camera Off</>}
              {isCameraEnabled && handState.gesture === 'orbit' && <><span>✋</span> Orbiting</>}
              {isCameraEnabled && handState.gesture === 'pointing' && <><span>☝️</span> Pointing</>}
              {isCameraEnabled && handState.gesture === 'none' && <><span>🖱️</span> Mouse Mode</>}
            </div>
          </div>
          <div className="title-block">
            <h1>{titleSymbol}</h1>
            <div className="subtitle">Financial Contagion Risk Framework</div>
            <div className="stats">
              {graphData
                ? `${filteredGraph?.appliedBlueCount??0} banks · ${filteredGraph?.appliedWhiteCount??0} nodes · ${displayEdges.length} edges`
                : loading ? '⏳ Loading graph data…' : 'No data'}
            </div>

            <AnimatePresence>
              {activeNode && (
                <motion.div
                  initial={{ opacity:0, x:20, filter:'blur(10px)' }}
                  animate={{ opacity:1, x:0, filter:'blur(0px)' }}
                  exit={{ opacity:0, scale:0.95 }}
                  className="data-card"
                >
                  <div className="data-card-title">
                    {activeNode.labels[0]} #{activeNode.id}
                  </div>
                  {Object.entries(activeNode.props).map(([key, val]) => (
                    <div className="data-row" key={key}>
                      <span className="data-key" style={{ textTransform:'capitalize' }}>{key}</span>
                      <span className="data-val">{formatGraphValue(val)}</span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {visibleHoveredEdge && !activeNode && (
                <motion.div
                  initial={{ opacity:0, x:20 }}
                  animate={{ opacity:1, x:0 }}
                  exit={{ opacity:0 }}
                  className="data-card"
                >
                  <div className="data-card-title">EDGE: {visibleHoveredEdge.type}</div>
                  {Object.entries(visibleHoveredEdge.props).map(([key, val]) => (
                    <div className="data-row" key={key}>
                      <span className="data-key" style={{ textTransform:'capitalize' }}>{key}</span>
                      <span className="data-val">{formatGraphValue(val)}</span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Quick limit sliders — bottom left */}
      <div className="home-quick-controls">
        <div className="quick-ctrl-row">
          <label>Banks <span>{bankLimit}</span></label>
          <input type="range" min={1} max={filteredGraph?.availableBlueCount ?? 50}
            value={bankLimit}
            onChange={(e) => setBankLimit(Number(e.target.value))}
          />
        </div>
        <div className="quick-ctrl-row">
          <label>Leaves/bank <span>{leafLimit}</span></label>
          <input type="range" min={1} max={20}
            value={leafLimit}
            onChange={(e) => setLeafLimit(Number(e.target.value))}
          />
        </div>
        <div className="quick-ctrl-hint">
          Full settings → <Link to="/tweaks" style={{ color:'#60a5fa' }}>Tweaks</Link>
        </div>
      </div>

      {/* Bottom hints */}
      <div className="bottom-bar">
        <div className="controls-hint">
          <span><kbd>Space</kbd> Reset</span>
          <span><kbd>C</kbd> Camera</span>
          <span>✋ 4-Finger Orbit</span>
          <span>☝️ Point to hover</span>
        </div>
      </div>
    </div>
  );
}
