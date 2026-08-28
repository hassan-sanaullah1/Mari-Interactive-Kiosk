"use client";

/**
 * The Three.js scene that fills AvatarStage's reserved area.
 *
 * Deliberately transparent: the kiosk's background artwork is a real <img>
 * behind this canvas (see app/page.tsx), so the scene sets no background
 * colour, no fog and no ground plane — only the presenter is drawn. Camera and
 * lighting values come from the working implementation
 * (THREEJS_A2F_INTEGRATION.md §3); the framing logic is this app's own, because
 * the avatar lives in a sized container here rather than a full viewport.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import AvatarModel from "./AvatarModel";
import { AVATAR_MODEL_URL, type AvatarState } from "./state";

/**
 * Framing, expressed the way the reference composition actually behaves:
 *
 *  - the top of the frame sits just above the head, on every screen size
 *  - a fixed slice of HER, not of the world, fills the container's height, so
 *    she reads at the same size whatever shape the stage is
 *
 * Anchoring on height rather than width is what lets the stage be wider than
 * her silhouette: the extra width is pure gesture room (her arms swing well
 * outside her standing outline in the talking segment, and anything past the
 * canvas edge is clipped), and widening it costs nothing because it no longer
 * changes her scale.
 */
const FRAME_HEIGHT_M = 1.15;
/** Clear air above the head, as a fraction of the rig's height. */
const HEAD_ROOM = 0.045;
/** Distance from the model. Together with the frame size this sets the fov. */
const CAMERA_Z = 2.5;
/** Fallback until the rig reports its real height (girl11.glb is ~1.68m). */
const FALLBACK_HEIGHT = 1.68;

/**
 * Drives the camera from the CONTAINER's size, not the viewport's — R3F's
 * `size` is the canvas element's own box, so this reframes correctly whenever
 * the stage resizes (breakpoint change, rotation, window drag) without any
 * resize listener of our own.
 */
function Framing({ modelHeight }: { modelHeight: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const centerY = useRef(1.26);

  useEffect(() => {
    const topY = modelHeight * (1 + HEAD_ROOM);
    // Never frame more than the whole rig — past her feet there is only empty
    // floor to show, and she would shrink for no reason.
    const frameHeight = Math.min(FRAME_HEIGHT_M, topY);
    centerY.current = topY - frameHeight / 2;

    camera.fov = 2 * Math.atan(frameHeight / 2 / CAMERA_Z) * (180 / Math.PI);
    camera.position.set(0, centerY.current, CAMERA_Z);
    camera.lookAt(0, centerY.current, 0);
    camera.updateProjectionMatrix();
    // `size` is a dependency so a container resize re-applies the framing;
    // only its height affects the result, but R3F updates both together.
  }, [camera, size.width, size.height, modelHeight]);

  // A very slow sway keeps the shot from reading as a still image. Amplitude is
  // scaled to this framing (the source scene used 0.05 across a much wider
  // frame); at 0.015 it is a couple of pixels of parallax.
  useFrame((state) => {
    camera.position.x = Math.sin(state.clock.elapsedTime * 0.08) * 0.015;
    camera.lookAt(0, centerY.current, 0);
  });

  return null;
}

/** Static port of the source scene's lighting rig (its per-state colour
 *  animation is dropped — the kiosk artwork sets the mood here). */
function Lighting() {
  const faceLight = useRef<THREE.SpotLight>(null);

  useEffect(() => {
    if (faceLight.current) {
      faceLight.current.target.position.set(0, 1.45, 0); // head
      faceLight.current.target.updateMatrixWorld();
    }
  }, []);

  return (
    <>
      <ambientLight intensity={0.65} />
      <directionalLight position={[2, 3, 2]} intensity={2.24} color="#ffe4c9" />
      <directionalLight position={[-2, 2, -1]} intensity={0.64} color="#c9d6ff" />
      <spotLight position={[0, 3, 1.5]} angle={0.4} penumbra={1} intensity={1.44} color="#e8daf5" />
      <spotLight position={[0, 2, -1.5]} angle={0.6} penumbra={0.8} intensity={0.8} color="#8b9cf7" />
      <spotLight
        ref={faceLight}
        position={[0, 2.2, 1]}
        angle={0.18}
        penumbra={0.6}
        intensity={2.4}
        distance={1.6}
        decay={2}
        color="#fff2e0"
      />
    </>
  );
}

export interface AvatarSceneProps {
  state?: AvatarState;
  url?: string;
}

export default function AvatarScene({ state = "idle", url = AVATAR_MODEL_URL }: AvatarSceneProps) {
  const [modelHeight, setModelHeight] = useState(FALLBACK_HEIGHT);
  const onMeasure = useCallback((h: number) => {
    if (Number.isFinite(h) && h > 0.2) setModelHeight(h);
  }, []);

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, toneMapping: THREE.ACESFilmicToneMapping }}
      camera={{ position: [0, 1.26, CAMERA_Z], fov: 20, near: 0.1, far: 100 }}
      // Transparent clear, so the kiosk artwork shows through the whole canvas.
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      style={{ background: "transparent" }}
      resize={{ scroll: false }}
    >
      <Framing modelHeight={modelHeight} />
      <Lighting />

      {/* Reflections only — an <Environment> with no `background` prop does not
          draw anything, so the artwork behind the canvas stays visible. */}
      <Environment resolution={256}>
        <Lightformer intensity={3.2} position={[0, 2, 3]} scale={[4, 1, 1]} color="#ffe0cc" />
        <Lightformer intensity={1.8} position={[-3, 1, -1]} scale={[3, 2, 1]} color="#c9d6ff" />
        <Lightformer intensity={0.9} position={[3, 0, -2]} scale={[2, 3, 1]} color="#ffd6e0" />
      </Environment>

      <Suspense fallback={null}>
        <AvatarModel url={url} state={state} onMeasure={onMeasure} />
      </Suspense>
    </Canvas>
  );
}
