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
 */

/**
 * The rate the windows below are quoted in, and the rate the pose index samples
 * at. girl15's clip is authored at 30fps; male3's is the same animation exported
 * at 24fps, whose windows are still quoted as 30fps frames because a window is a
 * position in seconds, not a keyframe — see MALE.
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
  // The original value, from when this was a module constant — she is the rig
  // it was tuned against, so it stays exactly as it was.
  skinEmissive: 0.25,
  // Her skin declares roughnessFactor 0.5 in the glTF; nothing to correct.
  skinRoughness: null,
  // She is the rig the other is matched TO, so nothing is scaled here and her
  // appearance is exactly what it was before male1 existed.
  materialTint: {},
  faceMaterial: "lambert12",
  hasMorphs: true,
  a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
};

/**
 * male3.glb — the alternate presenter. (Built by scripts/optimize_glb.py from
 * male_inital03.glb; see the `--keep-windows` note at the end of this comment.)
 *
 * male_inital03 is a re-export of male_inital02 (which built male2.glb), and was
 * diffed against it rather than re-measured from scratch. Same 116 nodes, same
 * 109-joint skin, same UVs and weights, and all 51 morph targets byte-identical
 * on every primitive whose vertex count did not change. What did change:
 *
 *   - The head texture (`Std_Skin_Head_Diffuse4`): a repainted face, 114 mean
 *     luminance where it lands on the front of the face against the old 139.
 *   - The beard (16522 -> 16834 verts) and brows (3368 -> 3370) were rebuilt.
 *     Their jawOpen/mouthFunnel deltas were re-checked against the geometry:
 *     jawOpen still drops the beard by 0.0306 at peak, mean (0, -0.016,
 *     -0.009), exactly as on male2, so the beard still follows the jaw.
 *   - The clip is exported at 24fps (716 keys over 29.79s) instead of 30fps
 *     (894 keys). Sampled at the same seconds, the body pose matches male2's
 *     to 0.00 rad over all 109 joints — the same motion, resampled.
 *
 * Everything below that was measured on male2 is therefore kept, and was re-run
 * on this rig where the resample could have moved it. The loop windows in
 * particular reproduce male2's behaviour through the simulated entry search to
 * the frame (re-entries at f155, f303 and f577; crossfade gap within 1%), so
 * they are left in male2's 30fps frame numbers rather than snapped to 24fps
 * keys, which would have changed the loops for no gain.
 *
 * Replaces male1.glb, whose one real defect was that it carried NO morph targets
 * — so it had no lipsync and no blink, and drove a jaw bone as a stand-in. This
 * export carries the same 51 ARKit blendshapes the female rig does, verified
 * against the live NIM's name list: 50 of A2F's 52 shapes land, the two that do
 * not being `TongueOut` (no morph on either rig) and `EyeLookOutLeft`, which this
 * export misspells "eyeLookOutLeftt". That is an eye-dart shape carrying no
 * speech, and the female rig has an exactly equivalent typo (`heekSquintRight`),
 * so this rig reaches the mouth with the same fidelity she does.
 *
 * Same skeleton as girl15 (all 109 of its `DeformationSystem` joints, plus jaw
 * and eye bones girl15 lacks) and the SAME AUTHORED ANIMATION retargeted onto a
 * different body — same clip name, same 894 frames, and the same three segments
 * in the same places as male1 and the female rig:
 *
 *   0-38    dead hold at the head of the clip, skipped
 *   38-245  breathing  (at-rest idle)
 *   245-393 listening  (hands rise at 245-300, then a settled listening pose)
 *   393-893 talking    (an authored settle-in, then the gesturing)
 *
 * The WINDOWS inside those segments were cut against THIS rig's curves rather
 * than copied — summed quaternion angle over its 109 rotation channels, no cloth
 * term because there is no cloth sim here.
 *
 * The seam is not the only thing a window has to get right, though: it also has
 * to survive `bestLoopEntry`, which re-enters at whichever frame matches the
 * outgoing pose best and will happily land deep inside a window whose start pose
 * recurs there. So each window below was scored by SIMULATING that search — take
 * the pose at loopEnd-0.35s, run the same nearest-frame scan over the same
 * excluded tail, and measure how much of the window still plays. That is what
 * chose breathing and rejected the seam-optimal alternatives:
 *
 *   breathing  seam-best [41-141] (0.019) re-enters at f111 and plays 29% of the
 *              cycle; [137-219] seams at 0.037 and plays 2.13s of its 2.73s.
 *   listening  seam-best [305-406] (0.055) re-enters at f384 and plays 11%;
 *              [300-393] seams at 0.059 and plays 98%.
 *
 * An idle is periodic, so its start pose genuinely recurs and some loss there is
 * unavoidable — the point is to pick the window that loses least, not to expect
 * none. This is the same failure mode male1's talking window hit, caught here by
 * measurement rather than by eye.
 *
 * If any window here changes, re-run the optimizer with the new numbers, given
 * in the CLIP'S 24fps frames (the script reads the rate off the keys and adds a
 * frame of margin each side) — so 137-219 at 30fps is 109.6-175.2, kept as:
 *   python scripts/optimize_glb.py male_inital03.glb male3.glb \
 *       --keep-windows 109-176,240-315,447-624
 * then delete the male3.glb.gz it also writes (this rig is served raw, see
 * `bytes`). It strips keyframes outside the windows, so a widened window seeks
 * into frames that are no longer in the file.
 */
const MALE: AvatarConfig = {
  id: "male",
  // The raw export, NOT run through scripts/optimize_glb.py — served as-is while
  // the rig is still being iterated on. male_inital05 is male_inital04 with a
  // warmer head texture (Std_Skin_Head_Diffuse6, 135 mean luminance against 04's
  // 143) and a rebuilt beard (16912 verts). Everything else matches 04: same
  // skeleton and 24fps clip (keys to 0.001), same materials, and all 51 morph
  // targets identical on every primitive but the beard, whose jawOpen still drops
  // it by 0.0306 as before — so A2F lipsync, blink and the loop windows below are
  // unchanged. (04 was 03 with a lighter head texture and its own beard rebuild.)
  url: "/models/male_inital05.glb",
  // Served uncompressed, so the two are equal and the progress readout needs no
  // correction. 65MB, against the 39MB the optimizer would make of it.
  bytes: { decoded: 65255428, encoded: 65255428 },
  segments: {
    // One full breathing cycle. The idle is periodic at ~82 frames (2.73s), with
    // troughs at f137 and f219, so this is a whole number of cycles and the loop
    // keeps its phase. Seam 0.037 rad over 109 joints — two hundredths of a
    // degree each.
    //
    // Chosen over the tighter-seaming [41-141] and [119-240] because of the
    // entry search: those re-enter at f111 and f201 and play 29% and 31% of
    // their cycle, against 78% here. See the comment above this object.
    breathing: { loop: [f(137), f(219)] },
    // The settled listening pose, entered AFTER the authored hands-rise at
    // 245-300 — the same window the female rig uses, and on this rig the right
    // one for the entry search rather than the seam: it re-enters at f302, two
    // frames in, and plays 98% of its 3.1s. The seam-optimal [305-406] (0.055
    // against this window's 0.059) re-enters at f384 and plays 11%.
    listening: { loop: [f(300), f(393)] },
    // The authored gesture performance — the same window male1 used and very
    // nearly the female's, unsurprising since it is the same animation.
    //
    // NOT the tightest-seaming window in the segment, deliberately, and this is
    // the case that taught the lesson above. The seam-optimal [653-853] (0.118
    // against this window's 0.164) carries LESS motion per cycle than this one
    // even before the entry search: 19.1 against 22.9. On male1 an equivalent
    // seam-only choice re-entered among tied held poses and left the rig looking
    // like it was barely talking.
    //
    // Scored the same way as the others: this re-enters at f577, 18 frames in,
    // and still plays 6.77s of its 7.37s — 89% of the window and the most
    // absolute motion (20.4 rad) of any candidate. 0.164 rad over 109 joints is
    // a tenth of a degree each, which the 0.35s crossfade covers easily.
    talking: { loop: [f(559), f(780)] },
  },
  // Measured off the rig: HeadEnd sits at 1.784 against girl15's 1.616 (and
  // male1's 1.783 — same skeleton, same proportions).
  fallbackHeight: 1.85,
  // Girl15's 1.45 sits 0.029 below her Head_M joint (1.479); this is the same
  // offset below this rig's, at 1.632.
  headTargetY: 1.6,
  // The head skin is `lambert5` here, NOT the `Std_Skin_Head` male1 named it:
  // this export renames the head material while keeping Std_Skin_Arm/Leg. On
  // male2 its texture was the one male1's head used; male3 repaints it — see
  // the lambert5 note in materialTint below.
  skinMaterials: new Set(["lambert5", "Std_Skin_Arm", "Std_Skin_Leg"]),
  // Zero, unlike the female rig's 0.25. The lift exists to open up the shadow
  // side of a face that has one; his albedo is already 36% brighter than hers,
  // and because emissive ignores the light rig entirely, on him it did not
  // reveal shading so much as erase it — the hard bright band across his
  // forehead and nose was this term sitting on top of an already-bright
  // texture. Measured over the face through the same lights: at 0.10 his p95
  // luminance was 169 against her 150; at 0 with the tint below he is at 147,
  // with the same spread of light to dark (std 47.5 against her 45.5).
  skinEmissive: 0,
  // null, unlike male1's 0.5. That override existed because male1 omitted
  // roughnessFactor on its skin and so loaded at glTF's 1.0 default; this export
  // authors 0.553 on all three skin materials (and a real value on every other
  // material too), so there is nothing left to correct and forcing 0.5 would
  // just overwrite what the artist set.
  //
  // male_inital04 and 05 drop roughnessFactor on lambert5 (the head), so it would
  // load at glTF's fully rough 1.0 default. 0.5 is what 03 authored on the head;
  // it also moves the arms and legs from 0.553 to 0.5, which is not visible.
  skinRoughness: 0.5,
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
  // Unlike male1, this export carries the full 51 ARKit shapes on one 12-primitive
  // mesh, so lipsync and blink both run the same code the female rig does.
  // Checked the way girl12's shifted-name bug taught us to: the names align with
  // the geometry (eyeBlinkLeft/Right are mirror-symmetric at x -0.0035/+0.0036
  // with matching y drops, jawOpen drops the jaw by 0.027, smile L/R are opposed)
  // rather than merely being present and plausible.
  hasMorphs: true,
  // The female rig's calibration, unchanged. It is a property of what the NIM
  // emits (JawOpen peaking past 2.5 while the lip shapes sit under 1) far more
  // than of the rig, and these two rigs carry the same authored blendshapes at
  // the same amplitudes — the jawOpen delta here is 0.027 against her 0.025.
  // Worth a look on screen even so; ?a2fGain= and ?a2fShapes= retune it live.
  a2f: { gain: 0.9, shapeGains: { jawopen: 0.375 } },
};

export const AVATARS: Record<AvatarId, AvatarConfig> = {
  female: FEMALE,
  male: MALE,
};

export const DEFAULT_AVATAR: AvatarId = "female";

export const avatarConfig = (id: AvatarId): AvatarConfig => AVATARS[id] ?? FEMALE;
