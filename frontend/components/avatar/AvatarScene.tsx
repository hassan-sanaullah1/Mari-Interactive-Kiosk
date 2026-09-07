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
 *
 * Three pieces of the source rig are deliberately NOT ported, because they
 * depend on that scene owning the whole viewport and this one owning a
 * transparent box over artwork:
 *
 *  - `<color attach="background">` (#0a0a14) would paint an opaque near-black
 *    rectangle over the artwork inside the stage box, since the canvas is only
 *    as large as .stage (see AvatarStage.module.css) rather than full-screen.
 *  - `<fog>` (#0a0a14, near 4, far 10) is a no-op at this framing regardless:
 *    the camera sits 2.5m out and the rig spans roughly 2.2–2.8m from it, so
 *    nothing ever reaches the fog's 4m near plane.
 *  - `<ContactShadows>` at y=0 is below the frame. This scene frames her head
 *    (y 0.61–1.76 at the default 1.685m rig), and the shadow plane's nearest
 *    corner at z=-2 still sits 0.15m under the bottom of the frustum, so it
 *    would cost a depth + blur pass every frame and never be seen.
 *
 * The light rig's positions and intensities are ported verbatim, but its
 * colours are not: the source scene retinted every light per conversation
 * state, and here the palette is fixed (see LIGHTING below), so only intensity
 * still lerps.
 */

import { Component, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import AvatarModel from "./AvatarModel";
import { fetchAvatar } from "@/lib/avatarFetch";
import { AVATAR_MODEL_URL, type AvatarState } from "./state";

// Start the ONE shared download the moment this chunk evaluates, rather than
// waiting for <AvatarModel> to mount under Suspense.
//
// This used to be useGLTF.preload(), which was a mistake: that starts a request
// owned by drei's loader cache, which the component's own extendLoader hook
// cannot intercept — so the model was fetched by the preload tag, by
// useGLTF.preload here, and by the component's useGLTF, three times. Locally
// the later two coalesce onto the first and it looks free; on a slow link the
// first is still in flight, nothing can be shared, and they become parallel
// copies of the same 20MB competing for one pipe.
//
// fetchAvatar is idempotent, so this and every later caller share one transfer.
fetchAvatar(AVATAR_MODEL_URL).catch(() => {
  // Swallowed deliberately: the component's error boundary owns the retry and
  // the user-visible failure. An unhandled rejection here would just be noise.
});

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
/** Fallback until the rig reports its real height (girl15.glb is ~1.68m). */
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

// ---------------------------------------------------------------------------
// LIGHTING
//
// A studio rig: warm key, cool fill, a rim from behind and a tight spot on the
// face. The colours are FIXED — every light holds the same hue in every
// conversation state, so the room never changes temperature. Only intensity
// still varies per state (and with her voice), which reads as her being lit
// more or less brightly rather than as the light changing colour.
// ---------------------------------------------------------------------------

/**
 * The one palette, used in every state. Set as JSX props on the lights below
 * and never touched afterwards, so no per-frame colour work happens at all.
 */
const KEY_COLOR = "#ffe4c9";
const FILL_COLOR = "#c9d6ff";
/**
 * The two backdrop halves, thrown back onto her silhouette edges: cyan down the
 * camera-left shoulder and sleeve, a weaker green on the camera-right edge.
 * These are the only colours changed from the original rig — the key, fill, top
 * and face lights keep their authored values, so the kameez and hair are lit
 * exactly as before and only her outline picks these up.
 */
const RIM_COLOR = "#4fd8e8";
const KICK_COLOR = "#3fd39a";
const TOP_COLOR = "#e8daf5";
const FACE_COLOR = "#fff2e0";

interface LightConfig {
  keyIntensity: number;
  fillIntensity: number;
  rimIntensity: number;
  kickIntensity: number;
  topIntensity: number;
}

/**
 * Per-state intensities. Colours are deliberately absent: the rig keeps one
 * palette throughout (see the constants above), so a state change only moves
 * how bright the lights are.
 *
 * This repo's AvatarState happens to use the same four names as the source
 * scene's conversationState, so the presets map across 1:1.
 */
const LIGHT_CONFIGS: Record<AvatarState, LightConfig> = {
  idle: {
    keyIntensity: 1.4,
    fillIntensity: 0.4,
    rimIntensity: 2,
    kickIntensity: 5,
    topIntensity: 0.9,
  },
  listening: {
    keyIntensity: 1.8,
    fillIntensity: 0.5,
    rimIntensity: 2,
    kickIntensity: 5,
    topIntensity: 1.1,
  },
  thinking: {
    keyIntensity: 1.2,
    fillIntensity: 0.5,
    rimIntensity: 2,
    kickIntensity: 5,
    topIntensity: 0.8,
  },
  speaking: {
    keyIntensity: 1.8,
    fillIntensity: 0.5,
    rimIntensity: 2,
    kickIntensity: 5,
    topIntensity: 1.2,
  },
};

/** Per-frame approach rate toward the active preset — slow enough that a state
 *  change takes about a second to land. */
const LERP_SPEED = 0.04;
/** Where the face spot aims. Retune if the rig's proportions change; girl15's
 *  head sits around here (its rig is the same 1.68m figure as girl11's). */
const HEAD_TARGET_Y = 1.45;

/**
 * `levelRef` carries this app's smoothed 0..1 amplitude (useVoiceSession's
 * levelRef — driven by the TTS analyser while she speaks and by the mic while
 * she listens). The source scene passed an `audioAnalysisRef` holding
 * `{ volume }`; the signal is the same, only the shape differs. Omit it and the
 * two volume boosts below simply become no-ops.
 */
interface DynamicLightingProps {
  state?: AvatarState;
  levelRef?: { current: number };
}

function DynamicLighting({ state = "idle", levelRef }: DynamicLightingProps) {
  const keyLightRef = useRef<THREE.DirectionalLight>(null);
  const fillLightRef = useRef<THREE.DirectionalLight>(null);
  const rimLightRef = useRef<THREE.SpotLight>(null);
  const kickLightRef = useRef<THREE.SpotLight>(null);
  const topLightRef = useRef<THREE.SpotLight>(null);
  const faceLightRef = useRef<THREE.SpotLight>(null);
  const smoothedVolume = useRef(0);

  useFrame(() => {
    const vol = levelRef?.current ?? 0;
    smoothedVolume.current += (vol - smoothedVolume.current) * 0.1;
    const sv = smoothedVolume.current;
    const config = LIGHT_CONFIGS[state];

    if (keyLightRef.current) {
      keyLightRef.current.intensity = THREE.MathUtils.lerp(
        keyLightRef.current.intensity,
        config.keyIntensity + sv * 0.4,
        LERP_SPEED,
      );
    }
    if (fillLightRef.current) {
      fillLightRef.current.intensity = THREE.MathUtils.lerp(
        fillLightRef.current.intensity,
        config.fillIntensity,
        LERP_SPEED,
      );
    }
    if (rimLightRef.current) {
      rimLightRef.current.intensity = THREE.MathUtils.lerp(
        rimLightRef.current.intensity,
        config.rimIntensity + sv * 0.5,
        LERP_SPEED,
      );
    }
    if (kickLightRef.current) {
      kickLightRef.current.intensity = THREE.MathUtils.lerp(
        kickLightRef.current.intensity,
        config.kickIntensity + sv * 0.3,
        LERP_SPEED,
      );
    }
    if (topLightRef.current) {
      topLightRef.current.intensity = THREE.MathUtils.lerp(
        topLightRef.current.intensity,
        config.topIntensity,
        LERP_SPEED,
      );
    }
    if (faceLightRef.current) {
      // A spotLight's default target is a bare Object3D outside the scene
      // graph, so its world matrix has to be refreshed by hand.
      faceLightRef.current.target.position.set(0, HEAD_TARGET_Y, 0);
      faceLightRef.current.target.updateMatrixWorld();
    }
  });

  return (
    <>
      <ambientLight intensity={0.3} />
      {/* Warm key, front-right and high. `castShadow` is inert until <Canvas>
          is given `shadows` — kept as the source scene had it. */}
      <directionalLight
        ref={keyLightRef}
        position={[2, 3, 2]}
        intensity={1.4}
        castShadow
        color={KEY_COLOR}
      />
      {/* Cool fill, opposite the key and behind. */}
      <directionalLight
        ref={fillLightRef}
        position={[-2, 2, -1]}
        intensity={0.4}
        color={FILL_COLOR}
      />
      {/* Top wash from just in front of her. */}
      <spotLight
        ref={topLightRef}
        position={[0, 3, 1.5]}
        angle={0.4}
        penumbra={1}
        intensity={0.9}
        color={TOP_COLOR}
        castShadow={false}
      />
      {/* CYAN RIM, behind and camera-left — the bright blue edge running down
          the shoulder and sleeve. Behind her, so it catches the silhouette
          only and never reaches the front of the kameez. */}
      <spotLight
        ref={rimLightRef}
        position={[-2.2, 2.2, -1.8]}
        angle={0.7}
        penumbra={0.9}
        intensity={1.4}
        color={RIM_COLOR}
        castShadow={false}
      />
      {/* GREEN KICK, behind and camera-right — the weaker counterpart from the
          green half of the backdrop, on the dupatta side. */}
      <spotLight
        ref={kickLightRef}
        position={[2.4, 2.0, -1.6]}
        angle={0.7}
        penumbra={0.9}
        intensity={0.8}
        color={KICK_COLOR}
        castShadow={false}
      />
      {/* Tight face spot, aimed at HEAD_TARGET_Y by the frame loop above. */}
      <spotLight
        ref={faceLightRef}
        position={[0, 2.2, 1]}
        angle={0.18}
        penumbra={0.6}
        intensity={1.6}
        distance={1.6}
        decay={2}
        color={FACE_COLOR}
        castShadow={false}
      />
    </>
  );
}

/**
 * Retries the avatar load once, uncached, when the first attempt fails.
 *
 * Chrome aborts a response whose body it cannot write into its HTTP cache and
 * reports ERR_CACHE_WRITE_FAILURE — a 200 OK that the page never receives,
 * surfacing to drei as "Could not load ...: Failed to fetch". The avatar is the
 * one asset large enough to trip it (it is served `immutable`, and an incognito
 * window caches in memory, where a single entry may not exceed a fraction of the
 * store). Because drei retries the same URL, every attempt repeated the same
 * failed cache write and re-downloaded the whole file — which is what turned a
 * cache problem into minutes of apparent hanging before it finally errored.
 *
 * A cache-busting query makes the retry uncacheable, so the browser streams it
 * straight through instead of trying to store it. The cost is one extra download
 * in the failure case; the normal path never renders the fallback at all.
 */
class ModelErrorBoundary extends Component<
  { url: string; children: (url: string) => ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn("[avatar] first load failed, retrying uncached:", error);
  }

  render() {
    const url = this.state.failed
      ? `${this.props.url}${this.props.url.includes("?") ? "&" : "?"}nocache=1`
      : this.props.url;
    // Remount on retry so Suspense re-runs the loader against the new URL.
    return <Suspense key={url} fallback={null}>{this.props.children(url)}</Suspense>;
  }
}

export interface AvatarSceneProps {
  state?: AvatarState;
  url?: string;
  /** Smoothed 0..1 amplitude, from useVoiceSession. Optional: without it the
   *  key and rim lights simply hold their per-state intensities. */
  levelRef?: { current: number };
  /** Fires once the rig has loaded and is posed — see AvatarModel's onReady. */
  onReady?: () => void;
}

export default function AvatarScene({
  state = "idle",
  url = AVATAR_MODEL_URL,
  levelRef,
  onReady,
}: AvatarSceneProps) {
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
      <DynamicLighting state={state} levelRef={levelRef} />

      {/* Reflections only — an <Environment> with no `background` prop does not
          draw anything, so the artwork behind the canvas stays visible. */}
      <Environment resolution={256}>
        <Lightformer intensity={2} position={[0, 2, 3]} scale={[4, 1, 1]} color="#ffe0cc" />
        <Lightformer intensity={1} position={[-3, 1, -1]} scale={[3, 2, 1]} color="#c9d6ff" />
        <Lightformer intensity={0.5} position={[3, 0, -2]} scale={[2, 3, 1]} color="#ffd6e0" />
      </Environment>

      <ModelErrorBoundary url={url}>
        {(modelUrl) => (
          <AvatarModel url={modelUrl} state={state} onMeasure={onMeasure} onReady={onReady} />
        )}
      </ModelErrorBoundary>
    </Canvas>
  );
}
