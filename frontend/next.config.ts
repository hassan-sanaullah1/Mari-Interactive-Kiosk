import type { NextConfig } from "next";

/** Origin of the existing FastAPI server (server/app.py). Override with MARI_API_ORIGIN. */
const API_ORIGIN = process.env.MARI_API_ORIGIN ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  // Standalone build for Docker: outputs a minimal server (node server.js) with only
  // the traced production deps, instead of requiring the full node_modules at runtime.
  output: "standalone",
  // The kiosk never uses next/image — the only raster assets are the two
  // backgrounds in app/page.tsx, served through a plain <img> inside a <picture>
  // that art-directs them. Leaving the optimizer enabled therefore buys nothing
  // and costs the `sharp` native module, which the standalone runtime loads
  // lazily on the first /_next/image request: it is the ONE thing in the runtime
  // dependency tree that shells out (sharp/lib/libvips.js runs
  // `pkg-config --modversion vips-cpp` and a `which brew` pipeline through
  // spawnSync with `shell: true`, no timeout). When the prebuilt binary does not
  // match the host — a different libc, an arm64 builder, or an x86-64 CPU below
  // the v2 microarchitecture the linux-x64 build requires — that shell-out is
  // what runs, and a killed child surfaces as an unreadable SIGTERM/spawnSync
  // dump with a Next error digest and empty stdout/stderr. Turning the optimizer
  // off takes sharp out of the runtime path entirely.
  images: { unoptimized: true },
  // REST calls are made same-origin as /api/* and proxied to FastAPI, so the browser
  // never needs CORS and the backend stays untouched. The WebSocket (/ws) is opened
  // directly against FastAPI instead — Next's dev proxy does not forward WS upgrades,
  // and WebSockets aren't subject to CORS. See lib/endpoints.ts.
  async rewrites() {
    return [
      { source: "/api/chat", destination: `${API_ORIGIN}/chat` },
      { source: "/api/voice", destination: `${API_ORIGIN}/voice` },
      { source: "/api/healthz", destination: `${API_ORIGIN}/healthz` },
      // The admin panel's API (server/admin.py), whose routes live under /upload/*
      // on the backend. Proxied under /api/admin/* so the Next page at /admin keeps
      // that path for itself: a rewrite on /admin/* would swallow the page.
      { source: "/api/admin/:path*", destination: `${API_ORIGIN}/upload/:path*` },
    ];
  },
  // Next's on-the-fly gzip stays ON for ordinary responses (HTML/JS/CSS), where
  // a chunked body is harmless. The avatar deliberately bypasses it by being
  // requested as an already-compressed .gz — see the /models headers below.
  async headers() {
    return [
      {
        // Pre-compressed rigs. The app requests these .gz paths DIRECTLY — they are
        // real files on disk, so they go out with a real Content-Length, unlike
        // Next's on-the-fly gzip which cannot know the length and falls back to
        // chunked. Content-Encoding tells the browser to inflate transparently, so
        // GLTFLoader still receives plain GLB bytes and lib/avatar-fetch.ts gets an
        // honest progress total.
        //
        // Not a micro-optimisation: the raw rigs are 30MB and 65MB, and a real
        // client abandoned the 30MB one mid-download with ERR_NETWORK_CHANGED and
        // no avatar. Pulled from the deployed origin it took 227s at 131 kB/s —
        // but that figure is a FLOOR, not the origin's speed: the same machine got
        // only 292 kB/s from a large public CDN, so the measuring link was the
        // constraint. TTFB was 0.49s, so the server and proxy are not the problem.
        // Either way a third fewer bytes is a third fewer bytes. Use /netcheck from
        // the kiosk itself for a number that reflects the real client.
        //
        // The origin does NOT compress these itself — verified by asking for one
        // with `Accept-Encoding: gzip`, which came back with no Content-Encoding
        // and the full uncompressed Content-Length. So shipping the .gz is the only
        // way the bytes get compressed at all.
        source: "/models/:file*.glb.gz",
        headers: [
          { key: "Content-Encoding", value: "gzip" },
          { key: "Content-Type", value: "model/gltf-binary" },
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
      {
        // The avatar .glb: large, versioned by filename (dress2_v6.glb,
        // Waist_coat_male1.glb) and never mutated in place — a rename
        // accompanies any actual model change. Safe to cache immutably so
        // returning visitors skip the re-download entirely instead of even
        // doing a revalidation round trip.
        //
        // This wildcard caches both rigs; neither needs a rule of its own.
        //
        // The rename convention is load-bearing HERE: re-exporting over the
        // same filename hands every returning visitor a year-stale model with
        // no way to revalidate. Bump the name.
        //
        // Kept for the raw .glb, which is still the canonical asset on disk even
        // though both rigs are now SERVED as .gz (see the rule above).
        source: "/models/:file*.glb",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
