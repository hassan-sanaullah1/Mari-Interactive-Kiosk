# interactive-kiosk

A touchscreen kiosk with a 3D presenter. A visitor speaks or types, and it answers
questions about Mari Energies from the company's own knowledge base, in English or Urdu,
in one of two presenters' voices, with the avatar's mouth matching the speech.

```
microphone → speech to text → retrieval → LLM → text to speech → audio + lipsync
```

## Tech stack

| | |
|---|---|
| **Backend** | Python (3.11 in the image and in CI; a 3.12 virtualenv also works), FastAPI, one process (`server/`) |
| **Frontend** | Next.js 15 + three.js (`frontend/`) |
| **Speech to text** | Soniox for Urdu, faster-whisper for English |
| **LLM** | Qwen 3.5 on vLLM, or DeepSeek |
| **Text to speech** | UpliftAI, optionally Matcha-TTS for the female Urdu voice |
| **Retrieval** | Qdrant, hybrid dense + sparse with FastEmbed |
| **Lipsync** | NVIDIA Audio2Face-3D, on a separate GPU host, optional |
| **Deployed** | `docker-compose.yml`, by Coolify |

## Run locally

Prerequisites: Docker with Compose, Make, Node 24, pipx (for pre-commit), and for work outside Docker, Python 3.11 (3.12 also works).

```bash
make setup     # once per clone: commit hooks, .env from .env.example (fill in at least
               # the LLM keys and MARI_RAG_QDRANT_API_KEY), frontend packages
make dev       # builds and starts everything, with live reload
make prod      # the same, from the production images Coolify deploys
make down      # stops either (your .env is kept)
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8010. **Check `/healthz` first when something is not
  working.** It reports which providers are configured and reachable, and whether
  retrieval has finished warming up.
- API docs: http://localhost:8010/docs

`make dev` mounts the source into the containers, so changes apply as you save: the
backend restarts on any change in `server/` (code, prompts, `personas.toml`, knowledge
base) and the frontend hot-reloads `app/`, `components/`, `hooks/`, `lib/` and `public/`.
Run `make dev` again only after changing `requirements.txt`, `package.json`,
`next.config.ts` or a Dockerfile. Before a release, `make prod` runs the production build
locally. `make lint` runs the checks every commit and every pull request must
pass (`.pre-commit-config.yaml`, enforced by `.github/workflows/pr-checks.yml`); `make check`
runs the tests, snapshots, types and import layers.

Health: `/health/live` (the process is up) and `/health/ready` (environment, commit, and
whether the LLM and Qdrant are usable; 503 if not). The frontend serves `/version.json`
with its commit. Local-only Compose settings live in `docker-compose.override.yml` and
`docker-compose.dev.yml`; see
[docs/deployment.md](docs/deployment.md).

A cold start takes minutes: the backend downloads embedding models on first boot and
answers from its core brief until retrieval is ready
([docs/architecture.md §7](docs/architecture.md#7-the-kiosk-always-speaks)).

**Without Docker:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn server.app:app --host 127.0.0.1 --port 8010

cd frontend && npm install && npm run dev      # http://localhost:3000
```

Retrieval still needs Qdrant: run `docker compose up -d qdrant` and point
`MARI_RAG_QDRANT_HOST` at it. `scripts/dev.sh {start|stop|restart|status}` starts the
backend, the frontend and the Audio2Face container together, with logs under `.run/`.

**Lipsync (optional, needs a GPU):** once per machine, fetch the Audio2Face model:

```bash
cd deploy/a2f
cp .env.example .env          # NGC_API_KEY from build.nvidia.com
docker login nvcr.io -u '$oauthtoken' -p "$NGC_API_KEY"
docker compose --profile init up nim-init    # first boot only, ~10 GB model pull
```

Then set `APP_A2F_URL=nim:52000` in the root `.env`. From then on `make dev` starts the
Audio2Face stack too and joins the backend to its network (`docker-compose.a2f.yml`), and
`make down` stops it. A plain `docker compose up` does **not** join that network, so
lipsync stays off that way. Leave `APP_A2F_URL` unset and the kiosk runs normally with a
still mouth. For a backend running on the host instead of in Docker, use
`APP_A2F_URL=127.0.0.1:52000`; the NIM has no authentication of its own, so its port is
loopback-only.

## Configuration

Every setting is an environment variable: `.env` locally, Coolify's environment variables
when deployed. `.env.example` lists every name, and a test keeps it in step with the code.

| Concern | Variables |
|---|---|
| LLM | `APP_LLM_*` (DeepSeek-compatible) or `APP_VLLM_*` (vLLM Qwen) |
| Urdu speech to text | `APP_SONIOX_API_KEY` |
| Text to speech | `APP_UPLIFT_API_KEY`; `APP_UR_TTS=matcha` for the local Urdu voice |
| English speech to text | local by default, no key needed |
| Retrieval | `MARI_RAG_*`, including `MARI_RAG_QDRANT_API_KEY` (required) |
| Lipsync | `APP_A2F_URL`; unset means no lipsync |
| Frontend → backend | `MARI_API_ORIGIN` (build time) and `NEXT_PUBLIC_MARI_WS` (build time) |

The frontend reaches the backend two ways. `/api/chat`, `/api/voice` and `/api/healthz`
go through a Next.js rewrite to `MARI_API_ORIGIN`. The `/ws` WebSocket connects to the
backend directly, because the Next proxy does not forward WebSocket upgrades; set
`NEXT_PUBLIC_MARI_WS=wss://<backend-domain>/ws` whenever frontend and backend are on
different domains. Both are read when the image is **built**, not when it starts.

## Environments

| Environment | Branch | URL |
|---|---|---|
| Dev | `develop` | set in Coolify |
| Staging | not created yet | |
| Production | not created yet | |

Each environment is one Coolify application that deploys when its branch changes. Dev:

1. A Coolify **Docker Compose** resource points at `Stixor-Technologies/interactive-kiosk`,
   branch `develop`, file `/docker-compose.yml`.
2. `backend` and `frontend` each get their own domain. `docker-compose.yml` publishes no
   ports; Coolify routes through its proxy.
3. Environment variables, all **Runtime only** (Buildtime off):
   - `APP_ENV=dev` and `APP_COMMIT=$SOURCE_COMMIT`; `/health/ready` reports both.
   - The provider keys from `.env.example`. `.env` is never committed.

   The one exception is `NEXT_PUBLIC_MARI_WS`, which stays **Buildtime** on the frontend
   (see Configuration).
4. Advanced: **Auto Deploy** on; **Include Source Commit in Build** off (on, it breaks
   the layer cache on every commit).
5. After a deploy, open the backend's `/health/ready` and check `"environment": "dev"`
   and the commit.
6. `deploy/a2f/` is deployed separately on a GPU host, and `APP_A2F_URL` points at it
   through a TLS proxy that checks `APP_A2F_API_KEY`.

Adding Staging and Production later: [docs/deployment.md](docs/deployment.md#adding-staging-and-production).

## Feature flags

| Flag | Purpose | Owner |
|---|---|---|
| none yet | | |

New or unfinished features go behind a flag named `enable_<feature>`, default off.

## Project structure

    server/          FastAPI backend: agent (one turn), rag, providers, avatar, prompts, data
    frontend/        Next.js kiosk UI and the three.js avatar
    eval/            retrieval and answer graders, and the recorded baselines
    tests/           pytest suite, including the golden snapshots
    scripts/         dev launcher, ingestion, lipsync audit, model optimisation
    deploy/a2f/      Audio2Face NIM stack (separate GPU host)
    docs/            architecture, decision records, measurements

| Read this | For |
|---|---|
| [AGENTS.md](AGENTS.md) | Conventions every change follows, including branches and PR titles |
| [docs/architecture.md](docs/architecture.md) | How it is put together, and why |
| [docs/decisions/](docs/decisions/) | Why each structural decision was made |
| [docs/retrieval.md](docs/retrieval.md) | Retrieval design and measurements |
| [docs/eval-baselines.md](docs/eval-baselines.md) | Quality baselines, and how to re-run them |
| [docs/prompts.md](docs/prompts.md), [docs/knowledge-base.md](docs/knowledge-base.md) | Prompt files, and the corpus format |
| [docs/deployment.md](docs/deployment.md) | Why the compose files and Dockerfiles are set up the way they are |

Before opening a pull request, run `make lint` and `make check`. Every pull request into
`develop`, `staging` or `main` runs `pr-checks`: the same hooks as `make lint`, both image
builds plus the compose files, types (mypy and `tsc`), and a security audit of the
dependencies the app runs on. The tests, snapshots and import layers are not in that
workflow; `make check` is where they run. Branch names are checked when you push, by the
hook `make setup` installs.

## Contacts

Standards: project setup guide
