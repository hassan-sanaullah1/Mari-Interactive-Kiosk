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
 * dress2_v6.glb — the MARI presenter, replacing dress2_v3. See AvatarModel's
 * header for how this rig's windows are derived; in short, they minimise the
 * baked cloth sim's drift at each seam subject to a tight body match.
 *
 * NOT a byte-identical drop-in the way v3 was from v2. Checked rather than
 * assumed:
 *
 *   - BODY. The 109-joint DeformationSystem skeleton's own rotation curves
 *     (plus the "dupatta" node that is animated alongside it, outside the
 *     cloth sim) are unchanged from v3's to within re-export noise — worst
 *     joint (Head_M) differs by 0.023 in a quaternion component, the same
 *     order of noise the MALE header below calls re-export rounding rather
 *     than content. So this is v3's performance, re-exported, not a new take
 *     — confirmed by v3's own talking window ([794,1026]) independently
 *     scoring a 0.25deg body gap on THIS clip too, matching what v3's header
 *     measured on its own.
 *   - FACE. Mesh.003 keeps the same 51 ARKit target names in the same order
 *     on every primitive, so lipsync's name lookup needs nothing. The mesh
 *     itself is not byte-identical though: vertex counts shift on several
 *     primitives (prim0 986->988, prim5 4354->4345), and one primitive
 *     (material "lambert12", 1672 verts of inner-mouth geometry) is gone
 *     outright — its slice reads as absorbed into a much smaller lambert5
 *     primitive (4252->251 verts) and a larger lambert16 one (1112->680).
 *     tuning.ts's `female.skinMaterials` and `female.materialEnvIntensity`
 *     still list "lambert12" — harmless, a name that now matches nothing is
 *     the same kind of dead reference v3's own header below left alone
 *     rather than guess-edit, but worth a look in the designer's glb-viewer
 *     Checks panel if the inner mouth looks off on screen.
 *   - GARMENT. Two of the three Kameez:lambert2 primitives (Mesh.060 and
 *     Mesh.064, 1142 and 1400 verts in v3) are gone; only Mesh.061 (5814
 *     verts, unchanged) remains under that material — matches the node
 *     count dropping 1204->1202. Fewer cloth pieces, not a material rename.
 *   - A2F. `female.a2f` (in ./tuning.ts) is still empty, i.e. NIM defaults.
 *     That was measured correct for v2's sculpt and ported untouched through
 *     v3 because v3's face was byte-for-byte v2's. It has NOT been
 *     re-measured against this face, which is byte-identical to neither.
 *     Run scripts/lipsync_audit.py against this rig before trusting the
 *     defaults if the mouth looks off.
 *
 * Same CINEMA_4D_Main clip, same 37.500s / 1125 frames (30fps indexing, as
 * elsewhere in this file).
 *
 * SEGMENTS, measured fresh against this clip by the method v3's header
 * describes: quaternion angle between a window's last and first frame,
 * summed over the 109 body joints, exhaustively over every (start, duration)
 * within each phase. Phases were re-located on this clip's own curve and
 * landed on the same boundaries v3 measured (consistent with the body curve
 * being unchanged, above): dead hold to ~39, breathing 40-289, listening
 * 290-519, talking 520-1125.
 *
 * The FIRST pass through this search picked the single lowest-gap window in
 * each phase with no other check, and shipped a breathing and a listening
 * window that were both a visibly broken idle — "breathing not working",
 * reported after it went out. Minimising the gap alone says nothing about
 * whether a window has any visible motion in it: the idle phases of this
 * clip are mostly still, so the global minimum in each is a near-static
 * sliver (around 1s) where the only thing above 0.05deg/frame is one leg's
 * knee/ankle/hip — correct as a loop, empty as an idle. Checking the
 * hand/arm subset alone (the thing v3's header's own first-pass bug called
 * out) would NOT have caught this: hands were motionless in both broken
 * windows too, so their subset gap was also ~0. The windows below instead
 * come from the same search widened to also require visible, bilateral
 * motion (both legs, not a one-sided twitch) — still exhaustive, still
 * scored on body gap / hand-arm gap / cloth seam, just no longer blind to a
 * candidate that "wins" by having nothing happen in it.
 *
 * A THIRD check, which caught the talking window going out stuck: a window is
 * only worth the frames it actually PLAYS. AvatarModel does not replay a
 * window start-to-end — at the seam, `bestLoopEntry` re-enters at whichever
 * frame best matches the pose ~0.35s before the window ends, so a window
 * plays in full only if that pose's nearest match lies near the window's
 * HEAD. Nothing about a tight seam gap guarantees that: the gap compares the
 * two ENDS, and a window whose end-pose instead matches its own middle will
 * re-enter there and replay a sliver of itself forever. The only way to know
 * is to run that search the way the player runs it, so each window below was
 * simulated over several laps and kept only if it converges to entering near
 * loop[0] and playing essentially all of itself every lap. Re-run that
 * simulation for any new rig; the three numbers alone will not tell you.
 */
const FEMALE: AvatarConfig = {
  id: "female",
  url: "/models/dress2_v6.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts). Run through
  // optimize_glb.py with --keep-windows matching the three loop windows
  // below (converted to this clip's own 24fps: 72-168, 238-375, 635-821 —
  // see clip_fps in that script): animation keyframes outside the played
  // windows are dropped, cloth rotations are requantised, and unused morph
  // target normals are stripped. Geometry, skinning, materials and all 51
  // morph target names are untouched (verified: mesh/skin/node/material
  // counts and target names identical to the un-optimized export). 72MB raw
  // dropped to 46MB, 52MB gzipped dropped to 36MB.
  bytes: { decoded: 46294600, encoded: 35687593 },
  segments: {
    // The search's global best, [60,90] (body gap 0.00deg), shipped first and
    // was wrong: minimising the pose gap alone says nothing about whether the
    // window has any visible motion in it, and that one didn't — every body
    // joint above 0.05deg/frame inside it is a knee/ankle/hip on the RIGHT leg
    // only, nothing bilateral, nothing above the waist. A perfect, 1s loop of
    // essentially standing still, which is what "breathing not working" was.
    // [90,210] (still body gap 0.00, hand/arm gap 0.00, cloth seam 4.1 frames
    // — better than the broken pick's 5.9) is the same search's next-best tier
    // and carries both legs' knee/hip/ankle sway plus the head, at a natural
    // 4s cadence close to v3's own 2.47s breathing window. No window in this
    // phase moves the chest or spine more than ~0.008deg/frame regardless of
    // which one is picked (checked directly) — that is this clip's own
    // breathing authored as a weight-shift and head sway, not a visible chest
    // rise, same as it was for v3 on this identical body animation.
    //
    // The play-through check above says this one re-enters 35 frames in and
    // so plays 2.5s of its 4s. Left alone, and only here: this phase is
    // exactly 30-frame periodic (every 30-frame multiple scores a 0.00deg
    // gap), so the 2.5s it plays carries the same 7 moving joints at the same
    // amplitudes as the full window — the slice and the whole are the same
    // motion. That argument does NOT transfer to the other two phases.
    breathing: { loop: [f(90), f(210)] },
    // Body gap 4.76deg, hand/arm gap 0.32deg, cloth seam 9.8 frames. The
    // loosest seam of the three, and the phase simply does not offer a tight
    // one — v3's header says the same about its own listening window.
    //
    // Two picks were wrong before this one. [480,510] (gap 3.56) was the
    // aggregate global best and, like breathing's first pick, carried one leg
    // and the head and nothing that reads as "attentive". [299,466] (gap 3.95)
    // fixed the content but failed the play-through check above: it converged
    // on entering 95 frames in, so steady-state it replayed 2.07s of its 5.57s
    // and dropped the left leg's sway (1.07deg) back to 0.11. This window is
    // 0.8deg looser at the seam than that one and keeps all 12 moving joints
    // at full amplitude, because it re-enters at loop[0] and plays 94% of
    // itself (5.40s) every lap. Trading a slightly wider crossfade for 2.6x
    // the motion the viewer actually sees is the right side of that deal.
    listening: { loop: [f(297), f(469)] },
    // Body gap 0.25deg, hand/arm gap 0.19deg, cloth seam 74.7 frames. This is
    // v3's own talking window, re-scored against this clip rather than
    // inherited — further evidence the body animation did not change.
    //
    // It replaces [814,900] (gap 0.67, cloth seam 46), which looked better on
    // both of those numbers and was the "gets stuck in a weird look" bug.
    // Simulating AvatarModel's own seam logic against this clip is what found
    // it: `bestLoopEntry` re-enters at whichever frame best matches the pose
    // ~0.35s before the window ends, and on [814,900] that search converged on
    // frame 860 — so after the first lap she replayed frames 860-890, a 1.0s
    // sliver of a 2.87s window, forever. A tight seam gap does NOT imply the
    // window plays: it only says the two ENDS match. What makes a window play
    // in full is that the pose near its end matches a frame near its HEAD, and
    // that has to be simulated, not inferred. This window converges to
    // entering 9 frames in and playing 92% of its 7.73s on every lap.
    //
    // Cloth seam is the one number that got worse (46 -> 74.7 frames), taken
    // deliberately: the 0.35s crossfade is there to absorb cloth drift at a
    // seam, and nothing absorbs replaying a 1-second sliver of a gesture.
    talking: { loop: [f(794), f(1026)] },
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
