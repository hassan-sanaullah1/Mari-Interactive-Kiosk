/**
 * The presenters the kiosk can show, and everything that differs between them.
 *
 * Both rigs are Character Creator exports sharing one 109-joint `DeformationSystem`
 * skeleton and one clip name, so the animation machinery in AvatarModel is common
 * to both. What is NOT common is everything below: the loop windows are cut from
 * each clip's own curves and the material names are per-export. Those all used to
 * be module constants keyed to a single rig; they are per-model here so a second rig
 * does not have to pretend to be the first.
 *
 * Both rigs carry the 51 ARKit blendshapes, so both drive the real lib/a2f-morphs.ts
 * lipsync path.
 *
 * Adding a third rig means measuring its clip the same way (see SEGMENTS on each
 * entry for what the numbers mean) rather than reusing another rig's windows —
 * they are properties of the authored animation, not of this app.
 *
 * What lives here is what describes the ASSET: where it is, how big it is, which
 * windows of its clip loop, and whether it carries morph targets. Everything
 * that decides how it LOOKS — framing, skin, tints, A2F gains and the per-theme
 * light rig — is in ./tuning.ts and is folded into each entry below, so a rig in
 * hand still answers `config.skinEmissive` and the rest exactly as before.
 */

import { RIG_TUNING, type RigTuning } from "./tuning";

/**
 * The rate the windows below are quoted in, and the rate the pose index samples
 * at. Both clips are authored at 30fps again — the male exports 03 to 05 were the
 * same animation at 24fps, whose windows were still quoted as 30fps frames because
 * a window is a position in seconds, not a keyframe. male_initial06 went back to
 * 30fps, which is why its windows had to be re-cut rather than re-labelled; see
 * MALE.
 */
export const FPS = 30;

/** Every rig here exports its body animation under this one clip name. */
export const CLIP_NAME = "CINEMA_4D_Main";

export type AvatarId = "female" | "male";

/** The three body segments the conversation drives. */
export type BodyState = "breathing" | "listening" | "talking";

/** A looping window of the clip, in seconds, and nothing else. */
export interface Segment {
  loop: [number, number];
}

/**
 * One presenter: the asset facts below, plus everything in its RigTuning entry.
 * Extending rather than re-listing is what keeps `config.materialTint` and the
 * rest reachable from a single object, so moving the look values into
 * ./tuning.ts changed no consumer.
 */
export interface AvatarConfig extends RigTuning {
  id: AvatarId;
  /** Where the rig lives, served from frontend/public. */
  url: string;
  /**
   * Decoded and over-the-wire byte counts, used only to keep the loading
   * percentage honest — see fetchAvatar. `encoded` differs from `decoded` only
   * when the response arrives gzipped.
   */
  bytes: { decoded: number; encoded: number };
  segments: Record<BodyState, Segment>;
  /**
   * True when the rig carries ARKit morph targets. False disables lipsync and
   * blinking for that rig — not a fallback, just nothing to drive.
   */
  hasMorphs: boolean;
  /**
   * Grammatical gender, for UI copy. Urdu marks gender on verbs, so a status
   * line about what the presenter is doing has to agree with who is on screen —
   * "سن رہی ہے" for her, "سن رہا ہے" for him. Mirrors `grammatical_gender` in
   * server/personas.toml, which does the same for the spoken reply.
   */
  grammaticalGender: "f" | "m";
  /**
   * What to call this presenter in the UI, per language. Here rather than in the
   * switch that renders it, so adding a presenter does not mean editing that switch.
   */
  label: Record<"en" | "ur", string>;
  /**
   * Which silhouette to show. A name, not the component: this module is data, and
   * the switch maps the name to an icon.
   */
  icon: "female" | "male";
}

const f = (frame: number) => frame / FPS;

/**
 * dress2_v2.glb — the MARI presenter. See AvatarModel's header for how this
 * rig's windows are derived; in short, they minimise the baked cloth sim's
 * drift at each seam subject to a tight body match.
 *
 * Her FACE is byte-identical to the dress2 export this replaces: all 12
 * primitives of Mesh.003, every rest position and all 51 ARKit morph deltas
 * compare exactly equal. So lipsync, the procedural blink and the A2F
 * calibration below port across untouched, and the girl12 shifted-name class
 * of bug is ruled out by construction rather than by inspection.
 *
 * What DID change is the hair and the clip. The four hair-card meshes and the
 * scalp (lambert19 through lambert23, ~29.7k vertices) are gone, replaced by
 * one 111k-vertex mesh on a single material, `pasted__lambert2` — which is why
 * the hair keys in tuning.ts moved there.
 *
 * SEGMENTS. This is NOT dress2's clip retimed: same 1084 tracks, but 37.54s
 * against 30.03s and the curves diverge immediately, so the windows below were
 * re-cut from scratch. Per-frame motion locates the breaks (110 body joints,
 * summed quaternion angle):
 *
 *   0-39      a dead hold at the head of the clip, skipped entirely
 *   40-289    breathing  (at-rest idle; arms 0.02-0.11, spine 0.04-0.24 deg/frame)
 *   290-519   listening  (the same idle carrying more spine, peaking 0.69)
 *   520-1126  talking    (the gesture performance, up to 92 deg/frame)
 *
 * The windows inside them were then scored by SIMULATING the runtime entry
 * search (`bestLoopEntry`) against this clip's own curves — take the pose at
 * loopEnd-0.35s, scan the same excluded tail, and measure how much of the
 * window still plays and how far apart the outgoing and incoming poses sit —
 * and, because this rig's visible motion at rest is the cloth rather than the
 * body, by the cloth seam alongside it. Cloth cost is quoted in frames of
 * ordinary cloth motion, the unit AvatarModel's header uses; the figures in
 * brackets are dress2's for the same measurement, for comparison.
 */
const FEMALE: AvatarConfig = {
  id: "female",
  url: "/models/dress2_v2.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what
  // crosses the wire and `decoded` is what the reader counts. 76MB raw, 53MB
  // gzipped. The RAW export: scripts/optimize_glb.py has not been run on it.
  bytes: { decoded: 76410448, encoded: 53455982 },
  segments: {
    // Three seconds of the at-rest idle. Re-enters 4 frames in and plays 2.87s
    // (96%) at a body gap of 0.000, for the cheapest cloth seam anywhere in the
    // segment: 1.6 frames [dress2: 2.0]. Longer windows exist and carry no more
    // motion worth having — the body moves 0.7 rad across this whole window —
    // while costing 2.4x the seam (the best window of 4s or more is 3.9 frames).
    // It also starts late enough that the cloth has settled out of its rest
    // state, the same reason dress2's breathing window did not start at frame 1.
    breathing: { loop: [f(188), f(278)] },
    // The settled listening pose. Re-enters 3 frames in and plays 3.93s (98%)
    // at a body gap of 0.001 and a cloth seam of 5.7 frames [dress2: 5.0] —
    // the cheapest in the segment. The windows carrying the most spine motion
    // sit at 9.0 frames of cloth for 0.1 rad more, which is not a trade.
    listening: { loop: [f(371), f(491)] },
    // The gesture performance. Enters at loop[0] — the pose genuinely closes on
    // itself here — and plays all 6.00s (100%) at a gap of 0.019, carrying
    // 84.7 rad through a cloth seam of 22.2 frames [dress2: 38.0, and that
    // segment offered nothing better]. The 8s windows carry 106 rad but cost
    // 47.5 frames of cloth and a gap of 0.120; a quarter more motion is not
    // worth doubling the one seam on this rig that cannot be made cheap.
    talking: { loop: [f(852), f(1032)] },
  },
  hasMorphs: true,
  grammaticalGender: "f",
  label: { en: "Female presenter", ur: "خاتون پیشکار" },
  icon: "female",
  // Framing, skin, tints, A2F and the per-theme light rig — see ./tuning.ts.
  ...RIG_TUNING.female,
};

/**
 * glb1.glb — the alternate presenter. Still a RAW export (see `bytes`), though
 * at 49MB/27MB it is now the cheaper of the two rigs to download.
 *
 * A drop-in for the male_initial13 export it replaces, and verified as one
 * rather than assumed:
 *
 *   - ANIMATION. Same 295 rotation tracks under the same names, same 29.80s at
 *     30fps. Summed over every track the per-frame curves differ by at most
 *     3.83 deg (mean 0.13), which is re-export rounding and not content — so
 *     the loop windows below carried over unchanged, and re-scoring them
 *     against this clip confirms them (see each window).
 *   - FACE. All 52 morph target names in the same order, and the head
 *     (lambert5), arms, eyes, both teeth rows, tongue, brows, beard and
 *     eyelashes compare byte-identical to 13 — rest positions and all 52
 *     deltas, max difference exactly zero. So lipsync, blink and the
 *     lip-outline multipliers fitted in server/personas.toml need nothing.
 *
 * What changed is below the waist and the garment. `Std_Skin_Leg` is gone
 * (legs and feet are no longer separate skin geometry, and `Std_Nails` drops
 * from 1112 vertices to 680 with the toes), and the kurta gains a waistcoat on
 * two new materials, `waistcoat:lambert2` and `waistcoat:lambert3`. Neither
 * waistcoat material authors a roughnessFactor, and glTF defaults that to fully
 * matte — the correction is in tuning.ts, the same one dress2's kameez needs.
 *
 * The hair is `standardSurface2` again, so the hair keys in tuning.ts stay put.
 */
const MALE: AvatarConfig = {
  id: "male",
  url: "/models/glb1.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what crosses
  // the wire and `decoded` is what the reader counts — the ratio keeps the loading
  // percentage honest. 49MB raw, 27MB gzipped. Still the RAW export: run
  // scripts/optimize_glb.py before this rig goes in front of anyone on a slow link.
  bytes: { decoded: 48863788, encoded: 26858655 },
  segments: {
    // Two full breath cycles of the at-rest idle. The idle here is strictly
    // periodic at 30 frames, so a whole number of cycles closes on itself: the
    // entry search lands on loop[0] and plays all 2.00s (100%) through a
    // crossfade gap of 0.000 — nothing in the segment does better. Unchanged
    // against this export, which scores it identically.
    breathing: { loop: [f(36), f(96)] },
    // The authored hands-rise and the settled pose after it, which is nearly the
    // whole 100-frame segment. Re-enters at loop[0] and plays all 3.20s (100%)
    // at a gap of 0.014, carrying 49.3 rad — the most motion of any window in
    // this segment that still plays in full. Scores identically here.
    listening: { loop: [f(300), f(396)] },
    // The gesture performance. On this export it re-enters at f554, 10 frames
    // in, and plays 7.67s of its 8.00s (96%) carrying 210.2 rad at a gap of
    // 0.097 — slightly better than the 89% it played on male_initial13, from
    // the same re-export rounding noted above. loop[0] is only the pose for a
    // first entry that has no outgoing pose to match; every loop re-enters
    // through the search above rather than playing the seam.
    talking: { loop: [f(544), f(784)] },
  },
  // This export carries the full 51 ARKit shapes on one 11-primitive mesh, so
  // lipsync and blink both run the same code the female rig does. Checked the
  // way girl12's shifted-name bug taught us to, and then some: the names align
  // with the geometry AND the geometry is byte-identical to the previous export
  // (see the header), so the shapes are the same ones already measured.
  hasMorphs: true,
  grammaticalGender: "m",
  label: { en: "Male presenter", ur: "مرد پیشکار" },
  icon: "male",
  // Framing, skin, tints, A2F and the per-theme light rig — see ./tuning.ts.
  ...RIG_TUNING.male,
};

export const AVATARS: Record<AvatarId, AvatarConfig> = {
  female: FEMALE,
  male: MALE,
};

export const DEFAULT_AVATAR: AvatarId = "female";

export const avatarConfig = (id: AvatarId): AvatarConfig => AVATARS[id] ?? FEMALE;
