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
 * girl15.glb — the original MARI presenter. See AvatarModel's header for the
 * full derivation of these windows; in short, they minimise the baked cloth
 * sim's drift at each seam subject to a tight body match, and they are
 * load-bearing for the ASSET as well as for playback (scripts/optimize_glb.py
 * strips keyframes outside them, so widening one without re-running the script
 * seeks into frames that are no longer in the file).
 */
const FEMALE: AvatarConfig = {
  id: "female",
  // Same clip as the girl15 export it replaced (rotations within 0.04 deg), so
  // the loop windows below carried over unchanged.
  url: "/models/dress2.glb.gz",
  bytes: { decoded: 70442516, encoded: 52101323 },
  segments: {
    breathing: { loop: [f(119), f(241)] },
    listening: { loop: [f(300), f(393)] },
    talking: { loop: [f(558), f(780)] },
  },
  hasMorphs: true,
  grammaticalGender: "f",
  label: { en: "Female presenter", ur: "خاتون پیشکار" },
  icon: "female",
  // Framing, skin, tints, A2F and the per-theme light rig — see ./tuning.ts.
  ...RIG_TUNING.female,
};

/**
 * male_initial13.glb — the alternate presenter. Still the RAW export (see `bytes`):
 * run scripts/optimize_glb.py before this rig goes in front of anyone on a slow link.
 *
 * Carries the same facial bone rig as 12 — 302 nodes, 295 rotation tracks, of which
 * 178 are face (EyeJoint, upperLidMain0..9, lip, cheek, brow) and animated by this
 * clip. They are ordinary quaternion tracks, so buildPoseIndex matches on them
 * alongside the body joints; that is why the window numbers below are an order of
 * magnitude larger than the 51-joint era's and must only be compared against each
 * other.
 *
 * Against male_initial12: the clip is the SAME 30fps but 894 keys over 29.80s where
 * 12 was 716 over 23.83s, and the content differs too — 12's windows land in the
 * wrong segments here (its breathing window falls inside this clip's idle but its
 * listening and talking windows both land in the idle's tail). So the windows below
 * were re-cut from scratch rather than rescaled.
 *
 * The face morphs are untouched: the same 52 target names on the same 12-primitive
 * head mesh (Mesh.003), with jawOpen and the mirrored blinks at 12's amplitudes — so
 * lipsync and the procedural blink need nothing. This export adds two morphs
 * (`kameez2`, `kameez2_Copy`) to a garment mesh; nothing drives them by name.
 *
 * The head texture is the same DARK repaint as 12 (`Std_Skin_Head_Diffuse7 copy`), and
 * every material name and roughness matches 12 except the hair: it is
 * `standardSurface2` again here (12 called it `standardSurface2.001`), which is why
 * the hair keys in tuning.ts moved back. The skin tints were set against this same
 * texture level, so the lighting carries over unchanged.
 *
 * SEGMENTS, measured off this clip's own per-frame motion rather than carried over
 * (summed joint rotation per frame, 10-frame means — scripts/lipsync_audit.py's rig
 * table is the same measurement path):
 *
 *   20-299   breathing  (at-rest idle, a clean ~30-frame cycle at 6-13 deg/frame)
 *   300-399  listening  (the authored hands-rise, 15-55)
 *   400-890  talking    (the gesture performance, 20-150)
 *
 * The windows inside them were scored the way every male window since male2 has
 * been: by SIMULATING the runtime entry search (`bestLoopEntry`) against this clip's
 * own curves — take the pose at loopEnd-0.35s, scan the same excluded tail, and
 * measure how much of the window still plays and how far apart the outgoing and
 * incoming trajectories sit through the fade.
 */
const MALE: AvatarConfig = {
  id: "male",
  url: "/models/male_initial13.glb.gz",
  // Served as the pre-compressed .gz (next.config.ts), so `encoded` is what crosses
  // the wire and `decoded` is what the reader counts — the ratio keeps the loading
  // percentage honest. 68MB raw, 42MB gzipped. Still the RAW export: run
  // scripts/optimize_glb.py before this rig goes in front of anyone on a slow link.
  bytes: { decoded: 67752008, encoded: 42294045 },
  segments: {
    // Two full breath cycles of the at-rest idle. The idle here is strictly
    // periodic at 30 frames, so a whole number of cycles closes on itself: the
    // entry search lands on loop[0] and plays all 2.00s (100%) through a
    // crossfade gap of 0.000 — nothing in the segment does better.
    breathing: { loop: [f(36), f(96)] },
    // The authored hands-rise and the settled pose after it, which is nearly the
    // whole 100-frame segment. Re-enters at loop[0] and plays all 3.20s (100%)
    // at a gap of 0.014, carrying 49.3 rad — the most motion of any window in
    // this segment that still plays in full.
    listening: { loop: [f(300), f(396)] },
    // The gesture performance. Re-enters at f571, 27 frames in, and plays 7.10s
    // of its 8.00s (89%) carrying 211.3 rad — the most motion of any candidate
    // that keeps both its gap under 0.15 and 85% of the window. loop[0] is only
    // the pose for a first entry that has no outgoing pose to match; every loop
    // re-enters through the search above rather than playing the seam.
    talking: { loop: [f(544), f(784)] },
  },
  // Unlike male1, this export carries the full 51 ARKit shapes on one 12-primitive
  // mesh, so lipsync and blink both run the same code the female rig does.
  // Checked the way girl12's shifted-name bug taught us to: the names align with
  // the geometry (eyeBlinkLeft/Right are mirror-symmetric at x -0.0035/+0.0036
  // with matching y drops, jawOpen drops the jaw by 0.027, smile L/R are opposed)
  // rather than merely being present and plausible.
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
