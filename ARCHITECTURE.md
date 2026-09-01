# Architecture: Modular Monolith + Ports & Adapters

This document describes the target architecture for this repo, what has been
implemented so far, and how to extend it. Read this before making structural changes
to `server/` or `mari_s2s/` — it's meant to give any new chat/session full context
without re-deriving it from scratch.

## Context — what this repo actually is

This repo is a **companion/benchmark implementation**, not the production kiosk.
Per `README.md`, the production kiosk (LiveKit, FastRTC, 3D avatar, RAG/Qdrant) lives
in a separate repo (`Mari-Interactive-kiosk`); this repo is the speech-to-speech (s2s)
arm being compared against it. Concretely, this repo contains:

- `server/` — a standalone FastAPI web demo (voice UI + REST/WebSocket backend).
  No LiveKit, no RAG, no 3D avatar.
- `mari_s2s/` — plugin handler classes registered into the external
  `huggingface/speech-to-speech` GPU pipeline (launched via `scripts/run_en.sh` /
  `run_ur.sh`), providing Urdu STT/TTS that the upstream pipeline doesn't ship.
- These two are separate entrypoints/processes. They are **not** wired together at
  the transport level, but as of this refactor they **share the same provider
  adapter code** (see below) instead of duplicating it.

## Chosen architecture: modular monolith with a ports-and-adapters core

**Why this and not microservices:** at this scale (one kiosk UI, ~4 external
providers, no independent traffic patterns) the STT/LLM/TTS "services" are mostly
thin wrappers around third-party HTTP/WS APIs that are already remote. Turning them
into your own network services would add latency to a latency-sensitive voice loop
without adding fault isolation you don't already have. See the full architecture
review (in conversation history / PR description) for the complete options
comparison (monolith / modular monolith / microservices / MVC / hybrid).

**The actual problem this solves:** before this refactor, STT/TTS provider logic
(the Soniox websocket client, the Uplift REST client) was implemented **twice** —
once in `server/providers.py`, once again in `mari_s2s/handlers/*.py` — with no
shared interface. Changing a provider, or swapping one out, meant hunting down and
editing every duplicate. Ports-and-adapters fixes this: one interface, one adapter
class per provider, reused by both entrypoints.

## Directory layout (current state)

```
server/
├── app.py                  # FastAPI routes, LLM calls, turn orchestration (NOT yet split)
├── config.py                # single source of truth for settings (.env + os.environ)
└── providers/                # ← the ports-and-adapters layer (this refactor)
    ├── __init__.py           # public API: stt(), tts(), warm(), SonioxStream, ...
    ├── base.py               # STTProvider / TTSProvider Protocols (the "ports")
    ├── stt.py                 # STT adapters + dispatch/cache
    └── tts.py                 # TTS adapters + dispatch/cache

mari_s2s/
├── handlers/
│   ├── soniox_stt_handler.py   # s2s BaseHandler wrapper — delegates to server.providers.stt.SonioxSTT
│   └── uplift_tts_handler.py   # s2s BaseHandler wrapper — delegates to server.providers.tts.UpliftTTS
├── arguments/                   # env var → s2s CLI flag mapping (separate concern, not touched)
└── register.py                  # monkey-patches handlers into s2s's internal registry
```

## The ports (`server/providers/base.py`)

Two `Protocol` interfaces define the contract every provider adapter must satisfy:

```python
class STTProvider(Protocol):
    async def transcribe_pcm(self, pcm: bytes) -> str: ...

class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> tuple[bytes, str]: ...
```

Callers (routes in `server/app.py`, handlers in `mari_s2s/`) depend only on these
interfaces — never on a concrete provider class directly by import elsewhere in
business logic (dispatch/config is the one place that names them).

## The adapters

### STT (`server/providers/stt.py`)

| Class | Provider | Used for | Notes |
|---|---|---|---|
| `SonioxSTT` | Soniox realtime websocket | Urdu (batch, one-shot) | `.transcribe(wav)` / `.transcribe_pcm(pcm)` |
| `SonioxStream` | Soniox realtime websocket | Urdu (**streaming**, live partials) | Not part of the `STTProvider` Protocol — has a richer streaming contract (`start()`/`send()`/`finish()`/`close()`, `on_partial` callback). Used directly by `/ws` in `app.py`. |
| `WhisperLocalSTT` | faster-whisper, in-process | English, `APP_EN_STT=local` | GPU if available, falls back to CPU int8. Has `.warm()` for startup preload. |
| `WhisperRemoteSTT` | OpenAI-compatible `/audio/transcriptions` | English, `APP_EN_STT=remote` | |

Also here: `wav_to_pcm16()`, `pcm16_to_wav()`, `resample_pcm16()` (audio format
helpers), `get_stt_provider(lang)` (cached adapter selection), `stt(wav, lang)`
(thin dispatch function kept for call-site convenience).

### TTS (`server/providers/tts.py`)

| Class | Provider | Used for | Notes |
|---|---|---|---|
| `UpliftTTS` | UpliftAI REST | Urdu | `.synthesize(text) -> (bytes, mime)` |
| `KokoroLocalTTS` | Kokoro, in-process | English, `APP_EN_TTS=local` | GPU if available. Has `.warm()`. |
| `KokoroRemoteTTS` | OpenAI-compatible `/v1/audio/speech` | English, `APP_EN_TTS=remote` | |

Also here: `get_tts_provider(lang)`, `tts(text, lang)`.

### LLM

**Not yet extracted.** `run_llm()` and `llm_stream_sentences()` still live directly
in `server/app.py`, calling DeepSeek or vLLM/Qwen (both OpenAI-compatible
`/chat/completions`) via `httpx`. No duplication existed here (the `mari_s2s` path
uses s2s's own built-in `--llm_backend chat-completions` and needs no custom code),
so it was lower priority. If extracted, it should become `server/providers/llm.py`
with an `LLMProvider` Protocol (`chat(...)` / `chat_stream(...)`), mirroring the
STT/TTS pattern.

## Grounding: the Sky47 knowledge base (`server/knowledge.py`)

The avatar answers *as Sky47*, so the LLM is not allowed to reply from its own
memory. `sky47_knowledge_base.md` (~90 KB) is the authoritative source — far too
large to prepend to every turn on a latency-sensitive voice pipeline — so
`server/knowledge.py` grounds each turn with two pieces:

* **`CORE_BRIEF`** — a short hand-written summary (ownership, campuses, the five
  service pillars, leadership, contact), always in the system prompt so the avatar
  can introduce itself and handle the common questions even if retrieval misses.
* **Retrieved sections** — the knowledge base is split into ~90 chunks at its `##`/`###`
  headings (oversized sections are sub-split), and `search()` ranks them with BM25 over
  a plain term-frequency index. The top few, capped at `MAX_CONTEXT_CHARS`, are appended
  under a "sections relevant to this question" header. Stdlib only: no embeddings, no
  vector store, no extra service to deploy — the whole index builds at import.

`system_prompt(lang, query)` assembles persona + rules + brief + retrieval, and both
`run_llm()` and `llm_stream_sentences()` call it with the visitor's own text, so the
mic path, the typed path and `/chat` are all grounded identically.

**Urdu.** The knowledge base is English but visitors ask in Urdu, so queries are expanded
through `PHRASES` and `GLOSSARY` before scoring — multi-word entries first, because Urdu
spells several terms out letter by letter (`سی ای او` = C-E-O) and the bare letters would
otherwise collide with unrelated words. The Urdu rules then tell the model to read English
and answer in fluent Urdu, leaving names and technical terms in Latin script so the Uplift
TTS voice pronounces them correctly.

Point `APP_KNOWLEDGE_FILE` at a different markdown file to re-ground the avatar;
`/healthz` reports `knowledge.ready` and the section count.

## How provider selection works

`get_stt_provider(lang)` / `get_tts_provider(lang)` in `stt.py`/`tts.py` are the
**only** place a provider is chosen by name. Each caches its instance per
`(lang, config-variant)` key so local-model adapters (Whisper/Kokoro) keep their
loaded model across calls instead of reloading per request.

```python
def get_stt_provider(lang: str) -> STTProvider:
    key = f"{lang}:{C.EN_STT if lang != 'ur' else 'soniox'}"
    if key not in _stt_cache:
        if lang == "ur":
            _stt_cache[key] = SonioxSTT(lang="ur")
        else:
            _stt_cache[key] = WhisperLocalSTT() if C.EN_STT == "local" else WhisperRemoteSTT()
    return _stt_cache[key]
```

Everything else — `server/app.py`'s `/chat`, `/voice`, `/ws` routes, and both
`mari_s2s` handlers — calls the adapter/interface, never a provider by name.

## How `mari_s2s` reuses the same adapters

`mari_s2s/handlers/soniox_stt_handler.py::SonioxSTTHandler.setup()` builds a
`server.providers.stt.SonioxSTT(api_key=..., url=api_base, model=model, lang=language)`
instance; `process()` calls `asyncio.run(self._provider.transcribe_pcm(pcm))`.

`mari_s2s/handlers/uplift_tts_handler.py::UpliftTTSHandler.setup()` builds a
`server.providers.tts.UpliftTTS(api_key=..., base=api_base, path=api_path, ...)`
instance; `process()` calls `asyncio.run(self._provider.synthesize(text))`, then
does its own mp3→PCM decoding/chunking (that part is s2s-specific — the streaming
handler contract, not duplicated network logic — and stays in the handler file).

This is why the s2s handlers import from `server.providers.*` — they're a
consumer of the same ports, just from a different entrypoint/process than the
FastAPI app.

## How to swap or add a provider

**Example: replacing Soniox with a different Urdu STT, or adding a new option.**

1. Add a new adapter class to `server/providers/stt.py` implementing `STTProvider`:
   ```python
   class MyNewSTT(STTProvider):
       def __init__(self, api_key: str = "", ...):
           self.api_key = api_key or C.MY_NEW_STT_KEY
       async def transcribe(self, wav: bytes) -> str: ...
       async def transcribe_pcm(self, pcm: bytes) -> str: ...
   ```
2. Point `get_stt_provider()` at it (one line):
   ```python
   if lang == "ur":
       _stt_cache[key] = MyNewSTT()   # was SonioxSTT()
   ```
3. Add any new config keys to `server/config.py` and `.env.example`.
4. If the provider supports live/streaming partials for `/ws`, write an equivalent
   of `SonioxStream` and swap the construction site in `server/app.py`'s `ws()`
   handler (`stream = providers.SonioxStream(...)` is currently the one place a
   streaming provider is still named directly — the streaming contract isn't yet
   folded into the `STTProvider` Protocol).
5. If retiring Soniox entirely, also retire/replace
   `mari_s2s/handlers/soniox_stt_handler.py` (or point its `_provider` construction
   at the new adapter class instead).

Do **not** need to touch: FastAPI route bodies (`/chat`, `/voice`, `/ws` message
handling), or anything in `mari_s2s/register.py`. The same pattern applies to TTS
(`server/providers/tts.py`, `get_tts_provider()`) and, once extracted, LLM.

## What is NOT yet modularized (remaining migration steps)

`server/app.py` is still a single file mixing:
- **routes** (`/`, `/healthz`, `/chat`, `/voice`, `/ws`)
- **LLM calls** (`run_llm`, `llm_stream_sentences`, `_llm_extra`)
- **turn orchestration** (`run_reply` — stream LLM sentences → TTS each → push audio)
- **session/connection state** (VAD buffering, `SonioxStream` lifecycle inside `ws()`)

Planned next steps (from the original migration plan), in order:
1. Extract `server/providers/llm.py` with an `LLMProvider` Protocol (DeepSeek/vLLM
   adapters), same pattern as STT/TTS.
2. Extract `server/voice_agent/` — turn orchestration (`run_reply`,
   `llm_stream_sentences`, sentence-splitting) out of `app.py`.
3. Extract `server/session/` — per-connection VAD/turn state currently inline in
   `ws()`.
4. Consolidate config: `server/config.py`'s hand-rolled `.env` parser and
   `mari_s2s/arguments/*.py`'s independent `os.getenv` reads are two separate
   config-loading mechanisms reading overlapping keys — worth a single typed
   settings source (e.g. `pydantic-settings`) if this repo grows.
5. Pin the `speech-to-speech` git dependency in `requirements.txt` to a commit SHA
   (currently unpinned — a real production risk, unrelated to this architecture
   work but worth fixing alongside it).
6. Fix `Dockerfile` (or add a second one) to package `server/` + `web/` — the
   current image only packages `mari_s2s/`, so the FastAPI demo isn't
   containerized.
7. Add `docker-compose.yml` for local/prod parity once both entrypoints are
   containerized.

## Non-goals

- **Not microservices.** Do not split STT/LLM/TTS into separately deployed
  network services — they already call out to remote APIs; wrapping that in
  another network hop adds latency without adding isolation.
- **Not adding RAG/Qdrant/LiveKit/3D-avatar code here** — those belong to the
  separate production kiosk repo. If/when this repo merges with that one, revisit
  this document's recommendation with the combined system in view.

## Avatar: Three.js GLB presenter + Audio2Face lipsync

Added on top of the pipeline above; it consumes the existing speech workflow and
changes none of it. Reference: `THREEJS_A2F_INTEGRATION.md` (the working
implementation this was ported from) — section numbers below point into it.

```
existing turn:  mic ─► /ws ─► STT ─► LLM ─► TTS ──► {"tts"} + audio bytes ─► <audio> playback
                                              │
avatar addition:                              └──► Audio2Face-3D NIM (gRPC)
                                                        │  52 ARKit blendshape
                                                        │  weight frames @30fps
                                                        ▼
                                       {"type":"lipsync",uid,names?,frames} on the SAME /ws
                                                        ▼
                                    blendshapePlayer → a2fMorphs → girl11.glb morph targets
```

### Backend (`server/avatar/`)

| File | Role |
|---|---|
| `a2f_client.py` | gRPC client to the A2F-3D NIM — near-verbatim port (§6–§8). One shared channel; one `ProcessAudioStream` per clip; silence priming; ~1s coalesced writes; 3-frame batches (first frame alone). Guarded import: no `grpcio`/`nvidia_ace` ⇒ `AVAILABLE = False` and lipsync is simply off. |
| `lipsync.py` | `LipsyncTurn` — one A2F clip per reply sentence. `open_clip()` opens and primes the stream *before* TTS runs, `feed()` hands it the exact audio bytes the browser is playing. Decodes mp3/wav → 16 kHz PCM16 (PyAV), trims the NIM's ~1.5s trailing silence, publishes batches. 2 concurrent clips, 2 failed opens disable A2F for the turn. |
| `__init__.py` | `get_a2f_client()` (process-wide, lazily built from config), `warm()`, `a2f_status()` for `/healthz`. |

`server/app.py`'s `run_reply` is the only touched route: it opens a clip per
sentence, tags the sentence's `{"tts"}` message with `clip`, and feeds A2F the
same bytes it just sent. All A2F work is in background tasks, so audio timing is
unchanged; the socket is held open by `drain()` until the last clip's frames are
out. Both the reply path and the A2F publishers share one send lock (Starlette
WebSockets are not safe for concurrent sends).

### Frontend (`frontend/`)

| File | Role |
|---|---|
| `lib/blendshapePlayer.ts` | Buffers clips by uid, interpolates keyframes, applies rig calibration, and gates playback on frame arrival (`waitForFrames`). `?a2f=off`, `?a2fGain=`, `?a2fShapes=`, `?a2fOffset=` still work. |
| `lib/a2fMorphs.ts` | Resolves the 52 ARKit names against the rig (direct, case-insensitive; 50/52 match) and writes `morphTargetInfluences` with a ~50ms follow filter, clamping, and decay to rest. |
| `components/avatar/AvatarModel.tsx` | The rig: 3-layer crossfade pool over `CINEMA_4D_Main`'s breathing/listening/talking segments (§5), procedural blink, per-frame lipsync at `useFrame` priority −1. |
| `components/avatar/AvatarScene.tsx` | Transparent `<Canvas>` (the kiosk artwork is behind it), the ported lighting rig, and container-driven framing. |
| `components/avatar/state.ts` | `Mode` → `AvatarState`, and the GLB path. |
| `components/AvatarStage.tsx` | Same placed/sized box as the placeholder it replaced; loads the scene client-side only. |

**Calibration is per-deployment, not inherited.** This NIM build does not
normalise its output: measured over real Urdu TTS sentences, `JawOpen` peaks at
**2.53** (p95 1.48) while every other mouth shape stays under ~0.9. The source
repo's constants (0.55 global, `jawOpen` 0.3 of that) therefore held the jaw's
p95 at 0.24 and the mouth read as murmuring. Now 0.9 global with `jawOpen` at
0.375 (0.3375 effective) — jaw p95 ~0.50, peak ~0.85, no clipping against the
`[0,1]` clamp. Re-measure if you change NIM build or rig; `?a2fGain=` /
`?a2fShapes=jawopen:` override live.

**Playback gate.** The NIM is clip-in/burst-out, so a clip's first frames land
after its audio is ready — measured ~540ms for the first sentence of a turn.
Playing immediately meant the opening syllables ran with the mouth at rest, so a
sentence's audio now waits (up to 700ms) for its frames. This is §10's
`APP_A2F_PLAYBACK_DELAY` made adaptive: later sentences are A2F'd while the
previous one plays, so they resolve instantly and pay nothing, and if A2F is
down the audio still plays on the timeout, just without lipsync.

**Timing — the one deliberate divergence from the source.** The original ran over
a single continuous LiveKit audio track, so it anchored one wall clock per turn
and the backend pre-offset each sentence onto that timeline. Here the browser
plays one `<audio>` element per sentence, so each clip keeps its own timeline and
is sampled against **that element's `currentTime`**. The audio playhead is the
clock: no wall-clock drift, no offsets to compound, and pause/resume or a
late-starting element stay in sync for free.

### What must be running

1. The FastAPI server and the frontend, as before.
2. `pip install grpcio av && pip install --no-deps nvidia-ace==1.2.0` — the
   `--no-deps` matters: `nvidia-ace`'s metadata pins `protobuf==4.24.1`, which
   conflicts with `onnxruntime`. Its generated stubs run fine on protobuf 7.
3. `frontend/public/models/girl11.glb` — gitignored (`models/` in
   `.gitignore`), so it is placed per environment.
4. **The Audio2Face-3D NIM**, via `deploy/a2f/` (see below). Without it
   everything else works and the avatar simply doesn't move its mouth — there is
   no fallback lipsync by design (§4/§15.6).

### Running the NIM — `deploy/a2f/`

```bash
docker login nvcr.io -u '$oauthtoken' -p "$NGC_API_KEY"
cd deploy/a2f
cp .env.example .env          # put your NGC key in it (gitignored)
docker compose --profile init up nim-init   # first host only: ~10GB model pull
docker compose up -d
docker compose logs -f nim    # ready at "[GrpcServer] Running..."
```

Then in the repo-root `.env`:

```
APP_A2F_URL=127.0.0.1:52000
APP_A2F_API_KEY=          # the local NIM has no auth of its own — see below
APP_A2F_MAX_CLIPS=1       # must be <= the NIM's stream_number
```

**Fitting a 6GB GPU.** The stock config does not fit an RTX 4050, and both
failures present as a crash loop rather than a clear message, so the shipped
config differs from NVIDIA's defaults in two places:

- `stream_number: 3 → 1` (`configs/deployment_config.yaml`). Each stream holds
  its own TensorRT execution context.
- `trt_model_generation.a2e` batch shapes `10 → 1/2`
  (`configs/advanced_config.yaml`). Audio2Emotion is FP32-only and its context
  is the single largest allocation: ~3GB at batch 10, a few hundred MB at 2.
  **The engine is cached, so editing this alone does nothing** — delete it and
  regenerate:

  ```bash
  docker run --rm -v mari_a2f_cache:/c alpine rm -f /c/a2e.trt
  docker run --rm --gpus all -v mari_a2f_cache:/tmp/a2x \
    -v "$PWD/configs:/mnt/configs:ro" --env-file .env \
    --entrypoint bash nvcr.io/nim/nvidia/audio2face-3d:2.0 \
    -c 'python3 /opt/nvidia/a2f_pipeline/service/generate_trt_models.py \
        --advanced-config /mnt/configs/advanced_config.yaml'
  ```

  The pipeline does **not** build engines on demand — it exits with "Please
  generate TRT engines using: ./service/generate_trt_models.py".

On a full-size GPU, raise both back toward the defaults (and `APP_A2F_MAX_CLIPS`
with `stream_number`); it is throughput, not correctness, that changes.

**Security.** This NIM has no authentication — the bearer-token check in a real
deployment lives in a TLS edge proxy in front of it. The compose file therefore
publishes to `127.0.0.1:52000` only. Do not change that to `52000:52000` on a
shared or internet-facing host; for a real deployment put it behind a proxy that
checks a token and use the `grpcs://` form of `APP_A2F_URL` with
`APP_A2F_API_KEY`.

**Diagnosing.** `/healthz` reports `avatar.a2f`. In the browser console,
`window.__A2F.state` shows messages/frames received, the active clip, and the
live gains — the fastest way to tell a backend problem from a rendering one.
Note the NIM emits blendshape names in PascalCase (`JawOpen`) while the rig uses
camelCase (`jawOpen`); the resolve step is case-insensitive on purpose (§15.5).
This build emits 68 names (52 ARKit + 16 tongue shapes) and 50 of them land on
the rig — the misses are the tongue set plus the two documented rig gaps.
