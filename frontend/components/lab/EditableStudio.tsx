"use client";

/**
 * The lab's editable copy of the kiosk's studio and camera (lab-rig.ts),
 * rendered the way the kiosk renders the real ones:
 *
 *   EditableStudioLights   DynamicLighting's six lights and ambient, with the
 *                          same per-state brightness, fill and back-light
 *                          multipliers, shadow and aim points — read from the
 *                          lab copy instead of tuning.ts. No easing: an edit
 *                          shows at once, and the voice boost is left out.
 *   LightHandles           a coloured ball per light; the selected one can be
 *                          dragged in 3D.
 *   EditablePanels         the studio's reflection panels, from the copy.
 *   LabFraming             Framing's camera maths with every number editable.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer, TransformControls } from "@react-three/drei";
import * as THREE from "three";
import type { AvatarState } from "@/components/avatar/state";
import type { Studio, ThemeLighting } from "@/components/avatar/tuning";
import { LIGHT_NAMES, type LabCameraRig, type LightName, type RigCamera, type RigLighting } from "./lab-rig";

type Vec3 = [number, number, number];

interface EditableStudioLightsProps {
  studio: Studio;
  lighting: ThemeLighting;
  backLight: RigLighting["backLight"];
  state: AvatarState;
  headTargetY: number;
}

/** Brightness of each light, exactly as DynamicLighting settles on it (voice silent). */
function intensities(studio: Studio, state: AvatarState, lighting: ThemeLighting, backLight: RigLighting["backLight"]) {
  const levels = studio.states[state];
  return {
    key: levels.key,
    fill: levels.fill * lighting.fill,
    top: levels.top,
    rim: levels.rim * backLight.rim,
    kick: levels.kick * backLight.kick,
    // DynamicLighting never eases the face spot; it keeps its mount value.
    face: studio.placement.face.intensity,
  };
}

export function EditableStudioLights({ studio, lighting, backLight, state, headTargetY }: EditableStudioLightsProps) {
  const { gl, scene } = useThree();
  const keyRef = useRef<THREE.DirectionalLight>(null);
  const faceRef = useRef<THREE.SpotLight>(null);
  const level = intensities(studio, state, lighting, backLight);
  const { placement, colors, shadow } = studio;

  useEffect(() => {
    gl.toneMappingExposure = lighting.exposure;
    scene.environmentIntensity = lighting.environment;
  }, [gl, scene, lighting.exposure, lighting.environment]);

  // Same aim points as DynamicLighting. Spot and directional targets are not in
  // the scene graph, so their world matrices are refreshed by hand.
  useFrame(() => {
    if (keyRef.current) {
      keyRef.current.target.position.set(0, shadow.targetY, 0);
      keyRef.current.target.updateMatrixWorld();
      keyRef.current.shadow.intensity = shadow.intensity;
    }
    if (faceRef.current) {
      faceRef.current.target.position.set(0, headTargetY, 0);
      faceRef.current.target.updateMatrixWorld();
    }
  });

  const spot = (name: "top" | "rim" | "kick" | "face") => ({
    position: placement[name].position,
    color: colors[name],
    intensity: level[name],
    angle: placement[name].angle,
    penumbra: placement[name].penumbra,
    distance: placement[name].distance ?? 0,
    decay: placement[name].decay ?? 2,
    castShadow: false,
  });

  return (
    <>
      <ambientLight color={studio.ambientColor} intensity={lighting.ambient} />
      <directionalLight
        ref={keyRef}
        position={placement.key.position}
        color={colors.key}
        intensity={level.key}
        castShadow
        shadow-mapSize-width={shadow.mapSize}
        shadow-mapSize-height={shadow.mapSize}
        shadow-bias={shadow.bias}
        shadow-normalBias={shadow.normalBias}
        shadow-camera-left={-shadow.extent}
        shadow-camera-right={shadow.extent}
        shadow-camera-top={shadow.extent}
        shadow-camera-bottom={-shadow.extent}
        shadow-camera-near={0.5}
        shadow-camera-far={8}
      />
      <directionalLight position={placement.fill.position} color={colors.fill} intensity={level.fill} />
      <spotLight {...spot("top")} />
      <spotLight {...spot("rim")} />
      <spotLight {...spot("kick")} />
      <spotLight ref={faceRef} {...spot("face")} />
    </>
  );
}

/** The studio's reflection panels, from the lab copy. */
export function EditablePanels({ studio }: { studio: Studio }) {
  const { resolution, lightformers } = studio.environment;
  // Keyed on the content: drei bakes the panels once, so an edit needs a rebake.
  const key = useMemo(() => JSON.stringify(lightformers), [lightformers]);
  return (
    <Environment key={key} resolution={resolution}>
      {lightformers.map((panel, i) => (
        <Lightformer key={i} {...panel} />
      ))}
    </Environment>
  );
}

interface LightHandlesProps {
  studio: Studio;
  selected: LightName;
  onSelect: (name: LightName) => void;
  onMove: (name: LightName, position: Vec3) => void;
}

/**
 * A ball where each light stands, in its colour (a black light, which adds
 * nothing, shows grey). Click one to select it; drag the arrows to move it.
 * Not lit, not tone mapped, casts nothing.
 */
export function LightHandles({ studio, selected, onSelect, onMove }: LightHandlesProps) {
  const [target, setTarget] = useState<THREE.Mesh | null>(null);
  return (
    <>
      {LIGHT_NAMES.map((name) => {
        const color = studio.colors[name] === "#000000" ? "#666666" : studio.colors[name];
        return (
          <mesh
            key={name}
            ref={name === selected ? setTarget : undefined}
            position={studio.placement[name].position}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(name);
            }}
          >
            <sphereGeometry args={[name === selected ? 0.09 : 0.06, 16, 12]} />
            <meshBasicMaterial color={color} toneMapped={false} />
          </mesh>
        );
      })}
      {target && (
        <TransformControls
          object={target}
          mode="translate"
          size={0.7}
          onObjectChange={() => onMove(selected, [target.position.x, target.position.y, target.position.z])}
        />
      )}
    </>
  );
}

interface LabFramingProps {
  camera: LabCameraRig;
  rig: RigCamera;
  modelHeight: number;
}

/**
 * components/avatar/AvatarScene.tsx's Framing, with CAMERA's numbers passed in
 * rather than imported, so the lab can edit them. The maths is the same: the
 * top of frame sits `headRoom` above the head, `frameHeightM` of her fills the
 * height, and the camera backs off until that fits the lens's field of view.
 */
export function LabFraming({ camera: settings, rig, modelHeight }: LabFramingProps) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const centerY = useRef(1.26);

  useEffect(() => {
    if (size.width <= 0 || size.height <= 0) return;
    const topY = modelHeight * (1 + settings.headRoom);
    const frameHeight = Math.min(settings.frameHeightM, topY);
    centerY.current = topY - frameHeight / 2;
    camera.aspect = size.width / size.height;
    camera.filmGauge = 36;
    camera.setFocalLength(rig.lensMm);
    const distance = rig.cameraDistanceM ?? frameHeight / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    camera.aspect = size.width / size.height / rig.widthSqueeze;
    camera.position.set(0, centerY.current, distance);
    camera.lookAt(0, centerY.current, 0);
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height, modelHeight, settings.headRoom, settings.frameHeightM, rig]);

  useFrame((state) => {
    camera.position.x = Math.sin(state.clock.elapsedTime * settings.sway.speed) * settings.sway.amplitude;
    camera.lookAt(0, centerY.current, 0);
  });

  return null;
}
