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
 *   skinTone       a colour correction on the skin only: saturation, warmth,
 *                  brightness, and calming the cheek blotches. The blotches are
 *                  picked out by how far red leads green in the face texture
 *                  (measured on dress2's Head_Diffuse, linear green/red: plain
 *                  skin 0.48-0.60, flush and blotches 0.33-0.47, lips 0.25-0.31),
 *                  so the lips are never touched.
 *   browDefinition darker, denser brow cards. Density strengthens the brow
 *                  texture's own alpha in the shader, so the faint hairs at the
 *                  edges turn solid; the cut-off is lowered so they are not
 *                  trimmed away. Measured before: the darkest fifth of the brow
 *                  was mostly skin showing through (143 101 83 vs 43 29 22).
 *   hairTame       the hair reflects less of a bright room (the grey haze),
 *                  drops its faintest wisps, and can be darkened.
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
  skinTone: boolean;
  browDefinition: boolean;
  hairTame: boolean;
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
  skinTone: false,
  browDefinition: false,
  hairTame: false,
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
  skinTone: true,
  browDefinition: true,
  hairTame: true,
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
  /** Skin saturation: 1 unchanged. */
  skinSaturation: number;
  /** Skin warmth: 0 unchanged, negative cooler (more blue, less red), positive warmer. */
  skinWarmth: number;
  /** Skin brightness: 1 unchanged. */
  skinBrightness: number;
  /** How far the cheek blotches are pulled back to plain skin: 0 none, 1 fully. */
  calmRedness: number;
  /** Brightness of the eyes with wet eyes on: 1 unchanged. Lifts the whites. */
  eyeBrightness: number;
  /** How much darker the brows get with definition on: 0 none, 1 much. */
  browDarken: number;
  /** Brow density with definition on: 1 as authored, higher fills the faint hairs in. */
  browDensity: number;
  /** How much of the environment the hair reflects with taming on. */
  hairReflection: number;
  /** Alpha cut-off on the hair cards with taming on: higher drops more wisps. */
  hairCutoff: number;
  /** Hair colour multiplier with taming on: 1 unchanged, lower darker. */
  hairShade: number;
  /** Hair roughness with taming on: higher turns bright strand streaks into a soft sheen. */
  hairRoughness: number;
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
  skinSaturation: 1,
  skinWarmth: 0,
  skinBrightness: 1,
  calmRedness: 0.5,
  eyeBrightness: 1.1,
  browDarken: 0.3,
  browDensity: 1,
  hairReflection: 0.1,
  hairCutoff: 0.25,
  hairShade: 0.9,
  hairRoughness: 0.32,
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
  skinSaturation: { value: 1 },
  skinToneTint: { value: new THREE.Color(1, 1, 1) },
  skinCalm: { value: DEFAULT_REALISM_PARAMS.calmRedness },
  browDensity: { value: DEFAULT_REALISM_PARAMS.browDensity },
};

/** Original values of everything the live parameters overwrite, so undo can restore them. */
interface Originals {
  color: THREE.Color;
  envMapIntensity: number;
  alphaTest: number;
  roughness: number;
}
const wetEyeMaterials = new Map<THREE.MeshPhysicalMaterial, THREE.Color>();
const browMaterials = new Map<THREE.MeshStandardMaterial, Originals>();
const hairMaterials = new Map<THREE.MeshStandardMaterial, Originals>();
/** Beard cards with taming on: the hair's sheen and shade, never its cut-off. */
const beardMaterials = new Map<THREE.MeshStandardMaterial, Originals>();

/** Brow cut-off with definition on: low, so the edges density fills in survive. */
const BROW_CUTOFF = 0.03;

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
  skinUniforms.skinSaturation.value = params.skinSaturation;
  skinUniforms.skinCalm.value = params.calmRedness;
  // Warmth trades red against blue around neutral; brightness scales all three.
  skinUniforms.skinToneTint.value
    .setRGB(1 + params.skinWarmth * 0.08, 1, 1 - params.skinWarmth * 0.12)
    .multiplyScalar(params.skinBrightness);
  for (const [material, base] of wetEyeMaterials) material.color.copy(base).multiplyScalar(params.eyeBrightness);
  skinUniforms.browDensity.value = params.browDensity;
  for (const [material, original] of browMaterials) {
    material.color.copy(original.color).multiplyScalar(1 - 0.6 * params.browDarken);
    // Lower, never higher: a higher cut-off would trim the faint hairs density fills in.
    material.alphaTest = Math.min(original.alphaTest, BROW_CUTOFF);
  }
  for (const [material, original] of hairMaterials) {
    material.color.copy(original.color).multiplyScalar(params.hairShade);
    material.envMapIntensity = params.hairReflection;
    material.alphaTest = Math.max(original.alphaTest, params.hairCutoff);
    material.roughness = params.hairRoughness;
  }
  for (const [material, original] of beardMaterials) {
    material.color.copy(original.color).multiplyScalar(params.hairShade);
    material.envMapIntensity = params.hairReflection;
    material.roughness = params.hairRoughness;
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

/**
 * Skin tone, after the colour texture is sampled. The flush/blotch band of the
 * green:red ratio (0.33-0.47) is lifted back towards plain skin (0.52) by
 * scaling green and blue together, which keeps the hue family; the lips sit
 * below 0.31 and are outside the mask. Then saturation and the warmth tint.
 */
const SKIN_TONE_TERM = `#include <color_fragment>
	{
		vec3 tone = diffuseColor.rgb;
		float greenOverRed = tone.g / max( tone.r, 1e-4 );
		float blotch = smoothstep( 0.31, 0.36, greenOverRed ) * ( 1.0 - smoothstep( 0.44, 0.50, greenOverRed ) );
		float lift = mix( 1.0, 0.52 / max( greenOverRed, 1e-4 ), blotch * skinCalm );
		tone.gb *= lift;
		float toneLuma = dot( tone, vec3( 0.2126, 0.7152, 0.0722 ) );
		tone = mix( vec3( toneLuma ), tone, skinSaturation ) * skinToneTint;
		diffuseColor.rgb = tone;
	}`;

interface SkinPatch {
  scatter: boolean;
  gloss: boolean;
  smooth: boolean;
  tone: boolean;
}

/** Null if a three.js upgrade moved a line this relies on: skip, don't break the shader. */
function patchedLightingChunk(): string | null {
  const chunk = THREE.ShaderChunk.lights_physical_pars_fragment;
  return chunk.includes(DIRECT_DIFFUSE_LINE) ? chunk.replace(DIRECT_DIFFUSE_LINE, SCATTER_TERM) : null;
}

function patchSkin(material: THREE.MeshStandardMaterial, patch: SkinPatch, undo: (() => void)[]): void {
  const lighting = patch.scatter ? patchedLightingChunk() : null;
  if (patch.scatter && !lighting) console.warn("[realism] three.js lighting chunk changed; skin scatter skipped");
  if (!lighting && !patch.gloss && !patch.smooth && !patch.tone) return;

  const previousCompile = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  material.onBeforeCompile = (shader, renderer) => {
    previousCompile.call(material, shader, renderer);
    Object.assign(shader.uniforms, skinUniforms);
    shader.fragmentShader = `uniform float skinWrap;\nuniform vec3 skinScatterColor;\nuniform float skinGloss;\nuniform float skinSmooth;\nuniform float skinSmoothRadius;\nuniform float skinSaturation;\nuniform vec3 skinToneTint;\nuniform float skinCalm;\n${shader.fragmentShader}`;
    if (patch.tone) {
      shader.fragmentShader = shader.fragmentShader.replace("#include <color_fragment>", SKIN_TONE_TERM);
    }
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
    `${previousKey.call(material)}|skin${lighting ? "-scatter" : ""}${patch.gloss ? "-gloss" : ""}${patch.smooth ? "-smooth" : ""}${patch.tone ? "-tone" : ""}`;
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
  const wet = new THREE.MeshPhysicalMaterial({
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
  wetEyeMaterials.set(wet, source.color.clone());
  wet.color.copy(source.color).multiplyScalar(currentParams.eyeBrightness);
  return wet;
}

// ── brows and hair ──────────────────────────────────────────────────────

/**
 * Alpha raised towards 1 before the alpha test: 1 - (1 - a)^density. A faint
 * hair at a = 0.2 reaches 0.49 at density 3; a solid one stays solid.
 */
const BROW_DENSITY_TERM = `diffuseColor.a = 1.0 - pow( 1.0 - clamp( diffuseColor.a, 0.0, 1.0 ), browDensity );
#include <alphatest_fragment>`;

function densifyBrow(material: THREE.MeshStandardMaterial, undo: (() => void)[]): void {
  const previousCompile = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  material.onBeforeCompile = (shader, renderer) => {
    previousCompile.call(material, shader, renderer);
    shader.uniforms.browDensity = skinUniforms.browDensity;
    shader.fragmentShader = `uniform float browDensity;\n${shader.fragmentShader}`.replace(
      "#include <alphatest_fragment>",
      BROW_DENSITY_TERM,
    );
  };
  material.customProgramCacheKey = () => `${previousKey.call(material)}|brow-density`;
  material.needsUpdate = true;
  undo.push(() => {
    material.onBeforeCompile = previousCompile;
    material.customProgramCacheKey = previousKey;
    material.needsUpdate = true;
  });
}

const isBrowCard = (material: THREE.MeshStandardMaterial): boolean =>
  material.transparent && /brow/i.test(`${material.name} ${material.map?.name ?? ""}`);

function track(
  registry: Map<THREE.MeshStandardMaterial, Originals>,
  material: THREE.MeshStandardMaterial,
  undo: (() => void)[],
): void {
  const original: Originals = {
    color: material.color.clone(),
    envMapIntensity: material.envMapIntensity,
    alphaTest: material.alphaTest,
    roughness: material.roughness,
  };
  registry.set(material, original);
  // Applied now through the same path the sliders use.
  setRealismParams(currentParams);
  undo.push(() => {
    registry.delete(material);
    material.color.copy(original.color);
    material.envMapIntensity = original.envMapIntensity;
    material.alphaTest = original.alphaTest;
    material.roughness = original.roughness;
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
 * already reads right, and coverage made them harsh and dark. So is the male
 * rig's beard card: stubble is all faint texels, and the hair cut-off erased
 * most of it.
 */
function isHairCard(material: THREE.MeshStandardMaterial): boolean {
  const label = `${material.name} ${material.map?.name ?? ""}`;
  return material.transparent && !/brow|lash|beard/i.test(label);
}

/** Measured on the male rig: its beard card ships at roughness 0.29 and the key's reflection greyed the moustache. */
const isBeardCard = (material: THREE.MeshStandardMaterial): boolean =>
  material.transparent && /beard/i.test(`${material.name} ${material.map?.name ?? ""}`);

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

/** Everything that applies to a skin material. */
function applyToSkin(material: THREE.MeshStandardMaterial, options: RealismOptions, undo: (() => void)[]): void {
  if (!options.skinGlow && material.emissiveIntensity !== 0) {
    const before = material.emissiveIntensity;
    material.emissiveIntensity = 0;
    undo.push(() => {
      material.emissiveIntensity = before;
    });
  }
  patchSkin(
    material,
    { scatter: options.skinScatter, gloss: options.lipGloss, smooth: options.skinSmooth, tone: options.skinTone },
    undo,
  );
  if (options.skinSheen) addSkinSheen(material, undo);
  if (options.surfaceDetail) addSurfaceDetail(material, "skin", undo);
}

function applyToMaterial(
  material: THREE.MeshStandardMaterial,
  rig: RealismRig,
  options: RealismOptions,
  undo: (() => void)[],
): void {
  if (rig.skinMaterials.has(material.name)) {
    applyToSkin(material, options, undo);
    return;
  }
  if (options.browDefinition && isBrowCard(material)) {
    track(browMaterials, material, undo);
    densifyBrow(material, undo);
  }
  if (options.hairTame && isHairCard(material)) track(hairMaterials, material, undo);
  if (options.hairTame && isBeardCard(material)) track(beardMaterials, material, undo);
  if (options.surfaceDetail && isCloth(material)) addSurfaceDetail(material, "cloth", undo);
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
    for (const wet of eyeReplacements.values()) {
      wetEyeMaterials.delete(wet);
      wet.dispose();
    }
  };
}
