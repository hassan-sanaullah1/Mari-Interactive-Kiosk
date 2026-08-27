"use client";

/**
 * The Three.js scene that fills AvatarStage's reserved area.
 *
 * Deliberately transparent: the kiosk's background artwork is a real <img>
 * behind this canvas (see app/page.tsx), so the scene sets no background
 * colour, no fog and no ground plane — only the presenter is drawn. Camera
 * values come from the working implementation (THREEJS_A2F_INTEGRATION.md §3)
 * and the framing logic is this app's own, because the avatar lives in a sized
 * container here rather than a full viewport. The lighting is NOT the source
 * scene's — see StudioEnvironment below for why it was replaced.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
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
/**
 * How hard the studio environment drives the model. 1.0 is what a glTF viewer
 * shows, and the punctual lights below are deliberately weak enough that this
 * stays the dominant source — so this is the one knob for overall brightness.
 * Measured against the white kameez, which is the first thing to blow out: at
 * 1.0 it peaks around 230/255, so there is a little headroom above this.
 */
const ENV_INTENSITY = 0.9;
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

/**
 * Image-based lighting — the reason she reads differently here than in a glTF
 * viewer.
 *
 * Viewers (three's own, gltf-viewer, Babylon's sandbox) all wrap the model in a
 * neutral studio environment and let that do nearly all the work; on skin, a
 * PBR material's diffuse comes overwhelmingly from the environment, not from
 * punctual lights. This scene had no such environment — only a handful of
 * tinted directional/spot lights and a few small lightformer panels — so the
 * face was lit from a few hard directions with nothing filling in between, and
 * every crevice (eye sockets first) fell to near-black.
 *
 * RoomEnvironment is three's own procedural studio: the exact box-of-softboxes
 * the three.js editor and viewer light with by default. It is generated on the
 * GPU at mount, so unlike an HDRI or drei's <Environment preset> it needs no
 * network — which matters for a kiosk. `scene.environment` alone lights and
 * reflects; nothing is drawn, so the artwork behind the canvas stays visible.
 */
function StudioEnvironment({ intensity }: { intensity: number }) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);

  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const target = pmrem.fromScene(new RoomEnvironment(), 0.04);
    scene.environment = target.texture;
    return () => {
      scene.environment = null;
      target.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);

  useEffect(() => {
    scene.environmentIntensity = intensity;
  }, [scene, intensity]);

  return null;
}

/**
 * Punctual lights, on top of the studio environment.
 *
 * Deliberately few and near-white. Their job is shaping only — a direction for
 * the highlights and a rim to lift her off the artwork — because the
 * environment above is what actually sets exposure and fills the shadows. The
 * rig this replaced tried to do everything with punctual lights, including a
 * narrow face spot (angle 0.18, distance 1.6, decay 2) whose range ran out at
 * the head: it pooled light on the brow and left the sockets outside its cone,
 * which is what drew the dark rings around the eyes.
 */
function Lighting() {
  return (
    <>
      {/* Key, camera-side so it never rakes across the face. */}
      <directionalLight position={[1.8, 2.4, 3.0]} intensity={0.4} color="#fff4e8" />
      {/* Fill, opposite and weak — shadow side only, no second highlight set. */}
      <directionalLight position={[-2.4, 1.6, 2.2]} intensity={0.12} color="#eef3ff" />
      {/* Rim from behind: separation against a background that is bright on
          both sides of her. */}
      <directionalLight position={[-1.4, 2.6, -2.4]} intensity={0.3} color="#ffffff" />
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
      gl={{
        antialias: true,
        alpha: true,
        // Neutral over ACES: ACES pulls saturation out of skin and crushes the
        // low end, which is what darkened the eye sockets and lips relative to
        // a glTF viewer. NeutralToneMapping (three r165+) is the Khronos
        // PBR-neutral curve — it holds midtone hue and only rolls off the
        // highlights, so the render matches the viewer far more closely.
        toneMapping: THREE.NeutralToneMapping,
        toneMappingExposure: 0.85,
      }}
      camera={{ position: [0, 1.26, CAMERA_Z], fov: 20, near: 0.1, far: 100 }}
      // Transparent clear, so the kiosk artwork shows through the whole canvas.
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      style={{ background: "transparent" }}
      resize={{ scroll: false }}
    >
      <Framing modelHeight={modelHeight} />
      <Lighting />

      <StudioEnvironment intensity={ENV_INTENSITY} />

      <Suspense fallback={null}>
        <AvatarModel url={url} state={state} onMeasure={onMeasure} />
      </Suspense>
    </Canvas>
  );
}
