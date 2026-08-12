# MARI × speech-to-speech

Integration of **[huggingface/speech-to-speech](https://github.com/huggingface/speech-to-speech)**
with MARI's stack: **vLLM (Qwen3.5)** LLM, **Whisper + Soniox** STT, **Kokoro + Uplift**
TTS. This is the "hugging voice" engine referenced by the kiosk project —
speech-to-speech is a modular VAD→STT→LLM→TTS pipeline, and this repo wires our
providers into it.

Companion to **`Mari-Interactive-kiosk`** (the production kiosk on FastRTC). That repo
keeps LiveKit-vs-speech-to-speech as a benchmark; this repo is the speech-to-speech
implementation being compared.

## What's here

```
mari_s2s/handlers/soniox_stt_handler.py   Urdu STT  (BaseHandler[STTIn, STTOut])
mari_s2s/handlers/uplift_tts_handler.py   Urdu TTS  (BaseHandler[TTSIn, TTSOut])
mari_s2s/arguments/                        CLI/config dataclasses for the above
mari_s2s/register.py                       make --stt soniox / --tts uplift resolve
scripts/run_en.sh                          English pipeline (s2s built-ins only)
scripts/run_ur.sh                          Urdu pipeline (our custom handlers)
docs/integration.md                        contract + registration walkthrough
```

## Provider mapping

| Stage | English | Urdu |
|---|---|---|
| STT | `faster-whisper` (s2s built-in) | **Soniox** (custom) |
| LLM | `chat-completions` → vLLM Qwen3.5 | same |
| TTS | `kokoro-82m` (s2s built-in) | **Uplift** (custom) |

**English needs no new code** — it's pure s2s configuration. Only **Urdu** required
custom handlers (s2s has no Urdu-native STT/TTS).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # (or Docker — see Dockerfile)
pip install -r requirements.txt                        # pulls s2s at your pin
cp .env.example .env                                   # set vLLM + Soniox + Uplift

# Confirm s2s's current flag names (they evolve), then run:
python -m speech_to_speech.s2s_pipeline --help

bash scripts/run_en.sh     # English (built-ins)
# register custom handlers (docs/integration.md), then:
bash scripts/run_ur.sh     # Urdu (Soniox + Uplift)
```

## Status & honest caveats

- The **custom handlers** are written against s2s's confirmed handler/message
  contract (`BaseHandler`, `VADAudio`/`Transcription`/`TTSInput`) and reuse the
  tested Soniox/Uplift logic from the kiosk's `voicecore`. They **compile**; full
  runtime validation needs s2s installed + reachable endpoints (I couldn't run the
  GPU stack here).
- The **registration hook** (`--stt soniox` / `--tts uplift`) is version-sensitive:
  s2s's builder registry isn't a documented public API. `register.try_autoregister()`
  handles the common cases and warns loudly otherwise; `docs/integration.md` has the
  explicit drop-in steps. **Pin an s2s commit** in `requirements.txt` before relying
  on it.
- s2s's exact CLI flag names for the LLM base URL can differ by commit — the run
  scripts note where to confirm with `--help`.

See [docs/integration.md](docs/integration.md) for the full contract and wiring.
