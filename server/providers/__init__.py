"""Provider adapters for the external speech and language services.

  stt(wav, lang) -> str            transcribe with the configured STT adapter
  get_tts_provider(lang, avatar)   the configured TTS adapter (used by server/agent/speech.py)
  llm                              chat-completions client (server/providers/llm.py)
  warm(lang)                       preload local-model adapters at startup
  SonioxStream                     live streaming STT for /ws
  wav_to_pcm16 / pcm16_to_wav      WAV <-> PCM helpers

Adapters implement the Protocols in ``base.py``.
"""

from __future__ import annotations

from .base import STTProvider, TTSProvider
from .stt import (
    SonioxStream,
    SonioxSTT,
    WhisperLocalSTT,
    WhisperRemoteSTT,
    get_stt_provider,
    get_urdu_fallback_stt,
    pcm16_to_wav,
    stt,
    stt_local_ur,
    wav_to_pcm16,
)
from .tts import KokoroLocalTTS, KokoroRemoteTTS, MatchaTTS, UpliftTTS, get_tts_provider

__all__ = [
    "KokoroLocalTTS",
    "KokoroRemoteTTS",
    "MatchaTTS",
    "STTProvider",
    "SonioxSTT",
    "SonioxStream",
    "TTSProvider",
    "UpliftTTS",
    "WhisperLocalSTT",
    "WhisperRemoteSTT",
    "get_stt_provider",
    "get_tts_provider",
    "get_urdu_fallback_stt",
    "pcm16_to_wav",
    "stt",
    "stt_local_ur",
    "warm",
    "warm_urdu_fallback",
    "wav_to_pcm16",
]


async def warm(lang: str = "en", avatar: str | None = None) -> None:
    """Preload local-model adapters (Whisper/Kokoro) in the background so the first
    turn in that language isn't slowed by model load, and check the Matcha-TTS server is
    up. No-op for remote adapters.

    ``avatar`` picks whose TTS adapter to warm; the default presenter's when None."""
    import asyncio

    stt_provider = get_stt_provider(lang)
    if hasattr(stt_provider, "warm"):
        try:
            await asyncio.to_thread(stt_provider.warm)
        except Exception:
            pass
    tts_provider = get_tts_provider(lang, avatar)
    if hasattr(tts_provider, "warm"):
        try:
            await asyncio.to_thread(tts_provider.warm)
        except Exception:
            pass


async def warm_urdu_fallback() -> None:
    """Preload the local Urdu model so the first Soniox-failure turn pays only transcription.
    A no-op when it shares English's model, which warm() has already loaded."""
    import asyncio
    import logging

    from .. import config

    if not (config.ENABLE_URDU_STT_FALLBACK and config.UR_FALLBACK_MODEL):
        return
    try:
        await asyncio.to_thread(get_urdu_fallback_stt().warm)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "urdu fallback model unavailable, Soniox has no local backstop: %s", exc
        )
