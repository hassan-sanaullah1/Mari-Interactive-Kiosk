import type { NextConfig } from "next";

/** Origin of the existing FastAPI server (server/app.py). Override with MARI_API_ORIGIN. */
const API_ORIGIN = process.env.MARI_API_ORIGIN ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  // Standalone build for Docker: outputs a minimal server (node server.js) with only
  // the traced production deps, instead of requiring the full node_modules at runtime.
  output: "standalone",
  // REST calls are made same-origin as /api/* and proxied to FastAPI, so the browser
  // never needs CORS and the backend stays untouched. The WebSocket (/ws) is opened
  // directly against FastAPI instead — Next's dev proxy does not forward WS upgrades,
  // and WebSockets aren't subject to CORS. See lib/endpoints.ts.
  async rewrites() {
    return [
      { source: "/api/chat", destination: `${API_ORIGIN}/chat` },
      { source: "/api/voice", destination: `${API_ORIGIN}/voice` },
      { source: "/api/healthz", destination: `${API_ORIGIN}/healthz` },
    ];
  },
  // Next's on-the-fly gzip stays ON for ordinary responses (HTML/JS/CSS), where
  // a chunked body is harmless. The avatar deliberately bypasses it by being
  // requested as an already-compressed .gz — see the /models headers below.
  async headers() {
    return [
      {
        // The app requests this .gz path directly (see components/avatar/state.ts).
        // It is a real file on disk, so it is served statically with a real
        // Content-Length — unlike Next's on-the-fly gzip, which cannot know the
        // length and falls back to chunked. Content-Encoding tells the browser to
        // inflate it transparently, so GLTFLoader still receives plain GLB bytes.
        source: "/models/girl15.glb.gz",
        headers: [
          { key: "Content-Encoding", value: "gzip" },
          { key: "Content-Type", value: "model/gltf-binary" },
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
      {
        // The avatar .glb: large, versioned by filename (girl15.glb), and never
        // mutated in place — a rename accompanies any actual model change. Safe
        // to cache immutably so returning visitors skip the re-download entirely
        // instead of even doing a revalidation round trip.
        //
        // NOTE: girl15.glb is the output of scripts/optimize_glb.py, not the raw
        // export — 30MB on disk / ~20MB gzipped, down from 56MB / 37MB. Re-run
        // that script after any re-export or the saving is silently lost.
        source: "/models/:file*.glb",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
