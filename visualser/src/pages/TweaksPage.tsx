/**
 * TweaksPage — all visualiser settings stored in localStorage via useTweaks.
 */

import { useTweaks } from '../store/useTweaks';
import { useMemo, useState, useEffect } from 'react';
import { fetchGraphFromNeo4j } from '../graph/neo4jData';
import { isBankNode } from '../graph/bankLeafView';
import type { GraphData } from '../graph/types';

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="tweak-row">
      <div className="tweak-label">
        <span>{label}</span>
        <span className="tweak-value">{value}{unit}</span>
      </div>
      <input
        type="range"
        className="tweak-slider"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
      />
      <div className="tweak-minmax">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  );
}

export function TweaksPage() {
  const { tweaks, setTweak, resetTweaks } = useTweaks();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchGraphFromNeo4j()
      .then(setGraphData)
      .catch(console.error);
  }, []);

  const stats = useMemo(() => {
    if (!graphData) return null;
    const banks = graphData.nodes.filter(isBankNode);
    const leaves = graphData.nodes.filter((n) => !isBankNode(n));
    return { totalBanks: banks.length, totalLeaves: leaves.length };
  }, [graphData]);

  const estimatedNodes = useMemo(() => {
    const approxLeaves = Math.min(tweaks.bankLimit * tweaks.leafLimit, tweaks.nbfcLimit + tweaks.bankLimit * tweaks.leafLimit);
    return tweaks.bankLimit + approxLeaves;
  }, [tweaks]);

  function handleSave() {
    // Settings are already auto-saved via setTweak, just show feedback
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="tweaks-page">
      <div className="tweaks-content">
        <div className="tweaks-header">
          <div>
            <h2 className="tweaks-title">⚙️ Visualiser Tweaks</h2>
            <p className="tweaks-subtitle">All settings persist across sessions via localStorage</p>
          </div>
          <div style={{ display:'flex', gap:'10px', alignItems:'center' }}>
            <div className={`tweak-saved-badge ${saved ? 'tweak-saved-badge-visible' : ''}`}>✓ Saved</div>
            <button className="tweak-reset-btn" onClick={resetTweaks}>Reset Defaults</button>
            <button className="tweak-save-btn" onClick={handleSave}>Apply</button>
          </div>
        </div>

        {/* Estimated size */}
        <div className="tweak-estimate">
          <span className="tweak-estimate-label">Estimated visible nodes</span>
          <span className="tweak-estimate-value">~{estimatedNodes}</span>
          <span className="tweak-estimate-hint">
            {estimatedNodes > 300 && '⚠️ High node count may slow rendering'}
            {estimatedNodes <= 300 && estimatedNodes > 100 && '✓ Moderate — should run smoothly'}
            {estimatedNodes <= 100 && '✓ Light — optimal performance'}
          </span>
        </div>

        <div className="tweaks-grid">
          {/* Node Limits */}
          <div className="tweak-card">
            <div className="tweak-card-title">
              <span className="tweak-card-icon">🔵</span>
              Node Limits — Home View
            </div>
            <div className="tweak-card-desc">
              Control how many nodes are rendered on the home 3D graph.
            </div>

            <Slider
              label="Bank nodes"
              value={tweaks.bankLimit}
              min={1}
              max={Math.max(stats?.totalBanks ?? 50, tweaks.bankLimit)}
              onChange={(v) => setTweak('bankLimit', v)}
            />
            <Slider
              label="Leaf nodes per bank"
              value={tweaks.leafLimit}
              min={1}
              max={20}
              onChange={(v) => setTweak('leafLimit', v)}
            />
            <Slider
              label="NBFC node cap (total)"
              value={tweaks.nbfcLimit}
              min={0}
              max={100}
              onChange={(v) => setTweak('nbfcLimit', v)}
            />
          </div>

          {/* 3D Layout */}
          <div className="tweak-card">
            <div className="tweak-card-title">
              <span className="tweak-card-icon">🌐</span>
              3D Layout
            </div>
            <div className="tweak-card-desc">
              How nodes are spatially arranged in the 3D view.
            </div>
            <div className="tweak-layout-btns">
              {(['centralized', 'separated', 'decentralized'] as const).map((layout) => (
                <button
                  key={layout}
                  className={`tweak-layout-btn ${tweaks.threeDLayout === layout ? 'tweak-layout-btn-active' : ''}`}
                  onClick={() => setTweak('threeDLayout', layout)}
                >
                  {layout === 'centralized' ? '🔵 Cluster' : layout === 'separated' ? '📐 Separated' : '🌐 Groups'}
                </button>
              ))}
            </div>
            <div className="tweak-layout-desc">
              {tweaks.threeDLayout === 'centralized' && 'Highest-degree node at centre, others orbiting by BFS distance.'}
              {tweaks.threeDLayout === 'separated' && 'Banks inner, NBFCs mid-shell, leaves outer — visually layered.'}
              {tweaks.threeDLayout === 'decentralized' && 'Each label-type forms its own hub cluster.'}
            </div>
          </div>

          {/* Camera */}
          <div className="tweak-card">
            <div className="tweak-card-title">
              <span className="tweak-card-icon">📷</span>
              Camera
            </div>
            <Slider
              label="Zoom (initial Z distance)"
              value={tweaks.cameraZoom}
              min={2}
              max={15}
              step={0.5}
              onChange={(v) => setTweak('cameraZoom', v)}
            />
            <div className="tweak-row">
              <div className="tweak-label">
                <span>Auto-rotate when idle</span>
                <span className="tweak-value">{tweaks.cameraAutoRotate ? 'ON' : 'OFF'}</span>
              </div>
              <div
                className={`tweak-toggle ${tweaks.cameraAutoRotate ? 'tweak-toggle-on' : ''}`}
                onClick={() => setTweak('cameraAutoRotate', !tweaks.cameraAutoRotate)}
                role="button"
              >
                <div className="tweak-toggle-thumb" />
              </div>
            </div>
          </div>

          {/* Simulator */}
          <div className="tweak-card">
            <div className="tweak-card-title">
              <span className="tweak-card-icon">⚡</span>
              Simulator Settings
            </div>
            <div className="tweak-card-desc">
              Controls for the Simulator page. Fewer nodes = faster response.
            </div>
            <Slider
              label="Connected nodes shown per bank"
              value={tweaks.simMaxNodes}
              min={1}
              max={50}
              onChange={(v) => setTweak('simMaxNodes', v)}
            />
            <div className="tweak-layout-desc">
              Shows the {tweaks.simMaxNodes} most-connected neighbours of the selected bank.
              Increase for more context, decrease for speed.
            </div>
            <Slider
              label="BFS depth (hops from bank)"
              value={tweaks.simDepth}
              min={1}
              max={5}
              onChange={(v) => setTweak('simDepth', v)}
            />
            <div className="tweak-layout-desc">
              Depth {tweaks.simDepth} means traverse {tweaks.simDepth} hop{tweaks.simDepth > 1 ? 's' : ''} outward
              from the bank, capped at {tweaks.simMaxNodes} total neighbour nodes.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
