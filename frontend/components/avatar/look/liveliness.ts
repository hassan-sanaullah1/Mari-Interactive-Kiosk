/**
 * The kiosk's own copy, taken from the avatar lab's when the approved looks were
 * exported (2026-10-19). The lab keeps its copy in components/avatar/; the two
 * are separate on purpose, so an experiment in the lab never changes the kiosk.
 *
 * Small involuntary motion that keeps a presenter from reading as a statue.
 *
 * A face that holds a perfectly neutral mouth, never moves its eyes and keeps
 * its head locked to the body clip reads as robotic however well it is lit.
 * Three things here, each switchable, all driven through the ARKit face shapes
 * and the head bone the rigs already have:
 *
 *   smile      a resting smile, as a floor under whatever lipsync sets. Past a
 *              light smile the cheeks rise and the eyes narrow with it, as in
 *              a real (Duchenne) smile; a mouth-only smile reads as forced.
 *   gaze       eye fixations: mostly on the viewer with tiny drifts, and now
 *              and then a short glance away and back, like a real listener
 *   headDrift  a few degrees of slow, irregular head motion on top of the clip
 *
 * Call `updateLife` once per rendered frame AFTER the body animation and the
 * lipsync have been applied for that frame, so it layers on top of both.
 */

import * as THREE from "three";

export interface LifeOptions {
  /** Resting smile weight, 0 to about 0.4. 0 disables it. */
  smile: number;
  gaze: boolean;
  headDrift: boolean;
}

export const NO_LIFE: LifeOptions = { smile: 0, gaze: false, headDrift: false };
export const DEFAULT_LIFE: LifeOptions = { smile: 0.18, gaze: true, headDrift: true };

const SHAPES = [
  "mouthSmileLeft",
  "mouthSmileRight",
  "cheekSquintLeft",
  "cheekSquintRight",
  "eyeSquintLeft",
  "eyeSquintRight",
  "eyeLookInLeft",
  "eyeLookOutLeft",
  "eyeLookUpLeft",
  "eyeLookDownLeft",
  "eyeLookInRight",
  "eyeLookOutRight",
  "eyeLookUpRight",
  "eyeLookDownRight",
] as const;

type Shape = (typeof SHAPES)[number];

/**
 * Shape names are matched loosely: case-insensitive, and a doubled final letter
 * collapsed. The male export misspells two of them ("eyeLookUpRIght",
 * "eyeLookOutLeftt"), and an exact match would leave his eyes frozen.
 */
const looseName = (name: string): string => name.toLowerCase().replace(/(.)\1+$/, "$1");

/** Misspellings that loose matching cannot catch: the female export drops a letter. */
const ALIASES: Partial<Record<Shape, string[]>> = {
  cheekSquintRight: ["heekSquintRight"],
};

interface FaceMesh {
  influences: number[];
  index: Partial<Record<Shape, number>>;
}

export interface LifeRig {
  faces: FaceMesh[];
  head: THREE.Object3D | null;
  /** The head rotation this module last wrote, to undo it when nothing else moves the head. */
  lastHead: THREE.Quaternion;
  hasLastHead: boolean;
  lastOffset: THREE.Quaternion;
  gaze: { x: number; y: number; targetX: number; targetY: number; nextShift: number; returnAt: number };
  /** Whether a switch wrote shapes last frame, so turning it off clears them once. */
  wrote: { smile: boolean; gaze: boolean };
}

/** Find the face meshes and the head bone once, after the rig has loaded. */
export function createLifeRig(root: THREE.Object3D): LifeRig {
  const faces: FaceMesh[] = [];
  let head: THREE.Object3D | null = null;
  root.traverse((object) => {
    if (!head && /^head(_m)?$/i.test(object.name)) head = object;
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh || !mesh.morphTargetDictionary || !mesh.morphTargetInfluences) return;
    const loose = new Map(Object.entries(mesh.morphTargetDictionary).map(([n, i]) => [looseName(n), i]));
    const index: Partial<Record<Shape, number>> = {};
    for (const shape of SHAPES) {
      const names = [shape, ...(ALIASES[shape] ?? [])];
      const found = names.map((n) => loose.get(looseName(n))).find((i) => i !== undefined);
      if (found !== undefined) index[shape] = found;
    }
    if (Object.keys(index).length) faces.push({ influences: mesh.morphTargetInfluences, index });
  });
  return {
    faces,
    head,
    lastHead: new THREE.Quaternion(),
    hasLastHead: false,
    lastOffset: new THREE.Quaternion(),
    gaze: { x: 0, y: 0, targetX: 0, targetY: 0, nextShift: 1, returnAt: Infinity },
    wrote: { smile: false, gaze: false },
  };
}

// ── gaze ────────────────────────────────────────────────────────────────

/** Fixations last 0.6-2.8 s; one in five is a glance away, held ~0.5 s. */
const FIXATION_MIN_S = 0.6;
const FIXATION_SPREAD_S = 2.2;
const GLANCE_CHANCE = 0.2;
const GLANCE_HOLD_S = 0.5;
/** Saccades are fast: ~40 ms to land. */
const SACCADE_RATE = 25;
/** Shape weights: a small drift around the viewer, a larger glance. */
const DRIFT = { x: 0.08, y: 0.05 };
const GLANCE = { x: 0.35, y: 0.18 };

function stepGaze(rig: LifeRig, time: number, delta: number): void {
  const gaze = rig.gaze;
  if (time >= gaze.returnAt) {
    gaze.targetX = (Math.random() * 2 - 1) * DRIFT.x;
    gaze.targetY = (Math.random() * 2 - 1) * DRIFT.y;
    gaze.returnAt = Infinity;
  } else if (time >= gaze.nextShift) {
    const glance = Math.random() < GLANCE_CHANCE;
    const range = glance ? GLANCE : DRIFT;
    gaze.targetX = (Math.random() * 2 - 1) * range.x;
    gaze.targetY = (Math.random() * 2 - 1) * range.y;
    gaze.returnAt = glance ? time + GLANCE_HOLD_S : Infinity;
    gaze.nextShift = time + FIXATION_MIN_S + Math.random() * FIXATION_SPREAD_S;
  }
  const step = Math.min(1, delta * SACCADE_RATE);
  gaze.x += (gaze.targetX - gaze.x) * step;
  gaze.y += (gaze.targetY - gaze.y) * step;
}

const GAZE_SHAPES: Shape[] = [
  "eyeLookOutLeft",
  "eyeLookInRight",
  "eyeLookInLeft",
  "eyeLookOutRight",
  "eyeLookUpLeft",
  "eyeLookUpRight",
  "eyeLookDownLeft",
  "eyeLookDownRight",
];
// Reused every frame rather than returned fresh — this runs once per rendered
// frame for as long as the rig is alive, and a plain object literal there
// made updateLife a steady source of garbage for the GC to sweep.
const GAZE_VALUES: number[] = GAZE_SHAPES.map(() => 0);

/**
 * Positive x is towards her own left: the left eye looks out, the right eye in.
 * Positive y is up. Each direction is its own shape, so only one of a pair is set.
 */
function gazeWeights(x: number, y: number): number[] {
  const right = Math.max(0, -x);
  const left = Math.max(0, x);
  const up = Math.max(0, y);
  const down = Math.max(0, -y);
  GAZE_VALUES[0] = left; // eyeLookOutLeft
  GAZE_VALUES[1] = left; // eyeLookInRight
  GAZE_VALUES[2] = right; // eyeLookInLeft
  GAZE_VALUES[3] = right; // eyeLookOutRight
  GAZE_VALUES[4] = up; // eyeLookUpLeft
  GAZE_VALUES[5] = up; // eyeLookUpRight
  GAZE_VALUES[6] = down; // eyeLookDownLeft
  GAZE_VALUES[7] = down; // eyeLookDownRight
  return GAZE_VALUES;
}

// ── head ────────────────────────────────────────────────────────────────

const headEuler = new THREE.Euler();
// rig.lastHead used to be cloned fresh each frame just to hold last frame's
// value for comparison; one quaternion per rig, copied into instead, does the
// same job with no per-frame allocation.
const invertedOffset = new THREE.Quaternion();

/**
 * Layer a small rotation on the head bone. When the body clip drives the head
 * it overwrites the bone every frame and the offset is simply re-applied; when
 * nothing does (a T-pose), the previous offset is undone first so it cannot
 * accumulate.
 */
function driftHead(rig: LifeRig, time: number, enabled: boolean): void {
  const head = rig.head;
  if (!head) return;
  if (rig.hasLastHead && head.quaternion.equals(rig.lastHead)) {
    invertedOffset.copy(rig.lastOffset).invert();
    head.quaternion.multiply(invertedOffset);
  }
  if (!enabled) {
    rig.hasLastHead = false;
    return;
  }
  // Sums of slow, unrelated sines: irregular enough not to read as a loop.
  // Radians: about 1.5 deg of yaw, 1 deg of pitch, half a degree of roll. The
  // head also follows the eyes slightly, as heads do.
  const yaw = Math.sin(time * 0.23) * 0.018 + Math.sin(time * 0.61 + 1.3) * 0.008 + rig.gaze.x * 0.04;
  const pitch = Math.sin(time * 0.17 + 0.7) * 0.012 + Math.sin(time * 0.47) * 0.005 + rig.gaze.y * 0.03;
  const roll = Math.sin(time * 0.13 + 2.1) * 0.008;
  headEuler.set(pitch, yaw, roll);
  rig.lastOffset.setFromEuler(headEuler);
  head.quaternion.multiply(rig.lastOffset);
  rig.lastHead.copy(head.quaternion);
  rig.hasLastHead = true;
}

// ── per frame ───────────────────────────────────────────────────────────

/** Set some shapes on every face mesh. `shapes` and `values` run in parallel. */
function writeShapes(rig: LifeRig, shapes: readonly Shape[], values: readonly number[], floor: boolean): void {
  for (const { influences, index } of rig.faces) {
    for (let k = 0; k < shapes.length; k++) {
      const i = index[shapes[k]];
      if (i === undefined) continue;
      // A floor leaves lipsync free to pull the shape further; otherwise overwrite.
      influences[i] = floor ? Math.max(influences[i], values[k]) : values[k];
    }
  }
}

const SMILE_SHAPES: Shape[] = [
  "mouthSmileLeft",
  "mouthSmileRight",
  "cheekSquintLeft",
  "cheekSquintRight",
  "eyeSquintLeft",
  "eyeSquintRight",
];
const SMILE_VALUES: number[] = SMILE_SHAPES.map(() => 0);
const ZERO_SMILE_VALUES: number[] = SMILE_SHAPES.map(() => 0);
const ZERO_GAZE_VALUES: number[] = GAZE_SHAPES.map(() => 0);

/**
 * The smile's shape weights. Cheeks and eyes join in only past a light smile
 * (0.15), and stay below the mouth: at 0.45 the cheeks sit at ~0.2 and the eyes
 * at ~0.09, which narrows them without closing them.
 */
function smileWeights(smile: number): number[] {
  const engaged = Math.max(0, smile - 0.15);
  SMILE_VALUES[0] = smile; // mouthSmileLeft
  SMILE_VALUES[1] = smile; // mouthSmileRight
  SMILE_VALUES[2] = engaged * 0.7; // cheekSquintLeft
  SMILE_VALUES[3] = engaged * 0.7; // cheekSquintRight
  SMILE_VALUES[4] = engaged * 0.3; // eyeSquintLeft
  SMILE_VALUES[5] = engaged * 0.3; // eyeSquintRight
  return SMILE_VALUES;
}

export function updateLife(rig: LifeRig, options: LifeOptions, time: number, delta: number): void {
  if (options.smile > 0) {
    writeShapes(rig, SMILE_SHAPES, smileWeights(options.smile), true);
  } else if (rig.wrote.smile) {
    writeShapes(rig, SMILE_SHAPES, ZERO_SMILE_VALUES, false);
  }
  rig.wrote.smile = options.smile > 0;

  if (options.gaze) {
    stepGaze(rig, time, delta);
    writeShapes(rig, GAZE_SHAPES, gazeWeights(rig.gaze.x, rig.gaze.y), false);
  } else if (rig.wrote.gaze) {
    writeShapes(rig, GAZE_SHAPES, ZERO_GAZE_VALUES, false);
  }
  rig.wrote.gaze = options.gaze;

  driftHead(rig, time, options.headDrift);
}
