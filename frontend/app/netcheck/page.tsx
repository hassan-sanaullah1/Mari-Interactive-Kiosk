"use client";

/**
 * /netcheck — a deployment-side answer to "why is the avatar slow here?"
 *
 * The avatar loads in seconds locally and takes minutes on the deployed host,
 * from the same image. That difference is not in the file or the code, so it has
 * to be measured on the machine that is actually slow. The browser's own
 * waterfall cannot separate the possibilities; this page can.
 *
 * It reports, per request:
 *   TTFB        time to the first delivered byte. Large here means the server or
 *               something in front of it is holding the response back rather
 *               than the bytes being slow — a proxy buffering the whole body
 *               before releasing any of it looks exactly like this.
 *   throughput  measured across the body only, so a slow start does not flatter
 *               or distort it.
 *
 * How to read the result:
 *   - Small request fast, large one slow  -> per-byte problem: bandwidth, or a
 *     proxy rate-limiting/buffering the large body.
 *   - Both slow, TTFB dominant            -> round-trip or origin problem, not size.
 *   - Second (cached) fetch fast          -> caching works; only the cold load hurts.
 *   - "no Content-Length"                 -> chunked: no progress, no resume.
 */

import { useCallback, useState } from "react";
import { AVATAR_MODEL_URL } from "@/components/avatar/state";

interface Row {
  label: string;
  ttfbMs: number;
  totalMs: number;
  bytes: number;
  mbps: number;
  note?: string;
}

async function timeFetch(label: string, url: string, bust: boolean): Promise<Row> {
  const t0 = performance.now();
  const res = await fetch(bust ? `${url}?t=${Date.now()}` : url, {
    cache: bust ? "no-store" : "default",
  });
  if (!res.ok) throw new Error(`${label}: HTTP ${res.status}`);
  let ttfb = 0;
  let bytes = 0;
  const reader = res.body?.getReader();
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (!ttfb) ttfb = performance.now() - t0;
      if (done) break;
      bytes += value?.length ?? 0;
    }
  } else {
    bytes = (await res.arrayBuffer()).byteLength;
    ttfb = performance.now() - t0;
  }
  const totalMs = performance.now() - t0;
  const bodyMs = Math.max(1, totalMs - ttfb);
  return {
    label,
    ttfbMs: Math.round(ttfb),
    totalMs: Math.round(totalMs),
    bytes,
    mbps: (bytes * 8) / bodyMs / 1000,
    note: res.headers.get("content-length")
      ? undefined
      : "no Content-Length (chunked) — no progress, not resumable",
  };
}

export default function NetCheck() {
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async () => {
    setBusy(true);
    setRows([]);
    const out: Row[] = [];
    const push = (r: Row) => { out.push(r); setRows([...out]); };
    try {
      // Small first: separates round-trip cost from per-byte cost.
      push(await timeFetch("page HTML (small)", "/", true));
      push(await timeFetch("avatar, cold", AVATAR_MODEL_URL, true));
      // Same URL without the cache-buster: if this is instant, the immutable
      // Cache-Control is working and only the first load is the problem.
      push(await timeFetch("avatar, cached", AVATAR_MODEL_URL, false));
    } catch (err) {
      push({ label: `FAILED — ${String(err)}`, ttfbMs: 0, totalMs: 0, bytes: 0, mbps: 0 });
    }
    setBusy(false);
  }, []);

  return (
    <main style={{ font: "14px/1.5 system-ui", padding: 24, maxWidth: 780, color: "#111", background: "#fff" }}>
      <h1 style={{ fontSize: 18, marginBottom: 4 }}>Avatar download check</h1>
      <p style={{ color: "#555", marginTop: 0 }}>
        Run this from the slow deployment, then from a fast one, and compare.
        Downloads ~20&nbsp;MB twice.
      </p>
      <button onClick={run} disabled={busy} style={{ padding: "8px 16px", fontSize: 14, cursor: "pointer" }}>
        {busy ? "measuring…" : "Run test"}
      </button>
      {rows.length > 0 && (
        <table style={{ marginTop: 20, borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
              <th>request</th><th>TTFB</th><th>total</th><th>size</th><th>throughput</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} style={{ borderBottom: "1px solid #eee", verticalAlign: "top" }}>
                <td style={{ padding: "6px 0" }}>
                  {r.label}
                  {r.note ? <div style={{ color: "#b00", fontSize: 12 }}>{r.note}</div> : null}
                </td>
                <td>{r.ttfbMs} ms</td>
                <td>{(r.totalMs / 1000).toFixed(1)} s</td>
                <td>{(r.bytes / 1e6).toFixed(1)} MB</td>
                <td>{r.mbps.toFixed(1)} Mbps</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
