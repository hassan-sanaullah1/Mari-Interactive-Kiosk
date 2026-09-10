/**
 * One download of the avatar, shared by everything that needs it.
 *
 * Three things used to ask for the model independently: the <link rel="preload">
 * in layout.tsx, drei's useGLTF (via AvatarScene's preload and the component's
 * own hook), and the loading screen's progress reader. Locally that is
 * invisible — the later requests land after the first is cached and coalesce
 * onto it. On a slow connection the first request is still in flight when the
 * others start, and a response that has not finished cannot be shared, so they
 * become parallel copies of the same 20MB competing for one pipe. That is a 3x
 * slowdown exactly where the link is already the constraint, and it multiplies
 * the cache pressure that shows up as ERR_CACHE_WRITE_FAILURE.
 *
 * So the fetch happens exactly once, here, and everyone reads this promise:
 * three.js is handed the finished bytes rather than a URL, and the loading
 * screen watches the same stream instead of opening its own.
 *
 * ---
 *
 * This is deliberately ONE plain GET, and it must stay that way.
 *
 * A previous version split the download into six parallel byte ranges, which
 * did make a cold load faster. It also broke caching completely: browsers write
 * a 200 into the HTTP disk cache but not a 206, so every visit re-downloaded the
 * whole model. Measured in headless Chrome, two launches sharing one profile:
 *
 *   one plain GET      64s cold, 1s warm   (21MB written to the disk cache)
 *   six ranged GETs   125s cold, 94s warm  (nothing cached at all)
 *
 * A kiosk reloads far more often than it cold-starts, so a fast first load paid
 * for with a slow every-other-load is the wrong trade. Storing the assembled
 * bytes in Cache Storage was tried as a way to keep both, and did not hold up on
 * the kiosk in practice.
 *
 * The response is served with `cache-control: public, max-age=31536000,
 * immutable`, so a warm load takes it straight from disk with no network at all.
 * Nothing here needs to manage that — the one requirement is that the request
 * stays a single, plain, uninstrumented GET of a stable URL. In particular do
 * not add Range headers, and do not add query strings (see cacheBust below).
 */

import { AVATARS } from "@/components/avatar/models";

/**
 * Decompressed size / transferred size, per model — girl15 is served as a real
 * .gz, male2 uncompressed, so the correction is 1.48x for one and 1.0 for the
 * other. Only used to keep the progress percentage honest — see fetchAvatar.
 *
 * Looked up by URL rather than passed in, so every existing call site keeps its
 * signature. An unknown URL (the ?nocache retry is stripped first, but a rig
 * added without a registry entry would not be) falls back to 1: the percentage
 * then runs slow rather than past 100.
 */
function inflateRatio(url: string): number {
  const base = url.split("?")[0];
  for (const config of Object.values(AVATARS)) {
    if (config.url === base) return config.bytes.decoded / config.bytes.encoded;
  }
  return 1;
}

/**
 * One in-flight (or settled) download per model URL.
 *
 * Keyed by URL rather than a single slot, because the presenter can be switched
 * at runtime: with one slot, asking for the second model handed back the first
 * model's bytes and the toggle silently did nothing.
 */
const inflight = new Map<string, Promise<ArrayBuffer>>();

/**
 * Models whose bytes GLTFLoader has already parsed.
 *
 * Once a URL is in here, drei owns a parsed scene for it and will hand that back
 * without going near the loader — so fetching those bytes again produces a
 * download nobody reads. That is exactly what the speculative warm in
 * AvatarScene would otherwise do on every presenter switch: measured, toggling
 * back and forth re-pulled the full 30MB / 36MB each way while the rig on
 * screen came from the cache regardless.
 */
const parsed = new Set<string>();

/** True once this model has been parsed, i.e. drei can serve it without a fetch. */
export function isAvatarParsed(url: string): boolean {
  return parsed.has(url.split("?")[0]);
}

type ProgressFn = (loaded: number, total: number) => void;
const listeners = new Set<ProgressFn>();

/** Subscribe to download progress. Returns an unsubscribe function. */
export function onAvatarProgress(fn: ProgressFn): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Drop the retained bytes for a model.
 *
 * Called once GLTFLoader has parsed them: past that point drei's own cache holds
 * the parsed scene keyed by the same URL, so switching back to this model never
 * asks for the bytes again — and with two models in the registry, holding both
 * ArrayBuffers for the life of the page would pin ~66MB behind the parsed
 * geometry that is already on the GPU.
 *
 * Safe to call at any time: a later fetchAvatar for the same URL simply starts a
 * new request, which on the normal path is an immutable-cached disk read.
 */
export function releaseAvatar(url: string): void {
  const key = url.split("?")[0];
  parsed.add(key);
  inflight.delete(key);
}

/**
 * Fetch the avatar once and hand back the bytes.
 *
 * `cacheBust` is for the retry path only: Chrome aborts a response whose body it
 * cannot write into its HTTP cache (ERR_CACHE_WRITE_FAILURE — a 200 the page
 * never receives), and the avatar is the one asset big enough to trip it. A
 * query string makes the retry uncacheable so the bytes stream straight through.
 * It costs the cache entry, so it must never be set on the normal path.
 */
export function fetchAvatar(url: string, cacheBust = false): Promise<ArrayBuffer> {
  const key = url.split("?")[0];
  const existing = inflight.get(key);
  if (existing && !cacheBust) return existing;

  const target = cacheBust ? `${url}${url.includes("?") ? "&" : "?"}nocache=${Date.now()}` : url;
  const ratio = inflateRatio(key);
  const request = (async () => {
    const res = await fetch(target);
    if (!res.ok) throw new Error(`avatar: HTTP ${res.status}`);

    // Where the response is Content-Encoding: gzip, the browser inflates BEFORE
    // handing bytes to this reader — so the stream yields the 30MB decompressed
    // model while Content-Length reports the 20MB that actually crosses the
    // network. Measured on girl15: 20165542 vs 29813520. Comparing them directly
    // would report ~148%, so the ratio is applied to put the total in the same
    // units the reader counts in. It is a fixed property of each asset (both
    // sizes are known at build time), not a guess about this particular
    // transfer, and it is 1 for a model served uncompressed.
    const encoded = Number(res.headers.get("content-length")) || 0;
    const total = encoded ? Math.round(encoded * ratio) : 0;
    const reader = res.body?.getReader();
    if (!reader) return res.arrayBuffer();

    const chunks: Uint8Array[] = [];
    let loaded = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        loaded += value.length;
        for (const fn of listeners) fn(loaded, total);
      }
    }
    // Concatenate once at the end rather than growing a buffer per chunk.
    const out = new Uint8Array(loaded);
    let at = 0;
    for (const c of chunks) { out.set(c, at); at += c.length; }
    return out.buffer;
  })();

  // Let a retry start clean rather than replaying the failure forever.
  request.catch(() => {
    if (inflight.get(key) === request) inflight.delete(key);
  });
  inflight.set(key, request);
  return request;
}
