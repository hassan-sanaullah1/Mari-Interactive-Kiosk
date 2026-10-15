"use client";

/**
 * The rig exactly as exported: parsed straight from the file with three.js's
 * GLTFLoader, with none of AvatarModel's corrections (materials, makeup, hair
 * cut-offs, wrist scale, crossfades, blinking, lipsync).
 *
 * It parses its OWN copy rather than going through drei's useGLTF, because
 * AvatarModel edits the cached materials in place; sharing that cache would mean
 * "raw" showed the kiosk's corrections the moment the kiosk look had been
 * opened once. The bytes still come from the one shared download.
 */

import { useEffect, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { fetchAvatar } from "@/lib/avatar-fetch";
import { CLIP_NAME, type BodyState, type Segment } from "@/components/avatar/models";
import { disposeScene } from "./lab-tools";

/** A body segment, or the bind pose the rig was modelled in. */
export type LabPose = "tpose" | BodyState;

interface RawModelProps {
  url: string;
  segments: Record<BodyState, Segment>;
  pose: LabPose;
  /** Fires once parsed, with the scene, so the lab can inspect and frame it. */
  onLoaded: (scene: THREE.Object3D) => void;
}

interface Rest {
  object: THREE.Object3D;
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
  scale: THREE.Vector3;
}

/** Every node's local transform as loaded, i.e. the bind pose. */
function captureRest(root: THREE.Object3D): Rest[] {
  const rest: Rest[] = [];
  root.traverse((object) =>
    rest.push({
      object,
      position: object.position.clone(),
      quaternion: object.quaternion.clone(),
      scale: object.scale.clone(),
    }),
  );
  return rest;
}

export default function RawModel({ url, segments, pose, onLoaded }: RawModelProps) {
  const [gltf, setGltf] = useState<{ scene: THREE.Group; clip: THREE.AnimationClip | null } | null>(
    null,
  );
  const mixerRef = useRef<THREE.AnimationMixer | null>(null);
  const actionRef = useRef<THREE.AnimationAction | null>(null);
  const restRef = useRef<Rest[]>([]);
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  useEffect(() => {
    let cancelled = false;
    let loaded: THREE.Group | null = null;
    fetchAvatar(url)
      .then((bytes) => new GLTFLoader().parseAsync(bytes, ""))
      .then((result) => {
        if (cancelled) {
          disposeScene(result.scene);
          return;
        }
        loaded = result.scene;
        restRef.current = captureRest(result.scene);
        const clip = result.animations.find((c) => c.name === CLIP_NAME) ?? result.animations[0] ?? null;
        setGltf({ scene: result.scene, clip });
        onLoadedRef.current(result.scene);
      })
      .catch((error) => console.error("[lab] raw rig failed to load:", error));
    return () => {
      cancelled = true;
      if (loaded) disposeScene(loaded);
    };
  }, [url]);

  useEffect(() => {
    if (!gltf?.clip) return;
    const mixer = new THREE.AnimationMixer(gltf.scene);
    const action = mixer.clipAction(gltf.clip);
    // Time is written by hand each frame, the same way AvatarModel drives it.
    action.paused = true;
    mixerRef.current = mixer;
    actionRef.current = action;
    return () => {
      mixer.stopAllAction();
      mixer.uncacheRoot(gltf.scene);
      mixerRef.current = null;
      actionRef.current = null;
    };
  }, [gltf]);

  useEffect(() => {
    const action = actionRef.current;
    if (!action) return;
    if (pose === "tpose") {
      action.stop();
      for (const rest of restRef.current) {
        rest.object.position.copy(rest.position);
        rest.object.quaternion.copy(rest.quaternion);
        rest.object.scale.copy(rest.scale);
      }
      return;
    }
    action.play();
    action.paused = true;
    action.time = segments[pose].loop[0];
  }, [pose, segments, gltf]);

  // A plain wrap at the loop end, no crossfade: this is the clip as authored.
  useFrame((_, delta) => {
    const action = actionRef.current;
    const mixer = mixerRef.current;
    if (!action || !mixer || pose === "tpose") return;
    const [start, end] = segments[pose].loop;
    let time = action.time + delta;
    if (time > end) time = start + (time - end);
    action.time = time;
    mixer.update(0);
  });

  return gltf ? <primitive object={gltf.scene} /> : null;
}
