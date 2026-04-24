/**
 * useTweaks — localStorage-backed settings hook.
 * All visualiser controls live here so TweaksPage can edit them
 * and every other page reads them.
 */

import { useCallback, useState } from 'react';

export interface TweakSettings {
  bankLimit: number;
  leafLimit: number;
  nbfcLimit: number;
  threeDLayout: 'centralized' | 'decentralized' | 'separated';
  cameraZoom: number;
  cameraAutoRotate: boolean;
  cameraEnabled: boolean;   // webcam hand-tracking on/off (persists across pages)
  simDepth: number;         // BFS depth for simulator page
  simMaxNodes: number;      // max neighbor nodes returned per bank in simulator
}

const STORAGE_KEY = 'fcrf_tweaks_v2';

const DEFAULTS: TweakSettings = {
  bankLimit: 8,
  leafLimit: 5,
  nbfcLimit: 20,
  threeDLayout: 'centralized',
  cameraZoom: 5,
  cameraAutoRotate: true,
  cameraEnabled: true,
  simDepth: 2,
  simMaxNodes: 10,
};

function load(): TweakSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

function save(settings: TweakSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // ignore quota errors
  }
}

// Module-level singleton so all hook instances share state
let _current: TweakSettings = load();
const _listeners = new Set<() => void>();

function notifyAll() {
  _listeners.forEach((fn) => fn());
}

export function useTweaks() {
  const [, forceRender] = useState(0);

  const subscribe = useCallback(() => {
    const handler = () => forceRender((n) => n + 1);
    _listeners.add(handler);
    return () => _listeners.delete(handler);
  }, []);

  // Subscribe on mount
  useState(() => {
    const unsub = subscribe();
    return unsub;
  });

  const setTweak = useCallback(<K extends keyof TweakSettings>(
    key: K,
    value: TweakSettings[K],
  ) => {
    _current = { ..._current, [key]: value };
    save(_current);
    notifyAll();
  }, []);

  const resetTweaks = useCallback(() => {
    _current = { ...DEFAULTS };
    save(_current);
    notifyAll();
  }, []);

  return {
    tweaks: _current,
    setTweak,
    resetTweaks,
  };
}

/** Read tweaks without subscribing (for non-reactive contexts) */
export function getTweaks(): TweakSettings {
  return _current;
}
