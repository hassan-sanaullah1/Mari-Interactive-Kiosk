# 0001 — One backend process, not microservices

**Status:** accepted · 2026-10

## Context

The backend does speech to text, retrieval, LLM calls, text to speech and lipsync for
one kiosk. Each of those is a plausible service boundary, and splitting them is the
reflex answer for "is this architected properly".

The load is one kiosk: one visitor at a time, a handful of turns a minute. The thing
that makes or breaks the product is how long the visitor waits before hearing a reply.

## Decision

One process, divided into packages with an enforced one-way import rule
(`[tool.importlinter]` in `pyproject.toml`). Only the two components that genuinely
need their own process have one: Qdrant, because it is a database, and the Audio2Face
NIM, because it needs a GPU.

## Considered

**Microservices per stage.** Rejected. Speech to text, the LLM and text to speech are
already HTTP calls to other people's servers. Wrapping each in a service of ours adds a
hop to a latency-critical loop and buys no fault isolation we do not already have — a
vendor outage is handled by the degradation rules either way, and those live in the
caller. At this traffic there is also nothing to scale independently.

**A single unstructured app.** What it was drifting towards: a 140-line turn function,
a socket handler nested seven levels deep, three separate HTTP clients for the same
LLM. The packages and the import contract are the response to that, not to scale.

## Consequences

- One deploy, one log stream, one place to reproduce a bug.
- The module boundaries are enforced by a tool, so they are real rather than aspirational.
- If a stage ever does need to scale alone, the adapter interface is the seam to cut at.
- Everything shares a process: a blocking call on the event loop stalls the whole kiosk.
  That is a real hazard and the reason model loading is pushed to threads.
