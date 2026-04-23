import { PanelLeftClose, PanelLeftOpen, Search, ShieldAlert } from 'lucide-react';
import type { EnrichedGraphNode, NodeKind } from '../graph/types';

interface GraphSidebarProps {
  isOpen: boolean;
  onToggleOpen: () => void;
  nodeKinds: NodeKind[];
  visibleKinds: Set<NodeKind>;
  onToggleKind: (kind: NodeKind) => void;
  riskHighlightEnabled: boolean;
  onToggleRiskHighlight: () => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  searchResults: EnrichedGraphNode[];
  onSelectSearchResult: (node: EnrichedGraphNode) => void;
}

const KIND_LABELS: Record<NodeKind, string> = {
  CentralBank: 'Central Banks',
  CommercialBank: 'Commercial Banks',
  Company: 'Companies',
  Leaf: 'Leaf Nodes',
};

export function GraphSidebar({
  isOpen,
  onToggleOpen,
  nodeKinds,
  visibleKinds,
  onToggleKind,
  riskHighlightEnabled,
  onToggleRiskHighlight,
  searchQuery,
  onSearchQueryChange,
  searchResults,
  onSelectSearchResult,
}: GraphSidebarProps) {
  return (
    <aside className={isOpen ? 'graph-sidebar is-open' : 'graph-sidebar'}>
      <button className="sidebar-toggle" onClick={onToggleOpen} type="button">
        {isOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        <span>{isOpen ? 'Collapse' : 'Filters'}</span>
      </button>

      {isOpen && (
        <div className="sidebar-panel">
          <div className="sidebar-section">
            <div className="sidebar-title">Search Node</div>
            <label className="search-field">
              <Search size={16} />
              <input
                value={searchQuery}
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="Search by name"
                type="search"
              />
            </label>
            {searchQuery.trim().length > 0 && (
              <div className="search-results">
                {searchResults.length > 0 ? searchResults.map((node) => (
                  <button
                    key={node.id}
                    className="search-result"
                    onClick={() => onSelectSearchResult(node)}
                    type="button"
                  >
                    <span>{node.displayName}</span>
                    <small>{node.kind}</small>
                  </button>
                )) : (
                  <div className="sidebar-empty">No matching nodes in the current filters.</div>
                )}
              </div>
            )}
          </div>

          <div className="sidebar-section">
            <div className="sidebar-title">Node Types</div>
            <div className="filter-list">
              {nodeKinds.map((kind) => (
                <label key={kind} className="filter-row">
                  <input
                    checked={visibleKinds.has(kind)}
                    onChange={() => onToggleKind(kind)}
                    type="checkbox"
                  />
                  <span>{KIND_LABELS[kind]}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="sidebar-section">
            <div className="sidebar-title">Risk Overlay</div>
            <button className="pill-button" onClick={onToggleRiskHighlight} type="button">
              <ShieldAlert size={16} />
              <span>{riskHighlightEnabled ? 'Risk highlight on' : 'Risk highlight off'}</span>
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
