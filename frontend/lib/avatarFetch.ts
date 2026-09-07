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

/**
 * Decompressed size / transferred size for the avatar (29813520 / 20165542).
 * Only used to keep the progress percentage honest — see fetchAvatar.
 */
const AVATAR_INFLATE_RATIO = 29813520 / 20165542;

let inflight: Promise<ArrayBuffer> | null = null;

type ProgressFn = (loaded: number, total: number) => void;
const listeners = new Set<ProgressFn>();

/** Subscribe to download progress. Returns an unsubscribe function. */
export function onAvatarProgress(fn: ProgressFn): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
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
  if (inflight && !cacheBust) return inflight;

  const target = cacheBust ? `${url}${url.includes("?") ? "&" : "?"}nocache=${Date.now()}` : url;
  inflight = (async () => {
    const res = await fetch(target);
    if (!res.ok) throw new Error(`avatar: HTTP ${res.status}`);

    // The response is Content-Encoding: gzip, and the browser inflates BEFORE
    // handing bytes to this reader — so the stream yields the 30MB decompressed
    // model while Content-Length reports the 20MB that actually crosses the
    // network. Measured: 20165542 vs 29813520. Comparing them directly would
    // report ~148%, so the ratio is applied to put the total in the same units
    // the reader counts in. It is a fixed property of the asset (both sizes are
    // known at build time), not a guess about this particular transfer.
    const encoded = Number(res.headers.get("content-length")) || 0;
    const total = encoded ? Math.round(encoded * AVATAR_INFLATE_RATIO) : 0;
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

  inflight.catch(() => { inflight = null; });  // let a retry start clean
  return inflight;
}
