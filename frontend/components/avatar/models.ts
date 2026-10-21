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
 * dress2_v3.glb — the MARI presenter. See AvatarModel's header for how this
 * rig's windows are derived; in short, they minimise the baked cloth sim's
 * drift at each seam subject to a tight body match.
 *
 * Her FACE is byte-identical to dress2_v2's: all 12 primitives of Mesh.003 —
 * positions, normals and every one of the 51 ARKit morph-target deltas —
 * compare equal by SHA-256. So lipsync, the procedural blink and the A2F
 * calibration below port across untouched, same as v2 did from its own
 * predecessor. Materials and mesh names are also an exact set match with v2.
 *
 * The export carries two pieces of dead weight that are NOT wired into the
 * kiosk and were left alone rather than guessed at: a second, orphaned copy
 * of the 109-joint body skeleton (scene root "DeformationSystem.001") that no
 * mesh is skinned to, and a second animation clip ("CINEMA_4D_Main.001", 327
 * channels) that only that orphaned skeleton uses. Confirmed via the glTF
 * skin/node data that neither affects anything rendered. scripts/optimize_glb.py
 * would be the place to strip them later; this swap did not touch it.
 *
 * SEGMENTS. The main clip retimed slightly from v2's (37.500s / 1126 frames
 * here vs v2's 37.542s / 1126.3), so v2's windows were not safe to reuse as-is
 * and were re-measured fresh against this clip, by the same method v2's own
 * comment describes: per-frame motion over the 109 body joints (summed
 * quaternion angle) locates the same phase shape v2 has —
 *
 *   0-39      a dead hold at the head of the clip, skipped entirely
 *   40-289    breathing  (at-rest idle, under ~2 deg/frame)
 *   290-519   listening  (the same idle carrying more spine, up to ~2 deg/frame)
 *   520-1125  talking    (the gesture performance, up to 92 deg/frame — matches
 *                         v2's documented peak almost exactly)
 *
 * — then candidate windows near v2's equivalent frames were scored on (a) the
 * body-pose gap between the window's last and first frame and (b) the cloth
 * seam at that same cut, in frames of ordinary cloth motion, same units v2's
 * comment uses. NOTE: this measurement was done with a one-off script written
 * for this swap, replicating the documented method rather than running it
 * through the designer's own avatar-lab tool — re-verify there if the loop
 * points look off in practice, particularly listening's (see below).
 */
const FEMALE: AvatarConfig = {
  id: "female",
  url: "/models/dress2_v3.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what
  // crosses the wire and `decoded` is what the reader counts. 77MB raw, 53MB
  // gzipped (plain gzip -9 of the raw export, same as v2: optimize_glb.py has
  // not been run on this file either).
  bytes: { decoded: 77338924, encoded: 53545823 },
  segments: {
    // Body gap 0.56deg (summed over 109 joints), cloth seam 6.3 frames —
    // cheapest nearby candidate; a near-identical window to v2's own [188,278].
    breathing: { loop: [f(194), f(272)] },
    // The weakest of the three: body gap ~14.7deg even after widening the
    // search well past v2's equivalent window, so this phase of the clip does
    // not close on itself as cleanly as v2's did (0.001-equivalent gap) — not
    // a search-radius artifact, the clip's own motion here. Worth a second
    // look from the avatar-lab tool if the listening loop visibly pops.
    listening: { loop: [f(353), f(474)] },
    // Body gap 30.1deg, cloth seam 8.6 frames. Like v2's talking window, this
    // is the gesture performance itself — some pose mismatch at the cut is
    // expected here, the same trade v2's comment describes for its own window.
    talking: { loop: [f(848), f(1038)] },
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
