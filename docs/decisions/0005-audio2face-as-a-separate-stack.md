# 0005 — Audio2Face deployed separately, and optional

**Status:** accepted · 2026-10

## Context

Lipsync comes from NVIDIA's Audio2Face-3D NIM: a container that takes audio and returns
52 ARKit blendshape weights per frame. It needs a GPU. The application host does not
have one.

## Decision

The NIM lives in its own compose stack (`deploy/a2f/`), on a GPU host, and is **not**
part of `docker-compose.yml`. The kiosk works without it: no `APP_A2F_URL`, or an
unreachable one, and turns run normally with a still mouth.

## Considered

**Put it in the main compose file.** Rejected: it would make the whole kiosk
undeployable on any host without a GPU, including every developer machine and CI.

**Require it.** Rejected. It is the component most likely to be down — it is the only
one needing specific hardware, it has a 300-second cold start, and on a small GPU it
only fits after hand-tuning its TensorRT batch shapes. A silent kiosk is a worse
failure than a still-faced one.

**A fallback lipsync from the audio envelope.** Rejected for now: a wrong mouth reads
worse than a closed one, and it is a second thing to maintain.

## Consequences

- Two deploys. The NIM is upgraded on its own schedule.
- The NIM has no authentication of its own, so it is published on loopback only and
  reached over the host network. Exposing it needs a TLS proxy checking a token.
- Audio2Face tuning per presenter has to travel from `personas.toml` through the turn
  to the gRPC call; `ws_golden.json` pins that it still arrives.
- The browser must handle a turn with audio and no frames, which it does by playing
  after a short wait.
