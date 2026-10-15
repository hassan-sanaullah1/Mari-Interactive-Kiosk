"use client";

/**
 * The avatar lab's canvas: the kiosk's own rendering pieces, each switchable on
 * its own, so one change can be seen in isolation.
 *
 *   look         raw (the file as exported) or kiosk (AvatarModel's corrections)
 *   lights       none, the kiosk's studio lights for the theme, the lab's
 *                editable copy of them (lab-rig.ts), or Reference v1
 *   environment  what she reflects: a neutral room, the studio's panels, or the
 *                theme's own backdrop image
 *   realism      the Phase A surface upgrades (components/avatar/realism.ts),
 *                with live strengths
 *   life         resting smile, eye movement, head drift (liveliness.ts)
 *   post         ambient occlusion and colour grade (PostEffects.tsx)
 *   tone         the renderer's tone mapping
 *   view         lit, albedo, normals or wireframe
 *   camera       the kiosk's framing, the lab's editable copy of it, or a free orbit
 *
 * Built from the same components the kiosk uses (AvatarModel, Framing,
 * DynamicLighting, STUDIO), so what it shows in "kiosk" mode is the kiosk.
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer, OrbitControls, useTexture } from "@react-three/drei";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import AvatarModel from "@/components/avatar/AvatarModel";
import { DynamicLighting, Framing } from "@/components/avatar/AvatarScene";
import { avatarConfig, type AvatarConfig, type AvatarId } from "@/components/avatar/models";
import { createLifeRig, updateLife, type LifeOptions } from "@/components/avatar/liveliness";
import PostEffects, { type AoSettings, type GradeSettings } from "@/components/avatar/PostEffects";
import {
  applyRealism,
  setRealismParams,
  type RealismOptions,
  type RealismParams,
} from "@/components/avatar/realism";
import type { AvatarState } from "@/components/avatar/state";
import type { Theme } from "@/lib/theme";
import { EditablePanels, EditableStudioLights, LabFraming, LightHandles } from "./EditableStudio";
import type { DeviceId } from "./devices";
import type { LabRig, Layout, LightName } from "./lab-rig";
import RawModel, { type LabPose } from "./RawModel";
import { MOBILE_BACKDROP_DEFAULT } from "./devices";
import {
  REFERENCE_ENVIRONMENT,
  REFERENCE_LIGHTS,
  REFERENCE_V3_ENVIRONMENT,
  REFERENCE_V3_LIGHTS,
  type ReferencePanel,
} from "./reference-look";
import { applyMaterialView, inventory, type AssetInventory, type MaterialView } from "./lab-tools";

export type LabLook = "raw" | "kiosk";
export type LabLights = "off" | "studio" | "editable" | "reference" | "reference3";
export type LabEnvironment = "room" | "panels" | "backdrop" | "reference" | "reference3";
export type LabCamera = "kiosk" | "editable" | "orbit-face" | "orbit-body" | "orbit-wide";
export type LabTone = "aces" | "agx" | "neutral" | "linear" | "none";

export const TONE_MAPPINGS: Record<LabTone, THREE.ToneMapping> = {
  aces: THREE.ACESFilmicToneMapping,
  agx: THREE.AgXToneMapping,
  neutral: THREE.NeutralToneMapping,
  linear: THREE.LinearToneMapping,
  none: THREE.NoToneMapping,
};

export interface LabSettings {
  presenter: AvatarId;
  look: LabLook;
  lights: LabLights;
  environment: LabEnvironment;
  /** Brightness of the backdrop-image environment. */
  backdropStrength: number;
  realism: RealismOptions;
  realismParams: RealismParams;
  life: LifeOptions;
  ao: AoSettings;
  grade: GradeSettings;
  /** CSS blur on the backdrop picture, standing in for depth of field. The page applies it. */
  backdropBlur: number;
  /**
   * Shadow edge blur. 0 keeps the kiosk's PCF soft shadows; above 0 the
   * renderer switches to VSM shadows blurred by this radius.
   */
  shadowSoftness: number;
  /**
   * Overrides every casting light's shadow darkness (0-1); 0 leaves each
   * light's own value. The jaw's shadow on the neck comes from here: AO wide
   * enough to draw it also darkened the open cheeks.
   */
  shadowStrength: number;
  theme: Theme;
  tone: LabTone;
  view: MaterialView;
  pose: LabPose;
  camera: LabCamera;
  /** The lab's editable copy of the kiosk studios and framing (lab-rig.ts). */
  rig: LabRig;
  /** Which light of the editable studio is selected for editing. */
  editLight: LightName;
  /** Draw a draggable ball where each editable light stands. */
  showHandles: boolean;
  /** Desktop (full window) or a portrait device frame. The page lays it out. */
  layout: Layout;
  device: DeviceId;
  /** "theme" for the kiosk's own portrait artwork, or a file in public/. */
  mobileBackdrop: string;
  /** Outline where the portrait controls sit. */
  showGuides: boolean;
  /** Step 0: the target picture beside or over the render. The page draws it. */
  compare: { mode: "off" | "side" | "overlay"; opacity: number; image: string };
}

interface LabSceneProps {
  settings: LabSettings;
  onInventory: (inventory: AssetInventory) => void;
  onReady: () => void;
  /** Selecting or dragging a light handle in the scene. */
  onSelectLight: (name: LightName) => void;
  onMoveLight: (name: LightName, position: [number, number, number]) => void;
}

/** The kiosk look cannot hold a T-pose: AvatarModel always animates. */
const KIOSK_STATE: Record<LabPose, AvatarState> = {
  tpose: "idle",
  breathing: "idle",
  listening: "listening",
  talking: "speaking",
};

/** The landscape artwork per theme — the same files page.module.css shows. */
const BACKDROP_IMAGE: Record<Theme, string> = {
  dark: "/bg-desktop-dark.png",
  light: "/bg-desktop-light.png",
};

function ToneMapping({ tone }: { tone: LabTone }) {
  const gl = useThree((s) => s.gl);
  useEffect(() => {
    // The renderer recompiles each material's program when this changes.
    gl.toneMapping = TONE_MAPPINGS[tone];
  }, [gl, tone]);
  return null;
}

/**
 * The neutral room three.js's own glTF viewer uses: soft, colourless, from every
 * side. Shows the asset without the kiosk's lighting choices in the way.
 */
function RoomEnvironmentMap() {
  const { gl, scene } = useThree();
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, 0.04).texture;
    scene.environment = environment;
    return () => {
      if (scene.environment === environment) scene.environment = null;
      environment.dispose();
      room.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);
  return null;
}

/**
 * The theme's backdrop picture wrapped round her as the environment, so what
 * she reflects is the room she is composited into: blue and green on the dark
 * plate, warm marble on the light one.
 *
 * The picture is flat, not a panorama, so it is stretched round a sphere. That
 * is acceptable here because the environment is pre-blurred for every surface
 * except a mirror; what survives is where the colours and the bright areas are.
 * It is centred behind her, mirrored so its left stays on her left, and it lights
 * nothing directly — the background itself is still the CSS image behind the
 * canvas, which this never draws (no `background` prop).
 */
function BackdropEnvironment({
  image,
  strength,
  panels = [],
  resolution = 256,
}: {
  image: string;
  strength: number;
  /** Extra highlight panels baked into the same environment. */
  panels?: ReferencePanel[];
  resolution?: number;
}) {
  const texture = useTexture(image);
  texture.colorSpace = THREE.SRGBColorSpace;
  const color = useMemo(() => new THREE.Color(strength, strength, strength), [strength]);
  return (
    <Environment key={`${image}-${strength}-${panels.length}`} resolution={resolution}>
      <mesh rotation={[0, Math.PI / 2, 0]} scale={[-50, 50, 50]}>
        <sphereGeometry args={[1, 64, 32]} />
        <meshBasicMaterial map={texture} color={color} side={THREE.BackSide} toneMapped={false} />
      </mesh>
      {panels.map((panel, i) => (
        <Lightformer key={i} {...panel} />
      ))}
    </Environment>
  );
}

/** The picture behind her right now: the portrait artwork in the mobile frame, else the landscape one. */
function currentBackdrop(settings: LabSettings): string {
  if (settings.layout === "desktop") return BACKDROP_IMAGE[settings.theme];
  return settings.mobileBackdrop === "theme" ? MOBILE_BACKDROP_DEFAULT[settings.theme] : settings.mobileBackdrop;
}

/** The reference portrait's lobby as soft panels (reference-look.ts). */
function ReferencePanels() {
  return (
    <Environment resolution={REFERENCE_ENVIRONMENT.resolution}>
      {REFERENCE_ENVIRONMENT.panels.map((panel, i) => (
        <Lightformer key={i} {...panel} />
      ))}
    </Environment>
  );
}

function EnvironmentChoice({ settings }: { settings: LabSettings }) {
  // From the lab copy: identical to the kiosk's panels until edited.
  if (settings.environment === "panels") return <EditablePanels studio={settings.rig.studio[settings.theme]} />;
  if (settings.environment === "reference") return <ReferencePanels />;
  if (settings.environment === "backdrop") {
    return (
      <Suspense fallback={null}>
        <BackdropEnvironment image={currentBackdrop(settings)} strength={settings.backdropStrength} />
      </Suspense>
    );
  }
  if (settings.environment === "reference3") {
    // Step 8: the room she stands in, plus the key's highlight and the catchlight.
    return (
      <Suspense fallback={null}>
        <BackdropEnvironment
          image={currentBackdrop(settings)}
          strength={REFERENCE_V3_ENVIRONMENT.backdropStrength}
          panels={REFERENCE_V3_ENVIRONMENT.panels}
          resolution={REFERENCE_V3_ENVIRONMENT.resolution}
        />
      </Suspense>
    );
  }
  return <RoomEnvironmentMap />;
}

function StudioLights({ config, theme, state }: { config: AvatarConfig; theme: Theme; state: AvatarState }) {
  const silentLevel = useMemo(() => ({ current: 0 }), []);
  return (
    <DynamicLighting
      state={state}
      levelRef={silentLevel}
      headTargetY={config.headTargetY}
      lighting={theme === "light" ? config.lightThemeLighting : config.darkThemeLighting}
      backLight={config.backLight}
      theme={theme}
    />
  );
}

/**
 * The reference portrait's light (reference-look.ts): soft key camera-left,
 * broad fill camera-right, cool rims from behind, sky-over-floor bounce. Fixed
 * rather than eased per conversation state: the reference is one moment.
 */
function ReferenceLights({ rig = REFERENCE_LIGHTS }: { rig?: typeof REFERENCE_LIGHTS | typeof REFERENCE_V3_LIGHTS }) {
  const { gl, scene } = useThree();
  const keyRef = useRef<THREE.DirectionalLight>(null);
  const { key, fill, rimLeft, rimRight, hemisphere, shadow } = rig;
  const extent = "extent" in shadow ? shadow.extent : 1;
  useEffect(() => {
    // Whatever the studio eased these towards, the reference starts from neutral.
    gl.toneMappingExposure = 1;
    scene.environmentIntensity = 1;
    const light = keyRef.current;
    if (!light) return;
    light.shadow.intensity = shadow.intensity;
    // Aim the key, and its shadow box, at her chest rather than the floor.
    light.target.position.set(0, shadow.targetY, 0);
    light.target.updateMatrixWorld();
  }, [gl, scene, shadow.intensity, shadow.targetY]);
  return (
    <>
      <hemisphereLight args={[hemisphere.sky, hemisphere.ground, hemisphere.intensity]} />
      <directionalLight
        ref={keyRef}
        position={key.position}
        color={key.color}
        intensity={key.intensity}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-bias={-0.0002}
        shadow-normalBias={0.01}
        shadow-camera-left={-extent}
        shadow-camera-right={extent}
        shadow-camera-top={extent}
        shadow-camera-bottom={-extent}
        shadow-camera-near={0.5}
        shadow-camera-far={8}
      />
      <directionalLight position={fill.position} color={fill.color} intensity={fill.intensity} />
      {/* Rims as directional lights from behind: they light only edges and
          back-facing surfaces, never the front of the face. */}
      <directionalLight position={rimLeft.position} color={rimLeft.color} intensity={rimLeft.intensity} />
      <directionalLight position={rimRight.position} color={rimRight.color} intensity={rimRight.intensity} />
    </>
  );
}

/** With the studio lights off, undo the exposure and reflection strength they ease towards. */
function NoLights() {
  const { gl, scene } = useThree();
  useEffect(() => {
    gl.toneMappingExposure = 1;
    scene.environmentIntensity = 1;
  }, [gl, scene]);
  return null;
}

/** A free camera, aimed at the face or the whole upper body. */
function OrbitRig({ targetY, distance }: { targetY: number; distance: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  useEffect(() => {
    // The canvas camera is `manual` (Framing needs it), so the aspect is ours to keep.
    camera.aspect = size.width / size.height;
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height]);
  useEffect(() => {
    camera.fov = 30;
    camera.position.set(0, targetY, distance);
    camera.lookAt(0, targetY, 0);
    camera.updateProjectionMatrix();
  }, [camera, targetY, distance]);
  return <OrbitControls makeDefault target={[0, targetY, 0]} enableDamping minDistance={0.15} maxDistance={8} />;
}

/**
 * The realism pass, then the debug view, in ONE effect: both edit the same
 * meshes' materials, and two separate effects would undo each other's work in
 * whatever order React happened to run their cleanups.
 */
function SurfaceController({
  config,
  realism,
  view,
  version,
}: {
  config: AvatarConfig;
  realism: RealismOptions;
  view: MaterialView;
  version: number;
}) {
  const scene = useThree((s) => s.scene);
  useEffect(() => {
    const undoRealism = applyRealism(scene, config, realism);
    const undoView = applyMaterialView(scene, view);
    return () => {
      undoView();
      undoRealism();
    };
  }, [scene, config, realism, view, version]);
  return null;
}

/**
 * Blur radius for every shadow-casting light in the scene. Only VSM shadows
 * honour it; the canvas switches to VSM whenever softness is above 0.
 */
function ShadowSoftness({ radius, strength }: { radius: number; strength: number }) {
  const scene = useThree((s) => s.scene);
  useFrame(() => {
    scene.traverse((object) => {
      const light = object as THREE.DirectionalLight;
      if (!light.isLight || !light.castShadow || !light.shadow) return;
      if (light.shadow.radius !== radius) {
        light.shadow.radius = radius;
        light.shadow.blurSamples = 16;
      }
      // Each frame, after the lights' own effects have set theirs.
      if (strength > 0) light.shadow.intensity = strength;
    });
  });
  return null;
}

/** Pushes slider values into the shared uniforms; never recompiles. */
function RealismParamsSync({ params }: { params: RealismParams }) {
  useEffect(() => setRealismParams(params), [params]);
  return null;
}

/**
 * Runs the liveliness layer each frame. Keyed on the rig's load version by the
 * parent, so it subscribes AFTER the rig's own frame callbacks (the body
 * mixer, lipsync, blink) and therefore layers on top of them.
 */
function Life({ root, options }: { root: THREE.Object3D; options: LifeOptions }) {
  const rig = useMemo(() => createLifeRig(root), [root]);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  useFrame((state, delta) => updateLife(rig, optionsRef.current, state.clock.elapsedTime, delta));
  // Switching every part off still runs one frame of each, which clears what it wrote.
  return null;
}

function CameraRig({ settings, config, modelHeight }: { settings: LabSettings; config: AvatarConfig; modelHeight: number }) {
  if (settings.camera === "editable") {
    return (
      <LabFraming
        camera={settings.rig.camera[settings.layout]}
        rig={settings.rig.camera[settings.layout].rigs[config.id]}
        modelHeight={modelHeight}
      />
    );
  }
  if (settings.camera === "kiosk") {
    return (
      <Framing
        modelHeight={modelHeight}
        widthSqueeze={config.widthSqueeze}
        lensMm={config.lensMm}
        cameraDistanceM={config.cameraDistanceM}
      />
    );
  }
  if (settings.camera === "orbit-wide") {
    // Far enough back to see every studio light (they stand 2-3 m out) and drag them.
    return <OrbitRig targetY={1.3} distance={8} />;
  }
  const isFace = settings.camera === "orbit-face";
  return <OrbitRig targetY={isFace ? config.headTargetY + 0.12 : modelHeight * 0.62} distance={isFace ? 0.75 : 3.2} />;
}

/** The editable studio for the current theme and presenter, plus its handles. */
function EditableLights({
  settings,
  config,
  state,
  onSelectLight,
  onMoveLight,
}: {
  settings: LabSettings;
  config: AvatarConfig;
  state: AvatarState;
  onSelectLight: LabSceneProps["onSelectLight"];
  onMoveLight: LabSceneProps["onMoveLight"];
}) {
  const studio = settings.rig.studio[settings.theme];
  const rigLighting = settings.rig.rigLighting[config.id];
  return (
    <>
      <EditableStudioLights
        studio={studio}
        lighting={rigLighting[settings.theme]}
        backLight={rigLighting.backLight}
        state={state}
        headTargetY={config.headTargetY}
      />
      {settings.showHandles && (
        <LightHandles studio={studio} selected={settings.editLight} onSelect={onSelectLight} onMove={onMoveLight} />
      )}
    </>
  );
}

export default function LabScene({ settings, onInventory, onReady, onSelectLight, onMoveLight }: LabSceneProps) {
  const config = avatarConfig(settings.presenter);
  const [modelHeight, setModelHeight] = useState(config.fallbackHeight);
  // Bumped when a rig finishes loading, so the realism pass and debug view re-apply to it.
  const [version, setVersion] = useState(0);
  const [modelRoot, setModelRoot] = useState<THREE.Object3D | null>(null);

  useEffect(() => setModelHeight(config.fallbackHeight), [config.fallbackHeight]);

  const report = useCallback(
    (root: THREE.Object3D) => {
      setModelHeight(new THREE.Box3().setFromObject(root).max.y || config.fallbackHeight);
      onInventory(inventory(root));
      setModelRoot(root);
      setVersion((v) => v + 1);
      onReady();
    },
    [config.fallbackHeight, onInventory, onReady],
  );

  // AvatarModel reports readiness but not its scene; it is the only child of
  // the group below, so read it from there.
  const kioskGroupRef = useRef<THREE.Group>(null);
  const onKioskReady = useCallback(() => {
    if (kioskGroupRef.current) report(kioskGroupRef.current);
  }, [report]);

  const state = KIOSK_STATE[settings.pose];

  return (
    <Canvas
      dpr={[1, 2]}
      shadows={settings.shadowSoftness > 0 ? "variance" : "soft"}
      // antialias is load-bearing: hair alpha-to-coverage needs the MSAA samples.
      // preserveDrawingBuffer: the compare eyedropper reads pixels back after the frame.
      gl={{ antialias: true, alpha: true, toneMapping: THREE.ACESFilmicToneMapping, preserveDrawingBuffer: true }}
      camera={{ position: [0, 1.26, 4], fov: 20, near: 0.05, far: 100, manual: true }}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      style={{ background: "transparent" }}
    >
      <ToneMapping tone={settings.tone} />
      <CameraRig settings={settings} config={config} modelHeight={modelHeight} />
      {settings.lights === "studio" && <StudioLights config={config} theme={settings.theme} state={state} />}
      {settings.lights === "reference" && <ReferenceLights />}
      {settings.lights === "reference3" && <ReferenceLights key="v3" rig={REFERENCE_V3_LIGHTS} />}
      {settings.lights === "editable" && (
        <EditableLights
          settings={settings}
          config={config}
          state={state}
          onSelectLight={onSelectLight}
          onMoveLight={onMoveLight}
        />
      )}
      {settings.lights === "off" && <NoLights />}
      <EnvironmentChoice settings={settings} />
      <SurfaceController config={config} realism={settings.realism} view={settings.view} version={version} />
      <RealismParamsSync params={settings.realismParams} />
      <ShadowSoftness radius={Math.max(1, settings.shadowSoftness)} strength={settings.shadowStrength} />
      {(settings.ao.enabled || settings.grade.enabled) && <PostEffects ao={settings.ao} grade={settings.grade} />}

      <Suspense fallback={null}>
        {settings.look === "raw" ? (
          <RawModel
            key={`raw-${config.id}`}
            url={config.url}
            segments={config.segments}
            pose={settings.pose}
            onLoaded={report}
          />
        ) : (
          <group ref={kioskGroupRef} key={`kiosk-${config.id}`}>
            <AvatarModel url={config.url} config={config} state={state} onReady={onKioskReady} />
          </group>
        )}
      </Suspense>
      {modelRoot && <Life key={version} root={modelRoot} options={settings.life} />}
    </Canvas>
  );
}
