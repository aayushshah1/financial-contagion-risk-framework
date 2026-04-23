import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force';
import { useEffect, useMemo, useRef, useState } from 'react';
import { APP_COLORS, getEdgeBaseColor, getNodeFillColor, hexToRgba } from './model';
import type { EnrichedGraphData, EnrichedGraphEdge, EnrichedGraphNode, RiskCluster } from './types';

type GraphPoint = { x: number; y: number };

interface ForceGraph2DProps {
  graphData: EnrichedGraphData;
  selectedNodeId: number | null;
  hoveredNodeId: number | null;
  hoveredEdgeId: string | null;
  onSelectNode: (node: EnrichedGraphNode | null) => void;
  onHoverNode: (node: EnrichedGraphNode | null) => void;
  onHoverEdge: (edge: EnrichedGraphEdge | null) => void;
  zoomLevel: number;
  riskHighlightEnabled: boolean;
}

interface SimNode extends GraphPoint {
  id: number;
  bankGroup: string | null;
}

interface SimLink {
  id: string;
  source: number;
  target: number;
}

function getNodeRadius(node: EnrichedGraphNode): number {
  const base = node.kind === 'CentralBank'
    ? 14
    : node.kind === 'CommercialBank'
      ? 11
      : node.kind === 'Company'
        ? 8
        : 6;

  return Math.min(20, base + node.degree * 0.8);
}

export function ForceGraph2D({
  graphData,
  selectedNodeId,
  hoveredNodeId,
  hoveredEdgeId,
  onSelectNode,
  onHoverNode,
  onHoverEdge,
  zoomLevel,
  riskHighlightEnabled,
}: ForceGraph2DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [positions, setPositions] = useState<Record<number, GraphPoint>>({});

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

  const zoomScale = 16 / Math.max(zoomLevel, 2);

  useEffect(() => {
    if (size.width === 0 || size.height === 0 || graphData.nodes.length === 0) {
      return;
    }

    const groupIds = [...new Set(graphData.nodes.map((node) => node.bankGroup ?? `ungrouped:${node.kind}`))];
    const groupRadius = Math.max(120, Math.min(size.width, size.height) * 0.18);
    const centers = new Map<string, GraphPoint>();
    groupIds.forEach((groupId, index) => {
      const angle = (index / Math.max(groupIds.length, 1)) * Math.PI * 2;
      centers.set(groupId, {
        x: Math.cos(angle) * groupRadius,
        y: Math.sin(angle) * groupRadius,
      });
    });

    const simNodes: SimNode[] = graphData.nodes.map((node) => ({
      id: node.id,
      bankGroup: node.bankGroup,
      x: 0,
      y: 0,
    }));

    const simLinks: SimLink[] = graphData.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
    }));

    const simulation = forceSimulation(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance((link) => {
            const source = graphData.nodes.find((node) => node.id === link.source);
            const target = graphData.nodes.find((node) => node.id === link.target);
            if (!source || !target) {
              return 90;
            }

            if (source.kind.includes('Bank') || target.kind.includes('Bank')) {
              return 110;
            }

            return 70;
          })
          .strength(0.2),
      )
      .force('charge', forceManyBody().strength(-260))
      .force(
        'collide',
        forceCollide<SimNode>((node) => {
          const sourceNode = graphData.nodes.find((candidate) => candidate.id === node.id);
          return sourceNode ? getNodeRadius(sourceNode) + 10 : 16;
        }),
      )
      .force('center', forceCenter(0, 0))
      .force(
        'x',
        forceX<SimNode>((node) => {
          const center = centers.get(node.bankGroup ?? `ungrouped:${graphData.nodes.find((candidate) => candidate.id === node.id)?.kind ?? 'Leaf'}`);
          return center?.x ?? 0;
        }).strength(0.18),
      )
      .force(
        'y',
        forceY<SimNode>((node) => {
          const center = centers.get(node.bankGroup ?? `ungrouped:${graphData.nodes.find((candidate) => candidate.id === node.id)?.kind ?? 'Leaf'}`);
          return center?.y ?? 0;
        }).strength(0.18),
      );

    let tickCount = 0;
    simulation.on('tick', () => {
      tickCount += 1;
      if (tickCount % 2 !== 0) {
        return;
      }

      setPositions(
        Object.fromEntries(
          simNodes.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]),
        ),
      );
    });

    return () => {
      simulation.stop();
    };
  }, [graphData.edges, graphData.nodes, size.height, size.width]);

  const edgeMap = useMemo(
    () => new Map(graphData.edges.map((edge) => [edge.id, edge])),
    [graphData.edges],
  );

  const clusterOverlays = useMemo(() => {
    return graphData.clusters
      .map((cluster) => {
        const points = cluster.nodeIds
          .map((nodeId) => positions[nodeId])
          .filter((point): point is GraphPoint => Boolean(point));

        if (points.length < 2) {
          return null;
        }

        const center = points.reduce(
          (accumulator, point) => ({
            x: accumulator.x + point.x,
            y: accumulator.y + point.y,
          }),
          { x: 0, y: 0 },
        );

        center.x /= points.length;
        center.y /= points.length;

        const radius = points.reduce((largest, point) => {
          const distance = Math.hypot(point.x - center.x, point.y - center.y);
          return Math.max(largest, distance);
        }, 0) + 46;

        return { cluster, center, radius };
      })
      .filter((overlay): overlay is { cluster: RiskCluster; center: GraphPoint; radius: number } => Boolean(overlay));
  }, [graphData.clusters, positions]);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;

  return (
    <div ref={containerRef} className="graph-surface graph-surface-2d">
      <svg
        className="force-graph"
        viewBox={`0 0 ${size.width || 1} ${size.height || 1}`}
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            onSelectNode(null);
            onHoverNode(null);
            onHoverEdge(null);
          }
        }}
      >
        <g transform={`translate(${size.width / 2}, ${size.height / 2}) scale(${zoomScale})`}>
          {riskHighlightEnabled && clusterOverlays.map(({ cluster, center, radius }) => (
            <g key={cluster.id}>
              <circle
                cx={center.x}
                cy={center.y}
                r={radius}
                fill={hexToRgba(cluster.accentColor, 0.07)}
                stroke={hexToRgba(cluster.accentColor, 0.55)}
                strokeWidth={2}
                strokeDasharray="10 8"
              />
            </g>
          ))}

          {graphData.edges.map((edge) => {
            const source = positions[edge.source];
            const target = positions[edge.target];
            if (!source || !target) {
              return null;
            }

            const isActive = edge.id === hoveredEdgeId
              || edge.source === activeNodeId
              || edge.target === activeNodeId;
            const stroke = getEdgeBaseColor(edge, riskHighlightEnabled);

            return (
              <g key={edge.id}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={stroke}
                  strokeOpacity={isActive ? 0.95 : 0.28}
                  strokeWidth={isActive ? 3 : 1.5}
                />
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
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

          {graphData.nodes.map((node) => {
            const point = positions[node.id];
            if (!point) {
              return null;
            }

            const radius = getNodeRadius(node);
            const fill = getNodeFillColor(node, riskHighlightEnabled);
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNodeId === node.id;
            const isConnectedToActive = graphData.edges.some((edge) => (
              (edge.source === activeNodeId && edge.target === node.id)
              || (edge.target === activeNodeId && edge.source === node.id)
            ));
            const emphasize = isSelected || isHovered || isConnectedToActive;

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
              >
                <circle
                  r={radius + 8}
                  fill={hexToRgba(node.accentColor, emphasize ? 0.18 : 0.08)}
                />
                <circle
                  r={radius}
                  fill={fill}
                  stroke={isSelected ? APP_COLORS.white : node.accentColor}
                  strokeWidth={isSelected ? 3 : 1.5}
                />
                {emphasize && (
                  <circle
                    r={radius + 5}
                    fill="none"
                    stroke={hexToRgba(APP_COLORS.white, 0.55)}
                    strokeWidth={1.5}
                  />
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
