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
