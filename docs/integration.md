# Integrating our providers into speech-to-speech

`huggingface/speech-to-speech` is a modular VAD→STT→LLM→TTS pipeline where each
stage is a `BaseHandler[In, Out]` selected by a CLI flag (`--stt`, `--tts`,
`--llm_backend`). This repo adds the two providers s2s lacks for **Urdu**, and uses
s2s's built-ins for everything else.

## Provider mapping

| Stage | English | Urdu | New code needed? |
|---|---|---|---|
| STT | `faster-whisper` (built-in) | **Soniox** (`mari_s2s/handlers/soniox_stt_handler.py`) | Urdu only |
| LLM | `chat-completions` → vLLM (built-in) | same | none |
| TTS | `kokoro` (built-in) | **Uplift** (`mari_s2s/handlers/uplift_tts_handler.py`) | Urdu only |

So **English runs on vanilla s2s** (`scripts/run_en.sh`) with no changes. Only the
**Urdu** path needs the two custom handlers registered.

## Handler contract (what the custom handlers implement)

Confirmed against the repo:

- Base: `from speech_to_speech.baseHandler import BaseHandler` → subclass
  `BaseHandler[In, Out]`, implement `setup(should_listen, **cfg)` and
  `process(input) -> Iterator[out]`. The base `run()` loop reads `queue_in`, calls
  `process`, and puts yielded items on `queue_out`.
- STT: `process(VADAudio) -> Iterator[Transcription]`.
  `VADAudio(.audio: np.ndarray, .mode, .turn_id, .turn_revision, .created_at_s)`;
  `Transcription(text, language_code, turn_id, turn_revision, speech_stopped_at_s)`.
- TTS: `process(TTSInput) -> Iterator[np.ndarray]` (int16 @ 16 kHz chunks).
  `TTSInput(.text, .language_code, ...)`.

Our two handlers follow exactly this.

## Registering the custom handlers (two options)

s2s resolves `--stt soniox` / `--tts uplift` via a name→class map in its pipeline
builder. The exact symbol name is version-specific, so pin a commit first
(`requirements.txt`) and pick one option:

### Option A — drop-in (recommended, explicit)
1. Clone s2s at your pinned commit.
2. Copy `mari_s2s/handlers/soniox_stt_handler.py` → `src/speech_to_speech/STT/`
   and `mari_s2s/handlers/uplift_tts_handler.py` → `src/speech_to_speech/TTS/`
   (fix the two intra-package imports if needed).
3. In the pipeline builder (`s2s_pipeline.py`) find the STT and TTS name→class
   maps and add:
   ```python
   "soniox": SonioxSTTHandler,   # in the STT map
   "uplift": UpliftTTSHandler,   # in the TTS map
   ```
   and register the argument dataclasses next to the built-in ones.
4. `pip install -e .` on that clone.

### Option B — runtime autoregister (no fork)
Call `mari_s2s.register.try_autoregister()` before the pipeline builds its handlers
(e.g. from a small launcher that imports s2s then calls the builder). It patches the
registry dict in place. It **no-ops loudly** if it can't find the registry — if you
see that warning, the dict name changed in your commit; use Option A.

> Why the caveat: s2s's internal builder isn't a documented public API and its
> registry symbol has changed across versions. The **handlers themselves** are
> written against the stable, confirmed message/handler contract above; only the
> *registration hook* is version-sensitive.

## Transport → browser

`--mode websocket` exposes raw 16 kHz PCM over WebSocket; `--mode realtime` (default)
speaks the **OpenAI Realtime protocol** at `/v1/realtime`, so any OpenAI-Realtime
client (or a small browser shim) can connect. For the MARI kiosk frontend you'd
point it at whichever transport you standardise on.

## Verification checklist
- [ ] `pip install -r requirements.txt` (pulls s2s at your pin)
- [ ] `python -m speech_to_speech.s2s_pipeline --help` — confirm the STT/TTS/LLM flag
      names in `scripts/run_*.sh` match your commit
- [ ] EN: `bash scripts/run_en.sh` connects and answers (needs vLLM + Kokoro weights)
- [ ] Register custom handlers (Option A or B)
- [ ] UR: `bash scripts/run_ur.sh` (needs Soniox + Uplift keys)
