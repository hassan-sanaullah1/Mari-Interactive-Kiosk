# MARI × speech-to-speech

Integration of **[huggingface/speech-to-speech](https://github.com/huggingface/speech-to-speech)**
with MARI's stack: **vLLM (Qwen3.5)** LLM, **Whisper + Soniox** STT, **Kokoro + Uplift**
TTS. This is the "hugging voice" engine referenced by the kiosk project —
speech-to-speech is a modular VAD→STT→LLM→TTS pipeline, and this repo wires our
providers into it.

Companion to **`Mari-Interactive-kiosk`** (the production kiosk on FastRTC). That repo
keeps LiveKit-vs-speech-to-speech as a benchmark; this repo is the speech-to-speech
implementation being compared.

This repo actually holds **two separate, independently runnable things**:

- **The kiosk web app** (`server/` FastAPI backend + `frontend/` Next.js UI, optionally
  `deploy/a2f/` for avatar lipsync) — a standalone voice UI, no GPU pipeline required.
  This is almost certainly what you want to run/deploy. See
  **[Running the kiosk](#running-the-kiosk)** below.
- **The `mari_s2s` GPU pipeline** (this file's original subject, below) — plugin
  handlers for the upstream `speech-to-speech` project, launched via
  `scripts/run_en.sh` / `run_ur.sh`. Unrelated transport-wise to the kiosk app above;
  see [ARCHITECTURE.md](ARCHITECTURE.md) for how the two relate.

---

## Running the kiosk

The kiosk is **backend** (FastAPI, `server/app.py`) + **frontend** (Next.js,
`frontend/`), with an optional third piece, **A2F** (NVIDIA Audio2Face-3D, avatar
lipsync, `deploy/a2f/`). Backend and frontend run fine without A2F — the avatar just
won't move its mouth.

### Option A — Docker Compose (recommended, also what Coolify deploys)

```bash
cp .env.example .env       # fill in at least the LLM (vLLM or DeepSeek) keys
docker compose up -d --build
```

- Backend → http://localhost:8010 (health at `/healthz`)
- Frontend → http://localhost:3000

`docker-compose.yml` builds `server/Dockerfile` and `frontend/Dockerfile`. The
frontend proxies `/api/*` to the backend server-side and opens `/ws` directly against
it from the browser — see `frontend/next.config.ts` and `frontend/lib/endpoints.ts`.
Because Next.js resolves both of those at **build time**, not container start,
`MARI_API_ORIGIN` and `NEXT_PUBLIC_MARI_WS` are passed as Docker **build args** in
`docker-compose.yml`, not runtime env vars — if you fork the compose file, keep them
as `args:`, not `environment:`.

**Deploying to Coolify:**

1. Point a Coolify "Docker Compose" resource at this repo; it'll pick up the root
   `docker-compose.yml` and build both services.
2. Give `backend` and `frontend` separate FQDNs in the Coolify UI (each service gets
   its own domain — Coolify's proxy handles routing; the `ports:` block in the compose
   file is only there so `docker compose up` also works standalone off-platform).
3. Set `NEXT_PUBLIC_MARI_WS=wss://<your-backend-domain>/ws` as a **build-time**
   variable on the `frontend` service before it builds — the browser opens the
   WebSocket directly against the backend's public domain, bypassing the frontend's
   proxy entirely, and the URL must be baked in at build time (see above). Skipping
   this leaves the WebSocket trying to reach the frontend's own origin instead.
4. Set the backend's env vars (LLM/STT/TTS provider keys — see `.env.example`,
   `server/config.py`) directly in Coolify's environment-variables UI. `.env` is
   gitignored and never committed; `docker-compose.yml`'s `env_file: .env` is a
   local-dev convenience only (`required: false`, so it's fine if it doesn't exist).
5. **A2F needs a GPU host** with the NVIDIA container runtime, which most Coolify
   targets don't have — it's deliberately *not* part of the root compose file. Deploy
   `deploy/a2f/` separately on a GPU-capable host (Coolify or otherwise), then point
   the backend at it with `APP_A2F_URL` (e.g. `grpcs://a2f.your-domain:443` through a
   TLS proxy that checks `APP_A2F_API_KEY` — see the security note in
   `deploy/a2f/docker-compose.yml`). Leave `APP_A2F_URL` unset and the kiosk runs
   fine without lipsync.

### Option B — local processes (no Docker)

```bash
# backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-web.txt
cp .env.example .env
python -m uvicorn server.app:app --host 127.0.0.1 --port 8010

# frontend (separate terminal)
cd frontend && npm install && npm run dev     # http://localhost:3000
```

Or use `./mari.sh {start|stop|restart|status}`, which manages backend, frontend, and
the A2F Docker container together (see the script's header comment).

The legacy static UI in `web/` is untouched and still served directly at
http://127.0.0.1:8010/ — useful for testing the backend without the Next.js frontend.

### A2F (avatar lipsync) — optional, GPU required

```bash
cd deploy/a2f
cp .env.example .env          # set NGC_API_KEY (build.nvidia.com)
docker login nvcr.io -u '$oauthtoken' -p "$NGC_API_KEY"
docker compose --profile init up nim-init    # first boot only, ~10GB model pull
docker compose up -d
```

Then set `APP_A2F_URL=127.0.0.1:52000` in the repo-root `.env` (or wherever the
backend runs). Full details, including the security note on why the port is
loopback-only by default, are in `deploy/a2f/docker-compose.yml`.

### Configuration reference

All backend settings are read from `.env` by `server/config.py` — copy
`.env.example` and fill in what you need:

| Concern | Vars |
|---|---|
| LLM | `APP_LLM_API_BASE`/`APP_LLM_API_KEY` (DeepSeek-compatible) or `APP_VLLM_API_BASE`/`APP_VLLM_API_KEY` (vLLM Qwen) |
| Urdu STT | `APP_SONIOX_API_KEY` |
| Urdu/English TTS | `APP_UPLIFT_API_KEY` |
| English STT | local by default (`faster-whisper`, no key needed) |
| Avatar lipsync | `APP_A2F_URL` (unset = no lipsync) |

`GET /healthz` on the backend reports which of these are actually configured and
reachable — check it first when something isn't working.

---

## The `mari_s2s` GPU pipeline

The rest of this document covers `mari_s2s/` — plugin handlers for the upstream
`huggingface/speech-to-speech` project — which is unrelated to the kiosk app above
except that it reuses the same provider credentials.

## What's here

```
mari_s2s/handlers/soniox_stt_handler.py   Urdu STT  (BaseHandler[STTIn, STTOut])
mari_s2s/handlers/uplift_tts_handler.py   Urdu TTS  (BaseHandler[TTSIn, TTSOut])
mari_s2s/arguments/                        CLI/config dataclasses for the above
mari_s2s/register.py                       make --stt soniox / --tts uplift resolve
scripts/run_en.sh                          English pipeline (s2s built-ins only)
scripts/run_ur.sh                          Urdu pipeline (our custom handlers)
docs/integration.md                        contract + registration walkthrough
```

## Provider mapping

| Stage | English | Urdu |
|---|---|---|
| STT | `faster-whisper` (s2s built-in) | **Soniox** (custom) |
| LLM | `chat-completions` → vLLM Qwen3.5 | same |
| TTS | `kokoro-82m` (s2s built-in) | **Uplift** (custom) |

**English needs no new code** — it's pure s2s configuration. Only **Urdu** required
custom handlers (s2s has no Urdu-native STT/TTS).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # (or Docker — see Dockerfile)
pip install -r requirements.txt                        # pulls s2s at your pin
cp .env.example .env                                   # set vLLM + Soniox + Uplift

# Confirm s2s's current flag names (they evolve), then run:
python -m speech_to_speech.s2s_pipeline --help

bash scripts/run_en.sh     # English (built-ins)
# register custom handlers (docs/integration.md), then:
bash scripts/run_ur.sh     # Urdu (Soniox + Uplift)
```

## Status & honest caveats

- The **custom handlers** are written against s2s's confirmed handler/message
  contract (`BaseHandler`, `VADAudio`/`Transcription`/`TTSInput`) and reuse the
  tested Soniox/Uplift logic from the kiosk's `voicecore`. They **compile**; full
  runtime validation needs s2s installed + reachable endpoints (I couldn't run the
  GPU stack here).
- The **registration hook** (`--stt soniox` / `--tts uplift`) is version-sensitive:
  s2s's builder registry isn't a documented public API. `register.try_autoregister()`
  handles the common cases and warns loudly otherwise; `docs/integration.md` has the
  explicit drop-in steps. **Pin an s2s commit** in `requirements.txt` before relying
  on it.
- s2s's exact CLI flag names for the LLM base URL can differ by commit — the run
  scripts note where to confirm with `--help`.

See [docs/integration.md](docs/integration.md) for the full contract and wiring.
