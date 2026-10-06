# MARI frontend — Next.js kiosk UI. Multi-stage build producing the `standalone`
# output (next.config.ts: output: "standalone") so the runtime image only needs
# node + the traced production deps, not the full node_modules tree.

FROM node:25-slim AS deps
WORKDIR /app
# Next's anonymous telemetry spawns a detached child process to flush its event
# file (next/dist/telemetry/storage.js). Harmless on a workstation; in a slim
# container it is one more thing that can hang or be killed mid-build, for no
# benefit. Off in every stage.
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
# Refuse to build a release with a known critical hole in a runtime dependency.
# Next.js 15.5.4 carried a public unauthenticated RCE (GHSA-9qr9-h5gf-34mp) for
# months; a bot found the Coolify deployment and ran shell commands inside this
# container (secret hunting, miner and flooder downloads). This makes Coolify fail
# the deploy — keeping the previous container up — instead of shipping another.
# If it fails: `npm audit --omit=dev` in frontend/, upgrade what it names, redeploy.
RUN npm audit --omit=dev --audit-level=critical

FROM node:25-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Cap the build's heap. Without a limit V8 sizes the old space from the HOST's
# total RAM, not from the container's cgroup limit, so on a memory-capped build
# (Coolify's default on a small VPS) the process happily grows past the limit and
# is killed rather than collecting. A ceiling under the limit makes it GC instead.
# Raise this if the build host has more headroom; lower it if the build is killed.
ENV NODE_OPTIONS=--max-old-space-size=2048
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Origin the /api/* rewrites proxy to (see next.config.ts).
#
# This MUST be set for any deployment where the backend is not inside the frontend
# container. `next build` resolves the destinations once and writes them into
# .next/routes-manifest.json as absolute URLs — verified, not assumed:
#   afterFiles[0] = { source: "/api/chat", destination: "<this value>/chat" }
# They are NOT re-read from the environment at request time, so the default below
# gets baked in permanently and the running frontend proxies every chat and voice
# call to port 8010 inside its OWN container, where nothing listens. The page loads,
# the avatar loads, and every turn fails — which looks like a backend fault.
#
# docker-compose.yml passes http://backend:8010 through `build.args`. Coolify only
# applies those args when the resource is deployed as a Docker Compose resource; a
# plain "Dockerfile" application ignores the compose file entirely, so set
# MARI_API_ORIGIN as a BUILD-TIME variable in the Coolify UI in that case.
ARG MARI_API_ORIGIN=http://127.0.0.1:8010
ENV MARI_API_ORIGIN=${MARI_API_ORIGIN}
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not read at
# container runtime — must be passed as a build ARG, not just a `docker run -e`.
ARG NEXT_PUBLIC_MARI_WS=""
ENV NEXT_PUBLIC_MARI_WS=${NEXT_PUBLIC_MARI_WS}
RUN npm run build

FROM node:25-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Files stay owned by root and the server runs as the image's unprivileged `node`
# user, so a compromised server can neither rewrite the app nor apt-get install
# tools (the attacker above tried exactly that, as root).
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

USER node
EXPOSE 3000
CMD ["node", "server.js"]
