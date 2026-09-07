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
 * `cacheBust` is for the retry path: Chrome aborts a response whose body it
 * cannot write into its HTTP cache (ERR_CACHE_WRITE_FAILURE — a 200 the page
 * never receives), and the avatar is the one asset big enough to trip it. A
 * query string makes the retry uncacheable so the bytes stream straight through.
 */
/**
 * How many ranged requests to pull the model with.
 *
 * The deployed host throttles per connection, not in total: measured against it,
 * one connection sustains ~0.2 MB/s and takes 103s for this file, while six
 * ranged requests over the same file finish in 34s. The bytes are not the
 * constraint and neither is the origin (time-to-first-byte is 0.47s) — a single
 * stream simply never gets more than a slice of the available bandwidth.
 *
 * Six is where the measured gain flattened; more connections start contending.
 * Requires Accept-Ranges, which the server does advertise; when it does not, or
 * when any part fails, the single-stream path below is used unchanged.
 */
const PARALLEL_PARTS = 6;
/** Don't bother splitting anything smaller than this — the round-trips cost more. */
const PARALLEL_MIN_BYTES = 4 * 1024 * 1024;

/**
 * Where the assembled model is kept between page loads.
 *
 * Ranged requests buy the first load a lot, but they cost every load after it:
 * Chrome will not write a 206 into its HTTP disk cache the way it writes a 200,
 * so splitting the download silently turned a cached asset into one that was
 * re-fetched in full on every visit. Measured in headless Chrome, two launches
 * sharing one profile: a plain GET took 64s cold and 1s warm (21MB written to
 * the disk cache), while the six-part ranged download took 125s cold and 94s
 * warm with nothing cached at all.
 *
 * The HTTP cache cannot hold this, so the bytes are kept here instead. The
 * parallel first load is unchanged; every load after it is a local read.
 */
const CACHE_NAME = "mari-avatar-v1";
/** Our own validator, stored beside the body — the entry is synthetic, so it has no real ETag. */
const ETAG_HEADER = "x-avatar-etag";

async function cacheGet(url: string): Promise<{ buf: ArrayBuffer; etag: string | null } | null> {
  if (typeof caches === "undefined") return null;
  try {
    const res = await (await caches.open(CACHE_NAME)).match(url);
    if (!res) return null;
    return { buf: await res.arrayBuffer(), etag: res.headers.get(ETAG_HEADER) };
  } catch {
    return null;  // private mode, or storage disabled
  }
}

async function cachePut(url: string, buf: ArrayBuffer, etag: string | null): Promise<void> {
  if (typeof caches === "undefined") return;
  try {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(url, new Response(buf, {
      headers: {
        "content-type": "model/gltf-binary",
        ...(etag ? { [ETAG_HEADER]: etag } : {}),
      },
    }));
  } catch {
    /* over quota or storage disabled — the model still loaded, so this is not fatal */
  }
}

/**
 * Download in parallel byte ranges, reassembled in order.
 *
 * Returns null if the server will not serve ranges, so the caller can fall back
 * rather than fail. Progress is reported across all parts combined.
 */
async function fetchRanged(url: string, total: number): Promise<ArrayBuffer | null> {
  const size = Math.ceil(total / PARALLEL_PARTS);
  const parts: Array<{ start: number; buf?: ArrayBuffer }> = [];
  for (let start = 0; start < total; start += size) parts.push({ start });

  let loaded = 0;
  const results = await Promise.all(parts.map(async (part) => {
    const end = Math.min(part.start + size, total) - 1;
    const res = await fetch(url, { headers: { Range: `bytes=${part.start}-${end}` } });
    // 206 is the only acceptable answer: a 200 means the server ignored the
    // Range and is sending the whole file on every connection.
    if (res.status !== 206) return null;
    const reader = res.body?.getReader();
    if (!reader) return res.arrayBuffer();
    const chunks: Uint8Array[] = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        got += value.length;
        loaded += value.length;
        for (const fn of listeners) fn(loaded, total);
      }
    }
    const out = new Uint8Array(got);
    let at = 0;
    for (const c of chunks) { out.set(c, at); at += c.length; }
    return out.buffer;
  }));

  if (results.some((r) => r === null)) return null;
  const merged = new Uint8Array(total);
  let at = 0;
  for (const buf of results) { merged.set(new Uint8Array(buf as ArrayBuffer), at); at += (buf as ArrayBuffer).byteLength; }
  return merged.buffer;
}

export function fetchAvatar(url: string, cacheBust = false): Promise<ArrayBuffer> {
  if (inflight && !cacheBust) return inflight;

  const target = cacheBust ? `${url}${url.includes("?") ? "&" : "?"}nocache=${Date.now()}` : url;
  inflight = (async () => {
    /** Hand a stored copy to the progress listeners as an instant, complete load. */
    const served = (buf: ArrayBuffer) => {
      for (const fn of listeners) fn(buf.byteLength, buf.byteLength);
      return buf;
    };

    let etag: string | null = null;
    // Ask first, so the size and range support are known before committing to a
    // strategy. HEAD is one round trip against a transfer measured in minutes.
    try {
      const head = await fetch(target, { method: "HEAD" });
      etag = head.headers.get("etag");

      // One round trip (0.47s against this host) to decide whether a download
      // measured in minutes is needed at all. Checked after the HEAD rather than
      // before it so a redeployed model is picked up instead of served stale.
      if (!cacheBust) {
        const hit = await cacheGet(url);
        if (hit && (!etag || !hit.etag || hit.etag === etag)) return served(hit.buf);
      }

      const len = Number(head.headers.get("content-length")) || 0;
      const ranged = head.headers.get("accept-ranges") === "bytes";
      // Only worth it on an unencoded body: ranges index the bytes on the wire,
      // so splitting a gzip stream would hand back fragments that cannot be
      // inflated independently.
      const encoded = head.headers.get("content-encoding");
      if (ranged && !encoded && len >= PARALLEL_MIN_BYTES) {
        const buf = await fetchRanged(target, len);
        if (buf) {
          await cachePut(url, buf, etag);
          return buf;
        }
      }
    } catch {
      // The origin is unreachable. A stored copy is better than no avatar, and
      // this is the kiosk's offline path, so take it before failing outright.
      if (!cacheBust) {
        const hit = await cacheGet(url);
        if (hit) return served(hit.buf);
      }
      /* otherwise fall through to the single-stream path */
    }

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
    // Deliberately not stored in CACHE_NAME: this was a plain 200, which the
    // browser's own HTTP cache keeps (measured: 1s on the next load). Storing it
    // again would hold a second 30MB copy to save nothing.
    return out.buffer;
  })();

  inflight.catch(() => { inflight = null; });  // let a retry start clean
  return inflight;
}
