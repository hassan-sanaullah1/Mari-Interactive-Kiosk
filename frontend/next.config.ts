import type { NextConfig } from "next";

/** Origin of the existing FastAPI server (server/app.py). Override with MARI_API_ORIGIN. */
const API_ORIGIN = process.env.MARI_API_ORIGIN ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
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
};

export default nextConfig;
