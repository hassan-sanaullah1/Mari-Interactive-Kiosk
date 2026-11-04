"use client";

/**
 * The scene pieces a presenter look is built from (profiles/looks.ts). Kiosk
 * only: the avatar lab has its own, so nothing tried in the lab reaches here.
 */

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import { createLifeRig, updateLife, type LifeOptions } from "./liveliness";
import {
  applyRealism,
  DEFAULT_REALISM_PARAMS,
  setRealismParams,
  type RealismOptions,
  type RealismParams,
  type RealismRig,
} from "./realism";
import type { FixedLightRig, LightPanel } from "../profiles/looks";

/**
 * A still light rig: key (the only caster), fill, two rims from behind and a
 * hemisphere bounce. Not eased per conversation state: it is one moment.
 */
export function FixedLights({ rig }: { rig: FixedLightRig }) {
  const { gl, scene } = useThree();
  const keyRef = useRef<THREE.DirectionalLight>(null);
  const { key, fill, rimLeft, rimRight, hemisphere, shadow } = rig;
  useEffect(() => {
    // Whatever the studio rig eased these towards, a fixed rig starts from neutral.
    gl.toneMappingExposure = 1;
    scene.environmentIntensity = 1;
    const light = keyRef.current;
    if (!light) return;
    light.shadow.intensity = shadow.intensity;
    // Aim the key, and its shadow box, at the body rather than the floor.
    light.target.position.set(0, shadow.targetY, 0);
    light.target.updateMatrixWorld();
  }, [gl, scene, shadow.intensity, shadow.targetY]);
  return (
    <>
      <hemisphereLight args={[hemisphere.sky, hemisphere.ground, hemisphere.intensity]} />
      <directionalLight
        ref={keyRef}
        position={key.position}
        color={key.color}
        intensity={key.intensity}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-bias={-0.0002}
        shadow-normalBias={0.01}
        shadow-camera-left={-shadow.extent}
        shadow-camera-right={shadow.extent}
        shadow-camera-top={shadow.extent}
        shadow-camera-bottom={-shadow.extent}
        shadow-camera-near={0.5}
        shadow-camera-far={8}
      />
      <directionalLight position={fill.position} color={fill.color} intensity={fill.intensity} />
      {/* Rims as directional lights from behind: they reach only edges and
          back-facing surfaces, never the front of the face. */}
      <directionalLight position={rimLeft.position} color={rimLeft.color} intensity={rimLeft.intensity} />
      <directionalLight position={rimRight.position} color={rimRight.color} intensity={rimRight.intensity} />
    </>
  );
}

/** Reflections only: an Environment with no `background` draws nothing, so the artwork stays visible. */
export function PanelEnvironment({ resolution, panels }: { resolution: number; panels: LightPanel[] }) {
  return (
    <Environment resolution={resolution}>
      {panels.map((panel, i) => (
        <Lightformer key={i} {...panel} />
      ))}
    </Environment>
  );
}

export function ToneMappingSync({ toneMapping }: { toneMapping: THREE.ToneMapping }) {
  const gl = useThree((s) => s.gl);
  useEffect(() => {
    // The renderer recompiles each material's program when this changes.
    gl.toneMapping = toneMapping;
  }, [gl, toneMapping]);
  return null;
}

/**
 * Blur radius for every shadow-casting light; only VSM shadows honour it, so
 * the canvas switches to VSM whenever softness is above 0. `strength` above 0
 * overrides each light's shadow darkness, every frame, after the lights' own
 * effects have set theirs.
 */
export function ShadowSoftness({ radius, strength }: { radius: number; strength: number }) {
  const scene = useThree((s) => s.scene);
  // Looking for the lights is not per-frame work: a traverse walks the whole rig
  // (1202 objects on the female model) to reach a handful of lights. The rigs
  // carry no lights of their own (no KHR_lights_punctual in any .glb), so every
  // caster is a direct child of the scene, put there by the light rig React
  // renders. The children are compared by identity, not by count, so a rig swap
  // that happens to keep the same number of lights still refreshes the list.
  const seenChildren = useRef<THREE.Object3D[]>([]);
  const casters = useRef<THREE.DirectionalLight[]>([]);
  useFrame(() => {
    const children = scene.children;
    const seen = seenChildren.current;
    let isChanged = children.length !== seen.length;
    for (let i = 0; !isChanged && i < children.length; i++) isChanged = children[i] !== seen[i];
    if (isChanged) {
      seenChildren.current = children.slice();
      const found: THREE.DirectionalLight[] = [];
      scene.traverse((object) => {
        const light = object as THREE.DirectionalLight;
        if (light.isLight && light.castShadow && light.shadow) found.push(light);
      });
      casters.current = found;
    }
    // The writes stay per-frame: the studio crossfade sets each light's shadow
    // intensity on its own frame callback, and this has to land after it.
    const lights = casters.current;
    for (let i = 0; i < lights.length; i++) {
      const light = lights[i];
      if (light.shadow.radius !== radius) {
        light.shadow.radius = radius;
        light.shadow.blurSamples = 16;
      }
      if (strength > 0) light.shadow.intensity = strength;
    }
  });
  return null;
}

/** Pushes the realism strengths into the shared uniforms; never recompiles. */
export function RealismParamsSync({ params }: { params: RealismParams }) {
  // Put the defaults back on unmount: the uniforms this writes are module-level
  // and outlive the look that set them, so a theme with no look of its own
  // otherwise keeps rendering with the previous look's skin tone values.
  useEffect(() => {
    setRealismParams(params);
    return () => setRealismParams(DEFAULT_REALISM_PARAMS);
  }, [params]);
  return null;
}

/**
 * The realism pass on the loaded rig. `version` changes whenever the rig (or
 * its material corrections) is rebuilt, so the pass is undone and laid again
 * on top of the current materials.
 */
export function RealismLayer({
  rig,
  realism,
  version,
}: {
  rig: RealismRig;
  realism: RealismOptions;
  version: unknown;
}) {
  const scene = useThree((s) => s.scene);
  useEffect(() => applyRealism(scene, rig, realism), [scene, rig, realism, version]);
  return null;
}

/**
 * Resting smile, eye movement and head drift, each frame. Mount it keyed on
 * the rig's load, so it subscribes AFTER the rig's own frame callbacks (body
 * mixer, lipsync, blink) and layers on top of them.
 */
export function LifeLayer({ root, options }: { root: THREE.Object3D; options: LifeOptions }) {
  const rig = useMemo(() => createLifeRig(root), [root]);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  useFrame((state, delta) => updateLife(rig, optionsRef.current, state.clock.elapsedTime, delta));
  return null;
}
