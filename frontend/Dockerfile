# MARI frontend — Next.js kiosk UI. Multi-stage build producing the `standalone`
# output (next.config.ts: output: "standalone") so the runtime image only needs
# node + the traced production deps, not the full node_modules tree.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Origin the build-time API rewrites point at (server-side proxy target for /api/*).
# Override at build time if the backend isn't reachable at this address during build
# (rewrites are resolved at request time, not baked in, so the default is fine for
# most deployments — see next.config.ts).
ARG MARI_API_ORIGIN=http://127.0.0.1:8010
ENV MARI_API_ORIGIN=${MARI_API_ORIGIN}
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not read at
# container runtime — must be passed as a build ARG, not just a `docker run -e`.
ARG NEXT_PUBLIC_MARI_WS=""
ENV NEXT_PUBLIC_MARI_WS=${NEXT_PUBLIC_MARI_WS}
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
