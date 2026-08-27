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
