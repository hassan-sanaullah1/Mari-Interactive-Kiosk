"""Provider interfaces (ports) — STT / TTS / LLM.

Every concrete provider (Soniox, Whisper, Uplift, Kokoro, ...) implements one of
these Protocols. Callers (server/app.py, mari_s2s/handlers/*) depend only on the
interface, so swapping a provider is a matter of instantiating a different adapter
class — not editing dispatch logic in multiple places.
"""

from __future__ import annotations

from typing import Protocol


class STTProvider(Protocol):
    """Speech-to-text: raw 16 kHz mono PCM in, transcript text out."""

    async def transcribe_pcm(self, pcm: bytes) -> str: ...


class TTSProvider(Protocol):
    """Text-to-speech: text in, (audio_bytes, mime_type) out."""

    async def synthesize(self, text: str) -> tuple[bytes, str]: ...
