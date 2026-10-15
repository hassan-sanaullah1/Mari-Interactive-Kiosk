/**
 * "Reference v1": the lab's attempt at the supplied reference portrait (a
 * daylit lobby, waist-up, warm skin, soft key from camera-left). Values only.
 *
 * What the reference shows, and the value each reading became:
 *
 *   key       large, soft, camera-left, ~40 deg off-axis and ~25 deg above the
 *             eyes; neutral-warm (~5200 K). Catchlights at ~10 o'clock, the
 *             faint nose shadow falls camera-right.
 *   fill      broad, camera-right and front; lit:shadow about 1.5-2 : 1, so the
 *             shadow side stays open. Low-contrast "beauty" light.
 *   rim       soft and cool from behind, mostly back-left (the window wall),
 *             separating hair and shoulders from the background.
 *   bounce    warm-grey from the stone floor, cool teal from the glass: a
 *             hemisphere light, sky teal-grey over warm ground.
 *   shadows   very soft and light; the darkest areas are contact shading
 *             (under the chin, arms against body, dupatta folds) — AO.
 *   skin      retouched-smooth with a broad low sheen on forehead, nose and
 *             cheekbones; warm translucent terminator; satin, natural lips.
 *   eyes      looking into the lens, bright catchlights.
 *   face      a full smile: corners up, cheeks raised, eyes slightly narrowed.
 *   camera    ~85 mm at eye level; shallow depth of field blurs the room.
 *   grade     neutral tone mapping, soft highlight roll-off, slightly lifted
 *             blacks, moderate contrast and saturation, warm highlights and
 *             cool-teal shadows, no visible vignette.
 *
 * Not reachable without changing the asset: the smooth bun (the rig has a
 * fringe), the charcoal waistcoat (the rig's is near-black), real pore detail.
 */

import type { GradeSettings } from "@/components/avatar/PostEffects";

type Vec3 = [number, number, number];

export interface ReferenceLight {
  position: Vec3;
  color: string;
  intensity: number;
}

export const REFERENCE_LIGHTS = {
  key: { position: [-2.3, 2.7, 2.6] as Vec3, color: "#fff1e2", intensity: 2.4 },
  fill: { position: [2.6, 1.5, 2.4] as Vec3, color: "#eef3fb", intensity: 1.1 },
  // Halved from the first pass (2.2 / 1.0): on the glossy hair cards the rim
  // read as white streaks on the crown rather than as soft separation.
  rimLeft: { position: [-1.6, 2.6, -2.4] as Vec3, color: "#d6ecff", intensity: 1.1 },
  rimRight: { position: [1.8, 2.3, -2.1] as Vec3, color: "#e9f1ff", intensity: 0.5 },
  /** Sky over ground: the glass and the stone floor. */
  hemisphere: { sky: "#cfe2e6", ground: "#8c8076", intensity: 0.55 },
  /** Light, soft shadow: the reference has no hard shadow edge anywhere. */
  shadow: { intensity: 0.4, targetY: 1.2 },
} satisfies Record<string, unknown>;

export interface ReferencePanel {
  intensity: number;
  position: Vec3;
  scale: Vec3;
  color: string;
  rotation?: Vec3;
}

/**
 * What she reflects: the lobby as soft panels. The big camera-left softbox is
 * what puts the catchlight at ten o'clock and the broad sheen on the skin.
 */
export const REFERENCE_ENVIRONMENT: { resolution: number; panels: ReferencePanel[] } = {
  resolution: 512,
  panels: [
    /** The window wall, camera-left and in front: the key's reflection. */
    { intensity: 3, position: [-3, 1.8, 2.2], scale: [3, 4, 1], color: "#fff6ec" },
    /** Broad fill reflection, camera-right. */
    { intensity: 1.2, position: [3, 1.4, 2], scale: [3, 3, 1], color: "#f2f6fb" },
    /** Ceiling, lying flat. 1.5708 = pi/2. */
    { intensity: 0.5, position: [0, 3.4, 0.5], scale: [8, 4, 1], color: "#f5f7f8", rotation: [1.5708, 0, 0] },
    /** Stone floor bounce, warm grey, lying flat. */
    { intensity: 0.7, position: [0, -0.8, 1], scale: [8, 4, 1], color: "#d8cfc6", rotation: [-1.5708, 0, 0] },
    /** The teal glass behind her. */
    { intensity: 0.8, position: [0, 1.6, -3.5], scale: [8, 4, 1], color: "#9fc4c9" },
  ],
};

export const REFERENCE_GRADE: GradeSettings = {
  enabled: true,
  contrast: 1.06,
  saturation: 1.04,
  lift: 0.025,
  warmth: 0.06,
  tealShadows: 0.05,
};

/** Background softness, in CSS pixels of blur: the reference's depth of field. */
export const REFERENCE_BACKDROP_BLUR = 4;

// ---------------------------------------------------------------------------
// REFERENCE v3 — values from measurement, not from reading the picture by eye.
//
// Sampled from the target and from the lab's v2 render side by side (9x9 px
// averages, sRGB):
//
//                      target            v2 render
//   forehead           210 169 145       200 152 123
//   camera-right cheek 233 180 157       201 136 110
//   camera-left cheek  197 138 116       218 169 149
//   under the jaw      106  69  46       204 160 125
//
// Three things follow, and v3 is built on them:
//   1. The key is camera-RIGHT. The bright cheek and the nose's shadow say so
//      (also checked on the full portrait). v1 and v2 lit from the left.
//   2. The face needs real modelling: the target's lit cheek is ~1.2x its dark
//      cheek and the neck under the jaw ~0.5x the forehead; v2's neck matched
//      its forehead, i.e. no jaw shadow at all. Hence a ~3:1 key:fill ratio,
//      much less sky bounce, a stronger shadow and tighter AO.
//   3. v2's skin is MORE orange than the target, not paler (blue/red 0.62 vs
//      0.69). So the skin is cooled and desaturated slightly, not warmed.
// ---------------------------------------------------------------------------

export const REFERENCE_V3_LIGHTS = {
  /** ~33 deg above her eyes and ~45 deg off-axis, camera-right: shadows fall down and to camera-left. */
  // Measured pass 2: at [2.3, 3.7, 2.3] / 3.0 both cheeks came out equal (191 vs 185);
  // more from the side and brighter, so the lit cheek leads the shadow one ~1.2x as in the target.
  // Pass 3: higher again (y 3.4 -> 4.0) so the jaw shadows the neck, as the target's does.
  key: { position: [3.0, 4.0, 1.8] as Vec3, color: "#fff6ef", intensity: 4.0 },
  /** Camera-left and cooler, matching the lobby's daylight. Pass 2: 0.75 filled the shadow cheek. */
  fill: { position: [-2.5, 1.7, 2.6] as Vec3, color: "#eef3f9", intensity: 0.45 },
  rimLeft: { position: [-1.6, 2.6, -2.4] as Vec3, color: "#e1eeff", intensity: 0.7 },
  rimRight: { position: [1.8, 2.4, -2.1] as Vec3, color: "#eef3ff", intensity: 0.6 },
  /** Far lower than v1 (0.55): the bounce was filling the shadows the target keeps. */
  hemisphere: { sky: "#dde8ee", ground: "#9a8f86", intensity: 0.22 },
  /** Stronger, and aimed at the head with a tighter box for finer shadow detail. */
  shadow: { intensity: 0.8, targetY: 1.4, extent: 0.7 },
} satisfies Record<string, unknown>;

/**
 * Highlight panels only; the room itself comes from the backdrop picture under
 * them (step 8), so what she reflects is the room she stands in.
 */
export const REFERENCE_V3_ENVIRONMENT: { resolution: number; backdropStrength: number; panels: ReferencePanel[] } = {
  resolution: 512,
  /** The backdrop picture, dimmed: colour from the room without flattening the face. */
  backdropStrength: 0.3,
  panels: [
    /** The key's softbox, camera-right: puts the sheen on forehead, nose bridge and the right cheekbone. */
    { intensity: 4, position: [2.4, 2.3, 2.2], scale: [1.4, 1.8, 1], color: "#fff6ee" },
    /** A small bright card up and to camera-right of the eyes: the catchlight. */
    { intensity: 10, position: [0.8, 1.95, 2.3], scale: [0.35, 0.25, 1], color: "#ffffff" },
    /** Fill reflection, camera-left, dim. */
    { intensity: 0.7, position: [-3, 1.4, 2], scale: [3, 3, 1], color: "#eef3f8" },
    /** Ceiling, lying flat. */
    { intensity: 0.35, position: [0, 3.4, 0.5], scale: [8, 4, 1], color: "#f5f7f8", rotation: [1.5708, 0, 0] },
    /** Stone floor bounce, warm grey, lying flat. */
    { intensity: 0.45, position: [0, -0.8, 1], scale: [8, 4, 1], color: "#d8cfc6", rotation: [-1.5708, 0, 0] },
  ],
};

/** A touch more contrast than v1, neutral white balance, the faintest teal in the shadows. */
export const REFERENCE_V3_GRADE: GradeSettings = {
  enabled: true,
  contrast: 1.08,
  saturation: 1,
  lift: 0.015,
  warmth: 0,
  tealShadows: 0.03,
};
