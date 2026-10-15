/**
 * Inspection helpers for the avatar lab (app/lab): what a loaded rig actually
 * carries, and debug views that swap its materials without touching the asset.
 */

import * as THREE from "three";

/** The texture slots a three.js standard material can carry, with short labels. */
const MAP_SLOTS = [
  ["map", "color"],
  ["normalMap", "normal"],
  ["roughnessMap", "roughness"],
  ["metalnessMap", "metalness"],
  ["aoMap", "ao"],
  ["emissiveMap", "emissive"],
  ["alphaMap", "alpha"],
  ["bumpMap", "bump"],
] as const;

export interface MaterialRow {
  name: string;
  /** e.g. "color 2048×2048"; empty when the material is a flat colour. */
  maps: string[];
  roughness: number | null;
  metalness: number | null;
  emissive: number;
  /** "opaque", "blend", or "mask 0.35". */
  alpha: string;
  meshes: number;
}

export interface AssetInventory {
  meshes: number;
  vertices: number;
  /** Morph target count on the mesh that carries the most (the face). */
  morphTargets: number;
  bones: number;
  materials: MaterialRow[];
  /** How many of the materials carry each kind of map. */
  mapCoverage: Record<string, number>;
}

function textureSize(texture: THREE.Texture): string {
  const image = texture.image as { width?: number; height?: number } | undefined;
  return image?.width ? `${image.width}×${image.height}` : "?";
}

function describeMaterial(material: THREE.Material, rows: Map<string, MaterialRow>): void {
  const existing = rows.get(material.uuid);
  if (existing) {
    existing.meshes += 1;
    return;
  }
  const std = material as THREE.MeshStandardMaterial;
  const slots = material as unknown as Record<string, THREE.Texture | null | undefined>;
  const maps = MAP_SLOTS.filter(([slot]) => slots[slot]).map(
    ([slot, label]) => `${label} ${textureSize(slots[slot]!)}`,
  );
  rows.set(material.uuid, {
    name: material.name || "(unnamed)",
    maps,
    roughness: std.isMeshStandardMaterial ? std.roughness : null,
    metalness: std.isMeshStandardMaterial ? std.metalness : null,
    emissive: std.isMeshStandardMaterial && std.emissiveMap ? std.emissiveIntensity : 0,
    alpha: material.transparent ? "blend" : material.alphaTest > 0 ? `mask ${material.alphaTest}` : "opaque",
    meshes: 1,
  });
}

/** Everything the lab panel reports about a rig, read off the loaded scene. */
export function inventory(root: THREE.Object3D): AssetInventory {
  const rows = new Map<string, MaterialRow>();
  const bones = new Set<string>();
  let meshes = 0;
  let vertices = 0;
  let morphTargets = 0;

  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if ((object as THREE.Bone).isBone) bones.add(object.uuid);
    if (!mesh.isMesh) return;
    meshes += 1;
    vertices += mesh.geometry.attributes.position?.count ?? 0;
    morphTargets = Math.max(morphTargets, mesh.morphTargetInfluences?.length ?? 0);
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) describeMaterial(material, rows);
  });

  const materials = [...rows.values()].sort((a, b) => a.name.localeCompare(b.name));
  const mapCoverage: Record<string, number> = {};
  for (const [, label] of MAP_SLOTS) {
    mapCoverage[label] = materials.filter((row) => row.maps.some((m) => m.startsWith(label))).length;
  }
  return { meshes, vertices, morphTargets, bones: bones.size, materials, mapCoverage };
}

/**
 * How the rig's surfaces are drawn.
 *
 *   lit        the real materials (whatever the current look gives them)
 *   albedo     the colour texture alone, unlit and not tone mapped
 *   normals    surface direction as colour: shows how smooth the mesh is, and
 *              that there is no normal map adding finer detail
 *   wireframe  the mesh itself
 */
export type MaterialView = "lit" | "albedo" | "normals" | "wireframe";

function overrideFor(material: THREE.Material, view: Exclude<MaterialView, "lit">): THREE.Material {
  const std = material as THREE.MeshStandardMaterial;
  if (view === "albedo") {
    return new THREE.MeshBasicMaterial({
      map: std.map ?? null,
      color: std.color ?? new THREE.Color(1, 1, 1),
      transparent: material.transparent,
      opacity: material.opacity,
      alphaTest: material.alphaTest,
      side: material.side,
      depthWrite: material.depthWrite,
      toneMapped: false,
    });
  }
  if (view === "normals") {
    return new THREE.MeshNormalMaterial({ side: material.side });
  }
  return new THREE.MeshBasicMaterial({ color: 0x22d3ee, wireframe: true, toneMapped: false });
}

/**
 * Swap every mesh under `root` to the debug view. Returns the undo, which puts
 * the original materials back and disposes the temporary ones; the originals
 * are never modified.
 */
export function applyMaterialView(root: THREE.Object3D, view: MaterialView): () => void {
  if (view === "lit") return () => {};
  const swapped: [THREE.Mesh, THREE.Material | THREE.Material[]][] = [];
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    const original = mesh.material;
    swapped.push([mesh, original]);
    mesh.material = Array.isArray(original)
      ? original.map((m) => overrideFor(m, view))
      : overrideFor(original, view);
  });
  return () => {
    for (const [mesh, original] of swapped) {
      const temporary = mesh.material;
      mesh.material = original;
      for (const m of Array.isArray(temporary) ? temporary : [temporary]) m.dispose();
    }
  };
}

/** Free a scene this code created itself. Never call on drei's cached scenes. */
export function disposeScene(root: THREE.Object3D): void {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const slots = material as unknown as Record<string, unknown>;
      for (const value of Object.values(slots)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
      material.dispose();
    }
  });
}
