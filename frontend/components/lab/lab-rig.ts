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
 * Where each exported section belongs in the code, so the JSON says what to
 * edit without anyone having to remember.
 */
const DESTINATIONS = {
  rig: {
    studio: "frontend/components/avatar/tuning.ts → STUDIO (DARK_STUDIO, LIGHT_STUDIO)",
    rigLighting:
      "frontend/components/avatar/tuning.ts → RIG_TUNING[presenter].lightThemeLighting / darkThemeLighting / backLight",
    "camera.desktop":
      "frontend/components/avatar/tuning.ts → CAMERA (frameHeightM, headRoom, sway) and RIG_TUNING[presenter].lensMm / cameraDistanceM / widthSqueeze",
    "camera.mobile":
      "NEW: the kiosk has one CAMERA for every layout. Mobile values that differ from camera.desktop need a portrait override added to tuning.ts and read by Framing when the stage is portrait.",
  },
  phaseA: "frontend/components/avatar/realism.ts, liveliness.ts, PostEffects.tsx (not yet in the kiosk)",
};

/** The export document: the full lab rig, what differs from the kiosk, and the scene it was judged in. */
export function buildExport(
  rig: LabRig,
  scene: Record<string, unknown>,
  extras: { resolved?: unknown; presets?: unknown } = {},
): Record<string, unknown> {
  const kiosk = kioskRig();
  return {
    kind: "mari-avatar-lab-export",
    version: 1,
    exportedAt: new Date().toISOString(),
    destinations: DESTINATIONS,
    changedFromKiosk: diff(kiosk, rig),
    rig,
    scene,
    // What is on screen with every preset name replaced by its values; import reads rig and scene.
    ...(extras.resolved === undefined ? {} : { resolved: extras.resolved }),
    ...(extras.presets === undefined ? {} : { presets: extras.presets }),
  };
}
