/**
 * Debug hooks the browser tests and a developer's console read.
 *
 * None of this changes behaviour. It exists because the kiosk's worst failures are
 * silent — the mouth stops moving, or the 43 MB rig downloads twice — and neither
 * shows up as an error.
 */

/**
 * Record that a module which must exist only once has been evaluated.
 *
 * Several modules here are singletons by design: `blendshapePlayer` holds the clip
 * buffer that the voice session fills and the rig samples, and `avatarFetch` holds the
 * in-flight map that stops the model being fetched more than once. If a bundler ever
 * resolves one of them through two different specifiers, each copy gets its own state
 * and the two halves stop seeing each other — the voice session pushes lipsync clips
 * into copy A while the rig samples copy B, so the mouth simply never moves. No error,
 * no failing unit test.
 *
 * Each such module calls this once at evaluation. A count above 1 means exactly that
 * failure, caught before anyone has to notice the symptom:
 *
 *     window.__MARI_SINGLETONS   // { blendshapePlayer: 1, avatarFetch: 1, ... }
 *
 * Asserted by e2e/singletons.spec.ts.
 */
export function registerSingleton(name: string): void {
  if (typeof window === "undefined") return;
  const registry = window as unknown as Record<string, Record<string, number>>;
  registry.__MARI_SINGLETONS = registry.__MARI_SINGLETONS ?? {};
  registry.__MARI_SINGLETONS[name] = (registry.__MARI_SINGLETONS[name] ?? 0) + 1;
}

/** Whether `?debug` is on the URL. Gates the noisy console output. */
export function debugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("debug");
}

/** Publish a named probe under `window.__MARI` for the tests and the console. */
export function publishProbe(name: string, probe: object): void {
  if (typeof window === "undefined") return;
  const registry = window as unknown as Record<string, Record<string, object>>;
  registry.__MARI = registry.__MARI ?? {};
  registry.__MARI[name] = probe;
}
