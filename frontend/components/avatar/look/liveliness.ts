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
  lastHead: THREE.Quaternion | null;
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
    lastHead: null,
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

/**
 * Positive x is towards her own left: the left eye looks out, the right eye in.
 * Positive y is up. Each direction is its own shape, so only one of a pair is set.
 */
function gazeWeights(x: number, y: number): Partial<Record<Shape, number>> {
  const right = Math.max(0, -x);
  const left = Math.max(0, x);
  const up = Math.max(0, y);
  const down = Math.max(0, -y);
  return {
    eyeLookOutLeft: left,
    eyeLookInRight: left,
    eyeLookInLeft: right,
    eyeLookOutRight: right,
    eyeLookUpLeft: up,
    eyeLookUpRight: up,
    eyeLookDownLeft: down,
    eyeLookDownRight: down,
  };
}

// ── head ────────────────────────────────────────────────────────────────

const headEuler = new THREE.Euler();

/**
 * Layer a small rotation on the head bone. When the body clip drives the head
 * it overwrites the bone every frame and the offset is simply re-applied; when
 * nothing does (a T-pose), the previous offset is undone first so it cannot
 * accumulate.
 */
function driftHead(rig: LifeRig, time: number, enabled: boolean): void {
  const head = rig.head;
  if (!head) return;
  if (rig.lastHead && head.quaternion.equals(rig.lastHead)) {
    head.quaternion.multiply(rig.lastOffset.clone().invert());
  }
  if (!enabled) {
    rig.lastHead = null;
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
  rig.lastHead = head.quaternion.clone();
}

// ── per frame ───────────────────────────────────────────────────────────

/** Set some shapes on every face mesh. */
function writeShapes(rig: LifeRig, weights: Partial<Record<Shape, number>>, floor: boolean): void {
  for (const { influences, index } of rig.faces) {
    for (const [shape, weight] of Object.entries(weights) as [Shape, number][]) {
      const i = index[shape];
      if (i === undefined) continue;
      // A floor leaves lipsync free to pull the shape further; otherwise overwrite.
      influences[i] = floor ? Math.max(influences[i], weight) : weight;
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

/**
 * The smile's shape weights. Cheeks and eyes join in only past a light smile
 * (0.15), and stay below the mouth: at 0.45 the cheeks sit at ~0.2 and the eyes
 * at ~0.09, which narrows them without closing them.
 */
function smileWeights(smile: number): Partial<Record<Shape, number>> {
  const engaged = Math.max(0, smile - 0.15);
  return {
    mouthSmileLeft: smile,
    mouthSmileRight: smile,
    cheekSquintLeft: engaged * 0.7,
    cheekSquintRight: engaged * 0.7,
    eyeSquintLeft: engaged * 0.3,
    eyeSquintRight: engaged * 0.3,
  };
}
const zeroes = (shapes: readonly Shape[]) => Object.fromEntries(shapes.map((s) => [s, 0]));

export function updateLife(rig: LifeRig, options: LifeOptions, time: number, delta: number): void {
  if (options.smile > 0) {
    writeShapes(rig, smileWeights(options.smile), true);
  } else if (rig.wrote.smile) {
    writeShapes(rig, zeroes(SMILE_SHAPES), false);
  }
  rig.wrote.smile = options.smile > 0;

  if (options.gaze) {
    stepGaze(rig, time, delta);
    writeShapes(rig, gazeWeights(rig.gaze.x, rig.gaze.y), false);
  } else if (rig.wrote.gaze) {
    writeShapes(rig, gazeWeights(0, 0), false);
  }
  rig.wrote.gaze = options.gaze;

  driftHead(rig, time, options.headDrift);
}
