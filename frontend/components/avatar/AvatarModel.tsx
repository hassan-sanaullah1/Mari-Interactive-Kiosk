"use client";

/**
 * The MARI presenter — either rig, driven by the config it is handed.
 *
 * Everything that differs between the two presenters lives in ./models.ts (loop
 * windows, material names, whether the rig has blendshapes at all); everything
 * in this file is the machinery they share. The notes below were written
 * against girl15.glb, which is still the default, and remain the reference for
 * how that rig's numbers were arrived at — see models.ts for male2.glb's.
 *
 * Ported from the working implementation (THREEJS_A2F_INTEGRATION.md §4/§5/§9).
 *
 * The mouth is driven by Audio2Face ONLY — no visemes, no mapping layer. This
 * rig makes that possible: its 51 morph targets carry the ARKit blendshape
 * names verbatim, which is exactly what A2F-3D emits, so a2fMorphs matches them
 * 1:1 by name and A2F's authored weights reach the mesh untouched. When A2F
 * sends nothing the mouth returns to rest; there is no fallback mouth animation
 * by design.
 *
 * The morphs live on a single glTF mesh ("Mesh.001") with 11 primitives — head,
 * brows, eyes, upper/lower teeth, tongue, eyelashes, arms, legs, nails — and
 * every primitive carries all 51 targets. three.js splits that into 11
 * SkinnedMeshes, so the traverse below picks up all of them and the teeth and
 * tongue move with the lips instead of staying frozen inside an open mouth.
 *
 * This rig succeeded girl11 through girl14. Its face is literally theirs — all
 * 561 morph target accessors are byte-identical to girl11's, under identical
 * names — so everything the mouth does ports across untouched. It keeps
 * girl14's baked cloth simulation (975 `a_cloth_parent_vtx_*_JNT` joints on a
 * second skin, ~10x the animated nodes of the rigs before it), which is what
 * the loop windows below have to account for.
 *
 * Against girl14 this is a re-skin and nothing more: the animation is identical
 * to 4e-6 (float rounding) channel for channel, the rig scale and the cloth sim
 * are unchanged, and only the material NAMES moved (eyelashes → lambert14,
 * brows → lambert15, brow_base → lambert13). The material pass below keys off
 * baseColorFactor and alphaMode rather than those names, so it is unaffected —
 * but that is the thing to re-check first if the eyes ever haze over again.
 * The windows below were still re-derived against this clip and came back
 * unchanged, so they are its own optimum rather than inherited numbers.
 *
 * The shipped girl15.glb is the output of scripts/optimize_glb.py rather than the
 * raw export: keyframes outside its three loop windows (./models.ts) are stripped, the
 * morph-target NORMAL deltas are dropped and the cloth rotations are stored as
 * normalized int16, taking it from 56MB to 30MB (37MB to 20MB over the wire, where
 * it is the single largest thing the kiosk downloads).
 * Everything this file relies on is bit-identical across that transform — verified
 * through three.js on every playable frame: all 51 ARKit morph names and their
 * POSITION deltas, and all 1083 bone world matrices. Two consequences worth
 * knowing: those windows are now load-bearing for the ASSET and not just for playback,
 * so widening a window here without re-running the script seeks into keyframes
 * that are no longer in the file; and a re-export has to go back through the
 * script or the file silently returns to 56MB.
 *
 * girl12.glb shipped with its morph NAMES shifted one place against that same
 * geometry, which drove every named morph onto its neighbour's shape — one eye
 * blinking, and jawOpen quietly driving mouthClose. girl15 is correct (checked:
 * the list matches girl11's, and the eyeBlink pair is mirror-symmetric), but
 * nothing about that failure points at the name list, so the check below keeps
 * watching for it.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useAnimations, useGLTF } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { fetchAvatar, releaseAvatar } from "@/lib/avatarFetch";
import { applyA2FLipsync, createA2FMorphState } from "@/lib/a2fMorphs";
import { setRigCalibration } from "@/lib/blendshapePlayer";
import type { AvatarState } from "./state";
import {
  CLIP_NAME,
  FPS,
  type AvatarConfig,
  type BodyState,
  type Segment,
} from "./models";

// ---------------------------------------------------------------------------
// Body animation — clip "CINEMA_4D_Main", 902 frames @ 30 fps (30.0s), holding
// three hand-authored segments concatenated on one timeline:
//   0–38    a dead hold at the head of the clip, skipped entirely
//   38–245  breathing  (at-rest idle, a clean 60-frame cycle)
//   245–393 listening  (hands rise at ~245–300, then a settled listening pose)
//   393–893 talking    (gesturing; the last ~10 frames run past the loop)
// The loop windows are trimmed inside those segments to land on frames whose
// pose actually matches at both ends, so the loop seam has nothing to hide.
//
// The boundaries were measured off this clip's own curves. Per-frame motion
// locates the segment breaks; the loop ends are then the frame pair with the
// smallest pose distance inside each segment. Two distances, because this rig
// animates two things that loop differently:
//
//   BODY — 110 skeleton joints, compared by summed quaternion angle. Rotations
//   only: the skeleton is authored in centimetres under a 0.01-scaled root, so
//   including translations would just weight this rig's units against it. Body
//   motion averages 0.061 per frame and peaks at 0.554.
//
//   CLOTH — the 975 baked simulation joints, as mean per-joint displacement.
//   A baked sim does not repeat, so unlike the body it never matches exactly at
//   any seam; the useful question is how many frames of ordinary cloth motion
//   (0.038 units) the seam is worth, since the crossfade has to absorb that.
//
// Optimising body alone would have picked girl12's windows, which cost 4 and 51
// frames of cloth drift; minimising cloth subject to a tight body match instead
// costs 1 and 29. The talking seam is the one that cannot be made cheap — no
// window in that segment does better than ~29 frames — so its cloth reconciles
// at roughly 3x normal speed across the 0.35s crossfade. That reads as fabric
// settling, not as a pop, and it is the best the authored clip offers.
//
// The cloth also needs the first ~120 frames to settle out of its rest state
// (per-frame motion 0.085 at frame 40, 0.027 by frame 119), which is the other
// reason the breathing loop starts where it does rather than at the first
// frame the body is willing to loop from.
// ---------------------------------------------------------------------------
// FPS, CLIP_NAME, BodyState and Segment are shared with the registry — see
// ./models.ts, which is where each rig's own windows are measured and kept.

/**
 * A looping window of the clip, and nothing else.
 *
 * The wrist distances quoted below were measured on girl15's clip by driving
 * the layer pool through every transition and reading Wrist_L/Wrist_R apart in
 * world space. girl14 and girl15 are animation-identical (6.8e-7), so they
 * hold for both.
 *
 * There used to be an `intro` here — an authored lead-in played once on entry
 * when arriving from a particular other segment — and it was the glitch. The
 * talking intro (frames 393–558, "settle into gesturing") is animated as an
 * entrance from a pose with the arms already down and open, so playing it on
 * the way out of listening, where the hands are held together, threw them out
 * to the sides first and brought them back: measured on the wrists, they went
 * from 0.119m apart to a peak of 0.481m before settling at 0.159m. Entering
 * the talking loop directly at its closest-matching frame instead peaks at
 * 0.389m against an endpoint of 0.353m — a 0.035m overshoot that is the
 * gesture's own opening rather than an artefact, and a 9x reduction in the
 * spread the intro was causing.
 *
 * An authored outro exists too (frames 870–892, the arms lowering back to
 * rest, landing within 0.0013 of the listening loop's start pose) and is not
 * used for the same reason in reverse: it can only be entered cleanly from
 * loop frame 698, and either waiting up to a 7.3s lap to reach that frame or
 * crossfading into it from elsewhere costs more than it saves. Crossfading in
 * measured 0.0995m of wrist spread against 0.0062m for going direct.
 */
// The Segment type itself, and each rig's windows, live in ./models.ts.
//
/** Crossfade (s) hiding a loop seam — both ends are near-identical poses. */
const LOOP_XFADE_SECS = 0.35;
/**
 * Crossfade (s) when switching segments.
 *
 * The same length as a loop seam, not longer. Blending two poses moves every
 * joint along its own shortest arc, all at once, and the arms are the joints
 * with the furthest to travel — so a longer fade does not soften the change,
 * it gives the hands more time to swing wide of both poses on the way. Measured
 * on the wrists, entering talking: 0.35s peaks 0.001m INSIDE the endpoints
 * (they close without ever parting), 0.55s overshoots by 0.006m, 0.8s by 0.027m
 * and 1.1s by 0.051m. Since `bestLoopEntry` already picks the closest frame in
 * the target loop, there is not much left to hide, and the shortest fade that
 * still reads as a blend rather than a cut is the one that hides it best.
 */
const SWITCH_XFADE_SECS = 0.35;

/**
 * How long the conversation must stay out of "speaking" before the body drops
 * out of the talking segment. Without it the arms twitch between consecutive
 * sentences of the same reply.
 */
const TALK_EXIT_DEBOUNCE_MS = 250;

const bodyStateFor = (state: AvatarState): BodyState => {
  if (state === "speaking") return "talking";
  // "thinking" sits between the user finishing and MARI replying — the
  // attentive listening pose is the right one to hold through it.
  if (state === "listening" || state === "thinking") return "listening";
  return "breathing";
};

/**
 * A2F weight gain for this rig, and a per-shape trim on top of it.
 *
 * Measured against this deployment's NIM (audio2face-3d:2.0) rather than
 * inherited: over a couple of real Urdu TTS sentences it emits
 *
 *   JawOpen          max 2.53   p95 1.48   mean 0.42   <- NOT normalised to 1
 *   MouthRollUpper   max 0.91   p95 0.69
 *   MouthPucker      max 0.56              MouthFunnel  max 0.38
 *   MouthLowerDown*  max 0.36              MouthClose   max 0.33
 *
 * JawOpen runs far past 1.0 while every other mouth shape sits below it, so the
 * two need opposite treatment. The source repo's calibration (0.55 global,
 * jawOpen trimmed to 0.3 of that = 0.165 effective) held the jaw's p95 at 0.24
 * — with all the other shapes at 0.55 of already-small values, the result read
 * as murmuring rather than speaking. So:
 *
 *   - global gain up to 0.9, which brings the lip shapes into a visible range
 *     (MouthRollUpper p95 -> 0.62, MouthPucker peak -> 0.51)
 *   - jawOpen trimmed to 0.375 of that (0.3375 effective), putting its p95 at
 *     ~0.50 and its peak at ~0.85 — an open vowel that reads as speech and a
 *     loudest-syllable peak that stops short of a gape, with no clipping
 *     against the [0,1] clamp in a2fMorphs.
 *
 * Still empirical, and still worth re-checking against a different NIM build or
 * a different rig. Tune live with ?a2fGain= / ?a2fShapes=jawopen: — the query
 * string overrides both.
 */
// The numbers are per-rig (`a2f` in ./models.ts); girl15's are 0.9 with jawOpen
// trimmed to 0.375 of that, and a rig with no morphs has none at all.

/**
 * Horizontal placement. The rig's origin is already its visual centreline, so
 * it sits at 0 — the source scene's 0.08 nudge was for a camera that was not
 * centred on the model, which is not the case here. Vertical placement is NOT
 * offset either: the scene frames the model from its measured bounding box
 * rather than assuming a height (see AvatarScene), so she stands at y = 0.
 */
const AVATAR_POSITION_X = 0;

/**
 * Skin-only brightening.
 *
 * The scene's light rig is shared by everything in frame, so raising it lifts
 * the kameez and the hair along with her. These three materials are the only
 * ones textured with skin (checked against the glTF: lambert11 carries
 * Head_Diffuse, lambert13 Arm_Diffuse, lambert12 Leg_Diffuse), so lifting them
 * here leaves the garment materials (Kameez:lambert2/3, lambert10), the hair
 * (pasted__lambert2) and every eye/teeth/lash card exactly as authored.
 *
 * Legs are included for consistency of skin tone even though this framing
 * usually crops them — a visible forearm and an invisible shin should not be
 * different colours if the shot ever widens.
 */
// Per-rig, as `skinMaterials` in ./models.ts: girl15's lambert11/12/13 and
// male2's lambert5/Std_Skin_Arm/Std_Skin_Leg.

/**
 * How much to lift skin, as an emissive term.
 *
 * Emissive rather than a brighter light because it is per-material: a light
 * bright enough to do this to the face would also blow out the white kameez
 * right next to it. The emissive map is the base colour texture itself, so the
 * lift follows the skin's own tone and shading detail instead of washing it to
 * a flat colour — pores, lips and nail beds keep their relative values, the
 * whole surface just sits higher.
 */
// Per-rig now, as `skinEmissive` in ./models.ts: the lift is proportional to
// the texture it samples, so one number cannot serve two skin tones. girl15
// keeps the 0.25 this constant held; male2 takes 0, because his albedo is
// already bright enough that the term erased his shading instead of revealing
// it. See that field for the measurements.

/**
 * Materials whose albedo has already been scaled by `materialTint`.
 *
 * The scale is in-place on a material that drei's glTF cache hands back across
 * an unmount, so without this guard every presenter switch would darken the
 * same material again.
 */
const tintedMaterials = new WeakSet<THREE.Material>();

/**
 * Which material carries the face — and therefore the makeup.
 *
 * Read off the glTF, not the material names: lambert12 is the material whose
 * baseColorTexture resolves to Head_Diffuse. (The neighbouring comment on
 * SKIN_MATERIALS has this backwards — it credits lambert11 with the head, but
 * lambert11 samples Arm_Diffuse and lambert12 the head. Verified against the
 * file's texture/image indices.)
 */
// Per-rig, as `faceMaterial` in ./models.ts — null for a rig with no makeup,
// which skips the read-back below entirely.

/**
 * How much chroma to remove from the makeup. 0 = texture as authored,
 * 1 = the made-up pixels go fully grey. This is the dial.
 *
 * 0.45 takes the lipstick from a saturated red to a muted rose and softens the
 * cheek flush, while leaving skin tone where it was. Raise for a barer face,
 * lower to keep more of the original makeup.
 */
const MAKEUP_DESATURATION = 0.20;

/**
 * The makeup separates from skin by HUE, not by saturation.
 *
 * Measured on Head_Diffuse: saturation is nearly uniform across the whole face
 * (median 0.44, p95 0.48), so a global desaturation washes the skin out just as
 * much as the lips and reads as "no difference" on the thing you wanted
 * changed. But of the chromatic pixels, 86% sit at hue 20-30° — the orange-tan
 * skin base — and the makeup is the red/pink tail below 20°. Keying on that
 * tail hits the lips and cheeks and almost nothing else.
 *
 * The face-region box excludes the garment and hair blocks parked in the
 * corners of the same UV sheet, which are also deep red and would otherwise be
 * caught by the hue test.
 */
const MAKEUP_MAX_HUE_DEG = 20;
const MAKEUP_MIN_SATURATION = 0.22;
const FACE_UV_BOX = { x0: 0.12, x1: 0.88, y0: 0.05, y1: 0.72 };

/** Hue in degrees and saturation, from 0-255 RGB. Value is not needed. */
function hueSaturation(r: number, g: number, b: number): [number, number] {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return [0, 0];

  let hue: number;
  if (max === r) hue = ((g - b) / delta) % 6;
  else if (max === g) hue = (b - r) / delta + 2;
  else hue = (r - g) / delta + 4;
  hue *= 60;
  if (hue < 0) hue += 360;

  return [hue, max === 0 ? 0 : delta / max];
}

/**
 * Textures this pass has already produced, tracked at module scope so it
 * survives across effect re-runs (and across component instances sharing the
 * same three.js scene/texture objects — R3F's glTF cache keeps them alive
 * when a model is swapped out and back). Without this, re-running the effect
 * would desaturate an already-desaturated texture, and repeated model
 * switches would walk the lipstick to black.
 */
const MAKEUP_TONED = new WeakSet<THREE.Texture>();

/**
 * Tone the painted-on makeup down, once, on the CPU.
 *
 * Done on a canvas copy rather than through a shader hook so it survives every
 * material recompile and needs no patched program: the result is just another
 * texture. Each matching pixel is pulled toward its own Rec. 709 luminance, so
 * it loses chroma without changing brightness — the lips get less red, not
 * darker. The strength ramps with how red and how saturated the pixel is, so
 * the treated area feathers into the skin instead of leaving a hard edge.
 *
 * Returns null if the image is not decoded yet or 2D canvas is unavailable, in
 * which case the caller leaves the original texture alone.
 */
function desaturateMakeup(
  source: THREE.Texture,
  amount: number,
): THREE.Texture | null {
  const image = source.image as HTMLImageElement | ImageBitmap | null;
  if (!image || !image.width || !image.height) return null;

  const canvas = document.createElement("canvas");
  canvas.width = image.width;
  canvas.height = image.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.drawImage(image as CanvasImageSource, 0, 0);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const px = data.data;

  for (let i = 0; i < px.length; i += 4) {
    const pixel = i / 4;
    const u = (pixel % canvas.width) / canvas.width;
    const v = Math.floor(pixel / canvas.width) / canvas.height;
    if (u < FACE_UV_BOX.x0 || u > FACE_UV_BOX.x1) continue;
    if (v < FACE_UV_BOX.y0 || v > FACE_UV_BOX.y1) continue;

    const r = px[i];
    const g = px[i + 1];
    const b = px[i + 2];
    const [hue, sat] = hueSaturation(r, g, b);
    if (hue >= MAKEUP_MAX_HUE_DEG || sat <= MAKEUP_MIN_SATURATION) continue;

    const redness =
      Math.min(1, (MAKEUP_MAX_HUE_DEG - hue) / MAKEUP_MAX_HUE_DEG) *
      Math.min(1, (sat - MAKEUP_MIN_SATURATION) / 0.15);
    const keep = 1 - amount * redness;

    const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    px[i] = luma + (r - luma) * keep;
    px[i + 1] = luma + (g - luma) * keep;
    px[i + 2] = luma + (b - luma) * keep;
  }
  ctx.putImageData(data, 0, 0);

  const result = new THREE.CanvasTexture(canvas);
  // Copy the sampler settings off the original: the glTF loader has already set
  // the flipY and colour space the UVs were authored against, and a fresh
  // CanvasTexture defaults differently on both counts.
  result.flipY = source.flipY;
  result.colorSpace = source.colorSpace;
  result.wrapS = source.wrapS;
  result.wrapT = source.wrapT;
  result.channel = source.channel;
  result.needsUpdate = true;
  return result;
}

/**
 * One layer of the crossfade pool.
 *
 * Three layers, not two. Two is enough for a plain A→B fade but not for a fade
 * that gets interrupted: with only two actions the incoming segment has to be
 * written onto a layer already carrying part of the visible pose, which snaps
 * the body (measured worst-case per-frame pose jump 0.083 with 2 layers vs
 * 0.0117 with 3; the clip's own motion peaks at ~0.0070). A pool lets an
 * interrupted fade run to zero while the new segment fades in on a free layer.
 * AnimationMixer normalises by cumulative weight, so partially-faded layers
 * blend correctly.
 */
interface Layer {
  action: THREE.AnimationAction | null;
  state: BodyState;
  time: number;
  weight: number;
  /** 1 for the incoming/current segment, 0 for anything fading out. */
  targetWeight: number;
  /** Weight units per second. */
  fadeRate: number;
}

const LAYER_COUNT = 3;

const makeLayer = (): Layer => ({
  action: null,
  state: "breathing",
  time: 0,
  weight: 0,
  targetWeight: 0,
  fadeRate: 0,
});

/**
 * Pose lookup built once from the clip's own rotation tracks.
 *
 * Entering a segment at a fixed frame only works when the clip has an authored
 * path from where the body actually is to that frame — true for the two intros
 * (breathing→listening, listening→talking) and false for every other pairing.
 * Coming back out of talking, or dropping to breathing, the fixed `loop[0]`
 * entry is an arbitrary pose against the one on screen, and the crossfade has
 * to invent the difference: at best it reads as a drift, at worst it snaps.
 *
 * So instead of a fixed entry, sample the skeleton once per frame of the clip
 * and, at transition time, enter the target loop at whichever frame is closest
 * to the pose being left. The crossfade then only ever has to cover a distance
 * we have already minimised, in every direction, including ones nobody
 * hand-tuned.
 *
 * Rotations only, summed as quaternion angle over the body joints — the same
 * measure each rig's loop windows were derived with (see ./models.ts), and
 * for the same reason: this rig is authored in centimetres under a 0.01-scaled
 * root, so translations would weight the rig's units against it. The 975 baked
 * cloth joints are skipped as well; a baked sim never repeats, so matching it is
 * not on offer, and including it would drown out the body signal we can act on.
 */
interface PoseIndex {
  /** Sample times, ascending, one per source frame. */
  times: Float32Array;
  /** Flat quaternions, 4 per joint per sample: [sample][joint][xyzw]. */
  quats: Float32Array;
  jointCount: number;
}

/** Body joints only — the baked cloth sim is excluded, see PoseIndex. */
const isClothTrack = (trackName: string): boolean => trackName.includes("a_cloth_parent_vtx_");

function buildPoseIndex(clip: THREE.AnimationClip): PoseIndex | null {
  const quatTracks = clip.tracks.filter(
    (track): track is THREE.QuaternionKeyframeTrack =>
      track instanceof THREE.QuaternionKeyframeTrack && !isClothTrack(track.name),
  );
  if (!quatTracks.length) return null;

  const sampleCount = Math.max(2, Math.round(clip.duration * FPS) + 1);
  const times = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i++) times[i] = Math.min(i / FPS, clip.duration);

  const jointCount = quatTracks.length;
  const quats = new Float32Array(sampleCount * jointCount * 4);

  // Interpolants evaluate a track at an arbitrary time exactly as the mixer
  // would, so these samples match what actually gets posed.
  quatTracks.forEach((track, joint) => {
    // Slerp for quaternions, matching how the mixer reads the same track.
    const interpolant = track.InterpolantFactoryMethodLinear(new Float32Array(4));
    for (let i = 0; i < sampleCount; i++) {
      const value = interpolant.evaluate(times[i]) as unknown as ArrayLike<number>;
      const base = (i * jointCount + joint) * 4;
      quats[base] = value[0];
      quats[base + 1] = value[1];
      quats[base + 2] = value[2];
      quats[base + 3] = value[3];
    }
  });

  return { times, quats, jointCount };
}

/** Nearest sample index for a time, clamped to the index. */
function sampleIndexFor(index: PoseIndex, time: number): number {
  const i = Math.round(time * FPS);
  return Math.min(Math.max(i, 0), index.times.length - 1);
}

/**
 * Summed rotation difference between a pose sample and an arbitrary quaternion
 * array of the same shape, as |dot| per joint.
 *
 * Quaternion dot is ±1 for identical rotations (double cover: q and -q are the
 * same orientation), so `1 - |dot|` is a cheap monotonic stand-in for the angle
 * between them. Monotonic is all this needs — the result is only ever compared
 * against other candidates, never read as an angle.
 */
function poseDistance(index: PoseIndex, sample: number, pose: Float32Array): number {
  const { quats, jointCount } = index;
  const base = sample * jointCount * 4;
  let total = 0;
  for (let joint = 0; joint < jointCount; joint++) {
    const a = base + joint * 4;
    const b = joint * 4;
    const dot = quats[a] * pose[b] + quats[a + 1] * pose[b + 1] + quats[a + 2] * pose[b + 2] + quats[a + 3] * pose[b + 3];
    total += 1 - Math.abs(dot);
  }
  return total;
}

/**
 * The pool's current pose, as one quaternion per body joint — what is
 * actually on screen, not any single layer's clock.
 *
 * A transition can itself be interrupted (talking→listening cancelled back to
 * talking by another mic click before the first crossfade finishes), and at
 * that moment the layer most recently handed to `beginSegment` may still be
 * near-zero weight while the pose on screen is dominated by whatever it was
 * fading out of. Matching against that layer's `time` alone picks an entry
 * frame for a pose nobody is looking at, which reintroduces the exact
 * hands-wide snap this whole mechanism exists to avoid — measured at up to
 * 0.26m of wrist overshoot, on par with not pose-matching at all. Weighting
 * every layer's sample by its actual on-screen contribution, the same way
 * AnimationMixer composites them, is what keeps an interrupted transition as
 * clean as an uninterrupted one.
 *
 * Weights need not sum to 1 (a layer's own fade may still be mid-flight); the
 * blend is renormalised by whatever they do sum to, same as the mixer.
 */
function blendedPoseSample(index: PoseIndex, layers: Layer[]): Float32Array | null {
  const { jointCount } = index;
  const out = new Float32Array(jointCount * 4);
  let weightSum = 0;
  for (const layer of layers) {
    if (layer.weight <= 0) continue;
    const sample = sampleIndexFor(index, layer.time);
    const base = sample * jointCount * 4;
    weightSum += layer.weight;
    for (let joint = 0; joint < jointCount; joint++) {
      const s = base + joint * 4;
      const o = joint * 4;
      // Align sign to the accumulator before adding — quaternion double cover
      // means a naive weighted sum can cancel two representations of the same
      // rotation instead of reinforcing them.
      const dot =
        out[o] * index.quats[s] +
        out[o + 1] * index.quats[s + 1] +
        out[o + 2] * index.quats[s + 2] +
        out[o + 3] * index.quats[s + 3];
      const w = dot < 0 ? -layer.weight : layer.weight;
      out[o] += index.quats[s] * w;
      out[o + 1] += index.quats[s + 1] * w;
      out[o + 2] += index.quats[s + 2] * w;
      out[o + 3] += index.quats[s + 3] * w;
    }
  }
  if (weightSum <= 0) return null;
  for (let joint = 0; joint < jointCount; joint++) {
    const o = joint * 4;
    const len = Math.hypot(out[o], out[o + 1], out[o + 2], out[o + 3]) || 1;
    out[o] /= len;
    out[o + 1] /= len;
    out[o + 2] /= len;
    out[o + 3] /= len;
  }
  return out;
}

/**
 * Where to enter `state`'s loop so the pose best matches `fromPose` — the
 * pool's actual blended pose, see `blendedPoseSample`.
 *
 * Searches the whole loop window rather than a neighbourhood of `loop[0]`: the
 * point is to find the genuinely closest pose, and these windows are only a few
 * hundred samples, once per transition.
 */
function bestLoopEntry(
  segments: Record<BodyState, Segment>,
  index: PoseIndex | null,
  state: BodyState,
  fromPose: Float32Array | null,
  /**
   * Seconds of the loop's tail to rule out. A self-crossfade at the seam is
   * looking for the pose it can *continue* from, and the closest match to the
   * frame it is standing on is that frame — which would enter at the seam it
   * is trying to leave and stall there. Rule out the tail and it lands at the
   * head of the loop, where the window was cut to match.
   */
  excludeTailSecs = 0,
): number {
  const [loopStart, loopEnd] = segments[state].loop;
  if (!index || !fromPose) return loopStart;

  const first = sampleIndexFor(index, loopStart);
  // Exclude the last sample: entering exactly at the loop end leaves no frames
  // to play before the seam crossfade fires.
  const last = Math.max(
    first,
    sampleIndexFor(index, loopEnd - excludeTailSecs) - 1,
  );

  let bestSample = first;
  let bestDistance = Infinity;
  for (let sample = first; sample <= last; sample++) {
    const distance = poseDistance(index, sample, fromPose);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestSample = sample;
    }
  }
  return index.times[bestSample];
}

/**
 * Hand the pool a new segment: it fades in on a free layer while every other
 * layer fades out. Picking a free layer (rather than reusing the one being
 * faded out of) is what keeps an interrupted fade from snapping.
 *
 * `entryTime` overrides the segment's default entry frame — that is how a
 * pose-matched transition gets in at the frame it picked.
 */
function beginSegment(
  segments: Record<BodyState, Segment>,
  layers: Layer[],
  activeIndexRef: { current: number },
  state: BodyState,
  fadeSecs: number,
  entryTime?: number,
): void {
  const activeIndex = activeIndexRef.current;
  let index = layers.findIndex(
    (layer, i) => i !== activeIndex && layer.weight <= 0.001 && layer.targetWeight <= 0,
  );
  if (index < 0) {
    // Three fades already in flight — recycle whichever contributes least, so
    // the unavoidable discontinuity lands on the least visible layer.
    let lowest = Infinity;
    for (let i = 0; i < layers.length; i++) {
      if (i === activeIndex) continue;
      if (layers[i].weight < lowest) {
        lowest = layers[i].weight;
        index = i;
      }
    }
  }

  const segment = segments[state];
  const incoming = layers[index];
  incoming.state = state;
  incoming.time = entryTime ?? segment.loop[0];
  incoming.weight = 0;
  incoming.targetWeight = 1;
  incoming.fadeRate = 1 / fadeSecs;
  if (incoming.action) incoming.action.time = incoming.time;

  for (let i = 0; i < layers.length; i++) {
    if (i === index) continue;
    layers[i].targetWeight = 0;
    layers[i].fadeRate = 1 / fadeSecs;
  }

  activeIndexRef.current = index;
}

/**
 * Advance one layer through its loop window. The loop end is clamped rather
 * than wrapped — a layer only reaches it while its replacement is already
 * fading in, and wrapping there would snap the pose behind the fade.
 */
function advanceLayer(
  segments: Record<BodyState, Segment>,
  layer: Layer,
  delta: number,
): void {
  const [loopStart, loopEnd] = segments[layer.state].loop;
  layer.time += delta;
  if (layer.time < loopStart) layer.time = loopStart;
  if (layer.time > loopEnd) layer.time = loopEnd;
}

export interface AvatarModelProps {
  url: string;
  /** Which rig this is, and everything that differs about it — see ./models.ts. */
  config: AvatarConfig;
  state?: AvatarState;
  /** Reports the rig's world-space height once, so the scene can frame it. */
  onMeasure?: (height: number) => void;
  /**
   * Fires once the rig is actually posed and safe to reveal. Before the pool
   * effect below runs, the SkinnedMesh sits in the glTF's bind pose — a
   * T-pose for this rig — which is otherwise visible for however long the
   * asset takes to parse plus however many render frames pass before that
   * effect's `mixer.update(0)` call applies a real pose. The loading screen
   * that gates on this uses it to hide exactly that window, on top of the
   * fetch/parse time Suspense already covers.
   */
  onReady?: () => void;
}

/**
 * Makes GLTFLoader read from the one shared download instead of fetching.
 *
 * three.js's FileLoader has its own cache keyed by URL, but it is only
 * consulted once a load completes — two loads started before either finishes
 * still hit the network twice. Overriding `load` routes every caller into the
 * same in-flight promise, so the model crosses the wire exactly once no matter
 * how many things ask for it or when.
 */
function useSharedFetch(loader: THREE.Loader) {
  const gltf = loader as unknown as {
    load: (
      url: string,
      onLoad: (result: unknown) => void,
      onProgress?: unknown,
      onError?: (err: unknown) => void,
    ) => void;
    parse: (
      data: ArrayBuffer,
      path: string,
      onLoad: (result: unknown) => void,
      onError?: (err: unknown) => void,
    ) => void;
  };
  gltf.load = (url, onLoad, _onProgress, onError) => {
    fetchAvatar(url)
      .then((buf) =>
        gltf.parse(
          buf,
          "",
          (result) => {
            // Parsed — drei caches the result under this URL from here on, so
            // switching presenters and back never asks for the bytes again and
            // holding them would just pin tens of MB per rig behind geometry
            // that is already on the GPU.
            releaseAvatar(url);
            onLoad(result);
          },
          onError,
        ),
      )
      .catch((err) => onError?.(err));
  };
}

export default function AvatarModel({
  url,
  config,
  state = "idle",
  onMeasure,
  onReady,
}: AvatarModelProps) {
  const segments = config.segments;
  // The loader is pointed at the single shared download (lib/avatarFetch.ts)
  // rather than issuing its own request. Without this the preload, this loader
  // and the progress readout are three separate requests for the same 20MB;
  // they only collapse into one when the first finishes before the others
  // start, which is exactly what does NOT happen on a slow connection.
  const { scene, animations } = useGLTF(url, undefined, undefined, useSharedFetch);
  const groupRef = useRef<THREE.Group>(null);
  const blinkRef = useRef({ nextBlink: 2, blinkProgress: 0 });
  const a2fStateRef = useRef(createA2FMorphState());

  // Each rig gets its own amplitude calibration; restore the shared defaults on
  // unmount, and for a rig with no morphs leave them alone entirely — there is
  // nothing for A2F to drive, so its own gain is the honest thing to keep.
  useEffect(() => {
    if (!config.a2f) return;
    setRigCalibration({ gain: config.a2f.gain, shapeGains: config.a2f.shapeGains });
    return () => setRigCalibration(null);
  }, [config]);

  const { actions, mixer } = useAnimations(animations, groupRef);

  /**
   * Signal readiness only once frames carrying the REAL pose have actually been
   * rendered by R3F.
   *
   * `mixer.update(0)` writes correct bone matrices immediately, but it does not
   * itself draw anything, and R3F renders on its own internal loop rather than
   * on a plain requestAnimationFrame we could schedule against. Signalling from
   * a rAF is therefore a race: both rAF callbacks can resolve before R3F's next
   * gl.render(), so the canvas un-hides while the glTF's bind pose (a T-pose for
   * this rig) is still what's on screen.
   *
   * Instead, arm a counter here and let the per-frame callback below decrement
   * it — every tick of that callback IS an R3F frame, so once it has counted
   * down, the posed rig has provably been drawn.
   */
  const readySignalledRef = useRef(false);
  /** >0 once armed; counts down one per rendered R3F frame, fires at 0. */
  const readyFramesLeftRef = useRef(-1);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  /** Frames to let pass before revealing her. Two: the first carries the pose
   *  written by mixer.update(0), the second gives the compositor a frame to put
   *  it on screen before the opacity transition starts. */
  const READY_FRAME_DELAY = 2;

  const signalReadyAfterPosedFrame = useCallback(() => {
    if (readySignalledRef.current) return;
    readySignalledRef.current = true;
    readyFramesLeftRef.current = READY_FRAME_DELAY;
  }, []);

  // ── BODY-ANIMATION STATE ────────────────────────────────────
  const layersRef = useRef<Layer[]>(Array.from({ length: LAYER_COUNT }, makeLayer));
  /** Index of the layer carrying the segment the avatar is meant to be in. */
  const activeLayerRef = useRef(0);
  const clonedClipsRef = useRef<THREE.AnimationClip[]>([]);
  /** Sampled skeleton, for choosing pose-matched entry points. */
  const poseIndexRef = useRef<PoseIndex | null>(null);

  // Debounced target body state, written from the effect below.
  const targetStateRef = useRef<BodyState>(bodyStateFor(state));
  const exitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── MEASURE (once) so the scene can frame the rig by its real height ──
  const measuredRef = useRef(false);
  useEffect(() => {
    if (measuredRef.current) return;
    measuredRef.current = true;
    const box = new THREE.Box3().setFromObject(scene);
    const height = box.max.y;
    console.log(
      `[Avatar] ${url}: height ${height.toFixed(3)}m, ` +
        `${animations.length} clip(s): ${animations.map((c) => c.name).join(", ")}`,
    );
    onMeasure?.(height);
    // onMeasure is a stable callback from the scene; re-running on identity
    // changes would re-measure needlessly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, animations, url]);

  // ── CREATE THE ACTION POOL ONCE ─────────────────────────────
  useEffect(() => {
    const base = actions[CLIP_NAME];
    if (!base) {
      // `useAnimations` populates `actions` asynchronously, so this effect can
      // legitimately run once with it still empty — that is NOT a broken
      // export, and signalling ready here would reveal the bind pose. Only
      // give up (and reveal her anyway, static) once the clips themselves have
      // arrived and genuinely lack the expected one.
      if (animations.length === 0) return;
      console.warn(
        `[Avatar] Clip "${CLIP_NAME}" not found — body animation disabled, ` +
          `lipsync unaffected. Available:`,
        Object.keys(actions),
      );
      // No body clip to pose her with, but she's still a usable (static) rig —
      // don't leave the loading screen spinning forever over a broken export.
      signalReadyAfterPosedFrame();
      return;
    }

    // Every layer needs its own action, and three.js caches one action per
    // (clip, root) — so the extra layers run on clones that share the
    // original's tracks, costing no extra keyframe memory.
    const original = animations.find((c) => c.name === CLIP_NAME)!;
    poseIndexRef.current = buildPoseIndex(original);
    const clones: THREE.AnimationClip[] = [];
    const pool: THREE.AnimationAction[] = [base];
    for (let i = 1; i < LAYER_COUNT; i++) {
      const cloned = new THREE.AnimationClip(
        `${CLIP_NAME}__layer${i}`,
        original.duration,
        original.tracks,
      );
      clones.push(cloned);
      pool.push(mixer.clipAction(cloned));
    }
    clonedClipsRef.current = clones;

    const initial = bodyStateFor(state);
    const loopStart = segments[initial].loop[0];
    const layers = layersRef.current;

    pool.forEach((action, i) => {
      action.reset();
      action.setLoop(THREE.LoopRepeat, Infinity);
      action.clampWhenFinished = false;
      action.enabled = true;
      // Times are written manually every frame; the mixer must not advance them
      // or its internal loop bookkeeping fights our own.
      action.paused = true;
      action.time = loopStart;
      action.weight = i === 0 ? 1 : 0;
      action.play();

      const layer = layers[i];
      layer.action = action;
      layer.state = initial;
      layer.time = loopStart;
      layer.weight = i === 0 ? 1 : 0;
      layer.targetWeight = i === 0 ? 1 : 0;
      layer.fadeRate = 0;
    });

    activeLayerRef.current = 0;
    targetStateRef.current = initial;

    // Apply that pose immediately rather than waiting for the next useFrame
    // tick: without this, the SkinnedMesh is still sitting in the glTF's bind
    // pose (a T-pose, for this rig) for however many frames pass between
    // mount and the render loop's first pass through the code below, and
    // that T-pose is what actually paints. mixer.update(0) evaluates every
    // action's current weight/time and writes bone + morph values right now,
    // at zero cost to playback (delta 0 does not advance anything).
    mixer.update(0);
    signalReadyAfterPosedFrame();
    // Intentionally excludes `state`: this sets the *initial* pose only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actions, animations, mixer, segments]);

  // ── CONVERSATION STATE → DEBOUNCED TARGET SEGMENT ───────────
  useEffect(() => {
    const next = bodyStateFor(state);

    if (exitTimerRef.current !== null) {
      clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }

    if (next === "talking" || targetStateRef.current !== "talking") {
      // Entering talking, or moving between the two non-talking poses — both
      // should read immediately.
      targetStateRef.current = next;
      return;
    }

    // Leaving talking: hold the gesture briefly in case the next sentence of
    // the same reply is about to start.
    exitTimerRef.current = setTimeout(() => {
      targetStateRef.current = next;
      exitTimerRef.current = null;
    }, TALK_EXIT_DEBOUNCE_MS);
  }, [state]);

  // ── CLEANUP ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (exitTimerRef.current !== null) clearTimeout(exitTimerRef.current);
      for (const clip of clonedClipsRef.current) {
        mixer.uncacheAction(clip);
        mixer.uncacheClip(clip);
      }
      clonedClipsRef.current = [];
    };
  }, [mixer]);

  // ── MATERIALS ───────────────────────────────────────────────
  /**
   * Normalise the rig's materials once — the fix for the grey haze around the
   * eyes, and for the same haze along the hair silhouette.
   *
   * It is a minification artefact, not lighting. The eyelash, brow, hair and
   * scalp cards are alpha-masked quads whose masks are mostly empty: in
   * Eyelash_Opacity 89% of texels sit below alpha 5 and only 0.3% above 250,
   * with a thin antialiased band between. The eyelash material is
   * baseColorFactor [0,0,0] — pure black — with that mask as its alpha.
   *
   * At the size a glTF viewer shows her, each lash samples the top mip and
   * reads as a lash. Here the whole head is ~110px tall, so the sampler drops
   * several mip levels and every texel it fetches is an average of mask and
   * gap — a uniform low alpha spread over the entire quad. Blended, that is a
   * black veil across the eye socket. Hence: right in the viewer, hazy here.
   *
   *  - `alphaTest` discards everything under the cut, so the averaged-away
   *    texels are dropped rather than smeared. What survives is the dense core
   *    of each lash, which is what should be visible at this scale.
   *  - `anisotropy` sharpens those cards where they run oblique to the camera
   *    (eyelashes are nearly edge-on), which pushes the sampler back up the mip
   *    chain and shrinks the averaged band in the first place.
   *  - `depthWrite` off stops the surviving blended texels occluding each other
   *    where cards overlap — which is exactly where they are densest, the eye.
   */
  const gl = useThree((s) => s.gl);
  useEffect(() => {
    const maxAnisotropy = gl.capabilities.getMaxAnisotropy();

    scene.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (!mesh.isMesh) return;

      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const material of materials) {
        const std = material as THREE.MeshStandardMaterial;
        if (!std.isMeshStandardMaterial) continue;

        // Tone the painted-on makeup before anything else reads std.map — the
        // emissive lift below points at the same texture, so it has to pick up
        // the desaturated copy or the lips would be lifted at full chroma.
        if (
          config.faceMaterial &&
          std.name === config.faceMaterial &&
          std.map &&
          !MAKEUP_TONED.has(std.map)
        ) {
          const toned = desaturateMakeup(std.map, MAKEUP_DESATURATION);
          if (toned) {
            MAKEUP_TONED.add(toned);
            std.map.dispose();
            std.map = toned;
          }
        }

        if (std.map) {
          std.map.anisotropy = maxAnisotropy;
          std.map.needsUpdate = true;
        }

        // Face and hands only — see `skinMaterials` in ./models.ts. Driving the
        // emissive from the diffuse map keeps the skin's own shading; a flat
        // emissive colour would fill the shadow side of the face and flatten it.
        if (config.skinMaterials.has(std.name)) {
          std.emissiveMap = std.map;
          std.emissive.setRGB(1, 1, 1);
          std.emissiveIntensity = config.skinEmissive;
          // Only where the export left roughnessFactor out — see skinRoughness.
          // Scoped to that case so a rig with nothing to correct (girl15) takes
          // exactly the path it took before this became per-rig.
          if (config.skinRoughness !== null) std.roughness = config.skinRoughness;
        }

        // Albedo scale, matching this rig's exposure to the female rig's under
        // the one shared light rig — see materialTint in ./models.ts.
        const tint = config.materialTint[std.name];
        if (tint !== undefined && !tintedMaterials.has(std)) {
          tintedMaterials.add(std);
          std.color.multiplyScalar(tint);
        }

        if (std.transparent) {
          // Two different cuts, because these cards fail two different ways.
          //
          // A card whose base colour is black contributes nothing but darkness
          // wherever its alpha survives — eyelashes (baseColorFactor [0,0,0])
          // and the scalp under the hair. Their mip-averaged haze IS the
          // artefact, so cut hard and keep only the dense core.
          //
          // The hair and brow cards carry real colour, and cutting them hard
          // shreds the strands into spikes and thins the brows to nothing. They
          // only need the faintest texels removed.
          const color = std.color;
          const isMaskOnly = color.r + color.g + color.b < 0.01;
          std.alphaTest = isMaskOnly ? 0.35 : 0.08;
          std.depthWrite = false;
        }

        std.needsUpdate = true;
      }
    });
  }, [scene, gl, config]);

  // ── MORPH TARGET MESHES ─────────────────────────────────────
  const morphMeshes = useMemo(() => {
    const meshes: (THREE.SkinnedMesh | THREE.Mesh)[] = [];
    scene.traverse((child) => {
      if (
        (child instanceof THREE.SkinnedMesh || child instanceof THREE.Mesh) &&
        child.morphTargetDictionary &&
        child.morphTargetInfluences
      ) {
        meshes.push(child);
      }
    });
    return meshes;
  }, [scene]);

  // ── RIG NAME CHECK ──────────────────────────────────────────
  // Everything below addresses the rig by morph name, so a name list that is
  // internally consistent but shifted against its own geometry (see the header)
  // produces a face that moves confidently and wrongly, with nothing in the
  // console to suggest the names are at fault. Two cheap invariants catch the
  // shift girl12 shipped with: it announced itself with a "weight_0_" entry,
  // and it also cost the list its last real name.
  useEffect(() => {
    if (!config.hasMorphs) {
      // A rig declared without blendshapes has nothing to check and nothing to
      // drive — say so once rather than leaving the silent mouth a mystery.
      if (morphMeshes.length === 0) {
        console.info(
          `[Avatar] ${url}: no morph targets — lipsync and blinking are off for this rig.`,
        );
      }
      return;
    }
    const dict = morphMeshes[0]?.morphTargetDictionary;
    if (!dict) {
      console.error(
        `[Avatar] ${url}: expected ARKit morph targets and found none — ` +
          `lipsync will be silent. Re-export with blendshapes, or set ` +
          `hasMorphs: false for this rig in models.ts.`,
      );
      return;
    }
    const missing = ["eyeBlinkLeft", "eyeBlinkRight", "jawOpen", "browDownLeft"].filter(
      (name) => dict[name] === undefined,
    );
    if ("weight_0_" in dict || missing.length) {
      console.error(
        `[Avatar] ${url}: morph target names look shifted against their geometry — ` +
          `every named morph will drive its neighbour's shape. ` +
          (missing.length ? `Missing: ${missing.join(", ")}. ` : "") +
          `Re-export with the names aligned.`,
      );
    }
  }, [morphMeshes, url, config]);

  // Blink indices, resolved once. This rig uses the ARKit names, and every
  // primitive (eyelashes included) carries them.
  const blinkTargets = useMemo(
    () =>
      morphMeshes.map((mesh) => {
        const dict = mesh.morphTargetDictionary!;
        return {
          mesh,
          left: dict["eyeBlinkLeft"] ?? dict["eyeBlink_L"] ?? dict["Eye_Blink_L"],
          right: dict["eyeBlinkRight"] ?? dict["eyeBlink_R"] ?? dict["Eye_Blink_R"],
        };
      }),
    [morphMeshes],
  );

  // ── PER-FRAME UPDATE ────────────────────────────────────────
  // Priority -1: runs before default-priority callbacks, so anything else that
  // reads morphTargetInfluences in the same frame sees this frame's values.
  useFrame((frame, delta) => {
    const layers = layersRef.current;
    const active = layers[activeLayerRef.current];

    if (active.action) {
      const target = targetStateRef.current;

      if (active.state !== target) {
        // Straight into the target's loop, entered at whichever of its frames
        // is closest to the pose actually on screen right now — the pool's
        // blend of every layer's contribution, not just this one's clock. See
        // blendedPoseSample for why: this branch also fires when a transition
        // interrupts one already in flight (two mic clicks in quick
        // succession), and at that moment `active.time` alone is not what the
        // viewer is looking at. No authored lead-in either: see the note on
        // Segment for why playing one is what threw the arms out.
        const poseIndex = poseIndexRef.current;
        const fromPose = poseIndex ? blendedPoseSample(poseIndex, layers) : null;
        beginSegment(
          segments,
          layers,
          activeLayerRef,
          target,
          SWITCH_XFADE_SECS,
          bestLoopEntry(
            segments,
            poseIndex,
            target,
            fromPose,
            SWITCH_XFADE_SECS + LOOP_XFADE_SECS,
          ),
        );
      } else if (active.weight >= 0.999) {
        // Settled on a segment: start the seam crossfade one fade-length before
        // the loop end, so the incoming copy is up to speed by the time the
        // outgoing one runs out of frames.
        const loopEnd = segments[active.state].loop[1];
        if (active.time >= loopEnd - LOOP_XFADE_SECS) {
          // Every rig's windows are cut so that loop[1] already matches
          // loop[0]; re-deriving the entry here costs one search and keeps the
          // seam honest if those windows are ever re-cut for a new rig. At
          // weight >= 0.999 the pool is effectively just this layer, so its
          // own time would do — blendedPoseSample is used anyway to keep this
          // and the interrupted-transition branch above going through the
          // same path rather than two subtly different notions of "current
          // pose".
          const poseIndex = poseIndexRef.current;
          const fromPose = poseIndex ? blendedPoseSample(poseIndex, layers) : null;
          beginSegment(
            segments,
            layers,
            activeLayerRef,
            active.state,
            LOOP_XFADE_SECS,
            // Rule out the whole crossfade tail, so the layer coming in has
            // frames left to play before its own seam comes round.
            bestLoopEntry(segments, poseIndex, active.state, fromPose, LOOP_XFADE_SECS * 2),
          );
        }
      }

      // Advance every layer's own fade first, then publish the weights in a
      // second pass — they have to be normalised together, see below.
      let weightSum = 0;
      for (const layer of layers) {
        if (!layer.action) continue;
        if (layer.weight <= 0 && layer.targetWeight <= 0) continue;
        // Fading-out layers keep playing rather than freezing — a body that
        // stops mid-motion behind the fade is visible even at low weight.
        advanceLayer(segments, layer, delta);
        const step = delta * layer.fadeRate;
        layer.weight =
          layer.targetWeight > layer.weight
            ? Math.min(layer.weight + step, layer.targetWeight)
            : Math.max(layer.weight - step, layer.targetWeight);
        weightSum += layer.weight;
      }

      /**
       * Normalise, because AnimationMixer fills any shortfall with the BIND
       * POSE — and this rig binds in a T-pose.
       *
       * PropertyMixer.apply does `if (weight < 1) accuN += original * (1 -
       * weight)`, where `original` is the bone's value at bind time. So the
       * pool's weights summing to less than 1 does not merely dim the
       * animation, it mixes the T-pose in for the remainder: arms out to the
       * sides.
       *
       * An uninterrupted fade never notices, because the incoming layer rises
       * at exactly the rate the outgoing one falls and the two always total
       * 1. An INTERRUPTED one does: beginSegment starts the new layer at
       * weight 0 while the layer it just cancelled was only partway up, so
       * the total sags. Measured against this pool's own fade logic, one
       * interruption bottoms out at 0.52 (48% T-pose) and two in quick
       * succession at 0.29 (71%). That is the hands-apart glitch, and it is
       * why it fires on essentially every mic click: the loop-seam
       * self-crossfade means there is nearly always a fade already in flight
       * for a state change to interrupt.
       *
       * Dividing through keeps every layer's *relative* contribution — the
       * crossfade still looks like a crossfade — while guaranteeing the mixer
       * never reaches for the bind pose.
       */
      const norm = weightSum > 1e-6 ? 1 / weightSum : 0;
      for (const layer of layers) {
        if (!layer.action) continue;
        if (layer.weight <= 0 && layer.targetWeight <= 0) {
          layer.action.weight = 0;
          continue;
        }
        layer.action.weight = layer.weight * norm;
        layer.action.time = layer.time;
      }
    }

    // ── PLACEMENT + SUBTLE BREATHING ───────────────────────────
    if (groupRef.current) {
      groupRef.current.position.x = AVATAR_POSITION_X;
      groupRef.current.position.y = Math.sin(frame.clock.elapsedTime * 0.8) * 0.003;
    }

    // ── LIPSYNC ────────────────────────────────────────────────
    // Audio2Face drives the rig's ARKit morphs by name, 1:1. Nothing else
    // touches the mouth: with no clip playing, applyA2FLipsync decays the
    // morphs it drove back to rest and the face simply settles.
    applyA2FLipsync(a2fStateRef.current, morphMeshes, delta);

    // ── EYE BLINK ──────────────────────────────────────────────
    // Procedural rather than from A2F: A2F's eye channels are near-silent
    // through speech, so the avatar would stare without this.
    const blink = blinkRef.current;
    blink.nextBlink -= delta;
    if (blink.nextBlink <= 0) {
      blink.blinkProgress = 1;
      blink.nextBlink = 2 + Math.random() * 4;
    }
    if (blink.blinkProgress > 0) {
      blink.blinkProgress = Math.max(0, blink.blinkProgress - delta * 8);
    }
    const blinkValue =
      blink.blinkProgress > 0.5 ? (1 - blink.blinkProgress) * 2 : blink.blinkProgress * 2;

    for (const { mesh, left, right } of blinkTargets) {
      const influences = mesh.morphTargetInfluences!;
      if (left !== undefined) influences[left] = blinkValue;
      if (right !== undefined) influences[right] = blinkValue;
    }

    // ── REVEAL GATE ────────────────────────────────────────────
    // Reaching here means this frame's real pose has been written. Counting
    // down inside the render loop (rather than from a rAF) is what guarantees
    // the rig has actually been drawn posed before the canvas un-hides — see
    // signalReadyAfterPosedFrame above.
    if (readyFramesLeftRef.current > 0) {
      readyFramesLeftRef.current -= 1;
      if (readyFramesLeftRef.current === 0) onReadyRef.current?.();
    }
  }, -1);

  return (
    <group ref={groupRef}>
      <primitive object={scene} />
    </group>
  );
}
