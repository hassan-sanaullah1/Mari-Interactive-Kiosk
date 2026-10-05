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
 * male_inital12.glb — the alternate presenter. Still the RAW export (see `bytes`):
 * run scripts/optimize_glb.py before this rig goes in front of anyone on a slow link.
 *
 * Carries the facial bone rig the 09-11 exports introduced — 302 nodes, 295 skin
 * joints, of which 178 are face (EyeJoint, upperLidMain0..9, lip, cheek, brow) and
 * animated by this clip. They are ordinary quaternion tracks, so buildPoseIndex
 * matches on them alongside the 117 body joints; that is why the window numbers
 * below are an order of magnitude larger than the 51-joint era's and must only be
 * compared against each other.
 *
 * Against male_inital10 (the last export measured here): the 716 keys are the same
 * count but NOT the same performance — key-for-key the two differ by up to 0.276,
 * and the clip is stamped 30fps (23.83s) where 10 was 24fps (29.79s). Both the
 * timing AND the content moved, so the windows were re-cut from scratch rather
 * than rescaled. Against 09 the face morphs are untouched: 52 names, the 51 ARKit
 * shapes byte-identical on the head (jawOpen still 2009 verts at 0.0296, blinks
 * still mirrored at x +-0.0255), and the face mesh is the only one carrying morph
 * targets at all — so lipsync and the procedural blink need nothing.
 *
 * The head texture is the DARK repaint again (`Std_Skin_Head_Diffuse7 copy`, 135.1
 * mean luminance — a different file from 08's `Diffuse6` but the same level), after
 * 09-10 briefly reverted to the pale original at 174.9. The tint in tuning.ts was
 * set against this level, so it needs no change. Every material authors roughness
 * and metalness, so the corrections 05-08 needed stay retired. The hair material
 * is named `standardSurface2.001` again (09/10 called it `standardSurface2`), which
 * is why the alphaTest key in tuning.ts moved back.
 *
 * SEGMENTS, measured off this clip's own per-frame motion rather than carried over:
 *
 *   20-235   breathing  (at-rest idle, 1.5-2.2 deg/frame over the body)
 *   240-320  listening  (the authored hands-rise, 2.4-5.9)
 *   340-715  talking    (the gesture performance, 25-77)
 *
 * The windows inside them were scored the way every male window since male2 has
 * been: by SIMULATING the runtime entry search (`bestLoopEntry`) against this
 * clip's own curves — take the pose at loopEnd-0.35s, scan the same excluded tail,
 * and measure how much of the window still plays and how far apart the outgoing
 * and incoming trajectories sit through the fade. Carrying 08's windows across
 * unchanged was tried first and is what forced the re-cut: they land in the wrong
 * segments here, playing 28% of the listening loop and 15% of the talking one.
 */
const MALE: AvatarConfig = {
  id: "male",
  url: "/models/male_inital12.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what crosses
  // the wire and `decoded` is what the reader counts — the ratio keeps the loading
  // percentage honest. 68MB raw, 43MB gzipped. Still the RAW export: run
  // scripts/optimize_glb.py before this rig goes in front of anyone on a slow link.
  bytes: { decoded: 68123604, encoded: 43348830 },
  segments: {
    // One breathing cycle out of the at-rest idle. Re-enters at f29 and plays
    // 1.97s of its 2.27s (87%) through a crossfade gap of 0.057 — the tightest
    // in the segment, and it carries 13.2 of the 14.4 rad the best-moving
    // candidate does.
    breathing: { loop: [f(20), f(88)] },
    // The authored hands-rise and the settled pose after it. The segment is only
    // 80 frames long, so this is most of it: re-enters at f246, six frames in,
    // and plays 1.90s of its 2.10s (90%), with the lowest gap (5.41) of any
    // window that keeps the rise. The gap is large in absolute terms because 178
    // of the 295 matched joints are face bones, and they are at their busiest
    // here — against other windows in this segment it is the smallest.
    listening: { loop: [f(240), f(303)] },
    // The gesture performance. Re-enters at f445, 32 frames in, and plays 6.27s
    // of its 7.33s (85%) carrying 185.6 rad — the most motion of any candidate
    // that also keeps its gap under 8.5. The seam is wide (33.6) and costs
    // nothing: every loop re-enters through the search above rather than playing
    // the seam, and loop[0] is only the pose for a first entry that has no
    // outgoing pose to match.
    talking: { loop: [f(413), f(633)] },
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
