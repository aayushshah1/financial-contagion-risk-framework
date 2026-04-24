import React, { useState, useRef, useCallback, useEffect } from 'react';

interface DockApp {
  id: string;
  name: string;
  /** URL string OR a render function (size: number) => ReactNode */
  icon: string | ((size: number) => React.ReactNode);
}

interface MacOSDockProps {
  apps: DockApp[];
  onAppClick: (appId: string) => void;
  openApps?: string[];
  className?: string;
}

const MacOSDock: React.FC<MacOSDockProps> = ({
  apps,
  onAppClick,
  openApps = [],
  className = '',
}) => {
  const [mouseX, setMouseX] = useState<number | null>(null);
  const [currentScales, setCurrentScales] = useState<number[]>(apps.map(() => 1));
  const [currentPositions, setCurrentPositions] = useState<number[]>([]);
  const dockRef = useRef<HTMLDivElement>(null);
  const iconRefs = useRef<(HTMLDivElement | null)[]>([]);
  const animationFrameRef = useRef<number | undefined>(undefined);
  const lastMouseMoveTime = useRef<number>(0);

  const getResponsiveConfig = useCallback(() => {
    if (typeof window === 'undefined') {
      return { baseIconSize: 64, maxScale: 1.6, effectWidth: 240 };
    }
    const smaller = Math.min(window.innerWidth, window.innerHeight);
    if (smaller < 480)  return { baseIconSize: Math.max(40, smaller * 0.08), maxScale: 1.4, effectWidth: smaller * 0.4 };
    if (smaller < 768)  return { baseIconSize: Math.max(48, smaller * 0.07), maxScale: 1.5, effectWidth: smaller * 0.35 };
    if (smaller < 1024) return { baseIconSize: Math.max(56, smaller * 0.06), maxScale: 1.6, effectWidth: smaller * 0.3 };
    return { baseIconSize: Math.max(64, Math.min(80, smaller * 0.05)), maxScale: 1.8, effectWidth: 300 };
  }, []);

  const [config, setConfig] = useState(getResponsiveConfig);
  const { baseIconSize, maxScale, effectWidth } = config;
  const minScale = 1.0;
  const baseSpacing = Math.max(4, baseIconSize * 0.08);

  useEffect(() => {
    const handleResize = () => setConfig(getResponsiveConfig());
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [getResponsiveConfig]);

  const calculateTargetMagnification = useCallback((mousePosition: number | null) => {
    if (mousePosition === null) return apps.map(() => minScale);
    return apps.map((_, index) => {
      const center = index * (baseIconSize + baseSpacing) + baseIconSize / 2;
      const minX = mousePosition - effectWidth / 2;
      const maxX = mousePosition + effectWidth / 2;
      if (center < minX || center > maxX) return minScale;
      const theta = ((center - minX) / effectWidth) * 2 * Math.PI;
      const scaleFactor = (1 - Math.cos(Math.min(Math.max(theta, 0), 2 * Math.PI))) / 2;
      return minScale + scaleFactor * (maxScale - minScale);
    });
  }, [apps, baseIconSize, baseSpacing, effectWidth, maxScale, minScale]);

  const calculatePositions = useCallback((scales: number[]) => {
    let x = 0;
    return scales.map((scale) => {
      const scaledWidth = baseIconSize * scale;
      const center = x + scaledWidth / 2;
      x += scaledWidth + baseSpacing;
      return center;
    });
  }, [baseIconSize, baseSpacing]);

  useEffect(() => {
    const initial = apps.map(() => minScale);
    setCurrentScales(initial);
    setCurrentPositions(calculatePositions(initial));
  }, [apps, calculatePositions, minScale, config]);

  const animateToTarget = useCallback(() => {
    const targetScales = calculateTargetMagnification(mouseX);
    const targetPositions = calculatePositions(targetScales);
    const lerpFactor = mouseX !== null ? 0.2 : 0.12;

    setCurrentScales((prev) =>
      prev.map((s, i) => s + (targetScales[i] - s) * lerpFactor),
    );
    setCurrentPositions((prev) =>
      prev.map((p, i) => p + (targetPositions[i] - p) * lerpFactor),
    );

    const needsUpdate =
      currentScales.some((s, i) => Math.abs(s - targetScales[i]) > 0.002) ||
      currentPositions.some((p, i) => Math.abs(p - targetPositions[i]) > 0.1) ||
      mouseX !== null;

    if (needsUpdate) {
      animationFrameRef.current = requestAnimationFrame(animateToTarget);
    }
  }, [mouseX, calculateTargetMagnification, calculatePositions, currentScales, currentPositions]);

  useEffect(() => {
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = requestAnimationFrame(animateToTarget);
    return () => { if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current); };
  }, [animateToTarget]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const now = performance.now();
    if (now - lastMouseMoveTime.current < 16) return;
    lastMouseMoveTime.current = now;
    if (dockRef.current) {
      const rect = dockRef.current.getBoundingClientRect();
      const padding = Math.max(8, baseIconSize * 0.12);
      setMouseX(e.clientX - rect.left - padding);
    }
  }, [baseIconSize]);

  const handleMouseLeave = useCallback(() => setMouseX(null), []);

  const handleAppClick = (appId: string, index: number) => {
    const el = iconRefs.current[index];
    if (el) {
      const bounceH = -baseIconSize * 0.15;
      el.style.transition = 'transform 0.2s ease-out';
      el.style.transform = `translateY(${bounceH}px)`;
      setTimeout(() => { el.style.transform = 'translateY(0px)'; }, 200);
    }
    onAppClick(appId);
  };

  const contentWidth =
    currentPositions.length > 0
      ? Math.max(...currentPositions.map((pos, i) => pos + (baseIconSize * currentScales[i]) / 2))
      : apps.length * (baseIconSize + baseSpacing) - baseSpacing;

  const padding = Math.max(8, baseIconSize * 0.12);

  return (
    <div
      ref={dockRef}
      className={`backdrop-blur-md ${className}`}
      style={{
        width: `${contentWidth + padding * 2}px`,
        background: 'rgba(20, 20, 30, 0.82)',
        borderRadius: `${Math.max(12, baseIconSize * 0.4)}px`,
        border: '1px solid rgba(255,255,255,0.12)',
        boxShadow: `
          0 ${Math.max(4, baseIconSize * 0.1)}px ${Math.max(16, baseIconSize * 0.4)}px rgba(0,0,0,0.5),
          inset 0 1px 0 rgba(255,255,255,0.12),
          inset 0 -1px 0 rgba(0,0,0,0.2)
        `,
        padding: `${padding}px`,
      }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <div className="relative" style={{ height: `${baseIconSize}px`, width: '100%' }}>
        {apps.map((app, index) => {
          const scale = currentScales[index] ?? 1;
          const position = currentPositions[index] ?? 0;
          const scaledSize = baseIconSize * scale;

          return (
            <div
              key={app.id}
              ref={(el) => { iconRefs.current[index] = el; }}
              className="absolute cursor-pointer flex flex-col items-center justify-end"
              title={app.name}
              onClick={() => handleAppClick(app.id, index)}
              style={{
                left: `${position - scaledSize / 2}px`,
                bottom: '0px',
                width: `${scaledSize}px`,
                height: `${scaledSize}px`,
                transformOrigin: 'bottom center',
                zIndex: Math.round(scale * 10),
              }}
            >
              {typeof app.icon === 'string' ? (
                <img
                  src={app.icon}
                  alt={app.name}
                  width={scaledSize}
                  height={scaledSize}
                  className="object-contain"
                  style={{
                    filter: `drop-shadow(0 ${scale > 1.2 ? Math.max(2, baseIconSize * 0.05) : 1}px ${scale > 1.2 ? Math.max(4, baseIconSize * 0.1) : 2}px rgba(0,0,0,${0.2 + (scale - 1) * 0.15}))`,
                  }}
                />
              ) : (
                <div
                  className="flex items-center justify-center"
                  style={{ width: scaledSize, height: scaledSize }}
                >
                  {app.icon(scaledSize * 0.62)}
                </div>
              )}

              {openApps.includes(app.id) && (
                <div
                  className="absolute"
                  style={{
                    bottom: `${Math.max(-2, -baseIconSize * 0.05)}px`,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: `${Math.max(3, baseIconSize * 0.06)}px`,
                    height: `${Math.max(3, baseIconSize * 0.06)}px`,
                    borderRadius: '50%',
                    backgroundColor: 'rgba(255,255,255,0.85)',
                    boxShadow: '0 0 6px rgba(255,255,255,0.5)',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default MacOSDock;
