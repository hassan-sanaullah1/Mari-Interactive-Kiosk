"use client";

/**
 * Post-processing for the presenter: screen-space ambient occlusion and a
 * colour grade. Both keep the canvas transparent, so the CSS artwork behind it
 * is never touched.
 *
 *   ambient occlusion  the soft darkening where light cannot reach — nostrils,
 *                      eye sockets, under the chin, arms against the body. The
 *                      rigs ship no AO map, so it is computed per frame from
 *                      depth and normals (three.js GTAOPass, no extra package).
 *   grade              lift, contrast, saturation, warm highlights and teal
 *                      shadows, in display space after tone mapping.
 *
 * Mounting this takes over R3F's render loop (a positive useFrame priority)
 * and renders through an EffectComposer:
 *
 *   RenderPass  the scene into a multisampled buffer (MSAA, which hair
 *               alpha-to-coverage also needs)
 *   GTAOPass    AO multiplied in; its blend multiplies alpha by 1
 *   OutputPass  tone mapping and colour space, which the renderer applies only
 *               when drawing straight to the screen
 *   grade       skips fully transparent pixels, so the background stays clear
 *
 * Unmount it and R3F renders directly again.
 */

import { useEffect, useMemo } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";

export interface AoSettings {
  enabled: boolean;
  /** 0 none, 1 full AO. */
  intensity: number;
  /** World-space reach in metres. The face's creases are a few centimetres. */
  radius: number;
}

export interface GradeSettings {
  enabled: boolean;
  /** 1 = unchanged, around mid-grey. */
  contrast: number;
  /** 1 = unchanged. */
  saturation: number;
  /** Raises the black point: 0 none, 0.05 visibly lifted. */
  lift: number;
  /** 0 neutral; positive warms the highlights. */
  warmth: number;
  /** 0 neutral; positive pushes the shadows towards teal. */
  tealShadows: number;
}

export const NO_GRADE: GradeSettings = {
  enabled: false,
  contrast: 1,
  saturation: 1,
  lift: 0,
  warmth: 0,
  tealShadows: 0,
};

const GradeShader = {
  uniforms: {
    tDiffuse: { value: null },
    contrast: { value: 1 },
    saturation: { value: 1 },
    lift: { value: 0 },
    warmth: { value: 0 },
    tealShadows: { value: 0 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
    }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float contrast;
    uniform float saturation;
    uniform float lift;
    uniform float warmth;
    uniform float tealShadows;
    varying vec2 vUv;
    void main() {
      vec4 texel = texture2D( tDiffuse, vUv );
      // Empty canvas: leave it empty, or the lift would tint the artwork behind.
      if ( texel.a < 0.001 ) { gl_FragColor = texel; return; }
      vec3 color = lift + texel.rgb * ( 1.0 - lift );
      color = ( color - 0.5 ) * contrast + 0.5;
      float luma = dot( color, vec3( 0.2126, 0.7152, 0.0722 ) );
      color = mix( vec3( luma ), color, saturation );
      color += warmth * smoothstep( 0.35, 1.0, luma ) * vec3( 0.5, 0.2, -0.2 );
      color += tealShadows * ( 1.0 - smoothstep( 0.0, 0.5, luma ) ) * vec3( -0.25, 0.08, 0.12 );
      gl_FragColor = vec4( clamp( color, 0.0, 1.0 ), texel.a );
    }`,
};

/**
 * Hair, brow and lash cards are drawn as solid quads in GTAO's depth/normal
 * pass, which would shade the forehead under their empty, transparent parts.
 * They are hidden for that pass and restored straight after.
 */
function hideCardsFromAo(pass: GTAOPass): void {
  const internals = pass as unknown as { _visibilityCache: THREE.Object3D[]; _overrideVisibility: () => void };
  const base = internals._overrideVisibility.bind(pass);
  internals._overrideVisibility = () => {
    base();
    pass.scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh || !mesh.visible) return;
      const material = mesh.material as THREE.Material;
      if (material.transparent || material.alphaTest > 0 || material.alphaToCoverage) {
        mesh.visible = false;
        internals._visibilityCache.push(mesh);
      }
    });
  };
}

export default function PostEffects({ ao, grade }: { ao: AoSettings; grade: GradeSettings }) {
  const { gl, scene, camera, size, viewport } = useThree();

  const composer = useMemo(() => {
    const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
    const effects = new EffectComposer(gl, target);
    effects.addPass(new RenderPass(scene, camera));
    const aoPass = new GTAOPass(scene, camera, 1, 1);
    hideCardsFromAo(aoPass);
    effects.addPass(aoPass);
    effects.addPass(new OutputPass());
    const gradePass = new ShaderPass(GradeShader);
    effects.addPass(gradePass);
    return { effects, aoPass, gradePass };
  }, [gl, scene, camera]);

  useEffect(() => {
    composer.effects.setPixelRatio(viewport.dpr);
    composer.effects.setSize(size.width, size.height);
  }, [composer, size.width, size.height, viewport.dpr]);

  useEffect(() => {
    composer.aoPass.enabled = ao.enabled;
    composer.aoPass.blendIntensity = ao.intensity;
    composer.aoPass.updateGtaoMaterial({ radius: ao.radius, distanceExponent: 1, thickness: 1, scale: 1, samples: 16 });
    composer.aoPass.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 16 });
  }, [composer, ao.enabled, ao.intensity, ao.radius]);

  useEffect(() => {
    const uniforms = composer.gradePass.uniforms;
    composer.gradePass.enabled = grade.enabled;
    uniforms.contrast.value = grade.contrast;
    uniforms.saturation.value = grade.saturation;
    uniforms.lift.value = grade.lift;
    uniforms.warmth.value = grade.warmth;
    uniforms.tealShadows.value = grade.tealShadows;
  }, [composer, grade]);

  useEffect(() => () => composer.effects.dispose(), [composer]);

  // Priority 1: R3F stops its own render and this one draws the frame.
  useFrame((_, delta) => composer.effects.render(delta), 1);

  return null;
}
