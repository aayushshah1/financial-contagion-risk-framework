// src/gestures/useHandTracking.ts
import { useEffect, useRef, useState } from 'react';
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import type { NormalizedLandmark } from '@mediapipe/tasks-vision';

export type GestureType = 'none' | 'v_zoom' | 'pointing' | 'orbit';

export interface HandState {
    gesture: GestureType;
    indexNorm: { x: number, y: number } | null;
    pinchDist: number; // For zoom calculation (dist between index and middle)
    orbitDelta: { dx: number, dy: number }; // For orbit calculation
    isReady: boolean;
    landmarks: NormalizedLandmark[] | null;
}

export function useHandTracking(videoRef: React.RefObject<HTMLVideoElement>) {
    const [state, setState] = useState<HandState>({
        gesture: 'none',
        indexNorm: null,
        pinchDist: 0,
        orbitDelta: { dx: 0, dy: 0 },
        isReady: false,
        landmarks: null
    });

    const handLandmarkerRef = useRef<HandLandmarker | null>(null);
    const orbitPrevRef = useRef<{ x: number, y: number } | null>(null);

    useEffect(() => {
        let active = true;

        async function init() {
            const vision = await FilesetResolver.forVisionTasks(
                "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
            );
            if (!active) return;

            const landmarker = await HandLandmarker.createFromOptions(vision, {
                baseOptions: {
                    modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                    delegate: "GPU"
                },
                runningMode: "VIDEO",
                numHands: 1,
            });
            if (!active) return;

            handLandmarkerRef.current = landmarker;
            setState(s => ({ ...s, isReady: true }));
        }
        init();

        return () => {
            active = false;
            if (handLandmarkerRef.current) {
                handLandmarkerRef.current.close();
            }
        };
    }, []);

    useEffect(() => {
        if (!state.isReady || !videoRef.current) return;
        const video = videoRef.current;
        let pId = 0;

        const loop = () => {
            if (video.currentTime > 0 && handLandmarkerRef.current) {
                const results = handLandmarkerRef.current.detectForVideo(video, performance.now());
                if (results.landmarks.length > 0) {
                    processHand(results.landmarks[0]);
                } else {
                    setState(s => ({ ...s, gesture: 'none', indexNorm: null, pinchDist: 0, orbitDelta: { dx: 0, dy: 0 }, landmarks: null }));
                    orbitPrevRef.current = null;
                }
            }
            pId = requestAnimationFrame(loop);
        };

        video.onloadeddata = () => loop();
        if (video.readyState >= 2) loop();

        return () => cancelAnimationFrame(pId);
    }, [state.isReady, videoRef]);

    const processHand = (lms: NormalizedLandmark[]) => {
        const up = (tip: number, pip: number) => lms[tip].y < lms[pip].y; // Note: y is down in web
        const down = (tip: number, pip: number) => lms[tip].y > lms[pip].y;

        const indexUp = up(8, 6);
        const middleUp = up(12, 10);
        const ringUp = up(16, 14);
        const pinkyUp = up(20, 18);

        const middleDown = down(12, 10);
        const ringDown = down(16, 14);
        const pinkyDown = down(20, 18);

        const nUp = [indexUp, middleUp, ringUp, pinkyUp].filter(Boolean).length;

        // dist between index and middle
        const dx = lms[8].x - lms[12].x;
        const dy = lms[8].y - lms[12].y;
        const distSq = dx * dx + dy * dy;
        const dist = Math.sqrt(distSq);

        const isPoint = indexUp && middleDown && ringDown && pinkyDown;
        const isOrbit = nUp >= 3;

        let gesture: GestureType = 'none';
        let orbitDelta = { dx: 0, dy: 0 };

        if (isOrbit) {
            gesture = 'orbit';
            const wx = lms[0].x;
            const wy = lms[0].y;
            if (orbitPrevRef.current) {
                orbitDelta = {
                    dx: wx - orbitPrevRef.current.x,
                    dy: wy - orbitPrevRef.current.y
                };
            }
            orbitPrevRef.current = { x: wx, y: wy };
        } else if (isPoint) {
            gesture = 'pointing';
            orbitPrevRef.current = null;
        } else {
            orbitPrevRef.current = null;
        }

        // x is flipped because webcam is mirrored usually
        setState(s => ({
            ...s,
            gesture,
            indexNorm: { x: 1.0 - lms[8].x, y: lms[8].y },
            pinchDist: dist,
            orbitDelta,
            landmarks: lms
        }));
    };

    return state;
}
