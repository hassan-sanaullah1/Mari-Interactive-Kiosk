"""MARI · Voice — provider adapters (no LiveKit, no s2s runtime).

Public surface used by server/app.py:

  stt(wav, lang) -> str                    dispatch to the configured STT adapter
  tts(text, lang) -> (bytes, mime)         dispatch to the configured TTS adapter
  warm(lang)                               preload local-model adapters at startup
  SonioxStream                             live streaming STT (used by /ws)
  wav_to_pcm16 / pcm16_to_wav              WAV<->PCM helpers used by /ws

Each adapter (SonioxSTT, WhisperLocalSTT, WhisperRemoteSTT, UpliftTTS,
KokoroLocalTTS, KokoroRemoteTTS) implements the STTProvider/TTSProvider Protocol in
``base.py``, so mari_s2s/handlers/*.py reuse the exact same classes instead of
reimplementing the Soniox/Uplift network calls.
"""

from __future__ import annotations

from .. import config as C
from .base import STTProvider, TTSProvider
from .stt import (
    SonioxStream,
    SonioxSTT,
    WhisperLocalSTT,
    WhisperRemoteSTT,
    get_stt_provider,
    pcm16_to_wav,
    stt,
    wav_to_pcm16,
)
from .tts import KokoroLocalTTS, KokoroRemoteTTS, UpliftTTS, get_tts_provider, tts

__all__ = [
    "STTProvider",
    "TTSProvider",
    "SonioxStream",
    "SonioxSTT",
    "WhisperLocalSTT",
    "WhisperRemoteSTT",
    "KokoroLocalTTS",
    "KokoroRemoteTTS",
    "UpliftTTS",
    "get_stt_provider",
    "get_tts_provider",
    "pcm16_to_wav",
    "wav_to_pcm16",
    "stt",
    "tts",
    "warm",
]


async def warm(lang: str = "en") -> None:
    """Preload local-model adapters (Whisper/Kokoro) in the background so the first
    turn in that language isn't slowed by model load. No-op for remote adapters."""
    import asyncio

    stt_provider = get_stt_provider(lang)
    if hasattr(stt_provider, "warm"):
        try:
            await asyncio.to_thread(stt_provider.warm)
        except Exception:
            pass
    tts_provider = get_tts_provider(lang)
    if hasattr(tts_provider, "warm"):
        try:
            await asyncio.to_thread(tts_provider.warm)
        except Exception:
            pass
