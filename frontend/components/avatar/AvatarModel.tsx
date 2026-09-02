"use client";

/**
 * girl14.glb — the MARI presenter.
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
 * This rig succeeded girl11 through girl13. Its face is literally theirs — all
 * 561 morph target accessors are byte-identical to girl11's, under identical
 * names — so everything the mouth does ports across untouched. It keeps
 * girl13's baked cloth simulation (975 `a_cloth_parent_vtx_*_JNT` joints on a
 * second skin, ~10x the animated nodes of the rigs before it), which is what
 * the loop windows below have to account for.
 *
 * The body clip is girl13's re-authored, not merely re-exported: same length
 * and same three segments, but a calmer idle (breathing moves ~0.004 per frame
 * against girl13's 0.014–0.031) and a dead hold at the head that runs to ~38
 * rather than ~30. The windows below were re-derived against it regardless, and
 * landed on the same frames — so they are this clip's own optimum, not
 * inherited numbers that happen to still parse.
 *
 * girl12.glb shipped with its morph NAMES shifted one place against that same
 * geometry, which drove every named morph onto its neighbour's shape — one eye
 * blinking, and jawOpen quietly driving mouthClose. girl14 is correct (checked:
 * the list matches girl11's, and the eyeBlink pair is mirror-symmetric), but
 * nothing about that failure points at the name list, so the check below keeps
 * watching for it.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { useAnimations, useGLTF } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { applyA2FLipsync, createA2FMorphState } from "@/lib/a2fMorphs";
import { setRigCalibration } from "@/lib/blendshapePlayer";
import type { AvatarState } from "./state";

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
const FPS = 30;
const CLIP_NAME = "CINEMA_4D_Main";

type BodyState = "breathing" | "listening" | "talking";

interface Segment {
  /** Authored lead-in played once on entry, when arriving from `after`. */
  intro: [number, number] | null;
  /** Which previous state makes `intro` the natural path in. */
  after: BodyState | null;
  loop: [number, number];
}

const SEGMENTS: Record<BodyState, Segment> = {
  // Starts at 119, not 0: the clip opens on ~38 frames of frozen pose, and of
  // the breathing cycles that follow this is the pair whose cloth agrees as
  // well as the body does (body 0.005, cloth 0.036 — one frame's worth).
  breathing: { intro: null, after: null, loop: [119 / FPS, 241 / FPS] },
  // Frames 241–300 are the authored hands-rise out of the at-rest pose: it
  // leaves the breathing cycle where the loop ends and the arms are settled
  // by 300. (body 0.070, cloth 0.245 at the loop seam.)
  listening: { intro: [241 / FPS, 300 / FPS], after: "breathing", loop: [300 / FPS, 393 / FPS] },
  // Frames 393–558 are the authored settle-into-gesturing — much longer than
  // the other intro, but it is all gesturing, and starting the loop here rather
  // than at 490 halves the cloth drift at the seam (body 0.002, cloth 1.10).
  talking: { intro: [393 / FPS, 558 / FPS], after: "listening", loop: [558 / FPS, 780 / FPS] },
};

/** Crossfade (s) hiding a loop seam — both ends are near-identical poses. */
const LOOP_XFADE_SECS = 0.35;
/** Crossfade (s) when switching segments — poses differ, so blend longer. */
const SWITCH_XFADE_SECS = 0.55;

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
const A2F_GAIN = 0.9;
const A2F_SHAPE_GAINS: Record<string, number> = { jawopen: 0.375 };

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
const SKIN_MATERIALS = new Set(["lambert11", "lambert13", "lambert12"]);

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
const SKIN_EMISSIVE_INTENSITY = 0.25;

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
  /** True while playing the segment's one-shot intro rather than its loop. */
  inIntro: boolean;
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
  inIntro: false,
  time: 0,
  weight: 0,
  targetWeight: 0,
  fadeRate: 0,
});

/**
 * Hand the pool a new segment: it fades in on a free layer while every other
 * layer fades out. Picking a free layer (rather than reusing the one being
 * faded out of) is what keeps an interrupted fade from snapping.
 */
function beginSegment(
  layers: Layer[],
  activeIndexRef: { current: number },
  state: BodyState,
  useIntro: boolean,
  fadeSecs: number,
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

  const segment = SEGMENTS[state];
  const incoming = layers[index];
  incoming.state = state;
  incoming.inIntro = useIntro;
  incoming.time = useIntro ? segment.intro![0] : segment.loop[0];
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
 * Advance one layer through its segment: run the one-shot intro if it is in
 * one, then hold inside the loop window. The loop end is clamped rather than
 * wrapped — a layer only reaches it while its replacement is already fading in,
 * and wrapping there would snap the pose behind the fade.
 */
function advanceLayer(layer: Layer, delta: number): void {
  const segment = SEGMENTS[layer.state];
  layer.time += delta;

  if (layer.inIntro) {
    const introEnd = segment.intro![1];
    if (layer.time >= introEnd) {
      layer.inIntro = false;
      layer.time = segment.loop[0] + (layer.time - introEnd);
    } else {
      return;
    }
  }

  const [loopStart, loopEnd] = segment.loop;
  if (layer.time < loopStart) layer.time = loopStart;
  if (layer.time > loopEnd) layer.time = loopEnd;
}

export interface AvatarModelProps {
  url: string;
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

export default function AvatarModel({ url, state = "idle", onMeasure, onReady }: AvatarModelProps) {
  const { scene, animations } = useGLTF(url);
  const groupRef = useRef<THREE.Group>(null);
  const blinkRef = useRef({ nextBlink: 2, blinkProgress: 0 });
  const a2fStateRef = useRef(createA2FMorphState());

  // This rig gets its own amplitude calibration; restore the shared defaults on
  // unmount.
  useEffect(() => {
    setRigCalibration({ gain: A2F_GAIN, shapeGains: A2F_SHAPE_GAINS });
    return () => setRigCalibration(null);
  }, []);

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
    const loopStart = SEGMENTS[initial].loop[0];
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
      layer.inIntro = false;
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
  }, [actions, animations, mixer]);

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

        if (std.map) {
          std.map.anisotropy = maxAnisotropy;
          std.map.needsUpdate = true;
        }

        // Face and hands only — see SKIN_MATERIALS. Driving the emissive from
        // the diffuse map keeps the skin's own shading; a flat emissive colour
        // would fill the shadow side of the face and flatten it.
        if (SKIN_MATERIALS.has(std.name)) {
          std.emissiveMap = std.map;
          std.emissive.setRGB(1, 1, 1);
          std.emissiveIntensity = SKIN_EMISSIVE_INTENSITY;
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
  }, [scene, gl]);

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
    const dict = morphMeshes[0]?.morphTargetDictionary;
    if (!dict) return;
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
  }, [morphMeshes, url]);

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
        const segment = SEGMENTS[target];
        // Take the authored lead-in only when arriving along the path the clip
        // was animated for; otherwise cut straight to the loop and let the
        // crossfade carry the pose change.
        const useIntro = segment.intro !== null && segment.after === active.state;
        // An intro is authored to pick up from its `after` segment's loop end,
        // not from wherever that loop happens to be mid-cycle (or, worse,
        // from partway through that segment's own intro). Firing early
        // crossfades two genuinely different poses (e.g. listening's hands
        // held together against talking's intro starting arms-apart), which
        // reads as a snap. Hold until the active layer has settled into its
        // loop and reached the seam — same wait the self loop-seam crossfade
        // below already uses — and only then hand off into the intro.
        if (useIntro && active.inIntro) {
          // Still playing the active segment's own lead-in: its pose hasn't
          // reached that segment's loop yet, so there is nothing valid to
          // seam into. Keep waiting.
        } else if (useIntro) {
          const activeLoopEnd = SEGMENTS[active.state].loop[1];
          if (active.time < activeLoopEnd - SWITCH_XFADE_SECS) {
            // Not yet at the seam: keep looping in place.
          } else {
            beginSegment(layers, activeLayerRef, target, useIntro, SWITCH_XFADE_SECS);
          }
        } else {
          beginSegment(layers, activeLayerRef, target, useIntro, SWITCH_XFADE_SECS);
        }
      } else if (active.weight >= 0.999 && !active.inIntro) {
        // Settled on a segment: start the seam crossfade one fade-length before
        // the loop end, so the incoming copy is up to speed by the time the
        // outgoing one runs out of frames.
        const loopEnd = SEGMENTS[active.state].loop[1];
        if (active.time >= loopEnd - LOOP_XFADE_SECS) {
          beginSegment(layers, activeLayerRef, active.state, false, LOOP_XFADE_SECS);
        }
      }

      for (const layer of layers) {
        if (!layer.action) continue;
        if (layer.weight <= 0 && layer.targetWeight <= 0) {
          layer.action.weight = 0;
          continue;
        }
        // Fading-out layers keep playing rather than freezing — a body that
        // stops mid-motion behind the fade is visible even at low weight.
        advanceLayer(layer, delta);
        const step = delta * layer.fadeRate;
        layer.weight =
          layer.targetWeight > layer.weight
            ? Math.min(layer.weight + step, layer.targetWeight)
            : Math.max(layer.weight - step, layer.targetWeight);
        layer.action.weight = layer.weight;
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
