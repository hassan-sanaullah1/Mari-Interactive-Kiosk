/** Where the existing FastAPI backend (server/app.py) lives, from the browser's view. */

/**
 * REST goes through Next's rewrite proxy (see next.config.ts) so it is same-origin
 * and needs no CORS handling on the FastAPI side.
 */
export const REST = {
  chat: "/api/chat",
  voice: "/api/voice",
  healthz: "/api/healthz",
} as const;

/**
 * The streaming WebSocket is opened straight at FastAPI: Next's dev proxy does not
 * forward WS upgrades, and WebSockets bypass CORS anyway.
 * Override with NEXT_PUBLIC_MARI_WS (e.g. wss://kiosk.example/ws).
 */
export function wsUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_MARI_WS;
  if (explicit) return explicit;
  const { protocol, hostname, port, host } = window.location;
  const proto = protocol === "https:" ? "wss:" : "ws:";
  // Served by `next dev`/`next start` → FastAPI is the separate process on :8010.
  // Served from any other origin → assume a single host in front of both.
  const target = port === "3000" ? `${hostname}:8010` : host;
  return `${proto}//${target}/ws`;
}
