/**
 * The lab's own, editable copy of the kiosk's lighting studios and camera
 * framing. It starts as an exact copy of components/avatar/tuning.ts and is
 * edited only here; tuning.ts itself is never written, so the kiosk cannot
 * change from the lab. When values are agreed they are exported as JSON
 * (`buildExport`) and moved into tuning.ts by hand, in a reviewed change.
 */

import { AVATARS, type AvatarId } from "@/components/avatar/models";
import { CAMERA, RIG_TUNING, STUDIO, type Studio, type ThemeLighting } from "@/components/avatar/tuning";
import type { Theme } from "@/lib/theme";

export type LightName = keyof Studio["placement"];
export const LIGHT_NAMES: LightName[] = ["key", "fill", "top", "rim", "kick", "face"];
/** The lights whose brightness is set per conversation state (Studio.states). */
export const STATE_LIGHTS = ["key", "fill", "rim", "kick", "top"] as const;

export interface RigLighting {
  light: ThemeLighting;
  dark: ThemeLighting;
  backLight: { rim: number; kick: number };
}

export interface RigCamera {
  lensMm: number;
  /** null: derive the distance from the lens so the frame height always fits. */
  cameraDistanceM: number | null;
  widthSqueeze: number;
}

export interface LabCameraRig {
  frameHeightM: number;
  headRoom: number;
  sway: { amplitude: number; speed: number };
  rigs: Record<AvatarId, RigCamera>;
}

/**
 * Landscape (desktop, landscape kiosk) and portrait (phone, portrait kiosk):
 * the kiosk switches layout at an aspect of 6:5 (page.module.css).
 */
export type Layout = "desktop" | "mobile";

export interface LabRig {
  studio: Record<Theme, Studio>;
  rigLighting: Record<AvatarId, RigLighting>;
  /**
   * One framing per layout. The kiosk has a single CAMERA for every screen
   * shape, so both start as that; a mobile value that differs is a NEW setting
   * the kiosk would have to grow.
   */
  camera: Record<Layout, LabCameraRig>;
}

const clone = <T>(value: T): T => structuredClone(value);
const presenters = () => Object.keys(AVATARS) as AvatarId[];

/** A fresh copy of exactly what the kiosk uses today. */
export function kioskRig(): LabRig {
  return {
    studio: clone(STUDIO),
    rigLighting: Object.fromEntries(
      presenters().map((id) => [
        id,
        {
          light: clone(RIG_TUNING[id].lightThemeLighting),
          dark: clone(RIG_TUNING[id].darkThemeLighting),
          backLight: clone(RIG_TUNING[id].backLight),
        },
      ]),
    ) as Record<AvatarId, RigLighting>,
    camera: { desktop: kioskCamera(), mobile: kioskCamera() },
  };
}

/** The kiosk's one framing, as a lab camera. */
function kioskCamera(): LabCameraRig {
  return {
    frameHeightM: CAMERA.frameHeightM,
    headRoom: CAMERA.headRoom,
    sway: clone(CAMERA.sway),
    rigs: Object.fromEntries(
      presenters().map((id) => [
        id,
        {
          lensMm: RIG_TUNING[id].lensMm,
          cameraDistanceM: RIG_TUNING[id].cameraDistanceM,
          widthSqueeze: RIG_TUNING[id].widthSqueeze,
        },
      ]),
    ) as Record<AvatarId, RigCamera>,
  };
}

export interface Change {
  path: string;
  kiosk: unknown;
  lab: unknown;
}

/** Every leaf that differs between two values, with its dotted path. */
export function diff(kiosk: unknown, lab: unknown, path = ""): Change[] {
  const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
  if (isObject(kiosk) && isObject(lab)) {
    const keys = new Set([...Object.keys(kiosk), ...Object.keys(lab)]);
    return [...keys].flatMap((key) => diff(kiosk[key], lab[key], path ? `${path}.${key}` : key));
  }
  return Object.is(kiosk, lab) ? [] : [{ path, kiosk, lab }];
}

/**
 * The part of the rig one presenter in one theme uses: that theme's studio,
 * that presenter's knobs for that theme and back light, and both layouts'
 * framing with only that presenter's lens. The framing's height, head room and
 * sway are shared by every presenter in the kiosk, so they always come along.
 */
export interface ScopedRig {
  studio: Partial<Record<Theme, Studio>>;
  rigLighting: Partial<Record<AvatarId, Partial<Omit<RigLighting, "backLight">> & Pick<RigLighting, "backLight">>>;
  camera: Record<Layout, Omit<LabCameraRig, "rigs"> & { rigs: Partial<Record<AvatarId, RigCamera>> }>;
}

export function scopeRig(rig: LabRig, presenter: AvatarId, theme: Theme): ScopedRig {
  const lighting = rig.rigLighting[presenter];
  const camera = (layout: Layout) => {
    const { rigs, ...framing } = rig.camera[layout];
    return { ...framing, rigs: { [presenter]: rigs[presenter] } };
  };
  return {
    studio: { [theme]: rig.studio[theme] },
    rigLighting: { [presenter]: { [theme]: lighting[theme], backLight: lighting.backLight } },
    camera: { desktop: camera("desktop"), mobile: camera("mobile") },
  };
}

/**
 * Where each exported section belongs in the code, so the JSON says what to
 * edit without anyone having to remember.
 */
function destinations(presenter: AvatarId, theme: Theme) {
  const studio = theme === "light" ? "LIGHT_STUDIO" : "DARK_STUDIO";
  const knobs = theme === "light" ? "lightThemeLighting" : "darkThemeLighting";
  return {
    rig: {
      [`studio.${theme}`]: `frontend/components/avatar/tuning.ts → STUDIO.${theme} (${studio})`,
      [`rigLighting.${presenter}`]: `frontend/components/avatar/tuning.ts → RIG_TUNING.${presenter}.${knobs} / backLight`,
      "camera.desktop": `frontend/components/avatar/tuning.ts → CAMERA (frameHeightM, headRoom, sway; shared by every presenter) and RIG_TUNING.${presenter}.lensMm / cameraDistanceM / widthSqueeze`,
      "camera.mobile":
        "NEW: the kiosk has one CAMERA for every layout. Mobile values that differ from camera.desktop need a portrait override added to tuning.ts and read by Framing when the stage is portrait.",
    },
    phaseA: "frontend/components/avatar/realism.ts, liveliness.ts, PostEffects.tsx (not yet in the kiosk)",
  };
}

/** What an export of this presenter and theme would list as changed from the kiosk. */
export function scopedChanges(rig: LabRig, presenter: AvatarId, theme: Theme): Change[] {
  return diff(scopeRig(kioskRig(), presenter, theme), scopeRig(rig, presenter, theme));
}

/**
 * The export document for ONE presenter in ONE theme: their part of the rig,
 * what differs from the kiosk there, and the scene it was judged in. Importing
 * it changes only that part; the other presenter and theme keep their values.
 */
export function buildExport(
  rig: LabRig,
  scene: Record<string, unknown>,
  scope: { presenter: AvatarId; theme: Theme },
  extras: { resolved?: unknown; presets?: unknown } = {},
): Record<string, unknown> {
  const { presenter, theme } = scope;
  return {
    kind: "mari-avatar-lab-export",
    version: 2,
    exportedAt: new Date().toISOString(),
    scope: { presenter, theme },
    destinations: destinations(presenter, theme),
    changedFromKiosk: scopedChanges(rig, presenter, theme),
    rig: scopeRig(rig, presenter, theme),
    scene,
    // What is on screen with every preset name replaced by its values; import reads rig and scene.
    ...(extras.resolved === undefined ? {} : { resolved: extras.resolved }),
    ...(extras.presets === undefined ? {} : { presets: extras.presets }),
  };
}
