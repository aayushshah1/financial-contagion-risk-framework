import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from 'd3-force';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { isBankNode, isNbfcNode } from './bankLeafView';
import type { GraphEdge, GraphNode } from './types';

interface GraphPlane2DProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  showLabels: boolean;
  edgeVisibility: 'important' | 'all' | 'hidden';
  nodeTypeFilter: 'all' | 'banks' | 'nbfc' | 'leaves';
  focusMode: boolean;
  zoomLevel: number;
  densityLevel: number;
  selectedNodeId: number | null;
  hoveredNodeId: number | null;
  hoveredEdgeId: string | null;
  onSelectNode: (node: GraphNode | null) => void;
  onHoverNode: (node: GraphNode | null) => void;
  onHoverEdge: (edge: GraphEdge | null) => void;
}

export interface GraphPlane2DHandle {
  downloadImage: () => void;
}

interface Point2D {
  x: number;
  y: number;
}

interface SimNode extends Point2D {
  id: number;
  isBank: boolean;
}

type SimLinkEndpoint = number | SimNode;

interface SimLink {
  id: string;
  source: SimLinkEndpoint;
  target: SimLinkEndpoint;
}

const LABEL_KEYS = ['bankSymbol', 'bankName', 'crisilName', 'companyName', 'name', 'title'] as const;

function endpointId(endpoint: SimLinkEndpoint): number {
  return typeof endpoint === 'number' ? endpoint : endpoint.id;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function resolveNodeLabel(node: GraphNode): string {
  for (const key of LABEL_KEYS) {
    const value = node.props[key];
    if (typeof value === 'string' && value.trim().length > 0) {
      return value;
    }
  }
  return `${node.labels[0] ?? 'Node'} ${node.id}`;
}

function edgePath(source: Point2D, target: Point2D): string {
  return `M ${source.x} ${source.y} L ${target.x} ${target.y}`;
}

function nodeAllowedByFilter(node: GraphNode, filter: GraphPlane2DProps['nodeTypeFilter']): boolean {
  if (filter === 'all') {
    return true;
  }
  if (filter === 'banks') {
    return isBankNode(node);
  }
  if (filter === 'nbfc') {
    return isNbfcNode(node);
  }
  return !isBankNode(node);
}

export const GraphPlane2D = forwardRef<GraphPlane2DHandle, GraphPlane2DProps>(function GraphPlane2D({
  nodes,
  edges,
  showLabels,
  edgeVisibility,
  nodeTypeFilter,
  focusMode,
  zoomLevel,
  densityLevel,
  selectedNodeId,
  hoveredNodeId,
  hoveredEdgeId,
  onSelectNode,
  onHoverNode,
  onHoverEdge,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rotateDragRef = useRef<{ active: boolean; startX: number; startDeg: number }>({
    active: false,
    startX: 0,
    startDeg: 0,
  });
  const panDragRef = useRef<{ active: boolean; startX: number; startY: number; startPanX: number; startPanY: number }>({
    active: false,
    startX: 0,
    startY: 0,
    startPanX: 0,
    startPanY: 0,
  });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [positions, setPositions] = useState<Record<number, Point2D>>({});
  const [rotationDeg, setRotationDeg] = useState(0);
  const [panOffset, setPanOffset] = useState<Point2D>({ x: 0, y: 0 });

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect;
      if (!next) {
        return;
      }
      setSize({ width: next.width, height: next.height });
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const meta = useMemo(() => {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const bankNodes = nodes.filter((node) => isBankNode(node)).sort((left, right) => left.id - right.id);
    const leafOwner = new Map<number, number>();
    const degreeByNode = new Map<number, number>();
    const adjacency = new Map<number, Set<number>>();

    nodes.forEach((node) => {
      degreeByNode.set(node.id, 0);
      adjacency.set(node.id, new Set<number>());
    });

    for (const edge of edges) {
      degreeByNode.set(edge.source, (degreeByNode.get(edge.source) ?? 0) + 1);
      degreeByNode.set(edge.target, (degreeByNode.get(edge.target) ?? 0) + 1);
      adjacency.get(edge.source)?.add(edge.target);
      adjacency.get(edge.target)?.add(edge.source);

      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) {
        continue;
      }

      const sourceIsBank = isBankNode(source);
      const targetIsBank = isBankNode(target);
      if (sourceIsBank === targetIsBank) {
        continue;
      }
      const bank = sourceIsBank ? source : target;
      const leaf = sourceIsBank ? target : source;
      if (!leafOwner.has(leaf.id)) {
        leafOwner.set(leaf.id, bank.id);
      }
    }

    return { nodeById, bankNodes, leafOwner, degreeByNode, adjacency };
  }, [edges, nodes]);

  useEffect(() => {
    if (size.width === 0 || size.height === 0 || nodes.length === 0) {
      return;
    }

    const bankTargetRadius = Math.max(280, Math.min(size.width, size.height) * 0.32);
    const bankTargets = new Map<number, Point2D>();
    meta.bankNodes.forEach((bank, index) => {
      const angle = (index / Math.max(meta.bankNodes.length, 1)) * Math.PI * 2;
      bankTargets.set(bank.id, {
        x: Math.cos(angle) * bankTargetRadius,
        y: Math.sin(angle) * bankTargetRadius,
      });
    });

    const leafOffsets = new Map<number, Point2D>();
    nodes.forEach((node) => {
      if (isBankNode(node)) {
        return;
      }
      const angle = ((node.id * 67) % 360) * (Math.PI / 180);
      const radius = 130 + ((node.id * 29) % 70);
      leafOffsets.set(node.id, {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      });
    });

    const simNodes: SimNode[] = nodes.map((node) => {
      const ownTarget = bankTargets.get(node.id);
      const ownerBankId = meta.leafOwner.get(node.id);
      const ownerTarget = ownerBankId !== undefined ? bankTargets.get(ownerBankId) : undefined;
      const offset = leafOffsets.get(node.id);
      const seed = ((node.id * 17) % 24) - 12;
      return {
        id: node.id,
        isBank: isBankNode(node),
        x: (ownTarget?.x ?? ownerTarget?.x ?? 0) + (offset?.x ?? 0) + seed,
        y: (ownTarget?.y ?? ownerTarget?.y ?? 0) + (offset?.y ?? 0) - seed,
      };
    });

    const simLinks: SimLink[] = edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
    }));

    const simulation = forceSimulation(simNodes)
      .alpha(0.9)
      .alphaTarget(0.012)
      .alphaDecay(0.04)
      .velocityDecay(0.52)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance((link) => {
            const sourceNode = meta.nodeById.get(endpointId(link.source));
            const targetNode = meta.nodeById.get(endpointId(link.target));
            if (!sourceNode || !targetNode) {
              return 180;
            }
            if (isBankNode(sourceNode) && isBankNode(targetNode)) {
              return 230;
            }
            if (isBankNode(sourceNode) || isBankNode(targetNode)) {
              return 170;
            }
            return 130;
          })
          .strength(0.25),
      )
      .force('charge', forceManyBody<SimNode>().strength((node) => (node.isBank ? -740 : -300)))
      .force('collide', forceCollide<SimNode>().radius((node) => (node.isBank ? 40 : 22)).strength(1))
      .force('center', forceCenter(0, 0))
      .force(
        'x',
        forceX<SimNode>((node) => {
          if (node.isBank) {
            return bankTargets.get(node.id)?.x ?? 0;
          }
          const ownerBankId = meta.leafOwner.get(node.id);
          const ownerTarget = ownerBankId !== undefined ? bankTargets.get(ownerBankId) : undefined;
          const offset = leafOffsets.get(node.id);
          return (ownerTarget?.x ?? 0) + (offset?.x ?? 0);
        }).strength((node) => (node.isBank ? 0.14 : 0.05)),
      )
      .force(
        'y',
        forceY<SimNode>((node) => {
          if (node.isBank) {
            return bankTargets.get(node.id)?.y ?? 0;
          }
          const ownerBankId = meta.leafOwner.get(node.id);
          const ownerTarget = ownerBankId !== undefined ? bankTargets.get(ownerBankId) : undefined;
          const offset = leafOffsets.get(node.id);
          return (ownerTarget?.y ?? 0) + (offset?.y ?? 0);
        }).strength((node) => (node.isBank ? 0.14 : 0.05)),
      );

    let frameId = 0;
    const commitPositions = () => {
      if (frameId !== 0) {
        return;
      }
      frameId = window.requestAnimationFrame(() => {
        frameId = 0;
        const margin = 56;
        setPositions(
          Object.fromEntries(
            simNodes.map((node) => [
              node.id,
              {
                x: clamp((node.x ?? 0) + size.width / 2, margin, size.width - margin),
                y: clamp((node.y ?? 0) + size.height / 2, margin, size.height - margin),
              },
            ]),
          ),
        );
      });
    };

    simulation.on('tick', commitPositions);
    commitPositions();

    return () => {
      simulation.on('tick', null);
      simulation.stop();
      if (frameId !== 0) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [edges, meta, nodes, size.height, size.width]);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;
  const topN = clamp(Math.round(densityLevel), 10, 40);
  const topNodeIds = useMemo(() => {
    return new Set(
      [...meta.degreeByNode.entries()]
        .sort((left, right) => right[1] - left[1])
        .slice(0, topN)
        .map(([nodeId]) => nodeId),
    );
  }, [meta.degreeByNode, topN]);

  const focusNodeIds = useMemo(() => {
    if (!focusMode || selectedNodeId === null) {
      return null;
    }
    const visited = new Set<number>([selectedNodeId]);
    let frontier = new Set<number>([selectedNodeId]);
    for (let hop = 0; hop < 2; hop += 1) {
      const next = new Set<number>();
      frontier.forEach((nodeId) => {
        const neighbors = meta.adjacency.get(nodeId) ?? new Set<number>();
        neighbors.forEach((neighborId) => {
          if (!visited.has(neighborId)) {
            visited.add(neighborId);
            next.add(neighborId);
          }
        });
      });
      frontier = next;
    }
    return visited;
  }, [focusMode, meta.adjacency, selectedNodeId]);

  const renderNodes = useMemo(
    () => nodes.filter((node) => nodeAllowedByFilter(node, nodeTypeFilter)),
    [nodeTypeFilter, nodes],
  );
  const renderNodeIds = useMemo(() => new Set(renderNodes.map((node) => node.id)), [renderNodes]);

  const renderEdges = useMemo(() => {
    if (edgeVisibility === 'hidden') {
      return [];
    }
    return edges.filter((edge) => renderNodeIds.has(edge.source) && renderNodeIds.has(edge.target));
  }, [edgeVisibility, edges, renderNodeIds]);

  const edgeMap = useMemo(() => new Map(edges.map((edge) => [edge.id, edge])), [edges]);
  const center = useMemo(() => ({ x: size.width / 2, y: size.height / 2 }), [size.height, size.width]);
  const focusTarget = focusMode && selectedNodeId !== null && positions[selectedNodeId]
    ? positions[selectedNodeId]
    : center;
  const focusScale = focusMode && selectedNodeId !== null ? 1.16 : 1;
  const sceneTransform = `translate(${center.x + panOffset.x} ${center.y + panOffset.y}) scale(${zoomLevel * focusScale}) rotate(${rotationDeg}) translate(${-focusTarget.x} ${-focusTarget.y})`;

  const getNodeRadius = useCallback((node: GraphNode): number => {
    const degree = meta.degreeByNode.get(node.id) ?? 0;
    if (isBankNode(node)) {
      return clamp(11 + degree * 0.65, 11, 22);
    }
    return clamp(5.5 + degree * 0.4, 5.5, 11);
  }, [meta.degreeByNode]);

  useImperativeHandle(ref, () => ({
    downloadImage: () => {
      if (size.width === 0 || size.height === 0 || renderNodes.length === 0) {
        return;
      }

      const canvas = document.createElement('canvas');
      canvas.width = Math.floor(size.width);
      canvas.height = Math.floor(size.height);
      const context = canvas.getContext('2d');
      if (!context) {
        return;
      }

      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.save();
      context.translate(center.x + panOffset.x, center.y + panOffset.y);
      context.scale(zoomLevel * focusScale, zoomLevel * focusScale);
      context.rotate((rotationDeg * Math.PI) / 180);
      context.translate(-focusTarget.x, -focusTarget.y);

      const exportNodeIds = new Set<number>();
      if (selectedNodeId !== null) {
        if (focusNodeIds) {
          focusNodeIds.forEach((nodeId) => exportNodeIds.add(nodeId));
        } else {
          exportNodeIds.add(selectedNodeId);
          const neighbors = meta.adjacency.get(selectedNodeId) ?? new Set<number>();
          neighbors.forEach((neighborId) => exportNodeIds.add(neighborId));
        }
      } else {
        renderNodes.forEach((node) => exportNodeIds.add(node.id));
      }

      const exportNodes = renderNodes.filter((node) => exportNodeIds.has(node.id));
      const exportEdges = renderEdges.filter(
        (edge) => exportNodeIds.has(edge.source) && exportNodeIds.has(edge.target),
      );

      exportEdges.forEach((edge) => {
        const source = positions[edge.source];
        const target = positions[edge.target];
        if (!source || !target) {
          return;
        }

        context.beginPath();
        context.moveTo(source.x, source.y);
        context.lineTo(target.x, target.y);
        context.strokeStyle = '#000000';
        context.lineWidth = 1.4;
        context.globalAlpha = 0.9;
        context.stroke();
      });

      exportNodes.forEach((node) => {
        const point = positions[node.id];
        if (!point) {
          return;
        }

        context.beginPath();
        context.arc(point.x, point.y, getNodeRadius(node), 0, Math.PI * 2);
        context.fillStyle = isNbfcNode(node) ? '#facc15' : isBankNode(node) ? '#2563eb' : '#1f6f3d';
        context.globalAlpha = 1;
        context.fill();
        context.strokeStyle = '#0f172a';
        context.lineWidth = 1;
        context.stroke();

        const label = resolveNodeLabel(node);
        const bankNode = isBankNode(node);
        context.fillStyle = '#111827';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.font = bankNode ? '600 12px Inter, sans-serif' : '500 10px Inter, sans-serif';
        context.fillText(label, point.x, bankNode ? point.y - 18 : point.y + 16);
      });

      context.restore();
      canvas.toBlob((blob) => {
        if (!blob) {
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'network-2d-export.png';
        link.click();
        URL.revokeObjectURL(url);
      }, 'image/png');
    },
  }), [center, focusNodeIds, focusScale, focusTarget, getNodeRadius, meta.adjacency, panOffset, positions, renderEdges, renderNodes, rotationDeg, selectedNodeId, size.height, size.width, zoomLevel]);

  const handlePointerDown = (event: ReactMouseEvent<SVGSVGElement>) => {
    if (event.button !== 2) {
      if (event.button === 0 && event.target === event.currentTarget) {
        panDragRef.current = {
          active: true,
          startX: event.clientX,
          startY: event.clientY,
          startPanX: panOffset.x,
          startPanY: panOffset.y,
        };
      }
      return;
    }
    event.preventDefault();
    rotateDragRef.current = {
      active: true,
      startX: event.clientX,
      startDeg: rotationDeg,
    };
  };

  const handlePointerMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    if (rotateDragRef.current.active) {
      event.preventDefault();
      const deltaX = event.clientX - rotateDragRef.current.startX;
      setRotationDeg(rotateDragRef.current.startDeg + deltaX * 0.35);
      return;
    }

    if (panDragRef.current.active) {
      event.preventDefault();
      const deltaX = event.clientX - panDragRef.current.startX;
      const deltaY = event.clientY - panDragRef.current.startY;
      setPanOffset({
        x: panDragRef.current.startPanX + deltaX,
        y: panDragRef.current.startPanY + deltaY,
      });
    }
  };

  const handlePointerEnd = () => {
    rotateDragRef.current.active = false;
    panDragRef.current.active = false;
  };

  return (
    <div ref={containerRef} style={{ position: 'absolute', inset: 0, zIndex: 3 }}>
      <svg
        style={{ width: '100%', height: '100%' }}
        viewBox={`0 0 ${size.width || 1} ${size.height || 1}`}
        onContextMenu={(event) => event.preventDefault()}
        onMouseDown={handlePointerDown}
        onMouseMove={handlePointerMove}
        onMouseUp={handlePointerEnd}
        onMouseLeave={handlePointerEnd}
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            onSelectNode(null);
            onHoverNode(null);
            onHoverEdge(null);
          }
        }}
      >
        <g transform={sceneTransform}>
          {renderEdges.map((edge) => {
            const source = positions[edge.source];
            const target = positions[edge.target];
            if (!source || !target) {
              return null;
            }

            const isActiveEdge = hoveredEdgeId === edge.id
              || (activeNodeId !== null && (edge.source === activeNodeId || edge.target === activeNodeId));
            const inFocus = focusNodeIds === null || (focusNodeIds.has(edge.source) && focusNodeIds.has(edge.target));
            const opacity = isActiveEdge ? 0.95 : inFocus ? 0.62 : 0.18;
            if (edgeVisibility === 'important' && !isActiveEdge && activeNodeId !== null) {
              return null;
            }

            const path = edgePath(source, target);

            return (
              <g key={edge.id}>
                <path
                  d={path}
                  fill="none"
                  stroke="#9ca3af"
                  strokeOpacity={opacity}
                  strokeWidth={isActiveEdge ? 2.6 : 1.3}
                />
                <path
                  d={path}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={12}
                  onMouseEnter={(event) => {
                    event.stopPropagation();
                    onHoverEdge(edgeMap.get(edge.id) ?? null);
                    onHoverNode(null);
                  }}
                  onMouseLeave={() => onHoverEdge(null)}
                />
              </g>
            );
          })}

          {renderNodes.map((node) => {
            const point = positions[node.id];
            if (!point) {
              return null;
            }

            const bankNode = isBankNode(node);
            const nbfcNode = isNbfcNode(node);
            const radius = getNodeRadius(node);
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNodeId === node.id;
            const inFocus = focusNodeIds?.has(node.id) ?? true;
            const opacity = inFocus ? 1 : 0.22;
            const showNodeLabel = isSelected || isHovered || topNodeIds.has(node.id) || (showLabels && isHovered);

            return (
              <g
                key={node.id}
                transform={`translate(${point.x}, ${point.y})`}
                onMouseEnter={(event) => {
                  event.stopPropagation();
                  onHoverNode(node);
                  onHoverEdge(null);
                }}
                onMouseLeave={() => onHoverNode(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectNode(node);
                }}
                style={{ cursor: 'pointer', opacity }}
              >
                <circle
                  r={radius + 7}
                  fill={nbfcNode
                    ? 'rgba(250, 204, 21, 0.24)'
                    : bankNode
                      ? 'rgba(59, 130, 246, 0.24)'
                      : 'rgba(255, 255, 255, 0.16)'}
                />
                <circle
                  r={radius}
                  fill={nbfcNode ? '#facc15' : bankNode ? '#3b82f6' : '#ffffff'}
                  stroke={isSelected || isHovered ? '#ffffff' : nbfcNode ? '#a16207' : bankNode ? '#1d4ed8' : '#cfcfcf'}
                  strokeWidth={isSelected || isHovered ? 2.6 : 1.4}
                />
                {showNodeLabel && (
                  <text
                    y={bankNode ? -18 : 15}
                    textAnchor="middle"
                    fill="#f9fafb"
                    style={{
                      fontSize: bankNode ? '12px' : '10px',
                      fontWeight: bankNode ? 600 : 500,
                      pointerEvents: 'none',
                      userSelect: 'none',
                    }}
                  >
                    {resolveNodeLabel(node)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
});
