# MARI Interactive Kiosk

A touchscreen kiosk with a 3D presenter. A visitor speaks or types, and it answers
questions about Mari Energies from the company's own knowledge base — in English or
Urdu, in one of two presenters' voices, with the avatar's mouth matching the speech.

```
microphone → speech to text → retrieval → LLM → text to speech → audio + lipsync
```

| | |
|---|---|
| **Backend** | FastAPI, one process (`server/`) |
| **Frontend** | Next.js 15 + three.js (`frontend/`) |
| **Speech to text** | Soniox for Urdu, faster-whisper for English |
| **LLM** | Qwen 3.5 on vLLM, or DeepSeek |
| **Text to speech** | UpliftAI, optionally Matcha-TTS for the female Urdu voice |
| **Retrieval** | Qdrant, hybrid dense + sparse with FastEmbed |
| **Lipsync** | NVIDIA Audio2Face-3D, on a separate GPU host, optional |
| **Deployed** | `docker-compose.yml`, by Coolify |

## Where to look

| | |
|---|---|
| **How it is put together, and why** | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Conventions a change has to follow** | [CLAUDE.md](CLAUDE.md) |
| **A walkthrough of the whole codebase** | [MARI_INTERACTIVE_KIOSK_GUIDE.md](MARI_INTERACTIVE_KIOSK_GUIDE.md) |
| **Why a structural decision was made** | [docs/decisions/](docs/decisions/) |
| **Retrieval design and measurements** | [README-RAG.md](README-RAG.md) |
| **Quality baselines, and how to re-run them** | [eval/baselines/README.md](eval/baselines/README.md) |

## Running it

### With Docker Compose — what Coolify deploys

```bash
cp .env.example .env     # fill in at least the LLM keys and MARI_RAG_QDRANT_API_KEY
docker compose up -d --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8010, status at `/healthz`

**Check `/healthz` first when something is not working.** It reports which providers
are configured and reachable, and whether retrieval has finished warming up.

Nothing is mounted into the containers, so after a change rebuild the service you
touched:

```bash
docker compose up -d --build backend     # or frontend
```

**A cold start takes minutes.** The backend downloads embedding models on first boot
and answers from its core brief until retrieval is ready. That is deliberate — see
[ARCHITECTURE.md §7](ARCHITECTURE.md#7-the-kiosk-always-speaks).

### Locally, without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python -m uvicorn server.app:app --host 127.0.0.1 --port 8010

cd frontend && npm install && npm run dev      # http://localhost:3000
```

Retrieval needs a Qdrant instance; the simplest route is `docker compose up -d qdrant`
and pointing `MARI_RAG_QDRANT_HOST` at it.

`scripts/dev.sh {start|stop|restart|status}` starts the backend, the frontend and the
Audio2Face container together, with logs under `.run/`.

### Lipsync — optional, needs a GPU

```bash
cd deploy/a2f
cp .env.example .env          # NGC_API_KEY from build.nvidia.com
docker login nvcr.io -u '$oauthtoken' -p "$NGC_API_KEY"
docker compose --profile init up nim-init    # first boot only, ~10 GB model pull
docker compose up -d
```

Then set `APP_A2F_URL=127.0.0.1:52000` in the root `.env`. Leave it unset and the kiosk
runs normally with a still mouth. The port is loopback-only on purpose: the NIM has no
authentication of its own. See `deploy/a2f/docker-compose.yml`.

## Configuration

Every setting is read from the environment — `.env` locally, Coolify's own environment
variables in production. Copy `.env.example`, which lists them all; a test enforces
that it stays in step with the code.

| Concern | Variables |
|---|---|
| LLM | `APP_LLM_*` (DeepSeek-compatible) or `APP_VLLM_*` (vLLM Qwen) |
| Urdu speech to text | `APP_SONIOX_API_KEY` |
| Text to speech | `APP_UPLIFT_API_KEY`; `APP_UR_TTS=matcha` for the local Urdu voice |
| English speech to text | local by default, no key needed |
| Retrieval | `MARI_RAG_*`, including `MARI_RAG_QDRANT_API_KEY` (required) |
| Lipsync | `APP_A2F_URL` — unset means no lipsync |

## Deploying to Coolify

1. Point a Coolify **Docker Compose** resource at this repository.
2. Give `backend` and `frontend` their own FQDNs. The `ports:` block exists only so
   plain `docker compose up` works off-platform.
3. Set `NEXT_PUBLIC_MARI_WS=wss://<backend-domain>/ws` as a **build-time** variable on
   the frontend. Next.js resolves it when the image is built, not when the container
   starts, so a runtime variable silently has no effect.
4. Set the backend's provider keys in Coolify's environment UI. `.env` is never
   committed; compose's `env_file` is a local convenience (`required: false`).
5. Deploy `deploy/a2f/` separately on a GPU host and point `APP_A2F_URL` at it through
   a TLS proxy that checks `APP_A2F_API_KEY`.

## Working on it

```bash
pytest -q                                      # 928 tests, a few seconds
ruff check . && lint-imports && mypy           # style, layering, types
cd frontend && npm run lint && npm run typecheck && npm run profiles:check
```

CI runs all of that plus both image builds on every pull request.

### Things that must not change by accident

These files record how the kiosk behaves today. A diff in one means behaviour moved, so
fix the code rather than refreshing the file — and if the change was deliberate, update
it in the same commit with the reason in the message.

| File | Pins |
|---|---|
| `tests/fixtures/golden.json` | what the kiosk says: speech text, prompts, LLM payloads |
| `tests/fixtures/ws_golden.json` | the WebSocket contract and every lipsync frame |
| `frontend/test/fixtures/avatar-profiles.json` | every per-presenter look value |
| `eval/baselines/` | retrieval and answer quality |
| `tests/test_turn_timing.py` | that sentence synthesis still overlaps |

### Quality checks that need live services

```bash
set -a && . ./.env && set +a
export MARI_RAG_QDRANT_HOST=<the qdrant container's address>   # its port is not published

python eval/run_eval.py --k 5 --baseline eval/baselines/retrieval.json
python eval/run_answers.py --repeat 2 --baseline eval/baselines/answers.jsonl
```

Both exit non-zero on a regression. Run them from the host, not inside the backend
container, which holds an image copy of the code. See
[eval/baselines/README.md](eval/baselines/README.md).
