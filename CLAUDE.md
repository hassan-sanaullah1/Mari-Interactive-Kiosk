# Working in this repo

A production voice kiosk: visitors speak to a 3D presenter and it answers from Mari
Energies' knowledge base. Built incrementally across many sessions, which is how it
accumulated duplicated logic and conflicting comments — so the rules below are about
not adding more.

Read `ARCHITECTURE.md` before any structural change.

## What this is

- `server/` — FastAPI, one process. Speech in over a WebSocket, retrieval, LLM, speech
  out, plus Audio2Face lipsync frames on the same socket.
- `frontend/` — Next.js kiosk UI with a three.js avatar.
- `eval/` — graders for retrieval and for what the kiosk actually says.
- Deployed with `docker-compose.yml` on Coolify. The Audio2Face NIM is a separate GPU
  stack in `deploy/a2f/` and is deliberately **not** in the compose file.

## The rules that matter

**1. Dependencies point one way.** `app → agent → rag → avatar | providers |
normalization | prompts → config`. Nothing imports upward. `lint-imports` enforces it
from `pyproject.toml`; on the frontend, `lib/` must not import from `components/` or
`hooks/`, and ESLint enforces that.

**2. Presenters are data.** Male and female differ only in configuration. Do not write
`if avatar == "male"`, and do not add a `"female"` default. Per-presenter values belong
in the avatar profile (frontend) or the persona config (backend). Both linters fail on
a bare `"male"`/`"female"` literal outside those files.

**3. One client per external service.** The LLM is reached through
`server/providers/llm.py` and nothing else. Do not open an `httpx.AsyncClient` in
business logic — there were three LLM clients once, and they drifted apart.

**4. Comments say *why*.** Keep a comment that explains a constraint, a workaround, or
a measurement that justifies a number. Delete anything that restates the code or tells
the file's history ("was 0.45", "used to", "girl14") — git has that. A measurement that
earns its keep goes in `docs/` with a one-line pointer from the code.

**5. Names are words.** `audio_context`, not `ac`. `message`, not `evt`. American
spelling (`normalize`). `logger`, not `log`. Booleans read as questions (`is_ready`,
`visitor_spoke`).

**6. Refactors and behaviour changes are separate commits.** Never both at once.

## Before you say you are done

```bash
pytest -q                      # includes the snapshots and the timing guard
ruff check . && lint-imports
cd frontend && npm run lint && npm run typecheck && npm run profiles:check
```

Then rebuild whatever you changed, because nothing is mounted into the containers:

```bash
docker compose up -d --build backend   # or frontend
```

## What must not change by accident

These are recorded measurements of how the kiosk behaves today. A diff in any of them
means behaviour moved, so fix the code rather than refreshing the file:

| File | Pins |
|---|---|
| `tests/fixtures/golden.json` | What the kiosk says: TTS text, prompts, LLM payloads, socket frames |
| `tests/fixtures/ws_golden.json` | The `/ws` endpoint and every lipsync frame, including per-presenter A2F tuning |
| `frontend/test/fixtures/avatar-profiles.json` | Every per-presenter look value |
| `eval/baselines/` | Retrieval quality and answer quality (see the README there) |
| `tests/test_turn_timing.py` | That sentence synthesis still overlaps instead of running one at a time |

A baseline may only be replaced in the same commit as the deliberate change that moved
it, with the reason in the message. Refreshing one to make a check pass removes the
check.

## Things that will bite you

- **Lipsync and the A2F face parameters are tuned by measurement**
  (`scripts/lipsync_audit.py`). Gains, teeth offsets and shape transfer have all been
  tried and rejected on screen. Do not retune them speculatively.
- **The LLM context is 8192 tokens** and the reply cap is not the limiting factor —
  answer misses are the model dropping facts it was given. Never shorten the reply cap
  to make room.
- **Prompt changes must be general rules**, not word-swap lists, and must be checked
  against live replies (`eval/run_answers.py`), not just the snapshot.
- **Urdu is gendered.** Verbs and UI status strings have to agree with the presenter.
- **Qdrant's port is not published.** Host-side eval needs
  `MARI_RAG_QDRANT_HOST` set to the container's address; see `eval/baselines/README.md`.
- **Changed a model file?** Give it a new filename. `/models/*` is served with
  immutable cache headers, so browsers keep the old one.
- **Do not commit.** Hand over a one-line `git commit` command instead. Never delete a
  branch.
