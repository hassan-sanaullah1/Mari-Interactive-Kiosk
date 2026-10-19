/**
 * Every number that decides how the presenters LOOK, in one place.
 *
 * Values only — no logic, no three.js objects, nothing that runs. AvatarScene
 * reads the shared half (camera, lighting studio); models.ts folds the per-rig
 * half into each AvatarConfig, so the rest of the app reads `config.skinEmissive`
 * and friends exactly as before.
 *
 *   - SHARED  — one studio, both presenters stand in it.
 *   - PER RIG — a property of that export's own geometry, textures or albedo.
 *
 * Not here, on purpose:
 *   - Asset facts (file path, byte counts, clip windows) — those stay in
 *     models.ts next to the asset they describe.
 *   - Animation timing (crossfades, blink, the talk-exit debounce) — that
 *     stays in AvatarModel.tsx.
 *
 * Measurements and reasoning behind the light-theme numbers: docs/avatar-lighting.md.
 */

// Type-only imports: this file is a leaf at runtime (models.ts imports IT), so
// a value import of either module would close a cycle.
import type { AvatarId } from "./models";
import type { AvatarState } from "./state";
import type { Theme } from "@/lib/theme";

/** An x/y/z triple, in the mutable shape three.js's JSX props expect. */
type Vec3 = [number, number, number];

// ---------------------------------------------------------------------------
// SHARED — CAMERA
// ---------------------------------------------------------------------------

export const CAMERA = {
  /** Metres of the rig that fill the container's height. */
  frameHeightM: 1.15,
  /** Clear air above the head, as a fraction of the rig's height. */
  headRoom: 0.045,
  /**
   * Baseline lens focal length in mm (36mm sensor, matches Blender's "Focal
   * Length" field). Every rig overrides this in RIG_TUNING; this is the
   * fallback. A longer lens stands the camera further back for the same
   * frame and exaggerates near geometry less.
   */
  lensMm: 85,
  /** Sensor width in mm that `lensMm` is quoted against. */
  sensorMm: 36,
  /** Slow idle sway so the shot doesn't read as a still image. */
  sway: { amplitude: 0.015, speed: 0.08 },
};

// ---------------------------------------------------------------------------
// SHARED — THE LIGHTING STUDIO
//
// One complete room per theme: light colours, placement, per-state brightness,
// reflection panels, and the key's shadow strength. AvatarScene cross-fades
// every field between STUDIO.dark and STUDIO.light on a theme switch.
// ---------------------------------------------------------------------------

/** The six lights. Ambient is separate — see Studio.ambientColor below. */
type LightName = "key" | "fill" | "top" | "rim" | "kick" | "face";

/**
 * Where a light stands and how it's shaped. `intensity` here is only the
 * MOUNT value — the frame loop immediately overwrites it from `states`
 * below, so changing it here alone changes nothing visible.
 */
interface LightPlacement {
  position: Vec3;
  intensity: number;
  /** Spotlight-only; absent on the two directionals (key, fill). */
  angle?: number;
  penumbra?: number;
  distance?: number;
  /** Inverse-square falloff. 2 on every spot in both studios. */
  decay?: number;
}

/** One invisible reflection panel — shows up only in glossy surfaces. */
interface LightformerSpec {
  intensity: number;
  position: Vec3;
  scale: Vec3;
  color: string;
  /** Radians, written as a literal — this file holds no expressions. */
  rotation?: Vec3;
}

/** The key light's shadow. Only the key casts. */
interface ShadowSettings {
  /** 0..1 — how dark the cast shadow lands. The per-theme dial: `shadows`
   *  itself is a <Canvas> prop and can't be toggled per theme. */
  intensity: number;
  /** Shadow map resolution in texels. */
  mapSize: number;
  /** Depth-bias; prevents shadow acne. */
  bias: number;
  /** Normal-offset bias; same purpose as `bias`, better on curved surfaces. */
  normalBias: number;
  /** Half-width (metres) of the ortho shadow box, around `targetY`. */
  extent: number;
  /** World Y the shadow box and the key light aim at. */
  targetY: number;
}

export interface LightState {
  key: number;
  fill: number;
  rim: number;
  kick: number;
  top: number;
}

export interface Studio {
  colors: Record<LightName, string>;
  /** Ambient has no direction, so this tints every surface equally. */
  ambientColor: string;
  placement: Record<LightName, LightPlacement>;
  /** Brightness per conversation state — the real intensity control. */
  states: Record<AvatarState, LightState>;
  environment: { resolution: number; lightformers: LightformerSpec[] };
  shadow: ShadowSettings;
}

/**
 * DARK — the rig as originally authored, against a dark studio backdrop.
 * `rim` (cyan) and `kick` (green) are that backdrop thrown back onto her
 * silhouette; the light studio below replaces rather than retints them.
 *
 * Pinned byte-for-byte by test/avatar-studio.test.ts.
 */
const DARK_STUDIO: Studio = {
  ambientColor: "#ffffff",
  colors: {
     key: "#ffe4c9",
    fill: "#c9d6ff",
    rim: "#4fd8e8",
    kick: "#3fd39a",
    top: "#e8daf5",
    face: "#fff2e0",
  },
  placement: {
    /** Warm key, front-right and high. */
    key: { position: [2, 3, 2], intensity: 1.4 },
    /** Cool fill, opposite the key and behind. */
    fill: { position: [-2, 2, -1], intensity: 0.4 },
    /** Top wash from just in front of her. */
    top: { position: [0, 3, 1.5], angle: 0.4, penumbra: 1, intensity: 0.9, decay: 2 },
    /** Cyan rim, behind and camera-left — catches the silhouette only. */
    rim: { position: [-2.2, 2.2, -1.8], angle: 0.7, penumbra: 0.9, intensity: 1.4, decay: 2 },
    /** Green kick, behind and camera-right. */
    kick: { position: [2.4, 2.0, -1.6], angle: 0.7, penumbra: 0.9, intensity: 0.8, decay: 2 },
    /** Tight face spot. Aim point is per-rig — see headTargetY. */
    face: { position: [0, 2.2, 1], angle: 0.18, penumbra: 0.6, intensity: 1.6, distance: 1.6, decay: 2 },
  },
  states: {
    idle: { key: 1.4, fill: 0.4, rim: 2, kick: 5, top: 0.9 },
    listening: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.1 },
    thinking: { key: 1.2, fill: 0.5, rim: 2, kick: 5, top: 0.8 },
    speaking: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.2 },
  },
  environment: {
    resolution: 256,
    lightformers: [
      { intensity: 2, position: [0, 2, 3], scale: [4, 1, 1], color: "#ffe0cc" },
      { intensity: 1, position: [-3, 1, -1], scale: [3, 2, 1], color: "#c9d6ff" },
      { intensity: 0.5, position: [3, 0, -2], scale: [2, 3, 1], color: "#ffd6e0" },
    ],
  },
  /** Softer than the light theme's: this rig was balanced with no shadow at all. */
  shadow: {
    intensity: 0.55,
    mapSize: 2048,
    bias: -0.0002,
    normalBias: 0.01,
    extent: 1,
    targetY: 1.1,
  },
};

/**
 * LIGHT — matched to frontend/public/bg-mobile-light.png, the marble lobby.
 * Key from camera-left (the window wall), a near-white rim separating her
 * shoulder from the dark side of the room, and `kick` as a low floor bounce
 * instead of a backdrop colour. No cyan, no green. Full reasoning and the
 * measurements behind each value: docs/avatar-lighting.md.
 */
const LIGHT_STUDIO: Studio = {
  ambientColor: "#fffefd",
  colors: {
    key: "#fffcfa",
    fill: "#fffcfa",
    /** The gold ceiling cove. */
    top: "#fffbf3",
    /** The one cool light in the rig — separates her shoulder from the dark side. */
    rim: "#d8e6ff",
    /** Floor bounce. Off (black) — see placement.kick. */
    kick: "#000000",
    face: "#fffdfc",
  },
  placement: {
    /** Camera-left, where the window wall is. */
    key: { position: [-2.4, 2.9, 2.2], intensity: 2.6 },
    fill: { position: [2.6, 1.6, 1.4], intensity: 0.8 },
    top: { position: [0, 3.2, 0.8], angle: 0.5, penumbra: 1, intensity: 1.4, decay: 2 },
    /** Camera-right and behind, against the dark side of the room. */
    rim: { position: [2, 2.4, -2.2], angle: 0.8, penumbra: 1, intensity: 3, decay: 2 },
    /** Low floor bounce — below the head but not a footlight. */
    kick: { position: [0.3, 0.35, 2.2], angle: 1, penumbra: 1, intensity: 3.2, decay: 2 },
    face: { position: [0, 2, 1.2], angle: 0.22, penumbra: 0.8, intensity: 0.9, distance: 2, decay: 2 },
  },
  /** `fill` is the FINAL value — AvatarScene multiplies it by the rig's
   *  `lightThemeLighting.fill`, which stays ~1 on both rigs for that reason. */
  states: {
    idle: { key: 2.2, fill: 0.7, rim: 2.5, kick: 1.7, top: 1.1 },
    listening: { key: 2.4, fill: 0.75, rim: 2.7, kick: 1.7, top: 1.15 },
    thinking: { key: 2.05, fill: 0.75, rim: 2.3, kick: 1.6, top: 1 },
    speaking: { key: 2.4, fill: 0.75, rim: 2.9, kick: 1.8, top: 1.25 },
  },
  environment: {
    /** 512, not the dark studio's 256: these panels have a hard bright/dark
     *  split that bands at low resolution in the eye highlight. */
    resolution: 512,
    lightformers: [
      /** The window wall, camera-left and tall. */
      { intensity: 2.6, position: [-3.2, 1.6, 1.2], scale: [2, 4, 1], color: "#fffcfb" },
      /** The gold ceiling cove, lying flat overhead. 1.5708 = pi/2. */
      { intensity: 2, position: [0, 3.2, 0.4], scale: [6, 0.5, 1], color: "#fff6e6", rotation: [1.5708, 0, 0] },
      /** The polished marble floor, lying flat below. -1.5708 = -pi/2. */
      { intensity: 1.5, position: [0, -1, 0.8], scale: [6, 3, 1], color: "#fffcf9", rotation: [-1.5708, 0, 0] },
      /** The dark side of the room. Kept dim on purpose: an environment built
       *  only from bright panels flattens every reflective surface. */
      { intensity: 0.3, position: [3, 1.2, -0.6], scale: [2, 3, 1], color: "#5a6478" },
    ],
  },
  shadow: {
    intensity: 0.2,
    mapSize: 2048,
    bias: -0.0002,
    normalBias: 0.01,
    extent: 1,
    targetY: 1.1,
  },
};

export const STUDIO: Record<Theme, Studio> = { dark: DARK_STUDIO, light: LIGHT_STUDIO };

/** Voice-amplitude boost added on top of the state's brightness, per light —
 *  the rig breathes with her voice. `fill` and `top` take none. */
export const VOICE_BOOST = { key: 0.4, rim: 0.5, kick: 0.3 };

/** Per-frame approach rate toward wherever the lights are heading. Bigger is faster. */
export const LERP_SPEED = 0.04;

// ---------------------------------------------------------------------------
// SHARED — THEME-LEVEL LIGHT KNOBS
// ---------------------------------------------------------------------------

/** Applied on top of the per-state brightness above, eased on a theme switch. */
export interface ThemeLighting {
  /** Renderer tone-mapping exposure — scales everything, highlights included. */
  exposure: number;
  /** Ambient light intensity — lifts the shadows, flattening contrast. */
  ambient: number;
  /** Multiplier on the fill light's per-state intensity. */
  fill: number;
  /** Strength of the environment reflections (scene.environmentIntensity). */
  environment: number;
}

/** The baseline every rig's dark theme starts from. */
export const DARK_LIGHTING: ThemeLighting = { exposure: 1, ambient: 0.3, fill: 1, environment: 1 };

// ---------------------------------------------------------------------------
// PER RIG
// ---------------------------------------------------------------------------

/**
 * Everything about one presenter's look: framing, material corrections, and
 * how the studio lights that rig on each theme. models.ts merges this into
 * AvatarConfig, so every field is reachable as `config.<field>`.
 */
export interface RigTuning {
  /** Height in metres, used to frame the shot until the rig reports its real one. */
  fallbackHeight: number;
  /** Horizontal squeeze on the render, as a width multiplier (1 = true proportions). */
  widthSqueeze: number;
  /** Lens focal length in mm for this rig — overrides CAMERA.lensMm. */
  lensMm: number;
  /** Camera distance in metres, or null to derive it from the lens so the
   *  presenter fills the frame the same on any screen. */
  cameraDistanceM: number | null;
  /** World Y the face spot aims at — this rig's face centre. */
  headTargetY: number;
  /** Materials textured with skin — these get the emissive lift below. */
  skinMaterials: Set<string>;
  /** Emissive lift on skinMaterials, driven from their own base-colour texture. */
  skinEmissive: number;
  /** Roughness forced on skinMaterials, or null to keep the export's value. */
  skinRoughness: number | null;
  /** Per-material albedo scale (`color.multiplyScalar`), by material name. */
  materialTint: Record<string, number>;
  /** The material with painted-on makeup, or null if this rig has none. */
  faceMaterial: string | null;
  /** How strongly the makeup pass desaturates it: 0 = untouched, 1 = fully
   *  grey. Unused when `faceMaterial` is null. */
  makeupDesaturation: number;
  /** Alpha cutoff for a transparent card, by material name — overrides
   *  AvatarModel's default guess from the card's base colour. */
  alphaTest: Record<string, number>;
  /** Roughness forced on a non-skin material, by name. */
  materialRoughness: Record<string, number>;
  /** Specular reflection strength forced on a material, by name — 1 is physical. */
  materialSpecular: Record<string, number>;
  /** Multiplier on how much of the <Environment> a material reflects, by name. */
  materialEnvIntensity: Record<string, number>;
  /** A2F weight calibration, or null for a rig with no morphs to calibrate. */
  a2f: { gain: number; shapeGains: Record<string, number> } | null;
  /** Uniform scale on both wrist bones (hands + fingers). 1 = as authored. */
  handScale: number;
  /** Multipliers on the two back lights (rim, kick) for this rig, both themes. */
  backLight: { rim: number; kick: number };
  /** The light rig under the light theme. */
  lightThemeLighting: ThemeLighting;
  /** The light rig under the dark theme. */
  darkThemeLighting: ThemeLighting;
}

export const RIG_TUNING: Record<AvatarId, RigTuning> = {
  female: {
    fallbackHeight: 1.68,
    headTargetY: 1.45,
    widthSqueeze: 1,
    lensMm: 85,
    cameraDistanceM: null,

    /** Head, arms, legs — every material whose texture is a skin diffuse. */
    skinMaterials: new Set(["lambert14", "lambert17", "lambert12"]),
    skinEmissive: 0.25,
    skinRoughness: null,
    materialTint: {},

    /** Head_Diffuse — the only map with makeup painted into it. */
    faceMaterial: "lambert14",
    /** Keeps the lipstick/cheek flush close to the source texture. */
    makeupDesaturation: 0.01,

    alphaTest: {
      /** Hair: the default cut leaves a translucent grey haze at the fringe.
       *  dress2_v2 merged the four hair cards and the scalp (lambert19 through
       *  lambert23) into one 111k-vertex mesh on this single material, so the
       *  card value carries over here and the scalp's own 0.35 is gone with the
       *  separate scalp geometry it was cutting. */
      pasted__lambert2: 0.22,
    },

    materialRoughness: {
      /** Export omits roughnessFactor on both — glTF would default to fully matte. */
      "Kameez:lambert2": 0.5,
      /** Dupatta: kept dull on purpose — 0.5 made it look like shiny satin. */
      "pasted__lambert10": 0.9,
      /** Eyes — a cornea is wet; this is what gives them a catchlight. */
      lambert11: 0.08,
      lambert16: 0.25, // nails, lacquered
      lambert9: 0.35, // upper teeth, enamel
      lambert10: 0.35, // lower teeth
      lambert15: 0.35, // tongue, wet
      /** Hair: a tighter specular lobe lets the top light lay a sheen on the crown. */
      pasted__lambert2: 0.32,
    },
    materialSpecular: {},
    materialEnvIntensity: {
      lambert11: 2.2, // eyes — the catchlight
      lambert16: 1.8, // nails
      lambert9: 0.8, // upper teeth
      lambert10: 0.8, // lower teeth
      /** Skin: 1.0 (the default) reads as plastic. */
      lambert14: 0.55,
      lambert17: 0.55,
      lambert12: 0.55,
      /** Hair: near-black cards handed a bright room back read as grey sheen. */
      pasted__lambert2: 0.15,
      /** Dupatta, dulled again — shine comes from reflection as well as roughness. */
      "pasted__lambert10": 0.2,
    },

    a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
    handScale: 1,

    /** Her hair is matte, so the back lights do exactly what they're tuned to do. */
    backLight: { rim: 1, kick: 1 },
    lightThemeLighting: { exposure: 0.8, ambient: 0.2, fill: 1, environment: 0.75 },
    darkThemeLighting: DARK_LIGHTING,
  },

  male: {
    fallbackHeight: 1.85,
    headTargetY: 1.6,
    /** Narrower than true proportions — his clasped-hands idle pushes the
     *  elbows and sleeves out past how he reads in the artist's reference. */
    widthSqueeze: 0.93,
    /** Longer than the shared 85mm: stands the camera further back so his
     *  clasped hands (held in front of his face) aren't drawn oversized. */
    lensMm: 135,
    cameraDistanceM: 4.92,

    /** This export names the head material lambert5, not Std_Skin_Head. glb1
     *  dropped Std_Skin_Leg — legs and feet are no longer separate skin
     *  geometry — so head and arms are the whole of his skin now. */
    skinMaterials: new Set(["lambert5", "Std_Skin_Arm"]),
    skinEmissive: 0.08,
    /** This export authors real roughness on every material — nothing to correct. */
    skinRoughness: null,
    /** Pulls this export's brighter albedo down onto the female rig's level
     *  under the shared lights. */
    materialTint: {
      "pasted__pasted__lambert6": 0.62,
      lambert5: 0.95,
      Std_Skin_Arm: 0.95,
    },

    faceMaterial: null,
    /** Unused — faceMaterial is null, so the makeup pass never runs on him. */
    makeupDesaturation: 0.2,

    /** Keyed to this export's hair material name, which has changed before. */
    alphaTest: { standardSurface2: 0.08 },
    /** male_initial13 authored real roughness on every material; glb1 omits
     *  roughnessFactor on the kurta and on one of the two new waistcoat
     *  materials, and glTF defaults that to fully matte. Same correction, and
     *  the same reason, as the female rig's kameez. `waistcoat:lambert3`
     *  authors its own 0.5 and is left alone. */
    materialRoughness: {
      "pasted__pasted__lambert6": 0.5,
      "waistcoat:lambert2": 0.5,
    },
    /** His hair's sheen. */
    materialSpecular: { standardSurface2: 0.6 },
    /** Not yet measured against the lobby plate the way the female rig has been. */
    materialEnvIntensity: {},

    a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
    /** 1 = hands as authored. Lower (~0.9) to shrink them; below ~0.85 the
     *  wrist shows a visible step at the cuff. */
    handScale: 1,

    /** Both off: the rim mirrors off his clearcoated hair and the kick off
     *  the kurta's bright albedo. */
    backLight: { rim: 0, kick: 0 },
    lightThemeLighting: { exposure: 0.98, ambient: 0.5, fill: 1.15, environment: 1.2 },
    darkThemeLighting: { exposure: 1, ambient: 0.45, fill: 1.35, environment: 1 },
  },
};
