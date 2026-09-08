/**
 * The presenters the kiosk can show, and everything that differs between them.
 *
 * Both rigs are Character Creator exports sharing one 109-joint `DeformationSystem`
 * skeleton and one clip name, so the animation machinery in AvatarModel is common
 * to both. What is NOT common is everything below: the loop windows are cut from
 * each clip's own curves, the material names are per-export, and only the female
 * rig carries blendshapes at all. Those all used to be module constants keyed to
 * girl15.glb; they are per-model here so a second rig does not have to pretend to
 * be the first.
 *
 * Adding a third rig means measuring its clip the same way (see SEGMENTS on each
 * entry for what the numbers mean) rather than reusing another rig's windows —
 * they are properties of the authored animation, not of this app.
 */

/** Both clips are authored at 30fps; the windows below are quoted in frames. */
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

export interface AvatarConfig {
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
  /** Height in metres, used to frame the shot until the rig reports its real one. */
  fallbackHeight: number;
  /** World Y the face spot aims at — the centre of this rig's face. */
  headTargetY: number;
  /**
   * Materials textured with skin, which get the emissive lift. Read off each
   * glTF's baseColorTexture rather than guessed from the names.
   */
  skinMaterials: Set<string>;
  /**
   * The material carrying painted-on makeup, or null for a rig with none. Only
   * set this where there is actually makeup to tone down: the pass reads the
   * texture back through a 2D canvas, which is not free.
   */
  faceMaterial: string | null;
  /**
   * True when the rig carries ARKit morph targets. False disables lipsync and
   * blinking for that rig — not a fallback, just nothing to drive.
   */
  hasMorphs: boolean;
  /** A2F weight calibration, or null for a rig with no morphs to calibrate. */
  a2f: { gain: number; shapeGains: Record<string, number> } | null;
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
  url: "/models/girl15.glb",
  bytes: { decoded: 29813520, encoded: 20165542 },
  segments: {
    breathing: { loop: [f(119), f(241)] },
    listening: { loop: [f(300), f(393)] },
    talking: { loop: [f(558), f(780)] },
  },
  fallbackHeight: 1.68,
  headTargetY: 1.45,
  skinMaterials: new Set(["lambert11", "lambert13", "lambert12"]),
  faceMaterial: "lambert12",
  hasMorphs: true,
  a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
};

/**
 * male1.glb — the alternate presenter.
 *
 * Same skeleton as girl15 (all 109 of its `DeformationSystem` joints, plus jaw
 * and eye bones girl15 lacks) and — measured, not assumed — the SAME AUTHORED
 * ANIMATION, retargeted onto a different body. Frame for frame against girl14
 * (the female clip before optimize_glb.py trims it), the two agree to 0.157 rad
 * per joint, which is retargeting and proportions rather than different motion:
 * their per-frame motion curves rise and fall together across all 893 frames,
 * and the held poses that bracket the gesture takes land in the same places
 * (f664-680 here, f657-670 there). Best alignment is offset 0, so this clip's
 * segment boundaries are the female one's:
 *
 *   0-38    dead hold at the head of the clip, skipped
 *   38-245  breathing  (at-rest idle)
 *   245-393 listening  (hands rise at 245-300, then a settled listening pose)
 *   393-893 talking    (an authored settle-in, then the gesturing)
 *
 * The WINDOWS inside those segments were still cut against THIS rig's curves
 * rather than copied, because the retarget moves the seams — summed quaternion
 * angle over the 54 shared body joints, closest-matching frame pair inside each
 * segment, with no cloth term because there is no cloth sim here. Two of the
 * three land within a frame of the female's anyway, which is what you would
 * expect of one animation on two bodies.
 *
 * The seam is not the only thing a window has to get right, though: it also has
 * to survive `bestLoopEntry`, which re-enters at whichever frame matches the
 * outgoing pose best and will happily land in the middle of a window whose
 * start pose recurs inside it. See the talking entry below — that is what a
 * seam-only choice cost here.
 */
const MALE: AvatarConfig = {
  id: "male",
  url: "/models/male1.glb",
  // Served uncompressed — no .gz is built for this one, so the two are equal
  // and the progress readout needs no correction.
  bytes: { decoded: 36572724, encoded: 36572724 },
  segments: {
    // The best 4-second cycle in the breathing segment (seam 0.073) — and the
    // same window the female rig uses, arrived at independently here. Shorter
    // cycles score better in isolation (179-240 seams at 0.030) and longer ones
    // worse (58-240 at 0.112), but a 2-second idle is a cycle the eye learns
    // immediately, and at 0.073 rad spread over 54 joints this seam is under a
    // tenth of a degree each before the crossfade even touches it.
    breathing: { loop: [f(119), f(240)] },
    // The settled listening pose, entered AFTER the authored hands-rise at
    // 245-300 — the same window the female rig uses, and on this rig the best
    // in its segment by a clear margin (0.217; every window starting before 300
    // is worse, because it is still inside the rise). Starting at 240 instead,
    // as an earlier cut of this file did, put the hands-rise itself on loop and
    // left the rig transitioning forever instead of holding the pose.
    listening: { loop: [f(300), f(393)] },
    // The authored gesture performance, very nearly the window the female rig
    // uses — unsurprising, since it is the same animation.
    //
    // NOT the tightest-seaming window in the segment, deliberately. An earlier
    // cut of this file took f680-834, whose seam is 4x tighter (0.15 against
    // 0.64), and it was the bug that made this rig look like it was barely
    // talking. The reason is `bestLoopEntry`: at the seam it re-enters the loop
    // at whichever frame best matches the pose going out, and this clip returns
    // to the SAME held pose several times inside 680-834 (f680, f721, f722 and
    // f723 are identical to five decimals). So the entry frame was decided by
    // float noise among those ties, the loop settled into whatever tail it
    // landed in, and the gesturing ahead of that point never played — at worst
    // a 23-frame slice holding a near-static pose. Measured as the summed
    // motion actually reached per cycle: 1.5 for that window against 97.3 for
    // this one.
    //
    // So the window is chosen on how much of it survives the entry search, not
    // on the seam alone: every frame within tie-tolerance of the best entry
    // here sits inside 14 frames of the start, so at least 94% of the window
    // plays whichever way the ties break. 0.64 rad spread over 57 joints is
    // 0.6 degrees a joint, which the 0.35s crossfade covers easily.
    talking: { loop: [f(559), f(780)] },
  },
  // Measured off the rig: HeadEnd sits at 1.783 against girl15's 1.616.
  fallbackHeight: 1.85,
  // Girl15's 1.45 sits 0.029 below her Head_M joint (1.479); this is the same
  // offset below this rig's, at 1.632.
  headTargetY: 1.6,
  skinMaterials: new Set(["Std_Skin_Head", "Std_Skin_Arm", "Std_Skin_Leg"]),
  // No makeup on this rig — the pass would read back a texture to change nothing.
  faceMaterial: null,
  // This export carries no morph targets at ALL: not the 51 ARKit shapes A2F
  // drives, not an eyeBlink pair. So there is no lipsync and no blink for this
  // rig — the mouth holds its authored rest shape while MARI speaks. Fixing that
  // needs a re-export with blendshapes, not a change here.
  hasMorphs: false,
  a2f: null,
};

export const AVATARS: Record<AvatarId, AvatarConfig> = {
  female: FEMALE,
  male: MALE,
};

export const DEFAULT_AVATAR: AvatarId = "female";

export const avatarConfig = (id: AvatarId): AvatarConfig => AVATARS[id] ?? FEMALE;
