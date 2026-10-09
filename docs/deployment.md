# Deployment notes

Why `docker-compose.yml`, the two Dockerfiles and the compose override are the way they
are. The compose file keeps one-line comments and points here for the reasoning.

## Which file runs where

| File | Read by | Holds |
|---|---|---|
| `docker-compose.yml` | Coolify and every local run | The services, what they are built from, their volumes and fixed settings |
| `docker-compose.override.yml` | Local runs only; Compose merges it automatically | Published ports (`8010`, `3000`) |
| `docker-compose.a2f.yml` | Local runs through `make dev`, which first starts `deploy/a2f/` when the machine has its `.env` | Joins the backend to the Audio2Face stack's network |

Coolify is pointed at `docker-compose.yml` alone, so nothing in the other two reaches a
server. Ports stay out of the deployed file because Coolify routes through its own
proxy, and a published port collides as soon as two environments share a host.

The A2F join is a separate opt-in file, not part of the override, because it names an
`external` network: a plain `docker compose up` on a machine that has never run the A2F
stack would fail outright. Never declare a `networks:` block in `docker-compose.yml`;
Coolify attaches its own network at deploy time.

## Audio2Face

The Audio2Face-3D NIM (avatar lipsync) needs a GPU host with the NVIDIA container
runtime, so it is not part of this stack. Deploy it separately (`deploy/a2f/`) and point
the backend at it with `APP_A2F_URL`, an address reachable from inside the compose
network: a LAN `host:port`, or `grpcs://` through a TLS proxy that checks
`APP_A2F_API_KEY`. A NIM published on the host's loopback is **not** reachable from
inside the network. Leave `APP_A2F_URL` unset and the kiosk runs without lipsync.

## Qdrant

- **The API key is required.** Qdrant has no authentication by default, and its REST
  API includes "delete collection". Anything that can reach the port could wipe the
  corpus, so compose refuses to start without `MARI_RAG_QDRANT_API_KEY`.
- **The port is not published.** The backend reaches Qdrant by service name. Publishing
  6333 would put an admin API on the host's interfaces; host-side eval uses the
  container's address instead (see [eval-baselines.md](eval-baselines.md)).
- **Named volume, not a bind mount.** The index is derived data and can always be
  rebuilt by re-ingesting, but that costs ~40 s of embedding on every recreate.
- **The healthcheck uses `CMD` + `bash`, not `CMD-SHELL`.** The image ships no curl or
  wget, so the check opens the socket with bash's `/dev/tcp`, a bash builtin that dash
  lacks. `CMD-SHELL` runs `/bin/sh`, which is dash in this image, so that form fails every
  time. Because the backend waits for Qdrant to be healthy, a failing check leaves the
  whole stack in "Created".
- **`/readyz`, not `/healthz`.** Qdrant answers `/healthz` before its collections are
  loaded, so a backend starting on that signal can race the storage load and see an
  empty collection.

## Backend

- **`env_file: .env`** delivers the provider keys: a local `.env`, or the one Coolify
  writes from its environment variables. `required: false` keeps compose working without
  one. The `environment:` entries win over `.env` values of the same name, which is what
  lets a `.env` written for running on the host work unchanged inside the network.
- **`MARI_RAG_QDRANT_HTTPS: "false"`.** The compose network is plaintext, and
  qdrant-client silently switches to HTTPS as soon as an API key is set, which turns into
  a TLS handshake against an HTTP port and an error that points nowhere near the cause.
- **`MARI_RAG_METADATA_DB` on the `rag_state` volume.** It records which corpus files are
  already in the index, so a restart does not re-embed the corpus. It is state about the
  Qdrant volume, so it lives on a volume with the same lifecycle, not in the image and
  not in the corpus directory it defaults to. If the two fall out of step, ingestion
  cross-checks the real point count before skipping a file.
- **`FASTEMBED_CACHE_PATH`.** Without it FastEmbed writes its ~3 GB of ONNX weights to
  `/tmp/fastembed_cache`, not the path the `fastembed_cache` volume is mounted at, so the
  weights were re-downloaded on every recreate while the volume sat empty.
- **`whisper_cache`.** faster-whisper's `base.en` model (~150 MB) downloads from Hugging
  Face on first use. On a slow link that took 15+ minutes and made English speech to
  text look broken; the volume makes it a one-time download.
- **Healthcheck.** In `server/Dockerfile`, against `/health/ready`. Retrieval still
  warming counts as ready, because turns are answered from the core brief meanwhile, so
  the check does not wait for the model downloads.

## Frontend

- **`MARI_API_ORIGIN` and `NEXT_PUBLIC_MARI_WS` are build arguments.** `next build`
  writes the `/api/*` rewrite destinations into its routes manifest, and inlines
  `NEXT_PUBLIC_*` values into the client bundle, so a runtime variable silently has no
  effect. `NEXT_PUBLIC_MARI_WS` is the backend's public `wss://…/ws` URL, needed whenever
  frontend and backend are on different domains (always on Coolify). Left empty locally,
  `lib/endpoints.ts` derives `ws://<same-host>:8010/ws`.
- **Hardening.** After the 2026-09 compromise through a Next.js RCE, the container is
  read-only apart from two small `noexec` tmpfs mounts, drops every capability, cannot
  regain privileges, and has PID, memory and CPU caps, so the next foothold can neither
  persist tools nor exhaust the host.
- **`depends_on: service_started`, not `service_healthy`.** Gating on backend health
  means a backend that is merely slow to become healthy (a cold boot downloading models)
  keeps the frontend from being created at all, and the proxy then answers "server not
  available" for the whole site. Started first, the page loads and `/api/*` returns 502
  until the backend answers, which the UI already handles.
- **Healthcheck.** In `frontend/Dockerfile`, against `/version.json`, with node because
  the image has neither curl nor wget.
