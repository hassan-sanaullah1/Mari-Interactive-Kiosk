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
  async headers() {
    return [
      {
        // The avatar .glb: large, versioned by filename (girl13.glb), and never
        // mutated in place — a rename accompanies any actual model change. Safe
        // to cache immutably so returning visitors skip the ~56MB re-download
        // entirely instead of even doing a revalidation round trip.
        source: "/models/:file*.glb",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
