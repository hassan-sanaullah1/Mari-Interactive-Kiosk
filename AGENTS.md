# AGENTS.md

Rules for anyone changing this repository: developers, reviewers and AI coding agents.

## Project
intelligent-kiosk is a touchscreen voice kiosk: visitors speak or type to a 3D presenter,
and it answers questions about Mari Energies from the company's knowledge base, in English
or Urdu.
Stack: Python (FastAPI), Qdrant, Next.js 15, three.js, Docker, deployed by Coolify.
Read [docs/architecture.md](docs/architecture.md) before any structural change.

## Commands
- `make setup` once per clone: installs the commit hooks, creates `.env` from `.env.example`, installs frontend packages
- `make dev`   start everything locally (frontend :3000, backend :8010), plus lipsync when this machine has `deploy/a2f/.env`
- `make down`  stop it (keeps `.env`)
- `make lint`  run every check on every file; the same checks run on each commit and on every PR
- `make check` the deeper checks before a PR: tests and snapshots, import layers, types

## Structure
- `server/app.py`        routes only: `/chat`, `/ws`, `/health/live`, `/health/ready`, `/healthz`
- `server/agent/`        one conversation turn: session, responder, reply policy
- `server/rag/`          retrieval: question in, system prompt out
- `server/providers/`    the only code that talks to vendors (LLM, speech to text, text to speech)
- `server/avatar/`       Audio2Face lipsync client
- `server/prompts/`, `server/data/`, `server/personas.toml`   prompts, knowledge base, per-presenter settings
- `server/config.py`, `server/logging_setup.py`   configuration and the shared logger
- `frontend/app/`, `components/`, `hooks/`, `lib/`   Next.js UI; `lib/` is the bottom layer
- `eval/`, `tests/`      quality graders and the test suite; `docs/` for anything longer than the README

## Conventions
- Type hints on every function (mypy enforces it). Pydantic models for every request and response.
- Imports point one way: `app → agent → rag → avatar | providers | normalization | prompts → config`.
  `lint-imports` enforces it; on the frontend, ESLint stops `lib/` importing `components/` or `hooks/`.
- Presenters are data. No `if avatar == "male"` and no `"female"` default: per-presenter values
  live in `server/personas.toml` and the frontend avatar profile.
- One client per external service. The LLM is reached only through `server/providers/llm.py`;
  no `httpx.AsyncClient` in business logic.
- Read configuration only through `server/config.py` (and `server/rag/settings.py` for `MARI_RAG_*`).
  No `os.getenv` elsewhere.
- Log through `logger = logging.getLogger(__name__)`; the request ID is added for you. No `print`.
- New endpoints return errors as `{"error": {"code": "...", "message": "..."}}`.
- New or unfinished features go behind a flag named `enable_<feature>`, default off.
- Comments say *why*: a constraint, a workaround, a measurement. Not what the code does, and not
  its history. A measurement worth keeping goes in `docs/` with a one-line pointer from the code.
- Names are words (`audio_context`, not `ac`), American spelling, booleans read as questions
  (`is_ready`). Files: Python snake_case, JS/TS kebab-case, React components PascalCase, folders kebab-case.
- Urdu is gendered: replies and UI status strings must agree with the presenter.
- Refactors and behaviour changes go in separate commits.

## Do not
- Commit secrets, `.env` files or real visitor data.
- Put secrets or environment values in a Dockerfile or pass them at build time, except the
  frontend's `NEXT_PUBLIC_MARI_WS` and `MARI_API_ORIGIN`, which Next.js needs when it builds.
- Add a dependency without explaining why in the PR description.
- Change the response shape of `/chat` or the `/ws` frames without a deliberate, versioned change.
- Refresh a pinned snapshot or baseline to make a check pass: `tests/fixtures/golden.json`,
  `tests/fixtures/ws_golden.json`, `frontend/test/fixtures/avatar-profiles.json`, `eval/baselines/`.
  A diff there means behaviour moved; update one only in the commit that moves it on purpose,
  with the reason in the message.
- Retune lipsync or the Audio2Face face parameters without measuring with `scripts/lipsync_audit.py`.
- Shorten the LLM reply cap to make room in the 8192-token context; missed facts come from
  the model dropping what it was given, not from the cap.
- Change a prompt with a word-swap list, or without checking live replies (`eval/run_answers.py`).
- Replace a model file under the same name: `/models/*` is cached as immutable, so give it a new one.
- Publish Qdrant's port; host-side eval uses the container's address (`docs/eval-baselines.md`).

## Git
- Branch: `<type>/<short-description>`, cut from `develop`, for example `fix/urdu-status-gender`.
  Types: `feature`, `fix`, `hotfix`, `chore`, `docs`, `refactor`.
- PR title: `<type>(<scope>): <summary>`, for example `fix(voice): agree Urdu status strings with the presenter`.
  Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `ci`, `build`, `revert`.
- Scopes in this repo: `repo`, `deploy`, `server`, `voice`, `rag`, `prompts`, `avatar`,
  `frontend`, `eval`, `deps`, `ci`.
- PRs into `develop` are squash-merged, so the PR title becomes the commit message.
- A PR that changes how the project is run, configured or deployed updates the README too.
