# 0002 — Borrow Pipecat's structure, don't depend on Pipecat

**Status:** accepted · 2026-10

## Context

[Pipecat](https://github.com/pipecat-ai/pipecat) is the established open-source
framework for exactly this kind of voice agent: typed frames through a pipeline of
processors, one service class per vendor, transport separated from the pipeline,
per-stage metrics. NVIDIA's own digital-human controller is built on it. It already
ships Soniox and Kokoro integrations, which we use.

The question when restructuring was whether to adopt it or to keep our own loop.

## Decision

Keep our own code, and take Pipecat's structure: a session object per connection
(`VoiceSession`), a turn assembled from stages (`TurnRunner`), one adapter per vendor
behind a Protocol (`providers/`).

## Considered

**Adopt Pipecat.** Rejected, for four reasons, in order of weight:

1. **No maintained Audio2Face support.** NVIDIA's `nvidia-pipecat` had an
   `Audio2Face3DService`; it was removed in v0.3.0 and the repository was archived in
   July 2026. Lipsync is the part of this product that took the most tuning, and we
   would be rewriting it as a custom processor on day one.
2. **It does not fit the turn model.** Pipecat assumes a continuous session with
   voice-activity-driven interruption. This kiosk is one socket per turn, with the
   browser deciding when the visitor has finished.
3. **The API moves.** 1.0 was a breaking rewrite; 1.3 renamed core classes.
4. **The custom surface is most of the app.** Uplift, Matcha, the Urdu speech
   normalization and the retrieval path would all be custom processors regardless.

**Keep the ad-hoc loop.** Rejected: that is what produced the tangle.

## Consequences

- We own the turn loop, including its bugs.
- We get the vocabulary and the shape, which is what makes the design explainable and
  familiar to anyone who has seen a voice agent before.
- Reconsider if this ever becomes a continuous conversation with barge-in, or moves to
  WebRTC. Then Pipecat's model is the right one and ours would be a bad copy of it.
