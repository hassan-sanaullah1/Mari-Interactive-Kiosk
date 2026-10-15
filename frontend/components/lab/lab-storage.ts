/**
 * Keeps the lab's settings across reloads, in this browser only.
 *
 * Without it, every page reload — including the full reloads Next.js does when
 * a lab module changes during development — dropped whatever had been tuned.
 * A convenience, not a record: the export is still how values leave the lab.
 */

import type { LabSettings } from "./LabScene";

const STORAGE_KEY = "mari-avatar-lab-v1";

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * Saved values laid over the defaults, field by field, so a field added to the
 * lab since the save gets its default instead of being undefined.
 */
function merge<T>(defaults: T, saved: unknown): T {
  if (!isObject(defaults) || !isObject(saved)) {
    return saved === undefined || typeof saved !== typeof defaults ? defaults : (saved as T);
  }
  const out: Record<string, unknown> = { ...defaults };
  for (const key of Object.keys(defaults)) {
    if (key in saved) out[key] = merge((defaults as Record<string, unknown>)[key], saved[key]);
  }
  return out as T;
}

export function loadLabSettings(defaults: LabSettings): LabSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? merge(defaults, JSON.parse(raw)) : defaults;
  } catch {
    // Unreadable or blocked storage: start from the defaults.
    return defaults;
  }
}

export function saveLabSettings(settings: LabSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Storage full or blocked: the lab still works, it just will not remember.
  }
}

export function clearLabSettings(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

export type ImportResult =
  | { ok: true; settings: LabSettings; backdrop: unknown; source: "export" | "settings" }
  | { ok: false; error: string };

/**
 * Turn an imported file back into lab settings.
 *
 * Accepts the lab's own export (buildExport: `rig` plus the `scene` it was
 * judged in) or a bare settings object. Laid over `base` field by field, like a
 * saved session: anything the file lacks (a setting added since it was
 * exported, or the editor's own selection) keeps its current value, and
 * anything of the wrong shape is ignored rather than trusted.
 */
export function settingsFromImport(base: LabSettings, text: string): ImportResult {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false, error: "Not valid JSON." };
  }
  if (!isObject(data)) return { ok: false, error: "The file does not hold an object." };

  if (data.kind === "mari-avatar-lab-export") {
    if (!isObject(data.rig) || !isObject(data.scene)) {
      return { ok: false, error: "A lab export, but its rig or scene is missing." };
    }
    const { backdrop, ...scene } = data.scene;
    return { ok: true, settings: merge(base, { ...scene, rig: data.rig }), backdrop, source: "export" };
  }
  if (isObject(data.rig) && "look" in data) {
    return { ok: true, settings: merge(base, data), backdrop: undefined, source: "settings" };
  }
  return { ok: false, error: "Not a lab export: expected kind \"mari-avatar-lab-export\"." };
}
