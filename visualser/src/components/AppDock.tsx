/**
 * AppDock — auto-hiding macOS-style dock for page navigation.
 *
 * Behaviour:
 *  - Hidden by default.
 *  - Appears when the mouse enters the bottom 80 px of the viewport.
 *  - Disappears 500 ms after the mouse leaves the trigger zone (or the dock itself).
 *  - Hovering the dock resets the hide timer.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Home, Zap, SlidersHorizontal } from 'lucide-react';
import MacOSDock from './ui/mac-os-dock';

const TRIGGER_ZONE = 80;  // px from viewport bottom that shows the dock
const HIDE_DELAY   = 500; // ms after leaving trigger zone before hiding

const PAGES = [
  {
    id: '/',
    label: 'Home',
    icon: (size: number) => (
      <Home
        size={size}
        color="#93c5fd"
        strokeWidth={1.5}
        style={{ filter: 'drop-shadow(0 0 6px rgba(147,197,253,0.4))' }}
      />
    ),
  },
  {
    id: '/simulator',
    label: 'Simulator',
    icon: (size: number) => (
      <Zap
        size={size}
        color="#fbbf24"
        strokeWidth={1.5}
        style={{ filter: 'drop-shadow(0 0 6px rgba(251,191,36,0.4))' }}
      />
    ),
  },
  {
    id: '/tweaks',
    label: 'Tweaks',
    icon: (size: number) => (
      <SlidersHorizontal
        size={size}
        color="#c084fc"
        strokeWidth={1.5}
        style={{ filter: 'drop-shadow(0 0 6px rgba(192,132,252,0.4))' }}
      />
    ),
  },
] as const;

export function AppDock() {
  const [visible, setVisible]   = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate     = useNavigate();
  const location     = useLocation();

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const scheduleHide = useCallback(() => {
    clearHideTimer();
    hideTimerRef.current = setTimeout(() => {
      setVisible(false);
      hideTimerRef.current = null;
    }, HIDE_DELAY);
  }, [clearHideTimer]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      const fromBottom = window.innerHeight - e.clientY;
      if (fromBottom < TRIGGER_ZONE) {
        clearHideTimer();
        setVisible(true);
      } else if (visible) {
        // Only schedule hide if not already scheduled
        if (!hideTimerRef.current) scheduleHide();
      }
    };

    window.addEventListener('mousemove', onMouseMove);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      clearHideTimer();
    };
  }, [visible, clearHideTimer, scheduleHide]);

  const apps = PAGES.map((p) => ({ id: p.id, name: p.label, icon: p.icon }));

  return (
    <AnimatePresence>
      {visible && (
        /* Full-width row so flexbox centres the dock without fighting framer's transform */
        <div
          style={{
            position: 'fixed',
            bottom: 16,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            zIndex: 9999,
            pointerEvents: 'none',
          }}
        >
          <motion.div
            key="app-dock"
            initial={{ y: 120, opacity: 0 }}
            animate={{ y: 0,   opacity: 1 }}
            exit={{   y: 120, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 380, damping: 28 }}
            onMouseEnter={clearHideTimer}
            onMouseLeave={scheduleHide}
            style={{ pointerEvents: 'auto' }}
          >
            <MacOSDock
              apps={apps}
              onAppClick={(id) => navigate(id)}
              openApps={[location.pathname]}
            />
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
