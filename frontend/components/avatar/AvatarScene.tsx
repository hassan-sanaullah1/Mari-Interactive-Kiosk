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
 *  - `<fog>` (#0a0a14, near 4, far 10) was tuned for the source scene's 2.5m
 *    camera. This one stands further back (see CAMERA.lensMm in ./tuning.ts),
 *    where that fog would grey the presenter herself rather than a distant
 *    background.
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
import { fetchAvatar, isAvatarParsed } from "@/lib/avatarFetch";
import { type AvatarState } from "./state";
import { avatarConfig, DEFAULT_AVATAR, type AvatarId } from "./models";
// Every number that decides how the scene looks lives in ./tuning.ts — this
// file is the machinery that applies them.
import {
  CAMERA,
  DARK_LIGHTING,
  ENVIRONMENT,
  LERP_SPEED,
  LIGHT_COLORS,
  LIGHT_PLACEMENT,
  LIGHT_STATES,
  VOICE_BOOST,
  type ThemeLighting,
} from "./tuning";
import type { Theme } from "@/lib/theme";
import { readAvatar } from "@/lib/avatar";

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
// fetchAvatar is idempotent per URL, so this and every later caller share one
// transfer.
//
// It warms the STORED presenter, not the default one. This module is only ever
// evaluated in the browser (AvatarStage imports it with ssr: false), so the
// stored choice is readable here, and reading it is what keeps a kiosk set to
// the non-default rig from pulling BOTH models on every cold load — measured,
// that was a whole unused 30MB ahead of the one it actually shows.
fetchAvatar(avatarConfig(readAvatar()).url).catch(() => {
  // Swallowed deliberately: the component's error boundary owns the retry and
  // the user-visible failure. An unhandled rejection here would just be noise.
});

// How the shot is framed — frame height, head room, lens and sensor — is in
// CAMERA in ./tuning.ts, along with what each value means. The fallback height
// used until a rig reports its real one is per-rig (`fallbackHeight` there).

/**
 * Drives the camera from the CONTAINER's size, not the viewport's — R3F's
 * `size` is the canvas element's own box, so this reframes correctly whenever
 * the stage resizes (breakpoint change, rotation, window drag) without any
 * resize listener of our own.
 */
function Framing({ modelHeight, widthSqueeze = 1 }: { modelHeight: number; widthSqueeze?: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const centerY = useRef(1.26);

  useEffect(() => {
    if (size.width <= 0 || size.height <= 0) return;
    const topY = modelHeight * (1 + CAMERA.headRoom);
    // Never frame more than the whole rig — past her feet there is only empty
    // floor to show, and she would shrink for no reason.
    const frameHeight = Math.min(CAMERA.frameHeightM, topY);
    centerY.current = topY - frameHeight / 2;

    // three's film gauge applies to the larger side of the frame, which is
    // exactly Blender's Auto sensor fit — so the fov matches Blender's for the
    // same lens on the same shape of frame. The aspect is set first because
    // the vertical fov depends on it.
    camera.aspect = size.width / size.height;
    camera.filmGauge = CAMERA.sensorMm;
    camera.setFocalLength(CAMERA.lensMm);
    // Then back off until `frameHeight` of her fills that fov.
    const distance = frameHeight / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    // The squeeze: claiming a wider frame than the canvas really is fits more
    // world into the same pixels across, so everything draws narrower while
    // the height is untouched. Needs `manual` on the camera (see <Canvas>), or
    // R3F would reset the aspect to the true one on the next resize.
    camera.aspect = size.width / size.height / widthSqueeze;
    camera.position.set(0, centerY.current, distance);
    camera.lookAt(0, centerY.current, 0);
    camera.updateProjectionMatrix();
    // `size` is a dependency so a container resize re-applies the framing —
    // the stage's shape changes the fov, and with it the distance.
  }, [camera, size.width, size.height, modelHeight, widthSqueeze]);

  // A very slow sway keeps the shot from reading as a still image — see
  // CAMERA.sway in ./tuning.ts.
  useFrame((state) => {
    camera.position.x =
      Math.sin(state.clock.elapsedTime * CAMERA.sway.speed) * CAMERA.sway.amplitude;
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
//
// The numbers themselves are all in ./tuning.ts: LIGHT_COLORS (the palette),
// LIGHT_PLACEMENT (where each light stands), LIGHT_STATES (how bright it is in
// each conversation state), VOICE_BOOST and LERP_SPEED. Where the face spot
// AIMS is per-rig (`headTargetY`), because the two faces sit at different
// heights.
// ---------------------------------------------------------------------------

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
  /** World Y the face spot aims at — this rig's face centre. */
  headTargetY: number;
  /** The theme's part of the rig — exposure, ambient, fill and reflections. */
  lighting: ThemeLighting;
}

function DynamicLighting({ state = "idle", levelRef, headTargetY, lighting }: DynamicLightingProps) {
  const { gl, scene } = useThree();
  const ambientLightRef = useRef<THREE.AmbientLight>(null);
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
    const config = LIGHT_STATES[state];

    if (keyLightRef.current) {
      keyLightRef.current.intensity = THREE.MathUtils.lerp(
        keyLightRef.current.intensity,
        config.key + sv * VOICE_BOOST.key,
        LERP_SPEED,
      );
    }
    if (fillLightRef.current) {
      fillLightRef.current.intensity = THREE.MathUtils.lerp(
        fillLightRef.current.intensity,
        config.fill * lighting.fill,
        LERP_SPEED,
      );
    }
    if (rimLightRef.current) {
      rimLightRef.current.intensity = THREE.MathUtils.lerp(
        rimLightRef.current.intensity,
        config.rim + sv * VOICE_BOOST.rim,
        LERP_SPEED,
      );
    }
    if (kickLightRef.current) {
      kickLightRef.current.intensity = THREE.MathUtils.lerp(
        kickLightRef.current.intensity,
        config.kick + sv * VOICE_BOOST.kick,
        LERP_SPEED,
      );
    }
    if (topLightRef.current) {
      topLightRef.current.intensity = THREE.MathUtils.lerp(
        topLightRef.current.intensity,
        config.top,
        LERP_SPEED,
      );
    }
    if (ambientLightRef.current) {
      ambientLightRef.current.intensity = THREE.MathUtils.lerp(
        ambientLightRef.current.intensity,
        lighting.ambient,
        LERP_SPEED,
      );
    }
    // Eased like the lights, so a theme switch fades rather than snaps.
    gl.toneMappingExposure = THREE.MathUtils.lerp(gl.toneMappingExposure, lighting.exposure, LERP_SPEED);
    scene.environmentIntensity = THREE.MathUtils.lerp(
      scene.environmentIntensity,
      lighting.environment,
      LERP_SPEED,
    );
    if (faceLightRef.current) {
      // A spotLight's default target is a bare Object3D outside the scene
      // graph, so its world matrix has to be refreshed by hand.
      faceLightRef.current.target.position.set(0, headTargetY, 0);
      faceLightRef.current.target.updateMatrixWorld();
    }
  });

  return (
    <>
      <ambientLight ref={ambientLightRef} intensity={DARK_LIGHTING.ambient} />
      {/* Warm key, front-right and high. `castShadow` is inert until <Canvas>
          is given `shadows` — kept as the source scene had it. */}
      <directionalLight ref={keyLightRef} {...LIGHT_PLACEMENT.key} castShadow color={LIGHT_COLORS.key} />
      {/* Cool fill, opposite the key and behind. */}
      <directionalLight ref={fillLightRef} {...LIGHT_PLACEMENT.fill} color={LIGHT_COLORS.fill} />
      {/* Top wash from just in front of her. */}
      <spotLight ref={topLightRef} {...LIGHT_PLACEMENT.top} color={LIGHT_COLORS.top} castShadow={false} />
      {/* CYAN RIM, behind and camera-left — the bright blue edge running down
          the shoulder and sleeve. Behind her, so it catches the silhouette
          only and never reaches the front of the kameez. */}
      <spotLight ref={rimLightRef} {...LIGHT_PLACEMENT.rim} color={LIGHT_COLORS.rim} castShadow={false} />
      {/* GREEN KICK, behind and camera-right — the weaker counterpart from the
          green half of the backdrop, on the dupatta side. */}
      <spotLight ref={kickLightRef} {...LIGHT_PLACEMENT.kick} color={LIGHT_COLORS.kick} castShadow={false} />
      {/* Tight face spot, aimed at the rig's headTargetY by the frame loop above. */}
      <spotLight
        ref={faceLightRef}
        {...LIGHT_PLACEMENT.face}
        color={LIGHT_COLORS.face}
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
  { failed: boolean; forUrl: string }
> {
  state = { failed: false, forUrl: this.props.url };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  /**
   * A failure belongs to the model that failed. Without this the flag is
   * sticky across a presenter switch, and the rig the user just picked would be
   * fetched cache-busted on its very first attempt — one guaranteed extra
   * multi-megabyte download for an error the other model had.
   */
  static getDerivedStateFromProps(
    props: { url: string },
    state: { failed: boolean; forUrl: string },
  ) {
    return props.url === state.forUrl ? null : { failed: false, forUrl: props.url };
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
  /** Which presenter to show. Defaults to the registry's default rig. */
  avatar?: AvatarId;
  /** Smoothed 0..1 amplitude, from useVoiceSession. Optional: without it the
   *  key and rim lights simply hold their per-state intensities. */
  levelRef?: { current: number };
  /** Fires once the rig has loaded and is posed — see AvatarModel's onReady. */
  onReady?: () => void;
  /** The page theme. The light theme's near-white backdrop needs a brighter
   *  rig — see `lightThemeLighting` in ./tuning.ts. */
  theme?: Theme;
}

export default function AvatarScene({
  state = "idle",
  avatar = DEFAULT_AVATAR,
  levelRef,
  onReady,
  theme = "dark",
}: AvatarSceneProps) {
  const config = avatarConfig(avatar);
  const lighting =
    theme === "light"
      ? config.lightThemeLighting
      : config.darkThemeLighting;

  /**
   * The rig's height, tagged with the rig it was measured on.
   *
   * Tagged rather than reset, because the two rigs differ by ~17cm and framing
   * one against the other's height is most of a head at this shot. Deriving the
   * height during render instead of clearing it from an effect keeps that
   * correct no matter how the mount interleaves: a measurement only ever
   * applies to the rig it came from, and any other rig frames on its own
   * fallback until it reports. (An effect that reset the height on config
   * change happened to work, but only because the incoming rig's measure landed
   * after the parent's reset — an ordering React does not owe us, and one that
   * silently flips when the model is already in drei's cache.)
   */
  const [measured, setMeasured] = useState<{ id: AvatarId; height: number } | null>(null);
  const modelHeight = measured?.id === config.id ? measured.height : config.fallbackHeight;
  const onMeasure = useCallback(
    (h: number) => {
      if (Number.isFinite(h) && h > 0.2) setMeasured({ id: config.id, height: h });
    },
    [config.id],
  );

  // The presenter's own bytes, warmed as soon as the choice is known — the
  // module-scope call above only covers whichever rig was stored at load.
  //
  // Skipped for a rig that has already been parsed once this session: drei then
  // serves it from its own cache without calling the loader, so warming it
  // again is a download nothing consumes. Without that check, every toggle back
  // and forth re-pulled a whole model.
  useEffect(() => {
    if (isAvatarParsed(config.url)) return;
    fetchAvatar(config.url).catch(() => {
      /* the error boundary owns the retry and the user-visible failure */
    });
  }, [config]);

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, toneMapping: THREE.ACESFilmicToneMapping }}
      camera={{ position: [0, 1.26, 4], fov: 20, near: 0.1, far: 100, manual: true }}
      // Transparent clear, so the kiosk artwork shows through the whole canvas.
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      style={{ background: "transparent" }}
      resize={{ scroll: false }}
    >
      <Framing modelHeight={modelHeight} widthSqueeze={config.widthSqueeze} />
      <DynamicLighting
        state={state}
        levelRef={levelRef}
        headTargetY={config.headTargetY}
        lighting={lighting}
      />

      {/* Reflections only — an <Environment> with no `background` prop does not
          draw anything, so the artwork behind the canvas stays visible. */}
      <Environment resolution={ENVIRONMENT.resolution}>
        {ENVIRONMENT.lightformers.map((panel, i) => (
          <Lightformer key={i} {...panel} />
        ))}
      </Environment>

      {/* Keyed on the rig, so switching presenters tears the old one down
          rather than trying to reconcile two different skeletons through the
          same component instance. */}
      <ModelErrorBoundary key={config.id} url={config.url}>
        {(modelUrl) => (
          <AvatarModel
            url={modelUrl}
            config={config}
            state={state}
            onMeasure={onMeasure}
            onReady={onReady}
          />
        )}
      </ModelErrorBoundary>
    </Canvas>
  );
}
