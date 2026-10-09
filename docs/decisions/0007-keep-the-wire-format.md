# 0007 — Formalise the WebSocket format, don't redesign it

**Status:** accepted · 2026-10

## Context

The browser and server exchange about twelve message types, built as dicts on one side
and parsed by string comparison on the other, with no schema. Lipsync frames are JSON
arrays of rounded floats — roughly 150 to 310 bytes a frame, in batches of three.

Restructuring was the moment to reconsider the format.

## Decision

The format does not change. It gets pinned, by a snapshot of the full ordered frame
list for eighteen scenarios (`tests/fixtures/ws_golden.json`), including lipsync frames
and the per-presenter Audio2Face tuning. Typed models are a later step and must not
alter a byte.

## Considered

**Binary lipsync frames.** Rejected. The saving is real but the kiosk is on a LAN,
frames are not the bottleneck, and the browser's frame handling is tuned against the
current shape. Revisit if it ever runs over the internet.

**A versioned envelope, or adopting RTVI.** Rejected for now. Both are better designs
for a protocol with more than one client. There is one client, shipped from the same
repository.

**Generating TypeScript types from the server's schema.** Rejected as more machinery
than twelve messages justify. Hand-written types on both sides, plus a shared file of
example messages both test suites parse, give the same protection.

## Consequences

- Browser and server can be restructured independently and the snapshot proves the
  contract held.
- The format keeps its awkward parts: no version field, and fields the browser ignores.
- An actual protocol change now means regenerating a snapshot deliberately, which is
  the point.
