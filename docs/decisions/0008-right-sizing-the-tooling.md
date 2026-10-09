# 0008 — The tools we deliberately did not adopt

**Status:** accepted · 2026-10

## Context

Researching how comparable projects are run turns up a long list of practices: uv,
structlog, OpenTelemetry, a dependency-injection container, generated API types,
Playwright, Trivy, jscpd, dependency-cruiser, pre-commit, complexity ratchets, a dozen
decision records, eight diagrams.

Each is defensible. Adopted together, on one kiosk maintained by a small team, they are
mostly ceremony — and every one is a thing that can break the build for reasons
unrelated to the product.

## Decision

Adopt the ones that catch a defect this codebase actually had, and record the rest as
deliberately declined.

**Adopted** — each tied to a real defect found in the audit:

| Tool | The defect it catches |
|---|---|
| ruff, with naming and complexity rules | a 1,578-line module, functions at complexity 28, `C` as a module alias |
| import-linter | two import cycles and six wrong-way imports |
| mypy | a Protocol that had drifted from its callers |
| ESLint with layering and literal rules | `lib/` importing `components/`, presenter branches in the UI |
| snapshot and timing tests | nothing covered the socket, the lipsync frames or the pipelining |
| committed eval baselines | the quality scripts existed but always exited zero |

**Declined:**

| Tool | Why not |
|---|---|
| uv | pinned requirements already give reproducible builds |
| structlog, OpenTelemetry | one log line per turn is what gets read; nothing aggregates it yet |
| a DI container | a module with cached provider lookups is enough at this size |
| generated TypeScript types | twelve messages; see 0007 |
| Playwright, Trivy, jscpd, dependency-cruiser, pre-commit | ruff, ESLint, tsc and pytest in one CI job cover the same ground |
| a complexity ratchet | the per-file exemption list in `pyproject.toml` is the same idea, readable, and shrinking |

## Consequences

- CI is one workflow, fast, and green for product reasons rather than tooling reasons.
- "We considered it and here is why not" is a better answer than an unexplained absence.
- Each declined item has a trigger. If per-stage latency ever has to be chased across
  turns, OpenTelemetry is the answer; if a second client ever speaks the protocol,
  generate the types.
