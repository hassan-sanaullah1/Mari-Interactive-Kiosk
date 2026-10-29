/**
 * The approved look of each presenter in each theme, as the avatar lab renders
 * it: lights, reflections, tone mapping, surface realism, resting expression,
 * ambient occlusion, grade and shadows. The page background is not part of a
 * look; the kiosk's artwork stays as it is.
 *
 * Copied from the lab exports the team signed off (test/fixtures/lab-exports/),
 * and test/presenter-looks.test.ts holds every value here to those files. A
 * presenter or theme with no entry renders exactly as before.
 */

import type { LifeOptions } from "../look/liveliness";
import type { AoSettings, GradeSettings } from "../look/PostEffects";
import type { RealismOptions, RealismParams } from "../look/realism";
import type { AvatarId } from "../models";
import type { Studio, ThemeLighting } from "../tuning";
import type { Theme } from "@/lib/theme";

/**
 * On at the team's request (2026-10-19), against AGENTS.md's off-by-default
 * rule for new features. False puts the kiosk back to its look before this.
 */
export const ENABLE_AVATAR_LOOKS = true;

/**
 * Resting expression for every presenter in every theme.
 *
 * The rest of a look is per-theme, but this is not: a presenter who smiles and
 * follows you in the light room and goes blank in the dark one reads as two
 * different people. Only the light themes carry a look (PRESENTER_LOOKS below),
 * so AvatarScene falls back to this rather than to NO_LIFE where there is none.
 */
export const PRESENTER_LIFE: LifeOptions = { smile: 0.5, gaze: true, headDrift: true };

type Vec3 = [number, number, number];

export interface FixedLight {
  position: Vec3;
  color: string;
  intensity: number;
}

/** A still rig, not eased per conversation state: key, fill, two rims and a sky-over-floor bounce. */
export interface FixedLightRig {
  key: FixedLight;
  fill: FixedLight;
  rimLeft: FixedLight;
  rimRight: FixedLight;
  hemisphere: { sky: string; ground: string; intensity: number };
  /** The key's shadow: darkness, the height it aims at, half-width of its box in metres. */
  shadow: { intensity: number; targetY: number; extent: number };
}

export interface LightPanel {
  intensity: number;
  position: Vec3;
  scale: Vec3;
  color: string;
  rotation?: Vec3;
}

export type LookLighting =
  /** The kiosk's own studio rig (DynamicLighting), with this studio for the theme. */
  | { kind: "studio"; studio: Studio; rigLighting: ThemeLighting }
  /** A fixed rig and its reflection panels. */
  | { kind: "fixed"; lights: FixedLightRig; environment: { resolution: number; panels: LightPanel[] } };

export interface PresenterLook {
  /** False: the rig's materials as exported, without AvatarModel's corrections (the lab's "raw" look). */
  isCorrected: boolean;
  lighting: LookLighting;
  toneMapping: "neutral" | "aces";
  /** CAMERA.headRoom for the landscape and the portrait layout. */
  headRoom: { landscape: number; portrait: number };
  realism: RealismOptions;
  realismParams: RealismParams;
  life: LifeOptions;
  ao: AoSettings;
  grade: GradeSettings;
  /** Shadow blur radius; above 0 the renderer switches to VSM shadows. */
  shadowSoftness: number;
  /** Overrides every casting light's shadow darkness; 0 keeps each light's own. */
  shadowStrength: number;
}

/** female.json, exported 2026-10-19 08:24: the raw rig under the lab's Reference v1 lights and lobby panels. */
const FEMALE_LIGHT: PresenterLook = {
  isCorrected: false,
  lighting: {
    kind: "fixed",
    lights: {
      key: { position: [-2.3, 2.7, 2.6], color: "#fff1e2", intensity: 2.4 },
      fill: { position: [2.6, 1.5, 2.4], color: "#eef3fb", intensity: 1.1 },
      rimLeft: { position: [-1.6, 2.6, -2.4], color: "#d6ecff", intensity: 1.1 },
      rimRight: { position: [1.8, 2.3, -2.1], color: "#e9f1ff", intensity: 0.5 },
      hemisphere: { sky: "#cfe2e6", ground: "#8c8076", intensity: 0.55 },
      shadow: { intensity: 0.4, targetY: 1.2, extent: 1 },
    },
    environment: {
      resolution: 512,
      panels: [
        { intensity: 3, position: [-3, 1.8, 2.2], scale: [3, 4, 1], color: "#fff6ec" },
        { intensity: 1.2, position: [3, 1.4, 2], scale: [3, 3, 1], color: "#f2f6fb" },
        { intensity: 0.5, position: [0, 3.4, 0.5], scale: [8, 4, 1], color: "#f5f7f8", rotation: [1.5708, 0, 0] },
        { intensity: 0.7, position: [0, -0.8, 1], scale: [8, 4, 1], color: "#d8cfc6", rotation: [-1.5708, 0, 0] },
        { intensity: 0.8, position: [0, 1.6, -3.5], scale: [8, 4, 1], color: "#9fc4c9" },
      ],
    },
  },
  // ACES, not the lab's neutral: the kiosk's <Canvas> mounts with ACES, so a
  // look asking for neutral only took effect once something re-ran
  // ToneMappingSync (a theme switch), and the same rig rendered visibly warmer
  // for the rest of the session than it did on a fresh load. Matching the
  // canvas is what keeps one presenter looking like itself throughout.
  toneMapping: "aces",
  // Judged with the kiosk's own framing, which has one head room for every layout.
  headRoom: { landscape: 0.045, portrait: 0.045 },
  realism: {
    skinGlow: false,
    skinScatter: true,
    lipGloss: true,
    surfaceDetail: true,
    skinSmooth: true,
    skinSheen: true,
    skinTone: true,
    browDefinition: true,
    hairTame: false,
    wetEyes: true,
    hairCoverage: false,
  },
  realismParams: {
    scatterWrap: 0.5,
    scatterStrength: 0.9,
    scatterWarmth: 0.8,
    lipGloss: 0.85,
    skinDetail: 2.1,
    clothDetail: 0,
    smoothAmount: 0.6,
    smoothRadius: 0.0025,
    skinRoughness: 0.53,
    skinSheen: 0.82,
    skinSaturation: 0.91,
    skinWarmth: 0,
    skinBrightness: 1.02,
    calmRedness: 0.05,
    eyeBrightness: 1.1,
    browDarken: 0.52,
    browDensity: 1.3,
    hairReflection: 0.1,
    hairCutoff: 0.25,
    hairShade: 0.9,
    hairRoughness: 0.32,
  },
  life: PRESENTER_LIFE,
  ao: { enabled: true, intensity: 0.6, radius: 0.1 },
  grade: { enabled: true, contrast: 1.16, saturation: 1, lift: 0.07, warmth: -0.06, tealShadows: 0.05 },
  shadowSoftness: 5,
  shadowStrength: 1,
};

/** male.json, exported 2026-10-19 09:10: the corrected rig in the light studio as the lab edited it. */
const MALE_LIGHT: PresenterLook = {
  isCorrected: true,
  lighting: {
    kind: "studio",
    studio: {
      ambientColor: "#fffefd",
      colors: { key: "#fffcfa", fill: "#fffcfa", top: "#fffbf3", rim: "#d8e6ff", kick: "#000000", face: "#fffdfc" },
      placement: {
        key: { position: [-2.3, 1.3, 2.2], intensity: 2.6 },
        fill: { position: [2.6, 1.6, 1.4], intensity: 0.8 },
        top: { position: [0, 3.2, 0.8], angle: 0.5, penumbra: 1, intensity: 1.4, decay: 2 },
        rim: { position: [2, 2.4, -2.2], angle: 0.8, penumbra: 1, intensity: 3, decay: 2 },
        kick: { position: [0.3, 0.35, 2.2], angle: 1, penumbra: 1, intensity: 3.2, decay: 2 },
        face: { position: [0, 2, 1.2], angle: 0.22, penumbra: 0.8, intensity: 0.9, distance: 2, decay: 2 },
      },
      states: {
        idle: { key: 2.3, fill: 0.7, rim: 2.5, kick: 1.7, top: 1.1 },
        listening: { key: 2.4, fill: 0.75, rim: 2.7, kick: 1.7, top: 1.15 },
        thinking: { key: 2.05, fill: 0.75, rim: 2.3, kick: 1.6, top: 1 },
        speaking: { key: 2.4, fill: 0.75, rim: 2.9, kick: 1.8, top: 1.25 },
      },
      environment: {
        resolution: 512,
        lightformers: [
          { intensity: 1.95, position: [-3.2, 1.6, 1.2], scale: [2, 4, 1], color: "#fffcfb" },
          { intensity: 2.3, position: [0, 3.2, 0.4], scale: [6, 0.5, 1], color: "#fff6e6", rotation: [1.5708, 0, 0] },
          { intensity: 1.3, position: [0, -1, 0.8], scale: [6, 3, 1], color: "#fffcf9", rotation: [-1.5708, 0, 0] },
          { intensity: 0.65, position: [3, 1.2, -0.6], scale: [2, 3, 1], color: "#5a6478" },
        ],
      },
      shadow: { intensity: 0.21, mapSize: 2048, bias: -0.0002, normalBias: 0.01, extent: 1, targetY: 1.1 },
    },
    // The export says environment 1.2, but the lab showed 1: drei's <Environment>
    // writes scene.environmentIntensity = 1 each time the panels re-render, after
    // the lab's one-time 1.2. Measured on the kiosk at the lab's resolution: 1.2
    // drew the male 2-3% brighter than the approved render, 1 matched it.
    rigLighting: { exposure: 0.75, ambient: 0.5, fill: 1.15, environment: 1 },
  },
  // ACES rather than the lab's neutral — see the female look's note above.
  toneMapping: "aces",
  headRoom: { landscape: 0.045, portrait: 0.055 },
  realism: {
    skinGlow: false,
    skinScatter: true,
    lipGloss: false,
    surfaceDetail: true,
    skinSmooth: false,
    skinSheen: true,
    skinTone: true,
    browDefinition: true,
    hairTame: false,
    wetEyes: true,
    hairCoverage: false,
  },
  realismParams: {
    scatterWrap: 0.5,
    scatterStrength: 0.9,
    scatterWarmth: 0.8,
    lipGloss: 0.85,
    skinDetail: 0.4,
    clothDetail: 0,
    smoothAmount: 0.6,
    smoothRadius: 0.0025,
    skinRoughness: 0.72,
    skinSheen: 0.4,
    skinSaturation: 1,
    skinWarmth: 0.15,
    skinBrightness: 1.02,
    calmRedness: 0,
    eyeBrightness: 1.1,
    browDarken: 0.52,
    browDensity: 1.3,
    hairReflection: 0.1,
    hairCutoff: 0.25,
    hairShade: 0.9,
    hairRoughness: 0.32,
  },
  life: PRESENTER_LIFE,
  ao: { enabled: false, intensity: 0.6, radius: 0.1 },
  grade: { enabled: true, contrast: 1.19, saturation: 1, lift: 0.07, warmth: -0.06, tealShadows: 0.05 },
  shadowSoftness: 5,
  shadowStrength: 1,
};

export const PRESENTER_LOOKS: Record<AvatarId, Partial<Record<Theme, PresenterLook>>> = {
  female: { light: FEMALE_LIGHT },
  male: { light: MALE_LIGHT },
};

/** The look to render, or null for the kiosk's look as it was before looks existed. */
export function presenterLook(avatar: AvatarId, theme: Theme): PresenterLook | null {
  if (!ENABLE_AVATAR_LOOKS) return null;
  return PRESENTER_LOOKS[avatar][theme] ?? null;
}

/**
 * This presenter's framing, for a theme with no look of its own (today, dark).
 *
 * The two rigs are framed differently on purpose — see MALE_LIGHT's headRoom,
 * 0.055 against the female's 0.045, a correction for how the rigs differ at
 * the chosen crop — so dark mode falling back to CAMERA.headRoom instead of
 * this presenter's own value moved the male rig noticeably between themes.
 * Only `light` carries a look today (PRESENTER_LOOKS above), so that is what
 * this reads; a presenter with no light look either falls through to null and
 * AvatarScene keeps using CAMERA.headRoom, same as before looks existed.
 */
export function presenterHeadRoom(avatar: AvatarId): PresenterLook["headRoom"] | null {
  return PRESENTER_LOOKS[avatar].light?.headRoom ?? null;
}
