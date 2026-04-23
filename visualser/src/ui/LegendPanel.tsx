interface LegendPanelProps {
  dataSource: 'neo4j' | 'demo';
  zoomLevel: number;
  onZoomLevelChange: (value: number) => void;
  edgeTypes: string[];
}

export function LegendPanel({
  dataSource,
  zoomLevel,
  onZoomLevelChange,
  edgeTypes,
}: LegendPanelProps) {
  return (
    <div className="legend-panel">
      <div className="legend-section">
        <label className="legend-label">
          <span>Data Source</span>
          <span className="legend-chip">{dataSource === 'neo4j' ? 'Proxy / Neo4j' : 'Client Demo'}</span>
        </label>
      </div>

      <div className="legend-section">
        <label className="legend-label">
          <span>Zoom Level</span>
          <span>{zoomLevel.toFixed(1)}</span>
        </label>
        <input
          max={15}
          min={2}
          onChange={(event) => onZoomLevelChange(Number(event.target.value))}
          step={0.1}
          type="range"
          value={zoomLevel}
        />
      </div>

      <div className="legend-section">
        <div className="legend-label">
          <span>Edge Types</span>
        </div>
        <div className="edge-legend">
          {edgeTypes.map((edgeType) => (
            <div key={edgeType} className="edge-legend-row">
              <span className="edge-legend-line" />
              <span>{edgeType}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
