/**
 * Rendering upgrades for the presenter that need no change to the asset.
 *
 * Every rig here ships colour textures only — no normal, roughness or AO maps
 * (the lab's inventory shows it) — so realism has to come from how those
 * surfaces are lit and drawn. Each upgrade is a separate switch, tried in
 * /lab before any of it reaches the kiosk:
 *
 *   skinGlow       the kiosk's emissive skin lift (AvatarModel). Emissive light
 *                  ignores direction, so it fills the face's own shading in;
 *                  turning it off gives the face its form back.
 *   skinScatter    a cheap stand-in for subsurface scattering. Light that the
 *                  hard day/night line on a surface would cut off re-emerges a
 *                  little past it, tinted warm, the way it does through skin.
 *   lipGloss       roughness that varies with the colour texture: the reddest
 *                  areas (lips, flushed skin) turn glossier, the rest stays
 *                  matte. Skin with one roughness everywhere reads as plastic.
 *   surfaceDetail  the colour texture reused as a bump map. Darker texels read
 *                  as slightly lower, so pores, freckles and the cloth's weave
 *                  catch the light instead of being painted flat.
 *   skinSmooth     a retouch: the skin's colour texture is blurred in the shader
 *                  and blended back, evening out blotches and painted noise while
 *                  the broad tone stays. The surface-detail bump still reads the
 *                  original texture, so keep that low when smoothing.
 *   skinSheen      one roughness and reflection strength for all the skin: the
 *                  soft, even sheen on forehead, nose and cheekbones.
 *   wetEyes        eyes get a clear-coat layer: a sharp, glossy reflection over
 *                  a softer iris, which is what puts a catchlight in them.
 *   hairCoverage   alpha-to-coverage on the hair cards instead of a hard alpha
 *                  cut-off, so strand edges dissolve over the MSAA samples.
 *
 * `applyRealism` edits the loaded materials in place and returns an undo that
 * restores every value it changed. The strengths (`RealismParams`) are live:
 * `setRealismParams` updates shared uniforms and bump scales without
 * recompiling a single shader, so they can sit on sliders.
 */

import * as THREE from "three";

export interface RealismOptions {
  /** Keep the kiosk's emissive skin lift (true) or remove it (false). */
  skinGlow: boolean;
  skinScatter: boolean;
  lipGloss: boolean;
  surfaceDetail: boolean;
  skinSmooth: boolean;
  skinSheen: boolean;
  wetEyes: boolean;
  hairCoverage: boolean;
}

/** What the kiosk renders today: none of the upgrades, glow on. */
export const KIOSK_REALISM: RealismOptions = {
  skinGlow: true,
  skinScatter: false,
  lipGloss: false,
  surfaceDetail: false,
  skinSmooth: false,
  skinSheen: false,
  wetEyes: false,
  hairCoverage: false,
};

export const ALL_REALISM: RealismOptions = {
  skinGlow: false,
  skinScatter: true,
  lipGloss: true,
  surfaceDetail: true,
  skinSmooth: true,
  skinSheen: true,
  wetEyes: true,
  // Off even in "all": it looked heavier than the hard cut in testing; judge it
  // on the kiosk's own GPU, where the MSAA it depends on is real.
  hairCoverage: false,
};

export interface RealismParams {
  /** How far past the shadow edge light wraps: 0 none, 1 all the way round. */
  scatterWrap: number;
  /** Brightness of the wrapped light. */
  scatterStrength: number;
  /** 0 neutral, 1 strongly red — skin scatters red furthest. */
  scatterWarmth: number;
  /** How much glossier the reddest areas get: 0 none, 1 mirror-like. */
  lipGloss: number;
  /** Bump strength on skin and on cloth, from their own colour textures. */
  skinDetail: number;
  clothDetail: number;
  /** How much of the blurred skin replaces the original: 0 none, 1 all. */
  smoothAmount: number;
  /** Blur reach in texture space; 0.001 is about two texels of a 2K face. */
  smoothRadius: number;
  /** Skin roughness with sheen on: lower is a tighter, brighter sheen. */
  skinRoughness: number;
  /** How much of the environment the skin reflects with sheen on. */
  skinSheen: number;
}

/** Starting values, chosen in the lab; every one sits on a slider there. */
export const DEFAULT_REALISM_PARAMS: RealismParams = {
  scatterWrap: 0.45,
  scatterStrength: 1,
  scatterWarmth: 0.75,
  lipGloss: 0.45,
  skinDetail: 0.6,
  clothDetail: 1.5,
  smoothAmount: 0.6,
  smoothRadius: 0.0025,
  skinRoughness: 0.45,
  skinSheen: 0.8,
};

/** What a rig must tell this module: which of its materials are skin. */
export interface RealismRig {
  skinMaterials: Set<string>;
}

// ── live parameters ─────────────────────────────────────────────────────

/**
 * Uniform objects shared by every patched skin material. three copies a
 * material's uniforms by reference, so writing `.value` here reaches every
 * compiled program at once.
 */
const skinUniforms = {
  skinWrap: { value: DEFAULT_REALISM_PARAMS.scatterWrap },
  skinScatterColor: { value: new THREE.Color() },
  skinGloss: { value: DEFAULT_REALISM_PARAMS.lipGloss },
  skinSmooth: { value: DEFAULT_REALISM_PARAMS.smoothAmount },
  skinSmoothRadius: { value: DEFAULT_REALISM_PARAMS.smoothRadius },
};

/** Skin materials with sheen on, so the sliders reach them live. */
const sheenMaterials = new Set<THREE.MeshStandardMaterial>();

/** Materials carrying the colour-as-bump detail, and which strength they take. */
const bumpMaterials = new Map<THREE.MeshStandardMaterial, "skin" | "cloth">();
let currentParams = DEFAULT_REALISM_PARAMS;

/** Fully warm, the colour wrapped light comes back with. */
const WARM_SCATTER = new THREE.Color(0.9, 0.35, 0.25);
const NEUTRAL_SCATTER = new THREE.Color(0.6, 0.6, 0.6);

function bumpScaleFor(role: "skin" | "cloth"): number {
  return role === "skin" ? currentParams.skinDetail : currentParams.clothDetail;
}

/** Apply new strengths everywhere at once. Never recompiles. */
export function setRealismParams(params: RealismParams): void {
  currentParams = params;
  skinUniforms.skinWrap.value = params.scatterWrap;
  skinUniforms.skinScatterColor.value
    .copy(NEUTRAL_SCATTER)
    .lerp(WARM_SCATTER, params.scatterWarmth)
    .multiplyScalar(params.scatterStrength);
  skinUniforms.skinGloss.value = params.lipGloss;
  skinUniforms.skinSmooth.value = params.smoothAmount;
  skinUniforms.skinSmoothRadius.value = params.smoothRadius;
  for (const [material, role] of bumpMaterials) material.bumpScale = bumpScaleFor(role);
  for (const material of sheenMaterials) {
    material.roughness = params.skinRoughness;
    material.envMapIntensity = params.skinSheen;
  }
}

setRealismParams(DEFAULT_REALISM_PARAMS);

// ── skin shader: scatter and gloss ──────────────────────────────────────

/** The one line in RE_Direct_Physical (three r183) that adds direct diffuse light. */
const DIRECT_DIFFUSE_LINE =
  "reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseContribution );";

const SCATTER_TERM = `${DIRECT_DIFFUSE_LINE}
	float skinNdotL = dot( geometryNormal, directLight.direction );
	float skinWrapped = saturate( ( skinNdotL + skinWrap ) / ( 1.0 + skinWrap ) );
	reflectedLight.directDiffuse += ( skinWrapped - saturate( skinNdotL ) ) * skinScatterColor * directLight.color * BRDF_Lambert( material.diffuseContribution );`;

/**
 * Lips and flushed skin, picked out by how much red leads green and blue in
 * the (linear) colour already sampled from the map. Plain skin leads by about
 * 0.2, lipstick by 0.35 and more.
 */
const GLOSS_TERM = `#include <roughnessmap_fragment>
	float skinRedness = diffuseColor.r - max( diffuseColor.g, diffuseColor.b );
	roughnessFactor *= 1.0 - skinGloss * smoothstep( 0.22, 0.36, skinRedness );`;

/**
 * three's map_fragment with the retouch: twelve taps on two rings around the
 * texel, averaged with the centre, blended back by skinSmooth. Small radii
 * stay inside the face's UV island, so no seam bleeds in.
 */
const SMOOTH_MAP_FRAGMENT = `#ifdef USE_MAP
	vec4 sampledDiffuseColor = texture2D( map, vMapUv );
	vec4 skinBlurred = sampledDiffuseColor;
	for ( int i = 0; i < 6; i ++ ) {
		float angle = float( i ) * 1.0472;
		vec2 ring = vec2( cos( angle ), sin( angle ) ) * skinSmoothRadius;
		skinBlurred += texture2D( map, vMapUv + ring );
		skinBlurred += texture2D( map, vMapUv + ring * 0.5 + vec2( -ring.y, ring.x ) * 0.25 );
	}
	sampledDiffuseColor = mix( sampledDiffuseColor, skinBlurred / 13.0, skinSmooth );
	diffuseColor *= sampledDiffuseColor;
#endif`;

interface SkinPatch {
  scatter: boolean;
  gloss: boolean;
  smooth: boolean;
}

/** Null if a three.js upgrade moved a line this relies on: skip, don't break the shader. */
function patchedLightingChunk(): string | null {
  const chunk = THREE.ShaderChunk.lights_physical_pars_fragment;
  return chunk.includes(DIRECT_DIFFUSE_LINE) ? chunk.replace(DIRECT_DIFFUSE_LINE, SCATTER_TERM) : null;
}

function patchSkin(material: THREE.MeshStandardMaterial, patch: SkinPatch, undo: (() => void)[]): void {
  const lighting = patch.scatter ? patchedLightingChunk() : null;
  if (patch.scatter && !lighting) console.warn("[realism] three.js lighting chunk changed; skin scatter skipped");
  if (!lighting && !patch.gloss && !patch.smooth) return;

  const previousCompile = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  material.onBeforeCompile = (shader, renderer) => {
    previousCompile.call(material, shader, renderer);
    Object.assign(shader.uniforms, skinUniforms);
    shader.fragmentShader = `uniform float skinWrap;\nuniform vec3 skinScatterColor;\nuniform float skinGloss;\nuniform float skinSmooth;\nuniform float skinSmoothRadius;\n${shader.fragmentShader}`;
    if (patch.smooth) {
      shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", SMOOTH_MAP_FRAGMENT);
    }
    if (lighting) {
      shader.fragmentShader = shader.fragmentShader.replace("#include <lights_physical_pars_fragment>", lighting);
    }
    if (patch.gloss) {
      shader.fragmentShader = shader.fragmentShader.replace("#include <roughnessmap_fragment>", GLOSS_TERM);
    }
  };
  // A distinct key per patch combination, so three compiles a separate program
  // instead of reusing the unpatched one it already has for this material type.
  material.customProgramCacheKey = () =>
    `${previousKey.call(material)}|skin${lighting ? "-scatter" : ""}${patch.gloss ? "-gloss" : ""}${patch.smooth ? "-smooth" : ""}`;
  material.needsUpdate = true;
  undo.push(() => {
    material.onBeforeCompile = previousCompile;
    material.customProgramCacheKey = previousKey;
    material.needsUpdate = true;
  });
}

// ── skin sheen ──────────────────────────────────────────────────────────

function addSkinSheen(material: THREE.MeshStandardMaterial, undo: (() => void)[]): void {
  const before = { roughness: material.roughness, envMapIntensity: material.envMapIntensity };
  material.roughness = currentParams.skinRoughness;
  material.envMapIntensity = currentParams.skinSheen;
  sheenMaterials.add(material);
  undo.push(() => {
    sheenMaterials.delete(material);
    Object.assign(material, before);
  });
}

// ── surface detail ──────────────────────────────────────────────────────

function addSurfaceDetail(
  material: THREE.MeshStandardMaterial,
  role: "skin" | "cloth",
  undo: (() => void)[],
): void {
  if (!material.map || material.bumpMap) return;
  const before = { bumpMap: material.bumpMap, bumpScale: material.bumpScale };
  material.bumpMap = material.map;
  material.bumpScale = bumpScaleFor(role);
  bumpMaterials.set(material, role);
  material.needsUpdate = true;
  undo.push(() => {
    bumpMaterials.delete(material);
    material.bumpMap = before.bumpMap;
    material.bumpScale = before.bumpScale;
    material.needsUpdate = true;
  });
}

/**
 * Opaque, colour-textured, and neither skin nor an eye, tooth or the like:
 * the garments. Cards (hair, lashes) and small parts are left alone.
 */
function isCloth(material: THREE.MeshStandardMaterial): boolean {
  if (material.transparent || material.alphaTest > 0 || !material.map) return false;
  const image = material.map.image as { width?: number } | undefined;
  // The garment textures are the large ones (4K); eyes, teeth and nails are <=1K.
  return (image?.width ?? 0) >= 2000;
}

// ── eyes ────────────────────────────────────────────────────────────────

/**
 * The eyeball material, recognised by name: the rigs call it "Std_Eye_*" or
 * sample a texture named "Eye_Diffuse". Lashes are excluded. When this moves
 * into the kiosk it becomes a per-rig field in tuning.ts like skinMaterials.
 */
function isEyeMaterial(material: THREE.MeshStandardMaterial): boolean {
  if (/eyelash/i.test(material.name)) return false;
  return /^std_eye/i.test(material.name) || /^eye_diffuse/i.test(material.map?.name ?? "");
}

function wetEyeMaterial(source: THREE.MeshStandardMaterial): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({
    name: source.name,
    map: source.map,
    color: source.color.clone(),
    // The iris and sclera under the film: soft.
    roughness: 0.4,
    metalness: 0,
    // The tear film over them: a sharp, bright reflection.
    clearcoat: 1,
    clearcoatRoughness: 0.03,
    ior: 1.376, // the cornea
    envMapIntensity: Math.max(source.envMapIntensity, 1.5),
    side: source.side,
  });
}

// ── hair ────────────────────────────────────────────────────────────────

/**
 * Cut-off for a card that arrives with none (the raw look). Below it a texel is
 * dropped outright; above it, alpha becomes MSAA coverage. A lower cut-off
 * turned the faint fringe texels into solid strands and the hair went heavy.
 */
const COVERAGE_MIN_CUTOFF = 0.15;

/**
 * Brows and lashes are excluded: they are thin enough that their blended edge
 * already reads right, and coverage made them harsh and dark.
 */
function isHairCard(material: THREE.MeshStandardMaterial): boolean {
  const label = `${material.name} ${material.map?.name ?? ""}`;
  return material.transparent && !/brow|lash/i.test(label);
}

function softenEdges(material: THREE.Material, undo: (() => void)[]): void {
  const before = {
    transparent: material.transparent,
    alphaTest: material.alphaTest,
    alphaToCoverage: material.alphaToCoverage,
    depthWrite: material.depthWrite,
  };
  // Drawn in the opaque pass with depth, so cards no longer need sorting; the
  // MSAA samples turn alpha into a soft edge. Needs `antialias` on the canvas.
  // The material's own cut-off is kept (the kiosk tunes it per card).
  material.transparent = false;
  material.alphaToCoverage = true;
  material.alphaTest = Math.max(material.alphaTest, COVERAGE_MIN_CUTOFF);
  material.depthWrite = true;
  material.needsUpdate = true;
  undo.push(() => {
    Object.assign(material, before);
    material.needsUpdate = true;
  });
}

// ── the pass ────────────────────────────────────────────────────────────

function applyToMaterial(
  material: THREE.MeshStandardMaterial,
  rig: RealismRig,
  options: RealismOptions,
  undo: (() => void)[],
): void {
  const isSkin = rig.skinMaterials.has(material.name);
  if (isSkin && !options.skinGlow && material.emissiveIntensity !== 0) {
    const before = material.emissiveIntensity;
    material.emissiveIntensity = 0;
    undo.push(() => {
      material.emissiveIntensity = before;
    });
  }
  if (isSkin) {
    patchSkin(material, { scatter: options.skinScatter, gloss: options.lipGloss, smooth: options.skinSmooth }, undo);
  }
  if (isSkin && options.skinSheen) addSkinSheen(material, undo);
  if (options.surfaceDetail && isSkin) addSurfaceDetail(material, "skin", undo);
  if (options.surfaceDetail && !isSkin && isCloth(material)) addSurfaceDetail(material, "cloth", undo);
  if (options.hairCoverage && isHairCard(material)) softenEdges(material, undo);
}

/** Apply `options` to every material under `root`. Returns the undo. */
export function applyRealism(root: THREE.Object3D, rig: RealismRig, options: RealismOptions): () => void {
  const undo: (() => void)[] = [];
  const seen = new Set<string>();
  const eyeReplacements = new Map<string, THREE.MeshPhysicalMaterial>();

  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh || Array.isArray(mesh.material)) return;
    const material = mesh.material as THREE.MeshStandardMaterial;
    if (!material.isMeshStandardMaterial) return;

    if (options.wetEyes && isEyeMaterial(material)) {
      let wet = eyeReplacements.get(material.uuid);
      if (!wet) {
        wet = wetEyeMaterial(material);
        eyeReplacements.set(material.uuid, wet);
      }
      mesh.material = wet;
      undo.push(() => {
        mesh.material = material;
      });
      return;
    }

    if (seen.has(material.uuid)) return;
    seen.add(material.uuid);
    applyToMaterial(material, rig, options, undo);
  });

  return () => {
    for (const step of undo.reverse()) step();
    for (const wet of eyeReplacements.values()) wet.dispose();
  };
}
