/**
 * Everything that decides the picture, as plain values. Lab settings name some
 * of it ("lights": "reference3"), and a name only means something next to this
 * code; the export carries this instead, so the file alone is enough to
 * rebuild the look anywhere, even after the presets here change.
 */

import { avatarConfig, type AvatarConfig } from "@/components/avatar/models";
import type { Theme } from "@/lib/theme";
import { MOBILE_BACKDROP_DEFAULT } from "./devices";
import type { LabCamera, LabSettings } from "./LabScene";
import { kioskRig, type LabRig } from "./lab-rig";
import {
  REFERENCE_BACKDROP_BLUR,
  REFERENCE_ENVIRONMENT,
  REFERENCE_GRADE,
  REFERENCE_LIGHTS,
  REFERENCE_V3_ENVIRONMENT,
  REFERENCE_V3_GRADE,
  REFERENCE_V3_LIGHTS,
} from "./reference-look";

/** The landscape artwork per theme — the same files page.module.css shows. */
export const BACKDROP_IMAGE: Record<Theme, string> = {
  dark: "/bg-desktop-dark.png",
  light: "/bg-desktop-light.png",
};

/** The picture behind her right now: the portrait artwork in the mobile frame, else the landscape one. */
export function currentBackdrop(settings: LabSettings): string {
  if (settings.layout === "desktop") return BACKDROP_IMAGE[settings.theme];
  return settings.mobileBackdrop === "theme" ? MOBILE_BACKDROP_DEFAULT[settings.theme] : settings.mobileBackdrop;
}

/** Field of view of the free orbit cameras, in degrees. */
export const ORBIT_FOV = 30;

/** Where an orbit camera starts: the point it circles and how far back it stands. */
export function orbitView(camera: LabCamera, config: AvatarConfig, modelHeight: number) {
  // Far enough back to see every studio light (they stand 2-3 m out) and drag them.
  if (camera === "orbit-wide") return { targetY: 1.3, distance: 8 };
  if (camera === "orbit-face") return { targetY: config.headTargetY + 0.12, distance: 0.75 };
  return { targetY: modelHeight * 0.62, distance: 3.2 };
}

/** Studio lights as the editable lights draw them, from the lab copy or the kiosk's own. */
function studioLights(rig: LabRig, settings: LabSettings, source: string) {
  const lighting = rig.rigLighting[settings.presenter];
  return {
    source,
    type: "studio",
    theme: settings.theme,
    studio: rig.studio[settings.theme],
    presenterLighting: lighting[settings.theme],
    backLight: lighting.backLight,
  };
}

function resolveLights(settings: LabSettings) {
  switch (settings.lights) {
    case "editable":
      return studioLights(settings.rig, settings, "lab editable rig");
    case "studio":
      return studioLights(kioskRig(), settings, "kiosk tuning.ts");
    case "reference":
      return { source: "Reference v1", type: "fixed", ...REFERENCE_LIGHTS, shadow: { ...REFERENCE_LIGHTS.shadow, extent: 1 } };
    case "reference3":
      return { source: "Reference v3", type: "fixed", ...REFERENCE_V3_LIGHTS };
    default:
      return { source: "none", type: "off" };
  }
}

function resolveEnvironment(settings: LabSettings) {
  switch (settings.environment) {
    case "panels":
      return { source: "lab editable rig", type: "panels", ...settings.rig.studio[settings.theme].environment };
    case "reference":
      return { source: "Reference v1", type: "panels", ...REFERENCE_ENVIRONMENT };
    case "reference3":
      return { source: "Reference v3", type: "backdrop+panels", image: currentBackdrop(settings), ...REFERENCE_V3_ENVIRONMENT };
    case "backdrop":
      return {
        source: "backdrop picture",
        type: "backdrop",
        image: currentBackdrop(settings),
        backdropStrength: settings.backdropStrength,
        resolution: 256,
      };
    default:
      return { source: "three.js RoomEnvironment", type: "room", blurSigma: 0.04 };
  }
}

function resolveCamera(settings: LabSettings, config: AvatarConfig) {
  if (settings.camera === "editable") {
    const camera = settings.rig.camera[settings.layout];
    const { rigs, ...framing } = camera;
    return { source: "lab editable rig", type: "framing", layout: settings.layout, ...framing, ...rigs[config.id] };
  }
  if (settings.camera === "kiosk") {
    const { rigs, ...framing } = kioskRig().camera.desktop;
    return { source: "kiosk tuning.ts", type: "framing", ...framing, ...rigs[config.id] };
  }
  // The body orbit aims at 62% of the loaded model's height; the export uses the
  // presenter's fallback height, which is within a few centimetres of it.
  const { targetY, distance } = orbitView(settings.camera, config, config.fallbackHeight);
  return {
    source: settings.camera,
    type: "orbit",
    fov: ORBIT_FOV,
    position: [0, targetY, distance],
    target: [0, targetY, 0],
    note: "free camera: wherever it was dragged to is not recorded",
  };
}

/** The look on screen, every preset replaced by its values. */
export function resolvedLook(settings: LabSettings, backdrop: string) {
  const config = avatarConfig(settings.presenter);
  return {
    presenter: { id: config.id, model: config.url, headTargetY: config.headTargetY },
    theme: settings.theme,
    layout: settings.layout,
    device: settings.layout === "mobile" ? settings.device : null,
    background: {
      page: backdrop,
      image: currentBackdrop(settings),
      blurPx: settings.backdropBlur,
    },
    renderer: {
      toneMapping: settings.tone,
      outputColorSpace: "srgb",
      antialias: true,
      shadowMap: settings.shadowSoftness > 0 ? "VSM" : "PCFSoft",
      shadowRadius: Math.max(1, settings.shadowSoftness),
      /** 0: each light keeps its own shadow strength. */
      shadowStrengthOverride: settings.shadowStrength,
    },
    lights: resolveLights(settings),
    environment: resolveEnvironment(settings),
    camera: resolveCamera(settings, config),
    surface: {
      look: settings.look,
      realism: settings.realism,
      realismParams: settings.realismParams,
    },
    life: settings.life,
    post: { ao: settings.ao, grade: settings.grade },
    view: settings.view,
    pose: settings.pose,
  };
}

/** Every built-in preset's values, so a lights or environment name in the file can always be looked up. */
export const PRESET_LIBRARY = {
  lights: {
    reference: REFERENCE_LIGHTS,
    reference3: REFERENCE_V3_LIGHTS,
  },
  environment: {
    reference: REFERENCE_ENVIRONMENT,
    reference3: REFERENCE_V3_ENVIRONMENT,
  },
  grade: {
    reference: REFERENCE_GRADE,
    reference3: REFERENCE_V3_GRADE,
  },
  backdropBlur: { reference: REFERENCE_BACKDROP_BLUR },
};
