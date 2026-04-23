interface ModeToggleProps {
  mode: '2d' | '3d';
  onChange: (mode: '2d' | '3d') => void;
  gestureHintActive: boolean;
}

export function ModeToggle({ mode, onChange, gestureHintActive }: ModeToggleProps) {
  return (
    <div className="mode-toggle">
      <button
        className={mode === '2d' ? 'mode-toggle-button is-active' : 'mode-toggle-button'}
        onClick={() => onChange('2d')}
        type="button"
      >
        2D
      </button>
      <button
        className={mode === '3d' ? 'mode-toggle-button is-active' : 'mode-toggle-button'}
        onClick={() => onChange('3d')}
        type="button"
      >
        3D
      </button>
      {gestureHintActive && <span className="mode-toggle-hint">V-sign toggles view</span>}
    </div>
  );
}
