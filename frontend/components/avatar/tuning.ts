/**
 * Every number that decides how the presenters LOOK, in one place.
 *
 * This file holds values only — no logic, no three.js objects, nothing that
 * runs. AvatarScene reads the scene half (camera, light colours, placement,
 * per-state brightness) and models.ts folds the per-rig half into each
 * AvatarConfig, so the rest of the app keeps reading `config.skinEmissive` and
 * friends exactly as before.
 *
 * The split to keep in mind when adding a value:
 *
 *   - SHARED  — one studio, both presenters stand in it. Changing one of these
 *               changes both rigs.
 *   - PER RIG — a property of that export's own geometry, textures or albedo.
 *               The two rigs were authored to different levels (see
 *               `materialTint`), so most of the look values differ.
 *
 * What is NOT here, on purpose:
 *
 *   - Asset facts — file path, byte counts, clip windows, whether the rig has
 *     morph targets. Those describe the .glb, not the look, and stay in
 *     models.ts next to the measurements that justify them.
 *   - Animation mechanism — crossfade lengths, the talk-exit debounce, blink
 *     timing, the face-refresh delay. Those are timing, not appearance, and
 *     stay in AvatarModel.tsx.
 */

// Type-only imports on purpose: this file is a leaf at runtime (models.ts
// imports IT), and a value import of either module would close a cycle.
import type { AvatarId } from "./models";
import type { AvatarState } from "./state";

/** An x/y/z triple, in the mutable shape three.js's JSX props expect. */
type Vec3 = [number, number, number];

// ---------------------------------------------------------------------------
// SHARED — THE CAMERA
// ---------------------------------------------------------------------------

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
 *
 * The fallback height each rig is framed against until it reports its real one
 * is per-rig — see `fallbackHeight` in RIG_TUNING below.
 */
export const CAMERA = {
  /** Metres of the rig that fill the container's height. */
  frameHeightM: 1.15,
  /** Clear air above the head, as a fraction of the rig's height. */
  headRoom: 0.045,
  /**
   * Lens focal length in mm, with the same meaning as Blender's camera "Focal
   * Length" (36mm sensor, Sensor Fit: Auto), so a value from the artist's
   * .blend can be dropped in as-is. The frame size stays fixed; the lens only
   * decides how far back the camera stands to get it. At this framing it
   * changes her proportions very little — measured, 28mm to 200mm moves the
   * shoulder-to-head width ratio by under 2%.
   */
  lensMm: 85,
  /** Blender's default sensor width, which its focal lengths are quoted against. */
  sensorMm: 36,
  /**
   * The very slow sway that keeps the shot from reading as a still image.
   * Amplitude is scaled to this framing (the source scene used 0.05 across a
   * much wider frame); at 0.015 it is a couple of pixels of parallax.
   */
  sway: { amplitude: 0.015, speed: 0.08 },
};

// ---------------------------------------------------------------------------
// SHARED — THE LIGHT RIG
//
// A studio rig: warm key, cool fill, a rim from behind and a tight spot on the
// face. The colours are FIXED — every light holds the same hue in every
// conversation state, so the room never changes temperature. Only intensity
// varies, per state and with her voice, which reads as her being lit more or
// less brightly rather than as the light changing colour.
// ---------------------------------------------------------------------------

/**
 * The one palette, used in every state and by both rigs. Set as JSX props in
 * AvatarScene and never touched afterwards, so no per-frame colour work
 * happens at all.
 *
 * `rim` and `kick` are the two backdrop halves thrown back onto the silhouette
 * edges: cyan down the camera-left shoulder and sleeve, a weaker green on the
 * camera-right edge. These are the only colours changed from the original rig
 * — key, fill, top and face keep their authored values, so the garment and
 * hair are lit exactly as before and only the outline picks these up.
 */
export const LIGHT_COLORS = {
  key: "#ffe4c9",
  fill: "#c9d6ff",
  rim: "#4fd8e8",
  kick: "#3fd39a",
  top: "#e8daf5",
  face: "#fff2e0",
};

/**
 * Where each light stands and how wide it throws. `intensity` here is only the
 * value the light mounts with — the frame loop immediately eases it toward the
 * per-state number in LIGHT_STATES, so moving one of these changes nothing you
 * can see. Move the per-state values instead.
 *
 * `castShadow` on the key is inert until <Canvas> is given `shadows`; it is
 * kept as the source scene had it.
 */
export const LIGHT_PLACEMENT = {
  /** Warm key, front-right and high. */
  key: { position: [2, 3, 2] as Vec3, intensity: 1.4 },
  /** Cool fill, opposite the key and behind. */
  fill: { position: [-2, 2, -1] as Vec3, intensity: 0.4 },
  /** Top wash from just in front of her. */
  top: { position: [0, 3, 1.5] as Vec3, angle: 0.4, penumbra: 1, intensity: 0.9 },
  /**
   * CYAN RIM, behind and camera-left — the bright blue edge running down the
   * shoulder and sleeve. Behind her, so it catches the silhouette only and
   * never reaches the front of the garment.
   */
  rim: { position: [-2.2, 2.2, -1.8] as Vec3, angle: 0.7, penumbra: 0.9, intensity: 1.4 },
  /**
   * GREEN KICK, behind and camera-right — the weaker counterpart from the
   * green half of the backdrop, on the dupatta side.
   */
  kick: { position: [2.4, 2.0, -1.6] as Vec3, angle: 0.7, penumbra: 0.9, intensity: 0.8 },
  /**
   * Tight face spot. Where it AIMS is per-rig (`headTargetY` below), because
   * the two faces sit at different heights.
   */
  face: {
    position: [0, 2.2, 1] as Vec3,
    angle: 0.18,
    penumbra: 0.6,
    intensity: 1.6,
    distance: 1.6,
    decay: 2,
  },
};

export interface LightState {
  key: number;
  fill: number;
  rim: number;
  kick: number;
  top: number;
}

/**
 * How bright each light is in each conversation state. Colours are
 * deliberately absent: the rig keeps one palette throughout, so a state change
 * only moves brightness.
 *
 * This repo's AvatarState happens to use the same four names as the source
 * scene's conversationState, so the presets map across 1:1.
 */
export const LIGHT_STATES: Record<AvatarState, LightState> = {
  idle: { key: 1.4, fill: 0.4, rim: 2, kick: 5, top: 0.9 },
  listening: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.1 },
  thinking: { key: 1.2, fill: 0.5, rim: 2, kick: 5, top: 0.8 },
  speaking: { key: 1.8, fill: 0.5, rim: 2, kick: 5, top: 1.2 },
};

/**
 * How much the smoothed 0..1 voice amplitude adds on top of the state's
 * brightness, per light — the rig breathes with her voice. The fill and top
 * lights take none, so the lift reads on the key and on her outline rather
 * than as the whole image pulsing.
 */
export const VOICE_BOOST = { key: 0.4, rim: 0.5, kick: 0.3 };

/**
 * Per-frame approach rate toward whatever the lights are heading for — the
 * active state, the voice lift, and the theme's lighting below. Slow enough
 * that a change takes about a second to land. Bigger is faster.
 */
export const LERP_SPEED = 0.04;

/**
 * The reflection panels. An <Environment> with no `background` prop draws
 * nothing, so these only ever show up as reflections in skin and cloth — the
 * kiosk artwork behind the canvas stays visible.
 */
export const ENVIRONMENT = {
  resolution: 256,
  lightformers: [
    { intensity: 2, position: [0, 2, 3] as Vec3, scale: [4, 1, 1] as Vec3, color: "#ffe0cc" },
    { intensity: 1, position: [-3, 1, -1] as Vec3, scale: [3, 2, 1] as Vec3, color: "#c9d6ff" },
    { intensity: 0.5, position: [3, 0, -2] as Vec3, scale: [2, 3, 1] as Vec3, color: "#ffd6e0" },
  ],
};

// ---------------------------------------------------------------------------
// SHARED — THE THEME'S PART OF THE RIG
// ---------------------------------------------------------------------------

/**
 * The theme-dependent part of the light rig, applied on top of the per-state
 * brightness above and eased toward on a theme switch. Every rig carries one
 * of these per theme (see RIG_TUNING).
 */
export interface ThemeLighting {
  /** Renderer tone-mapping exposure — lifts everything, highlights included. */
  exposure: number;
  /** Ambient light intensity — lifts the shadows, flattening the contrast. */
  ambient: number;
  /** Multiplier on the cool fill light's per-state intensity. */
  fill: number;
  /** Strength of the environment reflections (scene.environmentIntensity). */
  environment: number;
}

/**
 * The rig exactly as it was authored, before the light theme existed. The
 * female presenter still uses it unchanged on the dark theme; it is also what
 * the ambient light mounts with, and the baseline any new rig should start
 * from.
 */
export const DARK_LIGHTING: ThemeLighting = { exposure: 1, ambient: 0.3, fill: 1, environment: 1 };

// ---------------------------------------------------------------------------
// PER RIG
// ---------------------------------------------------------------------------

/**
 * Everything about one presenter's look: how the shot is framed on her or him,
 * what the materials need correcting to, and how the studio is lit for that rig
 * on each theme.
 *
 * models.ts merges this into AvatarConfig, so every field here is reachable as
 * `config.<field>` wherever a rig is in hand.
 */
export interface RigTuning {
  /** Height in metres, used to frame the shot until the rig reports its real one. */
  fallbackHeight: number;
  /**
   * Horizontal squeeze applied to the render, as a width multiplier: omitted
   * (or 1) is true proportions, 0.93 draws everything 7% narrower. An
   * anamorphic "slimming" trick — a real lens cannot do this (see CAMERA.lensMm
   * above). It narrows the face as much as the body, so keep it close to 1.
   */
  widthSqueeze?: number;
  /** World Y the face spot aims at — the centre of this rig's face. */
  headTargetY: number;
  /**
   * Materials textured with skin, which get the emissive lift. Read off each
   * glTF's baseColorTexture rather than guessed from the names.
   */
  skinMaterials: Set<string>;
  /**
   * How much to lift the skin materials above, as an emissive term driven by
   * their own base colour texture (see AvatarModel's material pass).
   *
   * Per-rig because it is a function of the rig's albedo, not of the scene: the
   * lift is proportional to the texture it samples, so the same number does
   * visibly different amounts of work on two different skin tones.
   */
  skinEmissive: number;
  /**
   * Roughness to force on the skin materials, or null to keep what the export
   * authored.
   *
   * Only set this where the export omitted `roughnessFactor`, which glTF
   * defaults to 1.0 — fully rough, so the surface takes a broad even sample of
   * the environment with no specular highlight.
   */
  skinRoughness: number | null;
  /**
   * Per-material albedo scale, by material name — `color.multiplyScalar` on
   * load. Empty for a rig that needs none.
   *
   * This is what actually matches one rig's exposure to another's under the one
   * shared light rig, and it is needed because the two exports were authored to
   * different albedo levels rather than because the scene lights them
   * differently. Measured off the base colour textures: male1's kurta is
   * 240/255 mean luminance against girl15's kameez at 185, and his skin is 175
   * against her 130.
   *
   * Roughness is the obvious suspect and is NOT the cause. male1 does omit
   * `roughnessFactor` on eight of its seventeen materials, so they load at
   * glTF's 1.0 default — but sweeping the garment from 0.2 to 1.0 and
   * re-rendering moves its mean luminance by two points out of the seventy that
   * separated the rigs. The albedo is the whole difference.
   */
  materialTint: Record<string, number>;
  /**
   * The material carrying painted-on makeup, or null for a rig with none. Only
   * set this where there is actually makeup to tone down: the pass reads the
   * texture back through a 2D canvas, which is not free.
   */
  faceMaterial: string | null;
  /**
   * Alpha cut for a transparent card, by material name, overriding the default
   * AvatarModel picks from the card's base colour. Only needed where that guess
   * is wrong — see the alphaTest block there.
   */
  alphaTest?: Record<string, number>;
  /**
   * Roughness to force on a NON-skin material, by name — skinRoughness already
   * covers the skin. Set it only where the export omitted `roughnessFactor` and
   * so loads at glTF's fully matte 1.0.
   */
  materialRoughness?: Record<string, number>;
  /**
   * Specular reflection strength to force on a material, by name — 1 is the
   * physical default, and anything above it reflects more light than arrives.
   *
   * The male rig's hair needs this: the export authors
   * `KHR_materials_specular.specularColorFactor [2, 2, 2]`, double strength, on
   * a near-black base colour (0.047) with a clearcoat over it. Black hair has
   * almost no diffuse of its own, so that doubled highlight IS what you see —
   * every lamp in the rig reads as a bright sheen down the sides of his head.
   * Nothing about the light rig causes it, and turning the back lights down
   * does not touch it (measured: the cyan rim at 0 changes his hair by under
   * half a level out of 255).
   */
  materialSpecular?: Record<string, number>;
  /** A2F weight calibration, or null for a rig with no morphs to calibrate. */
  a2f: { gain: number; shapeGains: Record<string, number> } | null;
  /**
   * Uniform scale on both wrist bones — hands and fingers together, with the
   * wrist itself staying put. 1 leaves the rig as authored. See AvatarModel's
   * HAND SCALE block for how it survives the animation.
   */
  handScale: number;
  /**
   * Multipliers on the two back lights (cyan rim, green kick) for this rig, in
   * both themes. 1 leaves them at the per-state intensity in LIGHT_STATES.
   *
   * Per-rig because what the edge light lands ON differs: the back lights are
   * meant to catch the silhouette of cloth, and how hot they read depends
   * entirely on the material at the edge. The male rig's hair is the case that
   * needs this — it authors metalness 0.755 with clearcoat (see alphaTest
   * below), so a spot aimed at his outline mirrors straight back off it and the
   * black hair lights up at the sides, which never happens on her matte hair.
   *
   * Only `rim` (the cyan one, camera-left) is dialled back today: it sits
   * higher and further forward than the kick, so it is the one that reaches his
   * hair. The green kick stays at 1 on both rigs.
   */
  backLight: { rim: number; kick: number };
  /**
   * The light rig under the light theme. The light backdrop is near-white, so a
   * rig lit for the dark one reads as a dark cut-out against it. Per-rig
   * because the two albedos differ (see materialTint) and so need different
   * amounts of lift.
   */
  lightThemeLighting: ThemeLighting;
  /**
   * The light rig under the dark theme. The female rig keeps DARK_LIGHTING
   * unchanged — she is what it was tuned against.
   */
  darkThemeLighting: ThemeLighting;
}

export const RIG_TUNING: Record<AvatarId, RigTuning> = {
  // -------------------------------------------------------------------------
  // girl15.glb — the original MARI presenter, and the rig every shared value
  // above was tuned against. Where a number here looks like it is doing
  // nothing, that is why: she is the baseline, and the male rig is matched to
  // her rather than the other way round.
  // -------------------------------------------------------------------------
  female: {
    fallbackHeight: 1.68,
    headTargetY: 1.45,
    skinMaterials: new Set(["lambert11", "lambert13", "lambert12"]),
    // The original value, from when this was a module constant — she is the rig
    // it was tuned against, so it stays exactly as it was.
    skinEmissive: 0.25,
    // Her skin declares roughnessFactor 0.5 in the glTF; nothing to correct.
    skinRoughness: null,
    // She is the rig the other is matched TO, so nothing is scaled here and her
    // appearance is exactly what it was before male1 existed.
    materialTint: {},
    faceMaterial: "lambert12",
    a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
    handScale: 1,
    // Her hair is matte, so the back lights do on her exactly what they were
    // tuned to do. Nothing to scale.
    backLight: { rim: 1, kick: 1 },
    // Lifted over the first light-theme pass (exposure 1.2, ambient 0.6, fill
    // 1.8): ambient carries most of it, so the gain lands on the shaded side of
    // her face and the folds of the kameez rather than on the whole image.
    lightThemeLighting: { exposure: 1.35, ambient: 0.9, fill: 2.3, environment: 1.3 },
    // The authored rig, unchanged.
    darkThemeLighting: DARK_LIGHTING,
  },

  // -------------------------------------------------------------------------
  // male_inital12.glb — the facial-bone rig (302 nodes) with the dark head repaint
  // back. What changed against the earlier exports, and which of the numbers below
  // answer to it, is in the MALE comment in models.ts, next to the clip windows the
  // same export decides.
  // -------------------------------------------------------------------------
  male: {
    // Measured off the rig: HeadEnd sits at 1.784 against girl15's 1.616 (and
    // male1's 1.783 — same skeleton, same proportions).
    fallbackHeight: 1.85,
    // Reads slimmer, closer to the artist's Blender render: the clasped-hands
    // idle pushes his elbows and sleeves out, which no lens choice changes.
    widthSqueeze: 0.93,
    // Girl15's 1.45 sits 0.029 below her Head_M joint (1.479); this is the same
    // offset below this rig's, at 1.632.
    headTargetY: 1.6,
    // The head skin is `lambert5` here, NOT the `Std_Skin_Head` male1 named it:
    // this export renames the head material while keeping Std_Skin_Arm/Leg. On
    // male2 its texture was the one male1's head used; male3 repaints it — see
    // the lambert5 note in materialTint below.
    skinMaterials: new Set(["lambert5", "Std_Skin_Arm", "Std_Skin_Leg"]),
    // Was 0: the lift used to erase his shading rather than reveal it (a hard
    // bright band across the forehead and nose at 0.10, measured p95 169
    // against her 150). Nudged back up now that the light theme needs him
    // brighter without pushing the kurta's highlight any further — watch that
    // same forehead band if this goes higher than 0.08.
    skinEmissive: 0.08,
    // null, unlike male1's 0.5. That override existed because male1 omitted
    // roughnessFactor on its skin and so loaded at glTF's 1.0 default; this
    // export authors 0.553 on all three skin materials (and a real value on
    // every other material too), so there is nothing left to correct and forcing
    // 0.5 would just overwrite what the artist set.
    //
    // male_inital04 and 05 drop roughnessFactor on lambert5 (the head), so it
    // would load at glTF's fully rough 1.0 default. 0.5 is what 03 authored on
    // the head; it also moves the arms and legs from 0.553 to 0.5, which is not
    // visible.
    // null again: 09 authors 0.5 on lambert5 and 0.553 on the arm and leg skin.
    // The 0.5 here existed only because 05-08 omitted roughnessFactor on the head.
    skinRoughness: null,
    // Scaled to bring this export's albedo onto the female rig's level under the
    // shared lights — see materialTint. The two garment entries are one texture
    // on two meshes (kurta and shalwar). Verified by rendering both rigs through
    // an identical rig: garment mean luminance 138 against her 134 (was 170),
    // face p95 147 against her 150 (was 169).
    // Carried over from male1 unchanged, because the albedo is: measured off this
    // export's own textures, skin is 175/180/178 mean luminance (male1: 175/180/
    // 178) and the garment 240 (male1: 240), against girl15's skin 130 and kameez
    // 185. Same textures, same correction. The garment is one material here
    // (`pasted__pasted__lambert6`) rather than male1's two meshes sharing one.
    //
    // male3's head texture is the exception, and its 0.85 is kept ON PURPOSE. The
    // repaint is darker (121 whole-texture mean, down from 175), and rendered
    // through the same lights his face now sits at mean 103 / p95 142, against
    // male2's 128 / 173 and girl15's 121 / 166. Raising lambert5 to ~1.03 would put
    // it back on male2's level, but that would paint out the artist's change
    // rather than correct an export fault, and on screen the darker face reads
    // naturally against his hands. That is the one number to move if it should not.
    materialTint: {
      "pasted__pasted__lambert6": 0.62,
      "lambert5": 0.95,
      "Std_Skin_Arm": 0.95,
      "Std_Skin_Leg": 0.95,
    },
    // No makeup on this rig — the pass would read back a texture to change nothing.
    faceMaterial: null,
    // male_inital06's hair is authored pure black (05 had it at 0.02 grey), which
    // AvatarModel's colour test reads as a mask card and cuts at 0.35 — that drops
    // 21% of the texture's visible texels against 4.2% at this cut, taking the soft
    // strands along the front hairline with it. The hair mesh and its opacity
    // texture are unchanged from 05, so this is the cut 05's hair actually got.
    // Re-keyed for 09, which names the hair material `standardSurface2` again
    // (08 called it `standardSurface2.001`). Still needed: the hair is authored
    // near-black (0.0005), which AvatarModel's colour test reads as a mask card
    // and would cut at 0.35 — 21% of the opacity texture's visible texels against
    // 4.2% here, which is what ate the front hairline when 06 first went black.
    // Keyed to 12's hair material name — the exports keep flipping between
    // `standardSurface2` and `standardSurface2.001`, and a key that misses is
    // silent. 12 authors the hair at 0.047 rather than near-black, so
    // AvatarModel's colour test would reach this same 0.08 on its own; the entry
    // stays because the cut is what we actually want, not a side effect of a
    // colour, and because 06 and 08 both shipped the hair black enough to take
    // the 0.35 mask cut, which ate 21% of the opacity texture's visible texels
    // and with them the front hairline.
    alphaTest: { "standardSurface2.001": 0.08 },
    // The kurta and shalwar (one material, two meshes). male_inital05 and 06 ship
    // it with no roughnessFactor at all, so it loads at glTF's fully matte 1.0 and
    // returns no specular — which is most of how the cyan rim and green kick show
    // up as coloured edges on cloth, so on those exports he lost the back lighting
    // the female rig has. 0.5 is what male_inital03 authored on this same material
    // and what girl15's kameez carries. Diffuse shading, and so his skin and the
    // garment's overall brightness, are untouched by this.
    // No override: 09 authors roughness 0.5 on the kurta, where 05-08 omitted it
    // and so loaded fully matte at glTF's 1.0 default. That default is what cost
    // him the cyan rim and green kick as coloured edges on cloth, and 0.5 is both
    // what this export now sets and what girl15's kameez carries — so there is
    // nothing left to correct and forcing a value would overwrite the artist's.
    // The export's own 0.2 is kept: it is what makes his hair read as hair
    // rather than felt. The sheen it was catching is handled by the specular
    // override below instead.
    materialRoughness: {},
    // TEST
    materialSpecular: { "standardSurface2.001": 0.6 },
    // The female rig's calibration, unchanged. It is a property of what the NIM
    // emits (JawOpen peaking past 2.5 while the lip shapes sit under 1) far more
    // than of the rig, and these two rigs carry the same authored blendshapes at
    // the same amplitudes — the jawOpen delta here is 0.027 against her 0.025.
    // Worth a look on screen even so; ?a2fGain= and ?a2fShapes= retune it live.
    a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
    // 1 = the hands as authored. Measured off male_inital05, they are 11.3% of his
    // height long and 7.6% wide, against the female rig's 10.4% and 6.4%, and the
    // camera enlarges them further because they are held in front of his face.
    // Lower this (0.9 or so) to shrink them; much below 0.85 the wrist starts to
    // show a step at the cuff.
    handScale: 1,
    // The cyan rim pulled back off his hair; the green kick left alone.
    backLight: { rim: 0, kick: 0 },
    // Brighter in the shadows than the shared rig on both themes: the lift sits
    // mostly in ambient and fill, so what opens up is the shaded side of his
    // face, his beard and the folds of the kurta rather than the whole image.
    // Lifted here from exposure 1.35 / ambient 0.65 / fill 2.1, the same way her
    // light-theme entry was. Exposure is the one to back off first if the cloth
    // flattens: the lit side of the kurta is 240/255 albedo before the tint
    // above, and it is the brightest thing in the shot.
    lightThemeLighting: { exposure: 1.3, ambient: 0.95, fill: 2.6, environment: 1.3 },
    darkThemeLighting: { exposure: 1, ambient: 0.45, fill: 1.35, environment: 1 },
  },
};
