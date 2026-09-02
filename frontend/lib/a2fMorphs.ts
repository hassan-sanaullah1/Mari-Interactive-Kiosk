/**
 * Applies Audio2Face blendshape weights to the avatar's morph targets.
 *
 * Ported from the working implementation (THREEJS_A2F_INTEGRATION.md §9/§11),
 * trimmed to the path girl14.glb actually takes.
 *
 * That rig carries the ARKit blendshape names verbatim (jawOpen, mouthFunnel,
 * mouthPucker, mouthRollLower, …) — exactly the vocabulary A2F-3D emits in
 * `skel_animation_header.blend_shapes` — so `resolve()` matches by name, 1:1,
 * at scale 1. The source repo's ARKIT_TO_METAHUMAN mapping table and its
 * coarse-viseme anti-conflict constraints exist for its *other* rigs and never
 * engage for this one (§15.4/§15.7), so they are deliberately not ported: this
 * app has one rig, and carrying dead code for the other rigs' vocabulary would
 * only obscure which path runs.
 *
 * A2F emits 52 shapes; 50 land. `tongueOut` has no morph on this rig and
 * `cheekSquintRight` is misspelled "heekSquintRight" in the rig itself — both
 * are known, accepted, and carry no speech (§15.6).
 *
 * Called once per render frame from the avatar's useFrame. When no clip covers
 * the audio playhead, the morphs it drove decay back to rest — there is no
 * fallback mouth animation by design.
 */

import * as THREE from "three";
import { isDisabled, sample as sampleBlendshapes } from "./blendshapePlayer";

interface ResolvedMesh {
  mesh: THREE.SkinnedMesh | THREE.Mesh;
  /** Morph index each clip blendshape drives, or -1 when the rig has no match. */
  drives: Int32Array;
  /** Every morph index this clip can touch, deduped — drives apply + decay. */
  touched: Int32Array;
  /** Scratch accumulator by morph index — summed, then clamped, then written. */
  accum: Float32Array;
}

export interface A2FMorphState {
  names: string[] | null;
  meshes: ResolvedMesh[];
  /** True while morphs still hold non-rest values from a clip. */
  active: boolean;
  /**
   * Ramp in/out of A2F over ~125ms. Batched frame delivery can starve briefly
   * mid-sentence; a hard flip at each seam reads as lipsync "stopping and
   * resuming", so amplitude is faded instead.
   */
  mix: number;
}

export function createA2FMorphState(): A2FMorphState {
  return { names: null, meshes: [], active: false, mix: 0 };
}

function resolve(
  state: A2FMorphState,
  names: string[],
  morphMeshes: (THREE.SkinnedMesh | THREE.Mesh)[],
): void {
  state.names = names;
  const report: string[] = [];

  state.meshes = morphMeshes.map((mesh) => {
    const dict = mesh.morphTargetDictionary!;
    // Case-insensitive: A2F's casing (e.g. "EyeBlinkLeft") and the GLB's
    // (e.g. "eyeBlinkLeft") are not guaranteed to agree (§15.5).
    const lower: Record<string, number> = {};
    for (const key of Object.keys(dict)) lower[key.toLowerCase()] = dict[key];

    const drives = new Int32Array(names.length);
    const touched = new Set<number>();
    let matched = 0;

    for (let i = 0; i < names.length; i++) {
      const idx = lower[names[i].toLowerCase()];
      if (idx === undefined) {
        drives[i] = -1;
        continue;
      }
      drives[i] = idx;
      touched.add(idx);
      matched++;
    }

    report.push(`${mesh.name}: ${matched}/${names.length}`);
    return {
      mesh,
      drives,
      touched: Int32Array.from(touched),
      accum: new Float32Array(mesh.morphTargetInfluences!.length),
    };
  });

  console.log(`[A2F] resolved ${names.length} blendshapes → ${report.join(" | ")}`);
}

/**
 * Sample the active clip and drive the morph targets. Returns the current A2F
 * amplitude mix in [0, 1] (1 = fully driven by A2F).
 */
export function applyA2FLipsync(
  state: A2FMorphState,
  morphMeshes: (THREE.SkinnedMesh | THREE.Mesh)[],
  delta: number,
): number {
  if (isDisabled()) return 0;
  const s = sampleBlendshapes();

  // Ramp toward the target over ~125ms in either direction.
  const target = s ? 1 : 0;
  state.mix += (target - state.mix) * Math.min(1, delta * 8);
  if (state.mix < 0.01 && target === 0) state.mix = 0;

  if (s) {
    if (state.names !== s.names) resolve(state, s.names, morphMeshes);

    // The keyframes were already time-interpolated in blendshapePlayer; this
    // lerp only smooths the render-rate remainder (~50ms time constant).
    const alpha = Math.min(1, delta * 20);
    for (const { mesh, drives, touched, accum } of state.meshes) {
      const influences = mesh.morphTargetInfluences!;

      // Sum first, write second — accumulating leaves the door open for two
      // clip shapes resolving onto the same morph index without clobbering.
      for (const idx of touched) accum[idx] = 0;
      for (let i = 0; i < drives.length; i++) {
        const idx = drives[i];
        if (idx < 0) continue;
        accum[idx] += s.weights[i];
      }

      for (let t = 0; t < touched.length; t++) {
        const idx = touched[t];
        // Influences past 1 tear the mesh.
        const want = Math.min(Math.max(accum[idx], 0), 1) * state.mix;
        influences[idx] += (want - influences[idx]) * alpha;
      }
    }
    state.active = true;
    return state.mix;
  }

  // No frames covering the playhead — decay what the last ones left behind
  // rather than snapping the face to neutral.
  if (state.active) {
    let residual = 0;
    for (const { mesh, touched } of state.meshes) {
      const influences = mesh.morphTargetInfluences!;
      for (const idx of touched) {
        influences[idx] = THREE.MathUtils.lerp(influences[idx], 0, delta * 10);
        if (influences[idx] > residual) residual = influences[idx];
      }
    }
    if (residual < 0.01) state.active = false;
  }

  return state.mix;
}
