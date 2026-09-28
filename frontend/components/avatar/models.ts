/**
 * The presenters the kiosk can show, and everything that differs between them.
 *
 * Both rigs are Character Creator exports sharing one 109-joint `DeformationSystem`
 * skeleton and one clip name, so the animation machinery in AvatarModel is common
 * to both. What is NOT common is everything below: the loop windows are cut from
 * each clip's own curves and the material names are per-export. Those all used to
 * be module constants keyed to girl15.glb; they are per-model here so a second rig
 * does not have to pretend to be the first.
 *
 * Both rigs now carry the 51 ARKit blendshapes, so both drive the real a2fMorphs
 * lipsync path. That was not true of male1.glb, which had no morph targets at all
 * and drove a single jaw BONE instead (lib/jawLipsync.ts, now unused).
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
 * a window is a position in seconds, not a keyframe. male_inital06 went back to
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
}

const f = (frame: number) => frame / FPS;

/**
 * girl15.glb — the original MARI presenter. See AvatarModel's header for the
 * full derivation of these windows; in short, they minimise the baked cloth
 * sim's drift at each seam subject to a tight body match, and they are
 * load-bearing for the ASSET as well as for playback (scripts/optimize_glb.py
 * strips keyframes outside them, so widening one without re-running the script
 * seeks into frames that are no longer in the file).
 */
const FEMALE: AvatarConfig = {
  id: "female",
  url: "/models/girl15.glb.gz",
  bytes: { decoded: 29813520, encoded: 20165542 },
  segments: {
    breathing: { loop: [f(119), f(241)] },
    listening: { loop: [f(300), f(393)] },
    talking: { loop: [f(558), f(780)] },
  },
  hasMorphs: true,
  // Framing, skin, tints, A2F and the per-theme light rig — see ./tuning.ts.
  ...RIG_TUNING.female,
};

/**
 * male_inital08.glb — the alternate presenter. The raw export, NOT run through
 * scripts/optimize_glb.py: used as exported while the rig is still being iterated on.
 *
 * Diffed against male_inital05 (the previous export) rather than re-measured from
 * scratch. Same 116 nodes, same 109-joint skin, the same 51 ARKit morph names, and
 * morph deltas byte-identical on every primitive whose vertex count did not change
 * — so A2F lipsync and blink are untouched. What DID change:
 *
 *   - THE CLIP IS NOW 30fps. The same 716 keys, carrying the same poses key for
 *     key (max difference 0.0005 over all 109 joints), are spaced 1/30s apart
 *     instead of 1/24s: 23.83s instead of 29.79s, so the body plays 25% FASTER
 *     and every window below had to be re-cut. They are quoted in this clip's own
 *     frames again, which is what `f()` and FPS=30 mean here.
 *   - The hair was rebuilt: 33917 -> 34557 verts, material renamed
 *     `standardSurface2` -> `standardSurface2.001`, its base colour now pure black
 *     with KHR_materials_clearcoat. Nothing here names that material.
 *   - The beard was rebuilt again (16912 -> 16920 verts); its jawOpen still drops
 *     it by 0.0306, mean (0, -0.016, -0.009), as on every export since male2.
 *   - Legs, nails and the lower garment moved by small amounts, and `hairs24` was
 *     renamed `hairs47`. HeadEnd_M and Shoulder_L gained translation tracks that
 *     hold a constant value, so they do nothing.
 *   - Textures are byte-identical to 05's, so the skin numbers below still hold.
 *
 * male_inital08 is 07 with NO geometry or animation change at all — every mesh,
 * UV, morph delta and animation key is identical (the clip diffs to exactly
 * 0.00), so the windows, lipsync and blink below are untouched. Only two
 * materials moved, both in ways this app has to know about:
 *
 *   - The hair (`standardSurface2.001`) now authors roughness 0.536 and
 *     metalness 0.755, where 07 left roughness out and set metalness 0. Its base
 *     colour went back to exactly 0, which is why the alphaTest override below
 *     is still load-bearing — the colour test still reads it as a mask card.
 *   - The scalp (`pasted__Scalp1_Transparency`) authors roughness 0.768 and
 *     OMITS metallicFactor, which glTF defaults to 1.0 — fully metallic, where
 *     07 had it at 0. Deliberately NOT corrected: the scalp is a mask card
 *     sitting under 1787 hair cards, and rendered through this scene the head
 *     is unchanged, so an override here would be a guess with nothing to fix.
 *     Its opacity texture was renamed with a `pasted__` prefix; nothing keys
 *     on image names.
 *
 * male_inital07 was 06 with one more hair pass and nothing else that matters:
 * the hair mesh is denser again (34557 -> 35237 verts), its node is renamed
 * `hairs47` -> `hairs`, and its base colour moved off exact black to 0.0005 —
 * still far under the 0.01 the alphaTest rule below tests for, so that override
 * is still doing the work. The beard is back to 16912 verts (05's count) with
 * jawOpen unchanged at 0.0306. Same 30fps clip (keys match 06 to 0.0005), same
 * skeleton, same 51 morph names, byte-identical textures, and the same three
 * materials still missing `roughnessFactor` — so everything measured for 06
 * below still holds, windows included.
 *
 * The windows were re-cut the way the earlier ones were: scored by SIMULATING the
 * runtime entry search (`bestLoopEntry`) against this clip's own curves, taking
 * the pose at loopEnd-0.35s, scanning the same excluded tail, and measuring how
 * much of the window still plays and how far apart the two crossfaded trajectories
 * are. Keeping 05's key indices was tried first and is what forced the re-cut: at
 * 30fps the fixed 0.35s fade spans 10.5 keys instead of 8.4, which moved the
 * talking re-entry to key 599 — 14% of the window, a rig that stands still while
 * it talks. See each window for its numbers.
 */
const MALE: AvatarConfig = {
  id: "male",
  url: "/models/male_inital08.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what
  // actually crosses the wire and `decoded` is what the reader counts — the ratio
  // keeps the loading percentage honest. 66MB raw, 42MB gzipped.
  //
  // This rig is still the raw export, NOT run through scripts/optimize_glb.py,
  // which would take it to ~39MB BEFORE compression. Run the optimizer before
  // this rig goes in front of anyone on a slow link.
  bytes: { decoded: 65923940, encoded: 42443574 },
  segments: {
    // One full breathing cycle, re-cut for the 30fps timing: seam 0.077 rad over
    // 109 joints, re-enters at f100 and plays 1.97s of its 2.53s (78%), and the
    // two crossfaded trajectories sit 0.049 rad apart — against 0.079 on 05's
    // window. Carrying 05's keys across unchanged (f110-f175 here) instead gives
    // 75% and 0.122, so this is the better cut on every axis.
    breathing: { loop: [f(83), f(159)] },
    // The settled listening pose, entered after the authored hands-rise. Re-enters
    // at f245 — the first frame, so the whole 2.63s plays — with a crossfade gap of
    // 0.276 against 05's 0.281, and slightly more motion per cycle (1.9 vs 1.7).
    listening: { loop: [f(245), f(324)] },
    // The authored gesture performance. This is the window that had to move: 05's
    // keys re-enter at f599 here and play 14% of the cycle, because the fixed 0.35s
    // crossfade covers 10.5 frames at 30fps where it covered 8.4 at 24fps.
    //
    // This cut re-enters at f543, one frame in, and plays 4.83s of its 4.87s
    // (100%), with the same absolute motion as 05's talking loop (95.6 rad against
    // 95.3) and a crossfade gap of 0.945 — an order of magnitude tighter than the
    // 9.93 that window lived with. Its seam (4.37 rad) is wide, which costs
    // nothing: every loop re-enters through the search above rather than playing
    // the seam, and loop[0] is only ever the pose for a first entry with no
    // outgoing pose to match.
    talking: { loop: [f(543), f(688)] },
  },
  // Unlike male1, this export carries the full 51 ARKit shapes on one 12-primitive
  // mesh, so lipsync and blink both run the same code the female rig does.
  // Checked the way girl12's shifted-name bug taught us to: the names align with
  // the geometry (eyeBlinkLeft/Right are mirror-symmetric at x -0.0035/+0.0036
  // with matching y drops, jawOpen drops the jaw by 0.027, smile L/R are opposed)
  // rather than merely being present and plausible.
  hasMorphs: true,
  // Framing, skin, tints, A2F and the per-theme light rig — see ./tuning.ts.
  ...RIG_TUNING.male,
};

export const AVATARS: Record<AvatarId, AvatarConfig> = {
  female: FEMALE,
  male: MALE,
};

export const DEFAULT_AVATAR: AvatarId = "female";

export const avatarConfig = (id: AvatarId): AvatarConfig => AVATARS[id] ?? FEMALE;
