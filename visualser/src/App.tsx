import { useRef, useState, useEffect } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera } from '@react-three/drei';
import { motion, AnimatePresence } from 'framer-motion';
import { useHandTracking } from './gestures/useHandTracking';
import { GraphCanvas } from './graph/GraphCanvas';
import type { GraphNode, GraphEdge } from './graph/demoData';
import { generateDemoGraph } from './graph/demoData';
import { fetchGraphFromNeo4j } from './graph/neo4jData';

const CameraController = ({ gestureState, isAutoRotate }: { gestureState: any, isAutoRotate: boolean }) => {
  const controlsRef = useRef<any>(null);

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


function App() {
  const videoRef = useRef<HTMLVideoElement>(null!);
  const handState = useHandTracking(videoRef);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null);
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[], edges: GraphEdge[] } | null>(null);
  const [nodeLimit, setNodeLimit] = useState<number>(10);
  const [cameraZoom, setCameraZoom] = useState<number>(5);
  const [dataSource, setDataSource] = useState<'neo4j' | 'demo'>('neo4j');

  useEffect(() => {
    if (dataSource === 'neo4j') {
      fetchGraphFromNeo4j().then(setGraphData).catch(err => console.error("Neo4j error:", err));
    } else {
      setGraphData(generateDemoGraph());
    }

    navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
    }).catch(err => console.error(err));

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === ' ') {
        setSelectedNode(null);
        setHoveredEdge(null);
      } else if (e.key.toLowerCase() === 'p') {
        setDataSource('neo4j');
      } else if (e.key.toLowerCase() === 'd') {
        setDataSource('demo');
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [dataSource]);

  // Translate Hand Point to Screen Coordinates
  const pointerPos = handState.indexNorm ? {
    x: handState.indexNorm.x * window.innerWidth,
    y: handState.indexNorm.y * window.innerHeight
  } : null;

  // When hand points, we want to simulate a mouse hover.
  // We can do this cleanly by positioning a small div exactly at the pointer location
  // and using pointer-events. However, since R3F listens to the canvas, we need to map
  // the pointer coordinate to R3F's raycaster.
  // Actually, the easiest way to show the data card is just using the hoveredNode state from mouse
  // and we'll add a raycast loop inside the canvas for gestures.
  const activeNode = hoveredNode || selectedNode;

  const displayNodes = graphData?.nodes.slice(0, nodeLimit) || [];
  const displayNodeIds = new Set(displayNodes.map(n => n.id));
  const displayEdges = graphData?.edges.filter(e => displayNodeIds.has(e.source) && displayNodeIds.has(e.target)) || [];

  // MediaPipe Hand Connections
  const connections = [
    [0, 1], [1, 2], [2, 3], [3, 4], // Thumb
    [0, 5], [5, 6], [6, 7], [7, 8], // Index
    [5, 9], [9, 10], [10, 11], [11, 12], // Middle
    [9, 13], [13, 14], [14, 15], [15, 16], // Ring
    [13, 17], [0, 17], [17, 18], [18, 19], [19, 20] // Pinky & Palm
  ];

  return (
    <div style={{ width: '100vw', height: '100vh', background: '#050505', position: 'relative' }}>

      {/* Fullscreen Webcam Background */}
      <video ref={videoRef} autoPlay playsInline muted className="video-background" />
      <div className="video-overlay" />

      {/* Hand Tracking SVG Overlay */}
      {handState.landmarks && (
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
      {pointerPos && handState.gesture === 'pointing' && (
        <div className="cursor-crosshair" style={{ left: pointerPos.x, top: pointerPos.y, zIndex: 100 }} />
      )}

      <Canvas style={{ position: 'absolute', top: 0, left: 0, zIndex: 3, width: '100%', height: '100%' }}>
        <PerspectiveCamera makeDefault position={[0, 0, cameraZoom]} fov={50} />
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={1} />

        <CameraController
          gestureState={handState}
          isAutoRotate={handState.gesture === 'none' && !selectedNode}
        />

        {graphData ? (
          <GraphCanvas
            nodes={displayNodes}
            edges={displayEdges}
            topology={'centralized'}
            selectedNodeId={selectedNode?.id ?? null}
            onSelectNode={setSelectedNode}
            onHoverNode={setHoveredNode}
            hoveredNodeId={hoveredNode?.id ?? null}
            onHoverEdge={setHoveredEdge}
            hoveredEdgeId={hoveredEdge?.id ?? null}
            // We pass the pointer override
            gesturePointer={handState.gesture === 'pointing' ? handState.indexNorm : null}
          />
        ) : (
          <mesh>
            <sphereGeometry args={[0.5, 32, 32]} />
            <meshBasicMaterial color="#ffffff" wireframe />
          </mesh>
        )}
      </Canvas>

      {/* UI Overlay */}
      <div className="bottom-bar">
        <div className="controls-hint">
          <span><kbd>Space</kbd> Reset</span>
          <span>✋ 4-Finger Orbit</span>
          <span>☝️ Index Point</span>
        </div>
      </div>
      <div className="overlay">
        <div className="top-bar">
          <div className="webcam-container">
            <div className="status-badge">
              {handState.gesture === 'v_zoom' && <><span>✌️</span> Zooming</>}
              {handState.gesture === 'orbit' && <><span>✋</span> Orbiting</>}
              {handState.gesture === 'pointing' && <><span>☝️</span> Pointing</>}
              {handState.gesture === 'none' && <><span>🖱️</span> Mouse Mode</>}
            </div>
          </div>

          <div className="title-block">
            <h1>Neo4J Capstone Bank Contagion</h1>
            <div className="stats" style={{ marginBottom: '10px' }}>
              {graphData ? `${displayNodes.length} nodes • ${displayEdges.length} edges` : "Loading Graph Data..."}
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
                      <span className="data-val">
                        {val && typeof val === 'object' && val.low !== undefined ? val.low : String(val)}
                      </span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {hoveredEdge && !activeNode && (
                <motion.div
                  initial={{ opacity: 0, x: 20, filter: 'blur(10px)' }}
                  animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
                  exit={{ opacity: 0, scale: 0.95, filter: 'blur(10px)' }}
                  className="data-card"
                >
                  <div className="data-card-title">
                    EDGE: {hoveredEdge.type}
                  </div>
                  {Object.entries(hoveredEdge.props).map(([key, val]) => (
                    <div className="data-row" key={key}>
                      <span className="data-key" style={{ textTransform: 'capitalize' }}>{key}</span>
                      <span className="data-val">
                        {val && typeof val === 'object' && val.low !== undefined ? val.low : String(val)}
                      </span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {graphData && (
        <div style={{
          position: 'absolute',
          bottom: '20px',
          right: '20px',
          zIndex: 100,
          display: 'flex',
          flexDirection: 'column',
          gap: '15px',
          background: 'rgba(0,0,0,0.6)',
          padding: '15px',
          borderRadius: '10px',
          border: '1px solid rgba(255,255,255,0.1)'
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
            <label style={{ fontSize: '12px', color: '#aaaaaa' }}>Showing {nodeLimit} / {graphData.nodes.length} nodes</label>
            <input
              type="range"
              min={1}
              max={graphData.nodes.length}
              value={nodeLimit}
              onChange={(e) => setNodeLimit(parseInt(e.target.value))}
              style={{ width: '200px' }}
            />
          </div>

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
        </div>
      )}
    </div>
  );
}

export default App;
